"""Fault injection plus opt-in real framework integration; no paid model calls."""
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
from memory_lab.langmem_bridge import run_worker, worker_environment
from jarvis_core.semantic_candidates import INSTRUCTIONS

GENERATE = {'type': 'generate', 'messages': [{'role': 'system', 'content': 'framework instructions'}],
            'tools': [], 'tool_choice': None}


class LangMemBridgeTests(unittest.TestCase):
    def run_fixture(self, body, transport=None, **kwargs):
        script = 'import json,sys,time\njson.loads(sys.stdin.readline())\n'+body
        return run_worker(sys.executable, 'synthetic', INSTRUCTIONS,
            transport or (lambda *_: {'status': 'SUCCEEDED', 'text': '{}'}),
            command=[sys.executable, '-u', '-c', script], timeout=4, **kwargs)

    def test_no_inherited_keys_proxy_trace_or_import_paths(self):
        with patch.dict(os.environ, {'OPENAI_API_KEY': 'synthetic-secret', 'LANGSMITH_API_KEY': 'synthetic',
                                    'HTTP_PROXY': 'http://invalid', 'PYTHONPATH': 'invalid'}):
            env = worker_environment()
        for name in ('OPENAI_API_KEY', 'LANGSMITH_API_KEY', 'HTTP_PROXY', 'PYTHONPATH'):
            self.assertNotIn(name, env)
        self.assertEqual(env['LANGSMITH_TRACING'], 'false')

    def test_extra_generation_never_reaches_gateway_and_keeps_cost_receipt(self):
        calls = []
        def transport(prompt, instructions):
            calls.append(prompt)
            return {'status': 'SUCCEEDED', 'text': '{}', 'billing': {'amount': .01}}
        body = (f'print(json.dumps({GENERATE!r}),flush=True)\nsys.stdin.readline()\n'
                f'print(json.dumps({GENERATE!r}),flush=True)\ntime.sleep(20)\n')
        result, info = self.run_fixture(body, transport)
        self.assertEqual(len(calls), 1)
        self.assertEqual(info['generate_requests'], 2)
        self.assertEqual(result['error_category'], 'lab_call_budget_exceeded')
        self.assertEqual(result['billing']['amount'], .01)
        self.assertTrue(info['worker_exited'])

    def test_unknown_outcome_is_not_retried_or_reclassified(self):
        result, info = self.run_fixture(f'print(json.dumps({GENERATE!r}),flush=True)\ntime.sleep(20)',
            lambda *_: {'status': 'UNKNOWN', 'outcome_uncertain': True, 'billing': {'amount': None}})
        self.assertEqual(result['status'], 'UNKNOWN')
        self.assertTrue(result['outcome_uncertain']); self.assertEqual(len(info['gateway']), 1)
        self.assertTrue(info['worker_exited'])

    def test_thrown_transport_preserves_uncertainty_and_dispatch_count(self):
        def transport(*args):
            raise RuntimeError('synthetic transport fault')
        result, info = self.run_fixture(f'print(json.dumps({GENERATE!r}),flush=True)\ntime.sleep(20)', transport)
        self.assertEqual(result['status'], 'UNKNOWN'); self.assertEqual(len(info['gateway']), 1)
        self.assertNotIn('billing', result)

    def test_cancel_and_crash_do_not_create_candidates(self):
        event = threading.Event(); event.set()
        result, info = self.run_fixture('time.sleep(20)', cancel_event=event)
        self.assertEqual(result['status'], 'CANCELLED'); self.assertTrue(info['worker_exited'])
        result, info = self.run_fixture('sys.exit(1)')
        self.assertEqual(result['error_category'], 'lab_worker_eof')
        self.assertEqual(info['gateway'], [])

    def test_invalid_or_oversized_pipe_frames_fail_closed(self):
        for body in ("print('not-json',flush=True)", "print('x'*65537,flush=True)"):
            result, info = self.run_fixture(body)
            self.assertEqual(result['status'], 'FAILED')
            self.assertEqual(info['gateway'], [])

    def test_timeout_reaps_worker(self):
        result, info = run_worker(sys.executable, 'synthetic', INSTRUCTIONS, lambda *_: self.fail('gateway'),
            command=[sys.executable, '-c', 'import time;time.sleep(20)'], timeout=.2)
        self.assertEqual(result['error_category'], 'lab_worker_timeout'); self.assertTrue(info['worker_exited'])

    def test_framework_scorer_requires_quote_and_typed_category(self):
        case = evaluation.load_cases(evaluation.CASES)['cases'][0]
        row = {'engine': 'langmem', 'status': 'SUCCEEDED', 'elapsed_ms': 1, 'case': case['id'], 'candidates': [
            {'segment': 0, 'quote': 'wrong', 'content': '我喜欢无糖茶',
             'classification': {'kind': 'preference', 'subject': 'owner', 'subject_label': ''}}]}
        self.assertFalse(evaluation.score(case, row, True)['case_pass'])
        self.assertEqual(evaluation.summarize([case], [row])['langmem']['typed']['tp'], 0)


