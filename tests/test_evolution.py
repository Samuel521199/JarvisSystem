"""Growth transactions, failure containment and actual LPAC candidate execution."""
from contextlib import contextmanager
import copy
import http.client
import json
import os
from pathlib import Path
import sys
import tempfile
import threading
import time
import unittest
import uuid
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT/'runtime/node-host'), str(ROOT/'apps/web')]
from jarvis_core import policy
from jarvis_core.evolution import EvolutionManager
from jarvis_core.evolution import recipes
from jarvis_core.evolution.runner import IsolatedRunner, validate_code
from jarvis_core.service import CoreService

GOOD = '''import csv
import io
def transform(data):
    rows = sorted(data['entries'], key=lambda row: row['path'])
    if data['format'] in ('csv', 'tsv'):
        stream = io.StringIO(newline='')
        writer = csv.writer(stream, delimiter=',' if data['format']=='csv' else '\\t', lineterminator='\\n')
        writer.writerow(['path','size'])
        for row in rows:
            writer.writerow([row['path'],row['size']])
        return stream.getvalue()
    result = '| path | size |\\n| --- | ---: |\\n'
    for row in rows:
        path = row['path']
        for old, new in [('&','&amp;'),('<','&lt;'),('>','&gt;'),('\\\\','&#92;'),('|','&#124;'),('\\r','&#13;'),('\\n','&#10;'),('\\t','&#9;')]:
            path = path.replace(old,new)
        result += '| ' + path + ' | ' + str(row['size']) + ' |\\n'
    return result
'''
BAD = "def transform(data):\n    return 'wrong'\n"


class Provider:
    def __init__(self, sources=None):
        self.sources = list(sources or [GOOD])
        self.calls = []
        self.entered = threading.Event()
        self.release = None

    def configuration(self, route, reasoning=None):
        if '::' not in route: raise policy.CoreError('evolution_route_invalid', '模型无效。')

    def generate(self, revision, route, previous, feedback, cancel, checkpoint, reasoning=None):
        self.calls.append({'revision': revision, 'route': route, 'reasoning': reasoning, 'previous': previous, 'feedback': feedback})
        self.entered.set()
        if self.release:
            while not self.release.wait(.01): checkpoint()
        source = self.sources.pop(0) if len(self.sources) > 1 else self.sources[0]
        if source is None: return None, {'status': 'UNKNOWN', 'outcome_uncertain': True}
        return {'code': source, 'notes': 'test fixture, not model evidence'}, {'status': 'SUCCEEDED', 'provider': 'test'}

    def analyze(self, observation, route, cancel, checkpoint, reasoning=None):
        self.calls.append({'observation': observation, 'route': route, 'reasoning': reasoning})
        return '检查结果解释（测试替身）', {'status': 'SUCCEEDED'}


class Runner:
    """Protocol fake; does not evaluate or exec candidate text on the Host."""
    def __init__(self): self.calls = []

    def run(self, source, inputs, checkpoint):
        checkpoint(); self.calls.append((source, copy.deepcopy(inputs)))
        return [recipes.expected(x) if source != BAD else 'wrong' for x in inputs], {'backend': 'test-double'}


class EvolutionTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        (self.root/'source').mkdir()
        self.core = CoreService(self.root/'data'); self.core.initialize(self.root/'source')
        self.provider = Provider(); self.runner = Runner()
        self.manager = EvolutionManager(self.core, provider=self.provider, runner=self.runner, monitor=False)
        self.addCleanup(self.manager.close)

    def submit(self, action, **kwargs):
        job = self.manager.submit({'action': action, 'request_id': uuid.uuid4().hex, **kwargs})
        return self.wait(job)

    def wait(self, job):
        end = time.monotonic()+8
        while self.manager.busy and time.monotonic() < end: time.sleep(.01)
        self.assertFalse(self.manager.busy)
        return self.manager.store.job(job['id'])

    def enable(self, revision=1):
        self.manager.configure({'enabled': True, 'route': 'test::test', 'target_revision': revision})

    def configure(self, **changes):
        fields = ('revision', 'enabled', 'interval_seconds', 'auto_heal', 'target_revision', 'models')
        settings = self.manager.store.settings()
        return self.manager.configure({**{k: settings[k] for k in fields}, **changes})

    def test_generation_independent_validation_activation_and_real_use(self):
        self.assertIsNone(self.manager.snapshot()['selection']['active'])
        job = self.submit('ensure', target_revision=1)
        self.assertEqual(job['status'], 'SUCCEEDED', job)
        self.assertEqual([e['phase'] for e in job['events']], ['STARTED','GENERATING','VALIDATING','ACTIVATED','OBSERVED','FINISHED'])
        active = self.manager.store.selection()['active']
        record, files = self.manager.store.read_package(active)
        self.assertIn('不适用', files['SKILL.md'])
        self.assertEqual(record['state'], 'VERIFIED')
        result = self.submit('execute', input=recipes.cases(1)[-1])
        self.assertEqual(result['result']['text'], recipes.expected(recipes.cases(1)[-1]))
        self.assertEqual(len(self.provider.calls), 1)

    def test_upgrade_preserves_old_contract_and_manual_rollback(self):
        first = self.submit('ensure', target_revision=1)['result']['package']
        second = self.submit('ensure', target_revision=2)['result']['package']
        self.assertNotEqual(first, second)
        self.assertEqual(self.manager.store.selection()['previous'], first)
        self.assertIn('tsv', json.loads(self.manager.store.read_package(second)[1]['manifest.json'])['formats'])
        self.enable(2)
        self.assertEqual(self.submit('rollback')['result']['restored'], first)
        self.assertFalse(self.manager.store.settings()['enabled'])
        self.assertTrue((self.manager.store.packages/second).is_dir())

    def test_healthy_checks_and_repeated_ensure_do_not_call_model(self):
        self.submit('ensure', target_revision=2); self.enable(2)
        self.assertTrue(self.submit('check')['result']['healthy'])
        self.assertFalse(self.submit('ensure', target_revision=2)['result']['changed'])
        self.assertEqual(len(self.provider.calls), 1)

    def test_failed_candidate_is_rejected_then_repaired_with_feedback(self):
        self.provider.sources = [BAD, GOOD]
        job = self.submit('ensure', target_revision=1)
        self.assertEqual(job['status'], 'SUCCEEDED')
        self.assertEqual(len(job['attempts']), 2)
        self.assertFalse(job['attempts'][0]['validation']['passed'])
        self.assertTrue(self.provider.calls[1]['feedback'])
        self.assertEqual(self.manager.store.package(job['attempts'][0]['package'])['state'], 'REJECTED')

    def test_two_bad_candidates_do_not_replace_good_version(self):
        first = self.submit('ensure', target_revision=1)['result']['package']
        self.provider.sources = [BAD]
        job = self.submit('ensure', target_revision=2)
        self.assertEqual(job['status'], 'FAILED')
        self.assertEqual(len(job['attempts']), 2)
        self.assertEqual(self.manager.store.selection()['active'], first)

    def test_corrupt_package_detected_and_fallback_verified(self):
        first = self.submit('ensure', target_revision=1)['result']['package']
        second = self.submit('ensure', target_revision=2)['result']['package']
        (self.manager.store.packages/second/'candidate.py').write_text(BAD, encoding='utf-8')
        job = self.submit('check')
        self.assertFalse(job['result']['healthy'])
        self.assertEqual(job['result']['classification'], 'fault')
        self.assertNotIn('rollback', job)
        self.assertEqual(self.manager.store.selection()['active'], second)
        healed = self.submit('heal')
        self.assertEqual(healed['rollback']['to'], first)
        self.assertEqual(healed['result']['restored_revision'], 2)
        self.assertEqual(self.manager.store.package(self.manager.store.selection()['active'])['revision'], 2)

    def test_enabled_check_records_missing_optional_without_building(self):
        self.enable(2)
        job = self.submit('check')
        self.assertEqual(job['result']['classification'], 'missing_optional')
        self.assertIsNone(self.manager.store.selection()['active'])
        self.assertEqual(self.provider.calls, [])

    def test_no_model_when_auto_disabled(self):
        self.assertFalse(self.submit('check')['result']['healthy'])
        self.assertEqual(self.provider.calls, [])

    def test_unknown_model_result_never_retried(self):
        self.provider.sources = [None]
        job = self.submit('ensure', target_revision=1)
        self.assertEqual(job['status'], 'UNKNOWN')
        self.assertEqual(len(self.provider.calls), 1)
        self.assertIsNone(self.manager.store.selection()['active'])

    def test_singleflight_cancellation_and_idempotent_request(self):
        self.provider.release = threading.Event()
        payload = {'action':'ensure','target_revision':1,'request_id':uuid.uuid4().hex}
        job = self.manager.submit(payload)
        self.assertTrue(self.provider.entered.wait(1))
        self.assertEqual(self.manager.submit(payload)['id'], job['id'])
        with self.assertRaises(policy.CoreError): self.manager.submit({**payload, 'request_id': uuid.uuid4().hex})
        self.manager.cancel(job['id'])
        self.assertEqual(self.wait(job)['status'], 'CANCELLED')
        self.assertIsNone(self.manager.store.selection()['active'])

    def test_stale_base_and_unverified_packages_cannot_activate(self):
        job, _ = self.manager.store.create_job({'action':'ensure','target_revision':1,'request_id':'manual123'})
        base = self.manager.store.selection()
        ident = self.manager.store.stage({'code': GOOD}, 1, {})
        with self.assertRaises(policy.CoreError): self.manager.store.activate(ident, base, job)
        self.manager.store.assess(ident, 'VERIFIED', {})
        self.manager.store.activate(ident, base, job)
        with self.assertRaises(policy.CoreError): self.manager.store.activate(ident, base, job)

    def test_interrupted_publication_deactivated_and_not_replayed(self):
        store = self.manager.store
        job, _ = store.create_job({'action':'ensure','target_revision':1,'request_id':'recover123'})
        ident = store.stage({'code': GOOD}, 1, {})
        store.assess(ident, 'VERIFIED', {})
        store.activate(ident, store.selection(), job)
        store.recover()
        self.assertEqual(store.job(job['id'])['status'], 'INTERRUPTED')
        self.assertIsNone(store.selection()['active'])
        self.assertEqual(self.provider.calls, [])

    def test_metadata_or_extra_file_drift_rejected(self):
        ident = self.submit('ensure', target_revision=1)['result']['package']
        (self.manager.store.packages/ident/'debug.txt').write_text('junk')
        with self.assertRaises(policy.CoreError): self.manager.store.read_package(ident)

    def test_background_incident_dedupe_and_daily_budget(self):
        store = self.manager.store
        self.assertTrue(store.reserve_incident('one'))
        self.assertFalse(store.reserve_incident('one'))
        for n in range(3): self.assertTrue(store.reserve_incident('n'+str(n)))
        self.assertFalse(store.reserve_incident('five'))

    def test_invalid_inputs_never_reach_worker(self):
        self.submit('ensure', target_revision=1)
        count = len(self.runner.calls)
        for value in ({}, {'format':'csv','entries':[{'path':'x','size':True}]}, {'format':'csv','entries':[],'path':'C:/'}):
            with self.assertRaises(policy.CoreError): self.submit('execute', input=value)
        self.assertEqual(len(self.runner.calls), count)

    def test_candidate_static_rejection_before_execution(self):
        for source in ('import os\ndef transform(data):\n return os.getcwd()',
                       'def transform(data):\n return data.__class__',
                       'def transform(data):\n return open("secret").read()',
                       'def transform(data=print("effect")):\n return "x"',
                       'import csv\nprint("effect")\ndef transform(data):\n return "x"'):
            with self.assertRaises(policy.CoreError): validate_code(source)

    def test_real_input_regression_rolls_back_without_returning_bad_output(self):
        first = self.submit('ensure', target_revision=1)['result']['package']
        self.submit('ensure', target_revision=2)
        real = self.runner.run
        self.runner.run = lambda source, inputs, cp: (['bad'], {}) if len(inputs)==1 else real(source, inputs, cp)
        job = self.submit('execute', input=recipes.cases(1)[0])
        self.assertEqual(job['status'], 'FAILED')
        self.assertIsNone(job['result'])
        self.assertEqual(self.manager.store.selection()['active'], first)

    def test_runtime_repair_survives_restart_while_original_call_stays_failed(self):
        self.submit('ensure',target_revision=1)
        self.submit('ensure',target_revision=2)
        self.enable(2)
        self.configure(auto_heal=True)
        real = self.runner.run
        self.runner.run = lambda source, inputs, cp: (['bad'], {}) if len(inputs)==1 else real(source, inputs, cp)
        job = self.submit('execute',input=recipes.cases(1)[0])
        self.assertEqual(job['status'],'FAILED')
        self.assertEqual(job['error'],'evolution_execution_recovered')
        repaired = self.manager.store.selection()['active']
        self.assertTrue(job['activation_confirmed'])
        self.manager.store.recover()
        self.assertEqual(self.manager.store.selection()['active'],repaired)

    def test_stopped_core_blocks_dispatch(self):
        self.core.ledger.stop('test')
        with self.assertRaises(Exception): self.submit('ensure', target_revision=1)
        self.assertEqual(self.provider.calls, [])

    def test_memory_pressure_stops_before_paid_call(self):
        with patch.object(self.manager, '_resources', side_effect=policy.CoreError('evolution_memory_pressure', '内存不足')):
            job = self.submit('ensure', target_revision=1)
        self.assertEqual(job['error'], 'evolution_memory_pressure')
        self.assertEqual(self.provider.calls, [])

    def test_temporary_resource_failure_does_not_quarantine_healthy_code(self):
        active = self.submit('ensure', target_revision=1)['result']['package']
        with patch.object(self.manager, '_resources', side_effect=policy.CoreError('evolution_memory_pressure', '内存不足')):
            job = self.submit('check')
        self.assertIsNone(job['error'])
        self.assertTrue(job['result']['healthy'])
        self.assertEqual(self.manager.store.selection()['active'], active)
        self.assertEqual(self.manager.store.package(active)['state'], 'VERIFIED')

    def test_healthy_automatic_records_bounded_and_failure_preserved(self):
        store = self.manager.store
        for n in range(40):
            job, _ = store.create_job({'action':'check','request_id':'auto-'+str(n).zfill(8)})
            store.update(job, status='SUCCEEDED', result={'healthy':True})
        job, _ = store.create_job({'action':'check','request_id':'auto-failed'})
        store.update(job,status='FAILED',error='test failure')
        store.compact_health_checks()
        with store.connection() as db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM jobs').fetchone()[0],31)
        self.assertEqual(store.job(job['id'])['status'],'FAILED')

    def test_post_activation_failure_rolls_back(self):
        first = self.submit('ensure', target_revision=1)['result']['package']
        real = self.manager._health
        def health(ident):
            if ident != first: raise policy.CoreError('evolution_regression', 'fault injection')
            return real(ident)
        with patch.object(self.manager, '_health', side_effect=health):
            job = self.submit('ensure', target_revision=2)
        self.assertEqual(job['status'], 'FAILED')
        self.assertEqual(self.manager.store.selection()['active'], first)

    def test_future_database_not_migrated(self):
        with self.manager.store.connection() as db: db.execute('PRAGMA user_version=99')
        from jarvis_core.evolution.store import EvolutionStore
        with self.assertRaises(policy.CoreError): EvolutionStore(self.core, 'test::test')
        with self.manager.store.connection() as db:
            self.assertEqual(db.execute('PRAGMA user_version').fetchone()[0], 99)

    def test_gap_is_not_a_fault_and_inspection_never_runs_worker(self):
        active = self.submit('ensure', target_revision=1)['result']['package']
        self.configure(target_revision=2, auto_heal=True)
        calls = len(self.runner.calls)
        checked = self.submit('check')
        self.assertEqual(checked['result']['classification'], 'capability_gap')
        self.assertTrue(checked['result']['healthy'])
        self.assertFalse(self.submit('heal')['result']['changed'])
        self.assertEqual(len(self.runner.calls), calls)
        self.assertEqual(len(self.provider.calls), 1)
        self.assertEqual(self.manager.store.selection()['active'], active)

    def test_heal_restores_original_contract_using_its_own_model(self):
        active = self.submit('ensure', target_revision=1)['result']['package']
        models = self.manager.store.settings()['models']
        models['heal']['primary'] = {'route':'test::repair', 'reasoning':'high'}
        self.configure(target_revision=2, models=models)
        (self.manager.store.packages/active/'candidate.py').write_text(BAD, encoding='utf-8')
        result = self.submit('heal')
        self.assertEqual(result['status'], 'SUCCEEDED', result)
        self.assertEqual(result['result']['restored_revision'], 1)
        self.assertEqual(self.provider.calls[-1]['route'], 'test::repair')
        self.assertEqual(self.provider.calls[-1]['reasoning'], 'high')
        self.assertEqual(self.provider.calls[-1]['revision'], 1)

    def test_diagnosis_is_advisory_and_has_independent_model(self):
        models = self.manager.store.settings()['models']
        models['inspect']['primary'] = {'route':'test::diagnose', 'reasoning':'low'}
        self.configure(models=models)
        before = self.manager.store.selection()
        job = self.submit('analyze')
        self.assertTrue(job['result']['advisory_only'])
        self.assertEqual(self.provider.calls[-1]['route'], 'test::diagnose')
        self.assertEqual(self.provider.calls[-1]['reasoning'], 'low')
        self.assertEqual(self.manager.store.selection(), before)
        self.assertEqual(self.runner.calls, [])

    def test_fallback_counts_against_two_calls_and_preserves_actual_route(self):
        models = self.manager.store.settings()['models']
        models['evolve'] = {'primary':{'route':'test::primary','reasoning':'high'},
                            'fallback':{'route':'test::fallback','reasoning':'low'}}
        self.configure(models=models)
        original = self.provider.generate
        def generate(revision, route, *args, **kwargs):
            if route == 'test::primary':
                return None, {'status':'FAILED','error_category':'quota_exhausted'}
            return original(revision, route, *args, **kwargs)
        with patch.object(self.provider, 'generate', side_effect=generate) as call:
            job = self.submit('ensure', target_revision=1)
        self.assertEqual(job['status'], 'SUCCEEDED', job)
        self.assertEqual(call.call_count, 2)
        self.assertEqual(len(job['attempts']), 2)
        self.assertTrue(job['attempts'][1]['coding']['fallback'])
        self.assertEqual(job['attempts'][1]['coding']['selection'], models['evolve']['fallback'])

    def test_unknown_partial_and_offline_never_switch_models(self):
        models = self.manager.store.settings()['models']
        models['evolve']['fallback'] = {'route':'test::fallback','reasoning':None}
        self.configure(models=models)
        for receipt in ({'status':'UNKNOWN','error_category':'provider_unavailable'},
                        {'status':'FAILED','error_category':'network_offline'},
                        {'status':'FAILED','error_category':'quota_exhausted','output_incomplete':True}):
            with self.subTest(receipt=receipt), patch.object(self.provider, 'generate', return_value=(None,receipt)) as call:
                job = self.submit('ensure', target_revision=1)
                self.assertNotEqual(job['status'], 'SUCCEEDED')
                self.assertEqual(call.call_count, 1)

    def test_config_compare_and_swap_and_job_policy_snapshot(self):
        old = self.manager.store.settings()
        self.configure(interval_seconds=3600)
        with self.assertRaises(policy.CoreError) as caught: self.configure(revision=old['revision'])
        self.assertEqual(caught.exception.code, 'evolution_conflict')
        job = self.submit('check')
        frozen = copy.deepcopy(job['policy'])
        self.configure(interval_seconds=900)
        self.assertEqual(self.manager.store.job(job['id'])['policy'], frozen)

    def test_disabled_primary_can_fallback_before_dispatch(self):
        models = self.manager.store.settings()['models']
        primary = models['evolve']['primary']['route']
        models['evolve']['fallback'] = {'route':'test::fallback','reasoning':None}
        self.configure(models=models)
        original = self.provider.generate
        def generate(revision, route, *args, **kwargs):
            if route == primary: raise policy.CoreError('evolution_route_invalid', 'disabled')
            return original(revision, route, *args, **kwargs)
        with patch.object(self.provider, 'generate', side_effect=generate):
            job = self.submit('ensure', target_revision=1)
        self.assertEqual(job['status'], 'SUCCEEDED', job)
        self.assertFalse(job['attempts'][0]['coding']['dispatched'])
        self.assertEqual(self.provider.calls[-1]['route'], 'test::fallback')

    def test_inspection_diagnosis_fallback_does_not_publish(self):
        models = self.manager.store.settings()['models']
        models['inspect']['fallback'] = {'route':'test::fallback','reasoning':'low'}
        self.configure(models=models)
        with patch.object(self.provider, 'analyze', side_effect=[
                (None,{'status':'FAILED','error_category':'authentication'}),
                ('advice',{'status':'SUCCEEDED'})]) as call:
            job = self.submit('analyze')
        self.assertEqual(job['status'], 'SUCCEEDED', job)
        self.assertEqual(call.call_count, 2)
        self.assertTrue(job['attempts'][1]['coding']['fallback'])
        self.assertEqual(self.manager.store.snapshot()['packages'], [])

    def test_automatic_heal_requires_opt_in_and_separate_fault_job(self):
        active = self.submit('ensure', target_revision=1)['result']['package']
        (self.manager.store.packages/active/'candidate.py').write_text(BAD, encoding='utf-8')
        checked = self.submit('check')
        self.manager._queue_automatic_heal(checked)
        self.assertEqual(len(self.provider.calls), 1)
        self.configure(auto_heal=True)
        self.manager._queue_automatic_heal(checked)
        self.wait(checked)
        healed = self.manager.store.snapshot()['jobs'][0]
        self.assertEqual(healed['action'], 'heal')
        self.assertEqual(healed['cause']['inspection_job'], checked['id'])
        self.assertEqual(self.manager.store.job(checked['id'])['attempts'], [])
        self.assertEqual(healed['status'], 'SUCCEEDED')

    def test_v1_settings_migration_preserves_artifacts_without_enabling_healing(self):
        from jarvis_core.evolution.store import EvolutionStore
        from jarvis_core.releases import RuntimeSlots
        self.submit('ensure', target_revision=1)
        before = self.manager.store.selection()
        with self.manager.store.connection() as db:
            db.execute('UPDATE settings SET document=?', (json.dumps({'enabled':True,'interval_seconds':300,'route':'test::old','target_revision':2}),))
            db.execute('PRAGMA user_version=1')
        migrated = EvolutionStore(self.core, 'test::new')
        self.assertEqual(migrated.selection(), before)
        value = migrated.settings()
        self.assertEqual(value['interval_seconds'], 300)
        self.assertTrue(value['enabled'])
        self.assertFalse(value['auto_heal'])
        self.assertEqual(value['models']['evolve']['primary']['route'], 'test::old')
        data_format = {'optional_versions':{'evolution/evolution.db':2}}
        self.assertFalse(RuntimeSlots._compatible('0.1.63', data_format))
        self.assertTrue(RuntimeSlots._compatible('0.1.64', data_format))


