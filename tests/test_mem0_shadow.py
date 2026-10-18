"""Mem0 failure injection and opt-in public-SDK tests; no external model calls."""
import json
import os
from pathlib import Path
import sys
import threading
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'tools'))
import eval_memory_extraction as evaluation
from memory_lab.mem0_bridge import run_worker

REQUEST = {'mode': 'sequence', 'steps': [{'op': 'add', 'text': '我喜欢绿茶。'}]}
GENERATE = {'type': 'generate', 'step': 0, 'messages': [
    {'role': 'system', 'content': 'native policy'}, {'role': 'user', 'content': 'synthetic source'}]}


def native(*texts):
    return {'status': 'SUCCEEDED', 'text': json.dumps({'memory': [
        {'id': str(i), 'text': text, 'attributed_to': 'user', 'linked_memory_ids': []}
        for i, text in enumerate(texts)]}, ensure_ascii=False), 'billing': {'amount': .001, 'currency': 'USD'}}


class Mem0BridgeTests(unittest.TestCase):
    def fixture(self, body, transport=None, **kwargs):
        return run_worker(sys.executable, REQUEST, transport or (lambda *_: native()),
            command=[sys.executable, '-u', '-c', 'import sys,json,time\nsys.stdin.readline()\n'+body], **kwargs)

    def test_duplicate_request_is_not_billed_twice(self):
        result, info = self.fixture(f'print(json.dumps({GENERATE!r}),flush=True)\nsys.stdin.readline()\n'
                                    f'print(json.dumps({GENERATE!r}),flush=True)\ntime.sleep(20)')
        self.assertEqual(result['error_category'], 'lab_call_budget_exceeded')
        self.assertEqual(len(info['gateway']), 1); self.assertEqual(result['billing']['amount'], .001)
        self.assertTrue(info['worker_exited']); self.assertTrue(info['scratch_removed'])

    def test_unknown_retained_without_retry(self):
        result, info = self.fixture(f'print(json.dumps({GENERATE!r}),flush=True)\ntime.sleep(20)',
            lambda *_: {'status': 'UNKNOWN', 'outcome_uncertain': True})
        self.assertEqual(result['status'], 'UNKNOWN'); self.assertTrue(result['outcome_uncertain'])
        self.assertEqual(len(info['gateway']), 1); self.assertTrue(info['scratch_removed'])

    def test_transport_exception_is_uncertain(self):
        def crash(*_): raise RuntimeError('synthetic')
        result, info = self.fixture(f'print(json.dumps({GENERATE!r}),flush=True)\ntime.sleep(20)', crash)
        self.assertEqual(result['status'], 'UNKNOWN'); self.assertTrue(info['worker_exited'])

    def test_result_requires_all_planned_inferences(self):
        result, info = self.fixture('print(json.dumps({"type":"result","value":{"steps":[]}}),flush=True)')
        self.assertEqual(result['error_category'], 'lab_missing_inference')
        self.assertFalse(info['gateway'])

    def test_bad_frame_and_timeout_are_reaped(self):
        for body, timeout, code in [('print("not-json",flush=True)', 4, 'lab_worker_error'),
                                    ('time.sleep(20)', .15, 'lab_worker_timeout')]:
            result, info = self.fixture(body, timeout=timeout)
            self.assertEqual(result['error_category'], code); self.assertTrue(info['worker_exited'])
            self.assertTrue(info['scratch_removed'])

    def test_cancellation_prevents_dispatch(self):
        event = threading.Event(); event.set()
        result, info = self.fixture('time.sleep(20)', cancel_event=event)
        self.assertEqual(result['status'], 'CANCELLED'); self.assertFalse(info['gateway'])


