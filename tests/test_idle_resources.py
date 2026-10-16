"""Prevent resource evidence from passing with short, unstable or expensive runs."""
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'tools'))
from probe_idle_resources import summarize, MIB


class IdleEvidenceTests(unittest.TestCase):
    def sample(self, seconds, cpu, pid=1, private=32*MIB):
        return {'elapsed_seconds': seconds, 'processes': [
            {'pid': pid, 'created_ticks': 10, 'cpu_seconds': cpu,
             'private_bytes': private, 'working_bytes': private}]}

    def test_cpu_uses_one_core_and_all_processes(self):
        samples = [self.sample(0, 1), self.sample(300, 4.1)]
        self.assertFalse(summarize(samples, 1)['checks']['idle_cpu'])
        for s in samples: s['processes'].append({**s['processes'][0], 'pid': 2})
        self.assertAlmostEqual(summarize(samples, 1)['cpu_percent_one_core'], 2.0666666667)

    def test_short_smoke_is_never_full_acceptance(self):
        result = summarize([self.sample(0, 1), self.sample(10, 1)], 1)
        self.assertEqual(result['status'], 'incomplete_or_failed')
        self.assertFalse(result['checks']['full_duration'])

    def test_process_disappearance_or_identity_reuse_invalidates_result(self):
        for pid, created in [(2, 10), (1, 20)]:
            samples = [self.sample(0, 1), self.sample(300, 1, pid)]
            samples[-1]['processes'][0]['created_ticks'] = created
            self.assertIsNone(summarize(samples, 1)['cpu_percent_one_core'])

    def test_memory_startup_and_valid_run(self):
        samples = [self.sample(0, 1), self.sample(300, 1.1)]
        self.assertEqual(summarize(samples, 1)['status'], 'passed_on_this_machine')
        samples[-1]['processes'][0]['private_bytes'] = 513*MIB
        result = summarize(samples, 6)
        self.assertFalse(result['checks']['private_memory'])
        self.assertFalse(result['checks']['ready_time'])