class EvolutionHTTPTests(unittest.TestCase):
    def setUp(self):
        from tests.test_web import FakeChat, web
        from jarvis_core.workspace import WorkspaceService
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name); (self.root/'source').mkdir()
        self.core = CoreService(self.root/'data'); self.core.initialize(self.root/'source')
        self.provider = Provider()
        self.manager = EvolutionManager(self.core, provider=self.provider, runner=Runner(), monitor=False)
        self.server = web.LocalChatServer(('127.0.0.1',0), self.core, FakeChat(), workspace=WorkspaceService(self.core))
        self.server.evolution = self.manager
        self.thread = threading.Thread(target=self.server.serve_forever, kwargs={'poll_interval':.01}, daemon=True)
        self.thread.start(); self.addCleanup(self.server.server_close); self.addCleanup(self.server.shutdown)
        self.port = self.server.server_address[1]

    def request(self, method, path, payload=None, headers=None):
        connection = http.client.HTTPConnection('127.0.0.1', self.port, timeout=3)
        values = {'Origin': f'http://127.0.0.1:{self.port}', 'X-Jarvis-Nonce':self.server.nonce}
        if payload is not None: values['Content-Type'] = 'application/json'
        values.update(headers or {})
        try:
            connection.request(method,path,body=json.dumps(payload) if payload is not None else None,headers=values)
            response=connection.getresponse(); return response.status,response.read()
        finally: connection.close()

    def test_auth_assets_strict_requests_and_asynchronous_job(self):
        self.assertEqual(self.request('GET','/api/evolution',headers={'X-Jarvis-Nonce':'bad'})[0],403)
        self.assertEqual(self.request('GET','/api/evolution',headers={'Origin':'https://evil.example'})[0],403)
        self.assertEqual(self.request('GET','/evolution.js')[0],200)
        self.assertEqual(self.request('GET','/evolution.js?file=secret')[0],404)
        self.assertEqual(self.request('GET','/api/evolution?other=1')[0],404)
        self.assertEqual(self.request('POST','/api/evolution/jobs',{'action':'shell','request_id':'invalid123'})[0],400)
        status,body=self.request('POST','/api/evolution/jobs',{'action':'ensure','target_revision':1,'request_id':'http123456'})
        self.assertEqual(status,202); job=json.loads(body)
        end=time.monotonic()+5
        while self.manager.busy and time.monotonic()<end:time.sleep(.01)
        status,body=self.request('GET','/api/evolution/jobs/'+job['id'])
        self.assertEqual(status,200);self.assertEqual(json.loads(body)['status'],'SUCCEEDED')

    def test_coding_does_not_occupy_chat_lane(self):
        self.provider.release=threading.Event()
        status,body=self.request('POST','/api/evolution/jobs',{'action':'ensure','target_revision':1,'request_id':'httpparallel'})
        self.assertEqual(status,202);self.assertTrue(self.provider.entered.wait(1))
        try:
            start=time.monotonic()
            self.assertEqual(self.request('POST','/api/chat',{'message':'hello'})[0],200)
            self.assertLess(time.monotonic()-start,1)
        finally:
            self.manager.cancel(json.loads(body)['id']);self.provider.release.set()

    def test_growth_initialization_failure_does_not_block_host_start(self):
        from tests.test_web import FakeChat, web
        with patch('jarvis_core.evolution.EvolutionManager', side_effect=policy.CoreError('evolution_schema_invalid','future schema')):
            server=web.create_server(core=self.core,chat=FakeChat(),port=0)
        try:
            self.assertIsNone(server.evolution)
            self.assertIsNotNone(server.modules)
            self.assertEqual(server.chat.reply('hello')['status'],'SUCCEEDED')
        finally: server.server_close()


@unittest.skipUnless(os.name == 'nt', 'Windows LPAC required')
class ActualWorkerTests(unittest.TestCase):
    def test_compiles_and_executes_candidate_with_real_lpac(self):
        runner = IsolatedRunner()
        inputs = recipes.cases(2, heldout=True)
        outputs, evidence = runner.run(GOOD, inputs, lambda: None)
        self.assertEqual(outputs, [recipes.expected(x) for x in inputs])
        self.assertTrue(evidence['lpac'])

    def test_infinite_candidate_is_terminated_by_real_limits(self):
        runner = IsolatedRunner()
        start = time.monotonic()
        with self.assertRaises(policy.CoreError):
            runner.run('def transform(data):\n    while True:\n        pass\n', recipes.cases(1)[:1], lambda: None)
        self.assertLess(time.monotonic()-start, 15)


if __name__ == '__main__': unittest.main()