@unittest.skipUnless(os.environ.get('JARVIS_MEM0_PYTHON'), 'Separate Mem0 environment required')
class RealMem0Tests(unittest.TestCase):
    def worker(self, steps, replies):
        output = iter(replies)
        return run_worker(os.environ['JARVIS_MEM0_PYTHON'], {'mode': 'sequence', 'steps': steps},
                          lambda *_: next(output))

    def test_public_add_update_delete_history_and_exact_dedup(self):
        result, info = self.worker([
            {'op': 'add', 'text': '我喜欢绿茶。', 'alias': 'tea'},
            {'op': 'add', 'text': '我喜欢绿茶。'},
            {'op': 'update', 'ref': 'tea', 'text': '我现在喜欢红茶。'},
            {'op': 'delete', 'ref': 'tea'}, {'op': 'history', 'ref': 'tea'},
            {'op': 'add', 'text': '今天你好。'}], [native('用户喜欢绿茶。'), native('用户喜欢绿茶。'), native()])
        self.assertEqual(result['status'], 'SUCCEEDED', result)
        rows = json.loads(result['text'])['steps']
        self.assertEqual(rows[1]['result']['results'], [])
        self.assertEqual(rows[2]['stores']['personal']['results'][0]['memory'], '我现在喜欢红茶。')
        self.assertFalse(rows[3]['stores']['personal']['results'])
        self.assertIn('绿茶', json.dumps(rows[4]['result'], ensure_ascii=False))
        self.assertIn('绿茶', info['gateway'][-1]['messages'][1]['content'])
        self.assertEqual(len(info['gateway']), 3)
        self.assertEqual(info['versions']['mem0ai'], '2.2.1')
        self.assertTrue(info['scratch_removed']); self.assertTrue(info['worker_exited'])
        self.assertGreater(info['resources']['embedding_requests'], 3)
        # urllib3's IPv6 capability probe can be denied; no external connection is allowed.
        self.assertTrue(all(d['event'] == 'socket.bind' and d['function'] == '_has_ipv6'
                            for d in info['resources']['denied_io']))

    def test_scope_filters_prevent_other_project_history(self):
        result, info = self.worker([
            {'op': 'add', 'scope': 'project-a', 'text': 'A项目代号紫杉。'},
            {'op': 'add', 'scope': 'project-b', 'text': 'B项目代号蓝鲸。'}],
            [native('A项目代号紫杉。'), native('B项目代号蓝鲸。')])
        self.assertEqual(result['status'], 'SUCCEEDED', result)
        rows = json.loads(result['text'])['steps']
        self.assertNotIn('紫杉', info['gateway'][1]['messages'][1]['content'])
        self.assertFalse(rows[1]['stores']['personal']['results'])
        self.assertEqual(len(rows[1]['stores']['project-a']['results']), 1)
        self.assertEqual(len(rows[1]['stores']['project-b']['results']), 1)

    def test_bad_native_output_is_failure_not_empty_success(self):
        for text in ('not JSON', '{"memory":[],"memory":[]}', '{"facts":[]}'):
            result, info = self.worker(REQUEST['steps'], [{'status': 'SUCCEEDED', 'text': text,
                                                          'billing': {'amount': .001}}])
            self.assertEqual(result['status'], 'FAILED', result)
            self.assertEqual(len(info['gateway']), 1); self.assertEqual(result['billing']['amount'], .001)
            self.assertTrue(info['scratch_removed'])

    def test_constrained_candidates_use_existing_source_validation(self):
        case = evaluation.load_cases(evaluation.CASES)['cases'][0]
        item = {'segment': 0, 'title': '饮品偏好', 'content': '我平时喜欢无糖茶',
                'category': 'preference', 'subject_label': ''}
        with patch('jarvis_core.chat.gateway.probe', return_value=native(json.dumps(item, ensure_ascii=False))) as probe:
            row = evaluation.evaluate(case, 'vertex', 'gemini-3.1-pro-preview', 'low',
                                      'mem0', os.environ['JARVIS_MEM0_PYTHON'])
        self.assertEqual(row['status'], 'SUCCEEDED', row)
        self.assertEqual(row['facts_committed'], 0); self.assertEqual(probe.call_count, 1)
        row['engine'] = 'mem0'
        self.assertTrue(evaluation.score(case, row, True)['case_pass'])
        self.assertTrue(row['framework']['scratch_removed'])

    def test_wrong_project_is_rejected_by_host(self):
        case = evaluation.load_cases(evaluation.CASES)['cases'][0]
        item = {'segment': 0, 'title': '项目', 'content': '我喜欢无糖茶',
                'category': 'project_fact', 'subject_label': ''}
        with patch('jarvis_core.chat.gateway.probe', return_value=native(json.dumps(item))) as probe:
            row = evaluation.evaluate(case, 'vertex', 'gemini-3.1-pro-preview', 'low',
                                      'mem0', os.environ['JARVIS_MEM0_PYTHON'])
        self.assertEqual(row['status'], 'FAILED'); self.assertEqual(row['candidates'], [])
        self.assertEqual(row['facts_committed'], 0); self.assertEqual(probe.call_count, 1)

    def test_excluded_source_never_spawns_worker(self):
        case = next(c for c in evaluation.load_cases(evaluation.CASES)['cases'] if c['id'] == 'P25')
        with (patch('memory_lab.mem0_bridge.subprocess.Popen', side_effect=AssertionError('spawn')),
              patch('jarvis_core.chat.gateway.probe', side_effect=AssertionError('model'))):
            row = evaluation.evaluate(case, 'vertex', 'gemini-3.1-pro-preview', 'low',
                                      'mem0', os.environ['JARVIS_MEM0_PYTHON'])
        self.assertEqual(row['status'], 'BLOCKED'); self.assertEqual(row['gateway_invocations'], 0)


if __name__ == '__main__': unittest.main()
