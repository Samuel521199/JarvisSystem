"""Connection isolation, immutable billing and local administration boundaries."""
from contextlib import closing
from copy import deepcopy
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import http.client
import asyncio
import importlib.util
import json
from pathlib import Path
import sqlite3
import sys
import tempfile
import threading
import unittest
from unittest.mock import Mock, patch

import httpx

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT/'runtime/node-host'), str(ROOT/'adapters/models/provider-native')]
from jarvis_models.registry import Registry, effective_config, template
from jarvis_models.gateway import probe, ProbeJournal, build_request, extract, validate_config, ModelError
from jarvis_models.catalog import public_models, select_model, resolve_settings
from jarvis_models.billing import clean_usage, tokens, estimate, report
from jarvis_models.vault import VaultError
from jarvis_core.chat import ChatService

SEED = ROOT/'config/model-profiles/providers.json'


class AdminTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.data = Path(self.temp.name)
        self.credentials = {'openai': {'api_key': 'fixture-old-secret'}}
        self.saves = 0
        def save(value):
            self.credentials = deepcopy(value)
            self.saves += 1
        self.registry = Registry(self.data, SEED, loader=lambda: deepcopy(self.credentials), saver=save, vault_exists=lambda: True)

    def change(self, **payload):
        return self.registry.mutate({'revision': self.registry.snapshot()['revision'], **payload})

    def config(self):
        return effective_config(SEED, self.data)

    def request(self, provider='eachlabs', usage=None):
        usage = usage or {'prompt_tokens': 100, 'completion_tokens': 20}
        seen = []
        def handler(request):
            seen.append(request)
            return httpx.Response(200, json={'choices': [{'message': {'content': 'ok'}}], 'usage': usage})
        client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        try:
            result = probe(self.config(), provider, 'synthetic prompt', self.data, lambda: None,
                           client=client, credentials_loader=lambda: self.credentials)
        finally:
            asyncio.run(client.aclose())
        return result, seen

    def test_constructor_never_reads_or_writes_vault_and_import_is_idempotent(self):
        self.assertEqual(self.saves, 0)
        self.registry.import_legacy()
        first = self.registry.snapshot()
        self.registry.import_legacy()
        self.assertEqual(first, self.registry.snapshot())
        self.assertEqual(self.saves, 1)
        serialized = json.dumps(first)
        self.assertNotIn('fixture-old-secret', serialized)
        self.assertNotIn('api_key', serialized)
        self.assertEqual(self.config()['providers']['openai']['adapter'], 'openai')

    def test_rotation_and_price_changes_keep_historical_key_and_rate(self):
        self.change(action='add_key', connection='eachlabs', label='第一版', secret='fixture-each-first')
        before = self.config()['providers']['eachlabs']['credential_id']
        first, seen = self.request()
        self.assertEqual(first['status'], 'SUCCEEDED')
        self.assertEqual(seen[0].headers['authorization'], 'Bearer fixture-each-first')
        self.assertEqual(str(seen[0].url), 'https://api.eachlabs.ai/v1/chat/completions')
        self.assertEqual(first['billing_identity']['key_id'], before)
        self.assertAlmostEqual(first['billing']['amount'], .000422)
        self.change(action='add_key', connection='eachlabs', label='第二版', secret='fixture-each-second', replace_key=before)
        price = dict(currency='USD', input=200, output=1000, fee_percent=0)
        self.change(action='model', connection='eachlabs', model='anthropic/claude-sonnet-5.5', price=price)
        second, seen = self.request()
        self.assertEqual(seen[0].headers['authorization'], 'Bearer fixture-each-second')
        self.assertNotEqual(second['billing_identity']['key_id'], before)
        history = report(self.data)
        self.assertEqual(len(history['keys']), 2)
        old = next(row for row in history['entries'] if row['id'] == first['request_id'])
        self.assertEqual(old['billing']['amount'], first['billing']['amount'])
        self.assertEqual(old['billing']['price']['input'], 2)
        self.assertFalse(self.config()['providers']['eachlabs']['keys'][before]['enabled'])

    def test_conflict_and_vault_failure_cannot_replace_active_configuration(self):
        revision = self.registry.snapshot()['revision']
        def change(label):
            try:
                self.registry.mutate(dict(revision=revision, action='add_key', connection='eachlabs', label=label, secret='fixture-secret-'+label))
                return 'saved'
            except ValueError:
                return 'conflict'
        with ThreadPoolExecutor(2) as pool:
            self.assertEqual(sorted(pool.map(change, ['one', 'two'])), ['conflict', 'saved'])
        old = self.registry.snapshot()
        self.registry.saver = Mock(side_effect=VaultError('unavailable'))
        with self.assertRaises(VaultError):
            self.change(action='add_key', connection='eachlabs', label='failed', secret='fixture-unsaved')
        self.assertEqual(old, self.registry.snapshot())

    def test_active_key_cannot_be_disabled_or_moved_to_another_route(self):
        self.change(action='add_key', connection='eachlabs', label='active', secret='fixture-active')
        item = resolve_settings(self.config(), 'eachlabs')
        with self.assertRaises(ValueError):
            self.change(action='key', connection='eachlabs', key_id=item['credential_id'], enabled=False)
        with self.assertRaises(VaultError):
            build_request('other', item, 'test', 20, self.credentials)
        with self.assertRaises(ValueError):
            self.change(action='connection', connection='eachlabs', base_url='https://other.example/v1')

    def test_custom_route_first_model_replaces_placeholder_and_stays_out_of_fallback(self):
        self.change(action='add_connection', template='compatible', label='自建中转', base_url='https://relay.example/v1')
        c = self.config()
        route = next(k for k in c['providers'] if k.startswith('conn_'))
        self.change(action='model', connection=route, model='vendor/text-model', label='Text model', max_output_tokens=1024)
        self.change(action='add_key', connection=route, label='测试凭据', secret='fixture-custom-key')
        c = self.config()
        self.assertEqual(list(c['providers'][route]['models']), ['vendor/text-model'])
        self.assertNotIn(route, c['fallback_order'])
        self.assertEqual(build_request(route, resolve_settings(c, route), 'test', 20, self.credentials)[0], 'https://relay.example/v1/chat/completions')
        self.change(action='connection', connection=route, enabled=False)
        self.assertNotIn(route, {m['provider'] for m in public_models(self.config())})
        with self.assertRaises(ValueError):
            select_model(self.config(), route, 'vendor/text-model')
        with self.assertRaises(ValueError):
            self.change(action='connection', connection='vertex', enabled=False)

    def test_native_anthropic_and_google_api_key_wire_protocols(self):
        for adapter, expected in [('anthropic', 'https://api.anthropic.com/v1/messages'), ('gemini', 'https://generativelanguage.googleapis.com/v1beta/models/')]:
            self.change(action='add_connection', template=adapter, label=adapter)
            c = self.config()
            route = next(k for k, v in c['providers'].items() if v.get('adapter') == adapter)
            self.change(action='add_key', connection=route, label='fixture', secret='fixture-'+adapter)
            item = resolve_settings(self.config(), route)
            url, headers, body = build_request(route, item, 'new', 100, self.credentials, [{'role':'user','content':'old'}])
            self.assertTrue(url.startswith(expected))
            self.assertNotIn('fixture-', url)
            if adapter == 'anthropic':
                self.assertEqual(headers['x-api-key'], 'fixture-anthropic')
                self.assertEqual(body['thinking']['type'], 'adaptive')
                self.assertEqual(len(body['messages']), 2)
                text, usage = extract(adapter, {'content':[{'type':'thinking','thinking':'private'},{'type':'text','text':'hello'}], 'usage':{'input_tokens':3,'output_tokens':4,'cache_read_input_tokens':2}})
                self.assertEqual(text, 'hello')
                self.assertEqual(tokens(adapter, usage)['total'], 9)
            else:
                self.assertEqual(headers['x-goog-api-key'], 'fixture-gemini')
                self.assertEqual(len(body['contents']), 2)

    def test_region_change_does_not_reuse_beijing_prices_and_duplicate_models_use_route(self):
        self.change(action='add_connection',template='bailian',label='新加坡账户',region='singapore')
        route=next(c for c in self.registry.snapshot()['connections'] if c['label']=='新加坡账户')
        self.assertEqual(route['base_url'],'https://dashscope-intl.aliyuncs.com/compatible-mode/v1')
        self.assertTrue(all('price' not in m for m in route['models'].values()))
        sys.path.insert(0,str(ROOT/'adapters/computer-use'))
        from jarvis_computer.planner import ModelPlanner
        with patch.object(ChatService,'models',return_value={'models':[{'provider':'first','model':'same-model'},{'provider':'second','model':'same-model'}]}):
            planner=ModelPlanner(Mock(),'second::same-model')
            self.assertEqual((planner.provider,planner.model),('second','same-model'))
            from jarvis_computer.protocol import ComputerError
            with self.assertRaises(ComputerError):ModelPlanner(Mock(),'same-model')

    def test_unsafe_parameters_and_endpoint_inputs_rejected_without_vault_write(self):
        old = self.registry.snapshot()
        for url in ('http://relay.example/v1','https://key:secret@relay.example/v1','https://relay.example/v1?api_key=secret','https://relay.example/v1#fragment'):
            with self.assertRaises((ValueError, ModelError)):
                self.change(action='add_connection',template='compatible',label='test',base_url=url)
        for model in ('https://evil.example','../escape','test//escape'):
            with self.assertRaises(ValueError):
                self.change(action='model',connection='eachlabs',model=model)
        for value in (-1, float('inf'), True):
            with self.assertRaises(ValueError):
                self.change(action='model',connection='eachlabs',model='bad-price',price={'currency':'USD','input':value})
        self.assertEqual(old, self.registry.snapshot())
        self.assertEqual(self.saves, 0)

    def test_usage_normalization_avoids_double_counting_cache_and_reasoning(self):
        raw={'input_tokens':100,'output_tokens':20,'input_tokens_details':{'cached_tokens':30,'cache_write_tokens':10,'secret':'private'},'output_tokens_details':{'reasoning_tokens':12},'cost_details':{'upstream_inference_cost':.2,'secret':'private'},'other':'private'}
        clean=clean_usage(raw)
        self.assertNotIn('private',json.dumps(clean))
        result=estimate('openai',clean,{'currency':'USD','input':2,'output':10,'cache_read':.1,'cache_write':2.5,'fee_percent':5.5})
        self.assertEqual(result['tokens']['total'],120)
        self.assertAlmostEqual(result['amount'],.00036714)
        google=tokens('vertex',{'promptTokenCount':10,'candidatesTokenCount':20,'thoughtsTokenCount':30})
        self.assertEqual(google['total'],60)
        anth=tokens('anthropic',{'input_tokens':60,'output_tokens':20,'cache_read_input_tokens':30,'cache_creation_input_tokens':10})
        self.assertEqual(anth['total'],120)
        self.assertIsNone(tokens('openai',{'input_tokens':10,'output_tokens':20,'cached_tokens':30}))

    def test_missing_rates_usage_expired_prices_and_cancellation_are_not_free(self):
        priced={'currency':'USD','input':2,'output':10,'max_input_tokens':200}
        for usage,price in (({},priced),({'input_tokens':100,'output_tokens':20},None),({'input_tokens':100,'output_tokens':20,'cached_tokens':5},priced),({'input_tokens':201,'output_tokens':20},priced),({'input_tokens':100,'output_tokens':20},{**priced,'valid_until':'2000-01-01'})):
            self.assertIsNone(estimate('openai',usage,price)['amount'])
        self.assertEqual(estimate('openai',{},priced,dispatched=False)['amount'],0)
        self.change(action='add_key',connection='eachlabs',label='test',secret='fixture-cancel')
        event=threading.Event()
        def handler(request):
            event.set()
            return httpx.Response(200,json={'choices':[{'message':{'content':'late'}}]})
        client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        try:
            result=probe(self.config(),'eachlabs','test',self.data,lambda:None,client=client,credentials_loader=lambda:self.credentials,cancel_event=event)
        finally:
            asyncio.run(client.aclose())
        self.assertEqual(result['status'],'UNKNOWN')
        self.assertIsNone(result['billing']['amount'])

    def test_timezone_boundaries_currencies_pagination_and_legacy_not_repriced(self):
        journal=ProbeJournal(self.data/'model-probes.db')
        for i in range(54):
            ident=journal.reserve('openai','same-model','not-persisted')
            currency='USD' if i%2==0 else 'CNY'
            bill={'basis':'estimated','amount':.01,'currency':currency,'tokens':{'total':30}}
            journal.finish(ident,'SUCCEEDED',{'billing':bill,'billing_identity':{'key_id':'key_fixture','key_label':'fixture'}})
            with closing(journal.connect()) as db,db:
                db.execute('UPDATE probes SET created_at=? WHERE id=?',('2026-10-15T16:00:00+00:00' if i else '2026-10-15T15:59:59+00:00',ident))
        legacy=journal.reserve('openai','same-model','secret-history')
        journal.finish(legacy,'SUCCEEDED',{'usage':{'input_tokens':10,'output_tokens':2}})
        with closing(journal.connect()) as db,db:
            db.execute('UPDATE probes SET created_at=? WHERE id=?',('2026-10-15T16:00:00+00:00',legacy))
        r=report(self.data,start='2026-10-16',end='2026-10-16')
        self.assertEqual(r['total']['requests'],54)
        self.assertEqual(r['total']['estimated'],{'USD':.26,'CNY':.27})
        self.assertEqual(r['total']['unpriced'],1)
        self.assertEqual(len(r['entries']),50)
        self.assertTrue(r['has_more'])
        self.assertEqual(len(report(self.data,start='2026-10-16',end='2026-10-16',offset=50)['entries']),4)
        self.assertEqual(report(self.data,start='2026-10-16',end='2026-10-16',key_id='legacy')['total']['requests'],1)
        self.assertNotIn('secret-history',json.dumps(r))
        self.assertNotIn('prompt_digest',json.dumps(r))

    def test_admin_http_requires_nonce_and_preserves_safe_error_responses(self):
        spec=importlib.util.spec_from_file_location('admin_test_web',ROOT/'apps/web/server.py')
        web=importlib.util.module_from_spec(spec);spec.loader.exec_module(web)
        class Core:
            def assert_running(self):pass
        core=Core();core.data_dir=self.data
        server=web.LocalChatServer(('127.0.0.1',0),core,ChatService(core))
        server.admin=self.registry
        thread=threading.Thread(target=server.serve_forever,kwargs={'poll_interval':.01},daemon=True);thread.start()
        self.addCleanup(server.server_close);self.addCleanup(server.shutdown)
        def call(method,path,body=None,nonce=True,origin=None):
            conn=http.client.HTTPConnection('127.0.0.1',server.server_port,timeout=3)
            headers={'Content-Type':'application/json'}
            if nonce:headers['X-Jarvis-Nonce']=server.nonce
            if method=='POST':headers['Origin']=origin or f'http://127.0.0.1:{server.server_port}'
            conn.request(method,path,json.dumps(body) if body is not None else None,headers)
            response=conn.getresponse();result=response.status,response.read().decode();conn.close();return result
        self.assertEqual(call('GET','/api/admin/config',nonce=False)[0],403)
        self.assertEqual(call('GET','/api/admin/config')[0],200)
        self.assertEqual(call('GET','/admin')[0],200)
        payload=dict(revision=1,action='add_key',connection='eachlabs',label='test',secret='fixture-not-in-response')
        self.assertEqual(call('POST','/api/admin/config',payload,origin='https://example.com')[0],403)
        status,body=call('POST','/api/admin/config',payload)
        self.assertEqual(status,200)
        self.assertNotIn(payload['secret'],body)
        status,body=call('GET','/api/admin/usage?start=invalid')
        self.assertEqual(status,400)
        self.assertNotIn('Traceback',body)
        self.assertEqual(call('GET','/api/admin/usage?provider=a&provider=b')[0],400)


if __name__=='__main__':
    unittest.main()
