"""Improvement admission, immutable baselines and receipt-driven results."""
import copy
import json
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch

import test_coding_workflow as fixture
from jarvis_core import policy
from jarvis_core.coding_demand import CodingDemands
from jarvis_core.conversations import ConversationStore
from test_conversations import document


class CodingDemandTests(fixture.CodingTests):
    def wait(self, item):
        deadline = time.monotonic() + 100
        while time.monotonic() < deadline:
            value = self.bridge.detail(self.cid, item['task_id'])
            if value['task']['status'] not in {'READY', 'RUNNING', 'CANCELLING'}: return value
            time.sleep(.1)
        self.fail('bounded coding task exceeded the test timeout: '+str(value))

    def setUp(self):
        super().setUp()
        doc = document(); doc['project_id'] = self.project['id']
        ConversationStore(self.core).put(self.cid, {'revision': 0, 'document': doc})
        self.demands = CodingDemands(self.core, self.bridge)

    def payload(self):
        return {'request_id': uuid.uuid4().hex, 'prompt': '修复求和，保留空表结果为0', 'coding': {
            'paths': ['calc.py'], 'cases': fixture.CASES,
            'heldout_cases': [{'input': [9], 'expected': '9'}, {'input': [-2, 1], 'expected': '-1'}],
            'model': 'vertex::gemini-3.8-flash', 'coding_provider': 'gateway', 'build_recipe': 'python-zipapp-v1'}}

    def test_full_bridge_zero_call_preview_receipt_apply_remains_explicit(self):
        p = self.payload(); job = self.demands.propose(self.cid, p)
        self.assertEqual(job['status'], 'PROPOSED'); self.assertFalse(self.calls)
        self.assertEqual(self.demands.propose(self.cid, p)['id'], job['id'])
        self.assertEqual(self.demands.lookup(self.cid, p['request_id'])['id'], job['id'])
        with self.assertRaises(policy.CoreError): self.demands.propose(self.cid, {**p, 'prompt': '不同目标'})
        started = self.demands.start(self.cid, job['id'], {})
        self.report(started)
        done = CodingDemands(self.core, self.bridge).bound(self.cid, job['id'])
        self.assertEqual(done['status'], 'SUCCEEDED', done)
        self.assertEqual(done['result']['cases'], 4)
        self.assertEqual(done['result']['delivery'], 'verified_candidate')
        self.assertFalse(done['result']['automatically_applied'])
        self.assertEqual((self.source/'calc.py').read_bytes(), b'\xef\xbb\xbf'+fixture.BAD.encode())
        self.assertEqual(len(self.calls), 1)
        self.assertNotIn('heldout', self.calls[0])
        self.demands.start(self.cid, job['id'], {})
        self.assertEqual(len(self.calls), 1)

    def test_concurrent_start_and_lost_response_use_one_atomic_link(self):
        self.manager.queue.set_paused(True)
        job = self.demands.propose(self.cid, self.payload())
        with ThreadPoolExecutor(max_workers=2) as pool:
            rows = list(pool.map(lambda _: self.demands.start(self.cid, job['id'], {}), range(2)))
        self.assertEqual(rows[0]['task_id'], rows[1]['task_id'])
        with self.core.ledger.connection() as db:
            self.assertEqual(db.execute('SELECT count(*) FROM tasks WHERE request_key=?', ('web-'+job['id'],)).fetchone()[0], 1)
        with patch.object(self.bridge, 'submit', side_effect=AssertionError('must not resubmit')):
            self.assertEqual(CodingDemands(self.core, self.bridge).start(self.cid, job['id'], {})['task_id'], rows[0]['task_id'])
        self.assertFalse(self.calls)
        self.demands.cancel(self.cid, job['id'], {})

    def test_snapshot_stale_at_start_and_after_enqueue(self):
        job = self.demands.propose(self.cid, self.payload())
        (self.source/'calc.py').write_text(fixture.GOOD)
        with self.assertRaises(policy.CoreError): self.demands.start(self.cid, job['id'], {})
        self.assertFalse(self.calls)
        self.demands.cancel(self.cid, job['id'], {})
        new = self.demands.reanalyse(self.cid, job['id'], {'request_id': uuid.uuid4().hex})
        self.assertEqual(new['request']['origin']['previous_job'], job['id'])
        self.manager.queue.set_paused(True)
        queued = self.demands.start(self.cid, new['id'], {})
        (self.source/'calc.py').write_text(fixture.BAD)
        self.manager.queue.set_paused(False)
        self.wait(queued)
        done = self.demands.bound(self.cid, new['id'])
        self.assertEqual(done['status'], 'FAILED', done); self.assertFalse(self.calls)
        self.assertEqual(done['error']['code'], 'coding_demand_conflict')

    def test_failed_independent_check_not_misreported_as_success(self):
        self.sources = ['def transform(data):\n    return "6" if data else "0"\n']
        job = self.demands.propose(self.cid, self.payload())
        started = self.demands.start(self.cid, job['id'], {})
        report = self.report(started)
        self.assertFalse(report['coding']['passed'])
        done = self.demands.bound(self.cid, job['id'])
        self.assertEqual(done['status'], 'FAILED'); self.assertEqual(len(self.calls), 2)
        self.assertFalse(done['result']['verified'])
        self.assertEqual(done['result']['delivery'], 'diagnostic_only')

    def test_unknown_reanalysis_and_cancel_never_automatically_retry(self):
        self.sources = [None]
        old = self.demands.propose(self.cid, self.payload())
        self.wait(self.demands.start(self.cid, old['id'], {}))
        self.assertEqual(self.demands.bound(self.cid, old['id'])['status'], 'UNKNOWN')
        self.demands.start(self.cid, old['id'], {}); self.assertEqual(len(self.calls), 1)
        p = {'request_id': uuid.uuid4().hex}
        new = self.demands.reanalyse(self.cid, old['id'], p)
        self.assertEqual(new['status'], 'PROPOSED'); self.assertEqual(len(self.calls), 1)
        self.assertEqual(self.demands.reanalyse(self.cid, old['id'], p)['id'], new['id'])
        self.demands.cancel(self.cid, new['id'], {})
        self.assertEqual(self.demands.start(self.cid, new['id'], {})['status'], 'CANCELLED')

    def test_cancel_running_and_scope_and_receipt_tampering(self):
        job = self.demands.propose(self.cid, self.payload())
        other = uuid.uuid4().hex; doc = document(); doc['project_id'] = self.project['id']
        ConversationStore(self.core).put(other, {'revision': 0, 'document': doc})
        for call in (lambda: self.demands.bound(other, job['id']), lambda: self.demands.start(other, job['id'], {}), lambda: self.demands.cancel(other, job['id'], {})):
            with self.assertRaises(policy.CoreError): call()
        entered = threading.Event()
        def blocked(prompt, instructions, guard):
            entered.set()
            while True:
                threading.Event().wait(.02); guard()
        self.manager.skills.coding_generate = blocked
        started = self.demands.start(self.cid, job['id'], {})
        self.assertTrue(entered.wait(15))
        self.demands.cancel(self.cid, job['id'], {})
        self.wait(started)
        self.assertEqual(self.demands.bound(self.cid, job['id'])['status'], 'CANCELLED')

    def test_modified_or_forged_binding_rejected(self):
        job = self.demands.propose(self.cid, self.payload())
        stored = self.demands.stored(self.cid, job['id'])
        args = copy.deepcopy(stored['frozen']['arguments']); args.pop('conversation_id')
        args['coding_demand'] = {'id': job['id'], 'digest': job['proposal']['binding']}
        args['cases'][0]['expected'] = 'fake'
        with self.assertRaises(policy.CoreError):
            self.bridge.submit(self.cid, {'request_id': 'web-'+job['id'], 'mode': 'skill', **args})
        self.assertFalse(self.calls)
        self.assertIsNone(self.demands.bound(self.cid, job['id'])['task_id'])

    def test_transaction_failure_rolls_back_task_and_proposal_link(self):
        job = self.demands.propose(self.cid, self.payload())
        with patch('jarvis_core.coding_demand.write', side_effect=RuntimeError('injected before commit')):
            with self.assertRaises(RuntimeError): self.demands.start(self.cid, job['id'], {})
        with self.core.ledger.connection() as db:
            self.assertEqual(db.execute('SELECT count(*) FROM tasks WHERE request_key=?', ('web-'+job['id'],)).fetchone()[0], 0)
        self.assertIsNone(self.demands.bound(self.cid, job['id'])['task_id']); self.assertFalse(self.calls)

    def test_execution_uses_declared_budget(self):
        begin = self.core.ledger.begin_dispatch
        def short_budget(*args, **kwargs):
            record = begin(*args, **kwargs)
            record['task']['budget']['max_runtime_seconds'] = 0
            return record
        job = self.demands.propose(self.cid, self.payload())
        with patch.object(self.core.ledger, 'begin_dispatch', side_effect=short_budget):
            done = self.wait(self.demands.start(self.cid, job['id'], {}))
        self.assertEqual(done['error']['code'], 'limit_exceeded'); self.assertFalse(self.calls)

    def test_queue_restart_keeps_one_task_and_waits_for_review(self):
        self.manager.queue.set_paused(True)
        job = self.demands.propose(self.cid, self.payload())
        first = self.demands.start(self.cid, job['id'], {})
        self.manager.close()
        self.manager = fixture.ComputerWeb(self.core, fixture.fixture.FakeChat()); self.addCleanup(self.manager.close)
        self.bridge = fixture.ConversationTasks(self.core, self.manager)
        self.demands = CodingDemands(self.core, self.bridge)
        self.assertTrue(self.manager.queue.snapshot()['paused'])
        with patch.object(self.bridge, 'submit', side_effect=AssertionError('no replay')):
            self.assertEqual(self.demands.start(self.cid, job['id'], {})['task_id'], first['task_id'])
        self.assertFalse(self.calls)
        self.assertEqual(self.demands.cancel(self.cid, job['id'], {})['status'], 'CANCELLED')

    def test_receipt_tampering_cannot_return_verified_result(self):
        (self.source/'calc.py').write_text(fixture.GOOD)
        job = self.demands.propose(self.cid, self.payload())
        started = self.demands.start(self.cid, job['id'], {})
        self.report(started)
        artifact = self.core.ledger.record(task_id=started['task_id'])['artifact']
        (self.core.ledger.artifact_dir/artifact['path']).write_bytes(b'{}')
        with self.assertRaises(policy.CoreError): self.demands.bound(self.cid, job['id'])
        self.assertFalse(self.calls)

    def test_http_scope_token_and_saved_proposal(self):
        import http.client
        import server as web
        from jarvis_core.evolution import EvolutionManager
        from test_evolution import Provider, Runner
        server = web.LocalChatServer(('127.0.0.1', 0), self.core, fixture.fixture.FakeChat(), workspace=self.workspace)
        server.evolution = EvolutionManager(self.core, provider=Provider(), runner=Runner(), monitor=False)
        server.conversation_tasks = self.bridge
        thread = threading.Thread(target=server.serve_forever, kwargs={'poll_interval': .02}, daemon=True); thread.start()
        try:
            def request(method, path, payload=None, token=True, origin=None):
                host = '127.0.0.1:'+str(server.server_port)
                headers = {'Origin': origin or 'http://'+host, 'Content-Type': 'application/json'}
                if token: headers['X-Jarvis-Nonce'] = server.nonce
                conn = http.client.HTTPConnection(host, timeout=15)
                conn.request(method, path, json.dumps(payload) if payload is not None else None, headers)
                response = conn.getresponse(); result = response.status, response.read(); conn.close(); return result
            base = '/api/conversation-growth/'+self.cid
            self.assertEqual(request('GET', base, token=False)[0], 403)
            self.assertEqual(request('POST', base, self.payload(), origin='https://evil.example')[0], 403)
            p = self.payload(); code, raw = request('POST', base, p); self.assertEqual(code, 200, raw)
            job = json.loads(raw); self.assertEqual(job['request']['action'], 'coding')
            self.assertEqual(json.loads(request('GET', base+'/requests/'+p['request_id'])[1])['id'], job['id'])
            self.assertNotEqual(request('POST', base, {'request_id': p['request_id'], 'prompt': 'CSV'})[0], 200)
            self.assertEqual(request('GET', base+'/'+job['id']+'/artifact')[0], 400)
            self.assertEqual(request('POST', base+'/'+job['id']+'/cancel', {})[0], 200)
            self.assertEqual(json.loads(request('GET', base+'/'+job['id'])[1])['status'], 'CANCELLED')
            self.assertFalse(self.calls)
        finally:
            server.shutdown(); server.server_close(); thread.join(2)


for name in dir(fixture.CodingTests):
    if name.startswith('test_') and name not in CodingDemandTests.__dict__:
        setattr(CodingDemandTests, name, None)