@unittest.skipUnless(os.environ.get('JARVIS_LANGMEM_PYTHON'), 'Opt-in separate LangMem environment')
class RealLangMemTests(unittest.TestCase):
    def test_actual_manager_prompts_schemas_gateway_and_shared_validator(self):
        cases = evaluation.load_cases(evaluation.CASES)['cases']
        case = cases[0]; seen = []
        item = {'segment': 0, 'title': '饮品偏好', 'content': '我平时喜欢无糖茶',
                'category': 'preference', 'subject_label': ''}
        def transport(config, provider, prompt, *args, **kwargs):
            value = json.loads(prompt); seen.append(value)
            self.assertEqual(provider, 'vertex')
            self.assertEqual(config['providers'][provider]['max_output_tokens'], 1024)
            self.assertIn('instructions', kwargs)
            self.assertTrue(any(t['function']['name'] == 'CandidateBatch' for t in value['tools']))
            self.assertTrue(any('memory' in m['content'].lower() for m in value['messages']))
            return {'status': 'SUCCEEDED', 'text': json.dumps({'tool_calls': [{'name': 'CandidateBatch',
                    'args': {'candidates': [item]}}]}), 'billing': {'amount': .001, 'currency': 'USD'}}
        with patch('jarvis_core.chat.gateway.probe', side_effect=transport):
            row = evaluation.evaluate(case, 'vertex', 'gemini-3.1-pro-preview', 'low',
                                      'langmem', os.environ['JARVIS_LANGMEM_PYTHON'])
        self.assertEqual(row['status'], 'SUCCEEDED', row)
        self.assertEqual(row['facts_committed'], 0); self.assertEqual(len(seen), 1)
        self.assertEqual(row['framework']['versions']['langmem'], '0.0.30')
        self.assertTrue(row['framework']['worker_exited'])
        row['engine'] = 'langmem'
        self.assertTrue(evaluation.score(case, row, True)['case_pass'])

    def test_excluded_source_never_starts_framework_or_provider(self):
        case = next(c for c in evaluation.load_cases(evaluation.CASES)['cases'] if c['id'] == 'P25')
        with (patch('memory_lab.langmem_bridge.subprocess.Popen', side_effect=AssertionError('spawn')),
              patch('jarvis_core.chat.gateway.probe', side_effect=AssertionError('network'))):
            row = evaluation.evaluate(case, 'vertex', 'gemini-3.1-pro-preview', 'low',
                                      'langmem', os.environ['JARVIS_LANGMEM_PYTHON'])
        self.assertEqual(row['status'], 'BLOCKED'); self.assertEqual(row['gateway_invocations'], 0)
        self.assertEqual(row['facts_committed'], 0)

    def test_actual_schema_rejects_bad_scope_and_no_retry(self):
        # A valid framework schema still has to pass Jarvis's project boundary.
        case = evaluation.load_cases(evaluation.CASES)['cases'][0]
        item = {'segment': 0, 'title': '错误项目', 'content': '我喜欢无糖茶',
                'category': 'project_fact', 'subject_label': ''}
        def transport(*args, **kwargs):
            return {'status': 'SUCCEEDED', 'text': json.dumps({'tool_calls': [{'name': 'CandidateBatch',
                    'args': {'candidates': [item]}}]})}
        with patch('jarvis_core.chat.gateway.probe', side_effect=transport) as mock:
            row = evaluation.evaluate(case, 'vertex', 'gemini-3.1-pro-preview', 'low',
                                      'langmem', os.environ['JARVIS_LANGMEM_PYTHON'])
        self.assertEqual(mock.call_count, 1); self.assertEqual(row['status'], 'FAILED')
        self.assertEqual(row['candidates'], []); self.assertEqual(row['facts_committed'], 0)

    def test_actual_schema_invalid_segment_is_not_automatically_repaired(self):
        case = evaluation.load_cases(evaluation.CASES)['cases'][0]
        item = {'segment': 'zero', 'title': '饮品', 'content': '我喜欢无糖茶',
                'category': 'preference', 'subject_label': ''}
        with patch('jarvis_core.chat.gateway.probe', return_value={'status': 'SUCCEEDED',
                   'billing': {'amount': .001}, 'text': json.dumps({'tool_calls': [{'name': 'CandidateBatch',
                   'args': {'candidates': [item]}}]})}) as mock:
            row = evaluation.evaluate(case, 'vertex', 'gemini-3.1-pro-preview', 'low',
                                      'langmem', os.environ['JARVIS_LANGMEM_PYTHON'])
        self.assertEqual(mock.call_count, 1); self.assertEqual(row['status'], 'FAILED')
        self.assertEqual(row['candidates'], []); self.assertEqual(row['billing']['amount'], .001)


if __name__ == '__main__':
    unittest.main()
