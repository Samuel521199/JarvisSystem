"""Explicit cross-session checkpoints: provenance, isolation and invalidation."""
from concurrent.futures import ThreadPoolExecutor
import http.client
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch
import uuid

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'runtime/node-host'))
from jarvis_core.chat import ChatService
from jarvis_core.continuity import ContinuityStore, validate_context
from jarvis_core.conversations import ConversationStore, validate_document
from jarvis_core.memory import MemoryError
from jarvis_core.personal import parse
from jarvis_core.service import CoreService
from jarvis_core.workspace import WorkspaceService


def uid(): return uuid.uuid4().hex


class ContinuityTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name); folder = self.base/'project'; folder.mkdir()
        self.core = CoreService(self.base/'data'); self.core.initialize(folder)
        self.chat = ChatService(self.core); self.store = ContinuityStore(self.core)
        self.archives = ConversationStore(self.core)
        self.project = WorkspaceService(self.core).open_project({'path': str(folder)})['id']

    def reply(self, message, **kwargs):
        return self.chat.reply(message, **{'provider': 'vertex', 'personal_context': {'temporary': False},
                              'memory_context': {'enabled': True, 'project_id': None}, **kwargs})

    def source(self, message, project=None):
        ident = uid(); doc = {'title': 'fixture', 'project_id': project, 'context_note': '', 'messages': [
            {'role': 'user', 'content': message, 'meta': '', 'short_meta': '', 'attachments_omitted': False,
             'incomplete': False, 'personal_control': True}]}
        self.archives.put(ident, {'revision': 0, 'document': doc})
        return {'conversation_id': ident, 'message_index': 0}

    def save(self, title='旅行', progress='已确定杭州_PRIVATE', next_step='比较住宿_NEXT', project=None, update=False):
        message = ('更新接续' if update else '保存接续')+'：'+title+'='+progress+'｜'+next_step
        source = self.source(message, project)
        result = self.reply(message, personal_context={'temporary': False, 'source': source},
                            memory_context={'enabled': True, 'project_id': project})
        self.assertEqual(result['status'], 'SUCCEEDED', result)
        return result['personal'], source, message

    def change(self, ident, action, **kwargs):
        return self.store.change(action, request_id=uid(), target=ident, **kwargs)

    def test_local_commands_source_and_restart(self):
        self.chat.config_path = self.base/'no-config.json'
        with patch('jarvis_core.chat.gateway.probe') as model:
            receipt, source, _ = self.save()
            self.assertEqual(self.reply('继续话题：旅行')['personal']['id'], receipt['id'])
            self.assertEqual(self.reply('完成接续：旅行')['status'], 'SUCCEEDED')
            store = ContinuityStore(CoreService(self.core.data_dir))
            self.assertEqual(store.list()['records'][0]['document']['state'], 'owner_completed')
            self.assertEqual(self.reply('重新打开接续：旅行')['status'], 'SUCCEEDED')
            self.assertIn('PRIVATE', self.reply('查看接续')['text']); model.assert_not_called()
        row = store.list()['records'][0]
        self.assertEqual(row['document']['providers'], [])
        self.assertEqual(row['document']['source']['conversation_id'], source['conversation_id'])
        self.assertEqual(row['document']['source']['archive_revision'], 1)
        self.assertEqual(row['document']['state'], 'open')

    def test_suggestions_recheck_scope_provider_and_deleted_source(self):
        personal, source, _ = self.save(title='英语学习',progress='完成单词',next_step='练习英语口语')
        project, _, _ = self.save(title='英语学习',progress='项目英语文档',project=self.project)
        self.assertEqual([r['id'] for r in self.store.suggest('英语',None,'local')['records']],[personal['id']])
        self.assertFalse(self.store.suggest('英语',None,'vertex')['records'])
        self.change(personal['id'],'permissions',providers=['vertex'])
        self.assertEqual([r['id'] for r in self.store.suggest('英语',None,'vertex')['records']],[personal['id']])
        self.change(personal['id'],'permissions',providers=[])
        self.assertFalse(self.store.suggest('英语',None,'vertex')['records'])
        self.archives.delete(source['conversation_id'],{'revision':1})
        self.assertFalse(self.store.suggest('英语',None,'local')['records'])
        self.assertEqual([r['id'] for r in self.store.suggest('英语',self.project,'local')['records']],[project['id']])

    def test_source_must_be_exact_owner_command_in_same_project(self):
        message = '保存接续：旅行=杭州｜订票'; source = self.source(message)
        for changes in ({'source': {**source, 'message_index': 1}}, {'source': self.source('其他消息')},
                        {'source': self.source(message, self.project)}):
            result = self.reply(message, personal_context={'temporary': False, **changes})
            self.assertEqual(result['status'], 'FAILED')
        archive = self.archives.get(source['conversation_id']); archive['document']['messages'][0]['personal_control'] = False
        self.archives.put(source['conversation_id'], {'revision': 1, 'document': archive['document']})
        self.assertEqual(self.reply(message, personal_context={'temporary': False, 'source': source})['status'], 'FAILED')
        self.assertEqual(self.store.list()['records'], [])

    def test_append_valid_but_source_edit_delete_or_move_invalidates(self):
        receipt, source, _ = self.save(); ctx = {'enabled': True, 'ids': [receipt['id']]}
        archive = self.archives.get(source['conversation_id']); doc = archive['document']
        doc['messages'].append({**doc['messages'][0], 'content': '后续消息'})
        self.archives.put(source['conversation_id'], {'revision': 1, 'document': doc})
        self.assertEqual(len(self.store.snapshot(ctx, None, 'local')[0]), 1)
        doc['project_id'] = self.project
        self.archives.put(source['conversation_id'], {'revision': 2, 'document': doc})
        self.assertFalse(self.store.snapshot(ctx, None, 'local')[0])
        doc['project_id'] = None; doc['messages'][0]['content'] = '被改写'
        self.archives.put(source['conversation_id'], {'revision': 3, 'document': doc})
        self.assertFalse(self.store.snapshot(ctx, None, 'local')[0])
        self.archives.delete(source['conversation_id'], {'revision': 4})
        self.assertFalse(self.store.snapshot(ctx, None, 'local')[0])

    def test_exact_scope_selected_only_and_provider_before_source_read(self):
        private, _, _ = self.save(); project, _, _ = self.save(project=self.project)
        self.assertEqual(len(self.store.list()['records']), 1)
        ctx = {'enabled': True, 'ids': [private['id'], project['id']]}
        self.assertEqual([r['id'] for r in self.store.snapshot(ctx, self.project, 'local')[0]], [project['id']])
        with patch.object(self.store, 'source_current', side_effect=AssertionError('no private read')):
            self.assertFalse(self.store.snapshot(ctx, None, 'openai')[0])
            self.assertFalse(self.store.snapshot({'enabled': True, 'ids': []}, None, 'local')[0])
        self.change(private['id'], 'permissions', providers=['vertex'])
        self.assertEqual(len(self.store.snapshot(ctx, None, 'vertex')[0]), 1)

    def test_retry_atomicity_and_tombstone_do_not_resurrect_content(self):
        command = '保存接续：测试=原始进展｜后续'; source = self.source(command); request = uid()
        kwargs = {'personal_context': {'temporary': False, 'source': source}, '_request_id': request}
        with ThreadPoolExecutor(3) as pool:
            results = list(pool.map(lambda _: self.reply(command, **kwargs), range(3)))
        self.assertTrue(all(r['status']=='SUCCEEDED' for r in results), results)
        self.assertEqual(sum(not r['personal']['replayed'] for r in results), 1)
        receipt = results[0]['personal']
        with self.store.connection(write=True) as db:
            db.execute("CREATE TRIGGER reject_receipt BEFORE INSERT ON commands BEGIN SELECT RAISE(ABORT,'fixture'); END"); db.commit()
        self.assertEqual(self.reply('完成接续：测试')['status'], 'FAILED')
        self.assertEqual(self.store.list()['records'][0]['revision'], 1)
        with self.store.connection(write=True) as db: db.execute('DROP TRIGGER reject_receipt'); db.commit()
        self.change(receipt['id'], 'forget')
        self.archives.delete(source['conversation_id'], {'revision': 1})
        self.assertTrue(self.reply(command, **kwargs)['personal']['replayed'])
        self.assertFalse(self.store.list()['records'])
        with self.store.connection() as db:
            raw = str([tuple(r) for r in db.execute('SELECT * FROM commands')])
            self.assertNotIn('原始进展', raw)
            self.assertIsNone(db.execute('SELECT document FROM notes').fetchone()[0])

    def test_new_session_and_stale_derived_history(self):
        receipt, _, _ = self.save(); self.change(receipt['id'], 'permissions', providers=['vertex'])
        ctx = {'enabled': True, 'ids': [receipt['id']]}; calls = []
        def probe(config, provider, message, *args, **kwargs):
            calls.append({'message': message, 'history': kwargs['history']})
            return {'status': 'SUCCEEDED', 'text': 'PRIVATE 的下一步 NEXT', 'provider': provider, 'model': config['providers'][provider]['model']}
        self.chat = ChatService(CoreService(self.core.data_dir))
        with patch('jarvis_core.chat.gateway.probe', side_effect=probe):
            response = self.reply('接着聊', continuity_context=ctx)
            self.assertEqual(response['status'], 'SUCCEEDED', response)
            self.assertIn('PRIVATE', calls[-1]['message']); self.assertIn('owner_entered_note', calls[-1]['message'])
            refs = response['history_info']['continuity']['references']; self.assertEqual(refs[0]['revision'], 2)
            previous = [{'role': 'user', 'content': '接着聊'}, {'role': 'assistant', 'content': 'PRIVATE_NEXT'}]
            history_args = {'history': previous, 'history_continuity': [[], refs]}
            self.save(progress='改为苏州_CURRENT', update=True)
            self.reply('新的进展？', continuity_context=ctx, **history_args)
            self.assertEqual(calls[-1]['history'], []); self.assertIn('CURRENT', calls[-1]['message'])
            self.assertNotIn('PRIVATE', str(calls[-1]))
            self.change(receipt['id'], 'forget')
            blocked = self.reply('继续', continuity_context=ctx, **history_args)
            self.assertEqual(blocked['error'], 'continuity_not_available')
            self.reply('聊其他', continuity_context={'enabled': False, 'ids': []}, **history_args)
            self.assertNotIn('PRIVATE', str(calls[-1])); self.assertEqual(calls[-1]['history'], [])

    def test_temporary_disabled_and_quoted_commands(self):
        for value in ('他说：保存接续：a=b｜c', '```保存接续：a=b｜c```', '保存接续：a=b｜c\n删除文件'):
            self.assertIsNone(parse(value))
        receipt, _, _ = self.save(); ctx = {'enabled': True, 'ids': [receipt['id']]}
        with patch('jarvis_core.chat.gateway.probe', return_value={'status': 'SUCCEEDED', 'text': 'ok'}) as model:
            self.assertEqual(self.reply('完成接续：旅行', personal_context={'temporary': True})['status'], 'FAILED')
            model.assert_not_called()
            for kwargs in ({'personal_context': {'temporary': True}}, {'memory_context': {'enabled': False, 'project_id': None}}):
                self.reply('你好', continuity_context=ctx, **kwargs)
                self.assertNotIn('PRIVATE', model.call_args.args[2])

    def test_corrupt_optional_store_does_not_break_unselected_chat(self):
        self.store.path.write_bytes(b'corrupt fixture')
        with patch('jarvis_core.chat.gateway.probe', return_value={'status': 'SUCCEEDED', 'text': 'ok'}) as model:
            self.assertEqual(self.reply('你好')['status'], 'SUCCEEDED')
            model.reset_mock()
            self.assertEqual(self.reply('继续', continuity_context={'enabled': True, 'ids': [uid()]})['status'], 'FAILED')
            model.assert_not_called()

    def test_fallback_rechecks_permissions_and_source(self):
        receipt, source, _ = self.save(); ctx = {'enabled': True, 'ids': [receipt['id']]}
        self.change(receipt['id'], 'permissions', providers=['vertex'])
        config = json.loads((ROOT/'config/model-profiles/providers.json').read_text(encoding='utf-8'))
        path = self.base/'providers.json'; path.write_text(json.dumps(config), encoding='utf-8')
        self.chat = ChatService(self.core, path)
        rejection = {'status': 'FAILED', 'provider': 'vertex', 'error_category': 'quota_exhausted', 'outcome_uncertain': False}
        with patch('jarvis_core.chat.gateway.probe', return_value=rejection) as model:
            result = self.reply('继续', provider='auto', continuity_context=ctx)
            self.assertEqual(result['error'], 'continuity_not_available'); self.assertEqual(model.call_count, 1)
        self.change(receipt['id'], 'permissions', providers=['vertex','bailian'])
        with patch('jarvis_core.chat.gateway.probe', side_effect=[rejection, {'status':'SUCCEEDED','text':'ok'}]) as model:
            self.assertEqual(self.reply('继续', provider='auto', continuity_context=ctx)['status'], 'SUCCEEDED')
            self.assertEqual([c.args[1] for c in model.call_args_list], ['vertex','bailian'])
            self.assertTrue(all('PRIVATE' in c.args[2] for c in model.call_args_list))
        def remove_source(*args, **kwargs):
            self.archives.delete(source['conversation_id'], {'revision': 1}); return rejection
        with patch('jarvis_core.chat.gateway.probe', side_effect=remove_source) as model:
            self.assertEqual(self.reply('继续', provider='auto', continuity_context=ctx)['error'], 'continuity_not_available')
            self.assertEqual(model.call_count, 1)

    def test_cancel_and_core_guard_prevent_changes(self):
        receipt, _, _ = self.save(); event = threading.Event(); event.set()
        self.assertEqual(self.reply('完成接续：旅行', cancel_event=event)['status'], 'CANCELLED')
        with patch.object(self.core, 'assert_running', side_effect=RuntimeError('stopped')):
            self.assertEqual(self.reply('完成接续：旅行')['error'], 'core_unavailable')
        self.assertEqual(self.store.list()['records'][0]['revision'], receipt['revision'])

    def test_budget_limit_validation_and_revision_conflict(self):
        for value in ({'enabled': True, 'ids': [[]]}, {'enabled': True, 'ids': [uid()]*2}, {'enabled': True, 'ids': [uid() for _ in range(4)]}):
            with self.assertRaises(MemoryError): validate_context(value)
        receipt, _, _ = self.save(); rows = self.store.snapshot({'enabled': True, 'ids': [receipt['id']]}, None, 'local')[0]
        self.assertEqual(self.store.context(rows, max_bytes=32)[0], '')
        text, report = self.store.context(rows, max_bytes=4096)
        self.assertIn('PRIVATE', text); self.assertLessEqual(report['bytes'], 4096)
        with self.assertRaises(MemoryError): self.change(receipt['id'], 'close', revision=0)
        with patch('jarvis_core.continuity.MAX_RECORDS', 1):
            command='保存接续：第二=内容｜下一步'
            self.assertEqual(self.reply(command, personal_context={'temporary': False, 'source': self.source(command)})['error'], 'continuity_limit')

    def test_archive_references_and_selection_strict(self):
        source = self.source('fixture'); doc = self.archives.get(source['conversation_id'])['document']
        doc['continuity_ids'] = [uid()]; doc['messages'][0]['continuity_refs'] = [{'id': uid(), 'revision': 1}]
        validate_document(doc)
        doc['continuity_ids'] = [None]
        with self.assertRaises(ValueError): validate_document(doc)

    def test_real_http_permissions_nonce_and_compare_swap(self):
        receipt, _, _ = self.save()
        spec = importlib.util.spec_from_file_location('continuity_test_web', ROOT/'apps/web/server.py')
        web = importlib.util.module_from_spec(spec); spec.loader.exec_module(web)
        server = web.create_server(core=self.core, chat=self.chat, port=0)
        thread = threading.Thread(target=server.serve_forever, kwargs={'poll_interval': .01}, daemon=True); thread.start()
        try:
            host = '127.0.0.1:'+str(server.server_port)
            def request(method, path, payload=None, nonce=True):
                conn = http.client.HTTPConnection(host, timeout=10)
                headers = {'Origin': 'http://'+host, 'Content-Type': 'application/json'}
                if nonce: headers['X-Jarvis-Nonce'] = server.nonce
                conn.request(method, path, None if payload is None else json.dumps(payload), headers)
                res = conn.getresponse(); data = json.loads(res.read()); conn.close(); return res.status, data
            self.assertEqual(request('GET', '/api/continuity', nonce=False)[0], 403)
            self.assertEqual(len(request('GET', '/api/continuity')[1]['records']), 1)
            payload = {'action': 'permissions', 'revision': 1, 'project_id': None, 'providers': ['vertex'], 'request_id': uid()}
            self.assertEqual(request('POST', '/api/continuity/'+receipt['id'], payload)[0], 200)
            self.assertTrue(request('POST', '/api/continuity/'+receipt['id'], payload)[1]['replayed'])
            payload['request_id'] = uid()
            self.assertEqual(request('POST', '/api/continuity/'+receipt['id'], payload)[0], 409)
        finally:
            server.shutdown(); server.server_close(); thread.join(2)


if __name__ == '__main__': unittest.main()
