"""Real ledger/FIFO contracts with deterministic, non-network model fixtures."""
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
import json
from pathlib import Path
import sys
import tempfile
import time
import unittest
import uuid

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT/'runtime/node-host'), str(ROOT/'adapters/computer-use'), str(ROOT/'tests')]
from jarvis_core.service import CoreService
from jarvis_core.policy import CoreError
from jarvis_core.team_tasks import TeamTaskService
from jarvis_core.team_protocol import CAPABILITY, decode, validate
from jarvis_core.conversation_tasks import ConversationTasks
from jarvis_computer.web import ComputerWeb
from test_web import FakeChat

PROPOSAL = {'summary': '分阶段制作本机助手', 'steps': [
    {'id': 's1', 'title': '先做样例', 'detail': '明确输入输出，验证最小实现。'}],
    'assumptions': ['普通 PC'], 'risks': ['尚需测量实际资源']}
REVIEW = {'summary': '方案可以作为起点，资源尚待测试', 'verdict': 'needs_revision',
          'findings': [{'step_id': 's1', 'severity': 'concern', 'issue': '补充内存测量'}],
          'criteria': [{'criterion_id': 'c1', 'status': 'uncertain', 'reason': '未提供实测'}]}


class Provider:
    def __init__(self): self.revision = 0
    def configuration(self, route, reasoning=None):
        if route not in {'local::planner', 'local::reviewer'} or reasoning not in {None, 'low'}:
            raise CoreError('invalid_route', 'Unregistered fixture model')
        return {'providers': {'local': {'model': route.split('::')[1], 'max_output_tokens': 4096,
                                      'revision': self.revision}}}, 'local'
    def receipt(self, response, config, provider):
        return {k: response[k] for k in ('status', 'usage', 'outcome_uncertain') if k in response}


class Calls:
    def __init__(self): self.requests, self.hook, self.change = [], None, None
    def probe(self, config, provider, prompt, data_dir, guard, **options):
        assert isinstance(guard()['security_epoch'], int)
        self.requests.append({'prompt': json.loads(prompt), 'options': options, 'config': deepcopy(config)})
        if self.hook: self.hook(guard, options)
        index = len(self.requests)-1
        response = {'status': 'SUCCEEDED', 'text': json.dumps(PROPOSAL if index == 0 else REVIEW),
                    'usage': {'input_tokens': 10, 'output_tokens': 20}, 'outcome_uncertain': False}
        if self.change: self.change(index, response)
        return response


class TeamTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(); self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name); source = self.root/'sample'; source.mkdir()
        self.core = CoreService(self.root/'data'); self.core.initialize(source)
        self.calls, self.provider = Calls(), Provider()
        self.service = TeamTaskService(self.core, model_calls=self.calls, provider=self.provider)
        self.cid = uuid.uuid4().hex
        self.args = {'prompt': '帮我设计本机助手的最小实现', 'criteria': ['资源占用有实测'],
                     'planner_model': 'local::planner', 'reviewer_model': 'local::reviewer',
                     'conversation_id': self.cid}

    def prepare(self, key=None):
        return self.core.ledger.prepare(key or uuid.uuid4().hex, self.service.admit(self.args),
                                        capability=CAPABILITY, model_requests=99, runtime_seconds=180)

    def run_task(self):
        prepared = self.prepare()
        result = self.service.run(prepared['action']['action_id'])
        return prepared, result

    def test_separate_contexts_fixed_budget_report_and_idempotence(self):
        prepared, result = self.run_task()
        self.assertEqual(result['action']['status'], 'CONFIRMED')
        self.assertEqual(result['task']['budget']['max_cost_units'], 2)
        report = json.loads((self.core.ledger.artifact_dir/result['artifact']['path']).read_bytes())
        self.assertFalse(report['checks']['semantic_acceptance_verified'])
        self.assertEqual(report['decision'], 'needs_revision')
        self.assertEqual(len(self.calls.requests), 2)
        first, second = self.calls.requests
        self.assertEqual(set(first['prompt']), {'goal', 'criteria'})
        self.assertEqual(set(second['prompt']), {'goal', 'criteria', 'proposal'})
        self.assertNotEqual(first['options']['instructions'], second['options']['instructions'])
        self.assertNotIn(self.cid, json.dumps(self.calls.requests))
        self.assertTrue(all(r['config']['providers']['local']['max_output_tokens'] == 2048 for r in self.calls.requests))
        self.service.run(prepared['action']['action_id'])
        self.assertEqual(len(self.calls.requests), 2)
        self.assertEqual([r['state'] for r in self.service.calls(result['task']['task_id'])], ['SUCCEEDED']*2)

    def test_unknown_retains_reservation_and_never_starts_reviewer(self):
        self.calls.change = lambda i, r: r.update(status='UNKNOWN', outcome_uncertain=True)
        prepared, result = self.run_task()
        self.assertEqual(result['action']['status'], 'UNKNOWN')
        self.assertIsNone(result['artifact'])
        self.assertEqual(self.service.calls(result['task']['task_id'])[0]['state'], 'UNCERTAIN')
        self.service.run(prepared['action']['action_id'])
        self.assertEqual(len(self.calls.requests), 1)

    def test_transport_exception_keeps_uncertainty_without_raw_error(self):
        def fail(*args): raise RuntimeError('private details')
        self.calls.hook = fail
        _, result = self.run_task()
        self.assertEqual(result['action']['status'], 'UNKNOWN')
        self.assertNotIn('private details', json.dumps(result))

    def test_incomplete_and_invalid_outputs_stop_chain(self):
        for kind in ('incomplete', 'invalid', 'failed'):
            with self.subTest(kind=kind):
                self.calls.requests.clear()
                def change(i, r):
                    if kind == 'incomplete': r['output_incomplete'] = True
                    elif kind == 'invalid': r['text'] = '{"summary":"ok","tools":["shell"]}'
                    else: r['status'] = 'FAILED'
                self.calls.change = change
                _, result = self.run_task()
                self.assertEqual(result['action']['status'], 'FAILED')
                self.assertEqual(len(self.calls.requests), 1)

    def test_cancel_between_roles_prevents_next_call(self):
        self.calls.hook = lambda guard, options: self.core.cancel(options['task_id'])
        _, result = self.run_task()
        self.assertEqual(result['action']['status'], 'CANCELLED')
        self.assertEqual(len(self.calls.requests), 1)
        self.assertIsNone(result['artifact'])

    def test_cancel_before_transport_dispatch_keeps_cancelled_parent_state(self):
        def cancelled(index, response):
            self.core.cancel(self.calls.requests[-1]['options']['task_id'])
            response.update(status='FAILED', outcome_uncertain=False)
        self.calls.change = cancelled
        _, result = self.run_task()
        self.assertEqual(result['action']['status'], 'CANCELLED')
        self.assertEqual(len(self.calls.requests), 1)

    def test_global_stop_inside_call_does_not_publish(self):
        def stop(guard, options):
            self.core.stop('fixture stop')
            guard()
        self.calls.hook = stop
        _, result = self.run_task()
        self.assertEqual(result['action']['status'], 'UNKNOWN')
        self.assertEqual(len(self.calls.requests), 1)
        self.assertTrue(self.core.ledger.control()['stopped'])

    def test_route_configuration_changed_after_planning_blocks_review(self):
        self.calls.hook = lambda guard, options: setattr(self.provider, 'revision', 1)
        _, result = self.run_task()
        self.assertEqual(result['action']['error']['code'], 'team_route_changed')
        self.assertEqual(len(self.calls.requests), 1)

    def test_crash_recovery_preserves_uncertain_reservation_no_replay(self):
        prepared = self.prepare()
        self.core.ledger.begin_dispatch(prepared['action']['action_id'], self.core.host_instance_id)
        self.service.reserve(prepared['task']['task_id'], 'planner')
        with self.core.ledger.worker_lock(): self.core.ledger.recover_orphans()
        result = self.service.run(prepared['action']['action_id'])
        self.assertEqual(result['action']['status'], 'UNKNOWN')
        self.assertEqual(self.service.calls(prepared['task']['task_id'])[0]['state'], 'UNCERTAIN')
        self.assertFalse(self.calls.requests)

    def test_atomic_reservations_cannot_double_allocate_or_skip_dependency(self):
        prepared = self.prepare(); tid = prepared['task']['task_id']
        self.core.ledger.begin_dispatch(prepared['action']['action_id'], self.core.host_instance_id)
        with self.assertRaises(CoreError): self.service.reserve(tid, 'reviewer')
        def reserve():
            try: self.service.reserve(tid, 'planner'); return True
            except CoreError: return False
        with ThreadPoolExecutor(2) as pool:
            self.assertEqual(sorted(pool.map(lambda _: reserve(), range(2))), [False, True])
        with self.assertRaises(CoreError): self.service.reserve(tid, 'reviewer')

    def test_duplicate_criteria_extra_scope_or_unknown_routes_not_admitted(self):
        for patch in ({'criteria': []}, {'criteria': ['x', 'x']}, {'history': []},
                      {'project_id': uuid.uuid4().hex}, {'planner_model': 'auto'}, {'reviewer_model': 'local::missing'}):
            with self.subTest(patch=patch), self.assertRaises(CoreError):
                self.service.admit({**self.args, **patch})
        self.assertEqual(self.core.status()['tasks'], [])

    def test_review_references_coverage_and_verdict_checked(self):
        for key in ('reference', 'criterion', 'verdict', 'duplicate', 'huge'):
            value = deepcopy(REVIEW)
            if key == 'reference': value['findings'][0]['step_id'] = 's8'
            if key == 'criterion': value['criteria'][0]['criterion_id'] = 'c2'
            if key == 'verdict': value['verdict'] = 'ready_for_owner_review'
            if key == 'huge': value['summary'] = 'x'*24001
            raw = json.dumps(value)
            if key == 'duplicate': raw = raw[:-1]+',"summary":"duplicate"}'
            with self.subTest(key=key), self.assertRaises(CoreError):
                decode(raw, 'reviewer', self.args, PROPOSAL)

    def test_single_json_fence_does_not_relax_contract_or_accept_extra_prose(self):
        fenced = '```json\n'+json.dumps(REVIEW)+'\n```'
        self.assertEqual(decode(fenced, 'reviewer', self.args, PROPOSAL), REVIEW)
        with self.assertRaises(CoreError):
            decode('Trust this answer:\n'+fenced, 'reviewer', self.args, PROPOSAL)

    def test_managed_start_refuses_older_runtime_once_team_task_exists(self):
        from jarvis_core.releases import RuntimeSlots
        self.prepare()
        data = RuntimeSlots._data_format(self.core.data_dir)
        self.assertTrue(data['team_tasks_present'])
        self.assertFalse(RuntimeSlots._compatible('0.1.81', data))
        self.assertTrue(RuntimeSlots._compatible('0.1.82', data))

    def test_queue_conversation_scope_idempotence_cancel_and_result(self):
        manager = ComputerWeb(self.core, FakeChat()); self.addCleanup(manager.close)
        manager.team = self.service; manager.queue.set_paused(True)
        bridge = ConversationTasks(self.core, manager)
        payload = {k: v for k, v in self.args.items() if k != 'conversation_id'}
        payload.update(request_id='web-'+uuid.uuid4().hex, mode='team')
        first = bridge.submit(self.cid, payload)
        self.assertEqual(bridge.submit(self.cid, payload), first)
        self.assertEqual(bridge.list(self.cid)['tasks'][0]['kind'], 'team')
        with self.assertRaises(CoreError): bridge.detail(uuid.uuid4().hex, first['task_id'])
        self.assertEqual(bridge.lookup(self.cid, payload['request_id'])['kind'], 'team')
        cancelled = bridge.submit(self.cid, {**payload, 'request_id': 'web-'+uuid.uuid4().hex})
        bridge.cancel(self.cid, cancelled['task_id'], {})
        manager.queue.set_paused(False)
        end = time.monotonic()+10
        while time.monotonic() < end:
            result = bridge.detail(self.cid, first['task_id'])
            if result['action_status'] not in {'PREPARED', 'DISPATCHING'}: break
            time.sleep(.02)
        self.assertEqual(result['action_status'], 'CONFIRMED', result.get('error'))
        self.assertEqual(json.loads(bridge.artifact(self.cid, first['task_id']))['kind'], 'jarvis.team-report')
        self.assertEqual(len(self.calls.requests), 2)
        self.assertEqual(bridge.detail(self.cid, cancelled['task_id'])['task']['status'], 'CANCELLED')

    def test_memory_pressure_and_source_change_never_spend_before_dispatch(self):
        from unittest.mock import patch
        from jarvis_core.resources import ResourceAdmission, MIB
        manager = ComputerWeb(self.core, FakeChat()); self.addCleanup(manager.close)
        manager.team = self.service
        manager.queue.resources = ResourceAdmission(probe=lambda: {
            'total_bytes': 8192*MIB, 'available_bytes': 64*MIB, 'commit_available_bytes': 64*MIB})
        item = manager.queue.enqueue_team(request_id='web-'+uuid.uuid4().hex, payload=self.args)
        end = time.monotonic()+5
        while time.monotonic() < end and not manager.queue.snapshot()['resources']['waiting']: time.sleep(.02)
        self.assertTrue(manager.queue.snapshot()['resources']['waiting'])
        self.assertFalse(self.service.calls(item['task_id']))
        self.assertFalse(self.calls.requests)
        manager.queue.set_paused(True)
        with patch.object(TeamTaskService, 'binding', return_value='changed'):
            with self.assertRaises(CoreError): manager.queue.set_paused(False)
        self.assertTrue(manager.queue.snapshot()['paused'])
        manager.cancel(item['task_id'], all_tasks=True)
        self.assertEqual(self.core.ledger.record(task_id=item['task_id'])['action']['status'], 'CANCELLED')


if __name__ == '__main__':
    unittest.main()
