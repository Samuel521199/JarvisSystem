"""Memory admission and real queue/HTTP behavior; no physical memory exhaustion."""
import json
import os
from pathlib import Path
import sys
import tempfile
import time
import unittest
import uuid

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'runtime/node-host'))
from jarvis_core.resources import ResourceAdmission, MIB, memory_snapshot, load_profile
from jarvis_core.policy import CoreError
import test_computer_queue as queue_helpers
import test_computer_web as web_helpers


def sample(available=4096, commit=4096):
    return {'total_bytes': 8192 * MIB, 'available_bytes': available * MIB,
            'commit_available_bytes': commit * MIB}


class ResourceTests(unittest.TestCase):
    def test_hysteresis_requires_margin_and_stable_recovery(self):
        state, clock = [sample(1000)], [0]
        guard = ResourceAdmission(probe=lambda: state[0], clock=lambda: clock[0])
        self.assertFalse(guard.check('browser.operate.v1'))
        state[0] = sample(2200); clock[0] = 10
        self.assertFalse(guard.check('browser.operate.v1'))
        state[0] = sample(); clock[0] = 11
        self.assertFalse(guard.check('browser.operate.v1'))
        self.assertEqual(guard.snapshot()['reason'], 'resource_recovering')
        clock[0] = 12
        self.assertFalse(guard.check('browser.operate.v1'))
        clock[0] = 13
        self.assertTrue(guard.check('browser.operate.v1'))

    def test_commit_shortage_and_probe_failure_wait_without_grant(self):
        guard = ResourceAdmission(probe=lambda: sample(commit=100))
        self.assertFalse(guard.check('filesystem.read_sample.v1'))
        self.assertEqual(guard.snapshot()['reason'], 'memory_pressure')
        def unavailable(): raise OSError('synthetic telemetry failure')
        guard.probe = unavailable
        self.assertFalse(guard.check('filesystem.read_sample.v1'))
        self.assertEqual(guard.snapshot()['reason'], 'resource_unavailable')
        self.assertIsNone(guard.snapshot()['sample'])
        guard.probe = lambda: {'total_bytes': 1, 'available_bytes': -1}
        self.assertFalse(guard.check('filesystem.read_sample.v1'))

    def test_readers_do_not_advance_recovery_and_idle_clears_wait(self):
        guard = ResourceAdmission(probe=lambda: sample(0))
        guard.check('filesystem.read_sample.v1')
        snapshot = guard.snapshot();snapshot['sample']['available_bytes'] = 999
        self.assertEqual(guard.snapshot()['sample']['available_bytes'], 0)
        guard.idle()
        self.assertFalse(guard.snapshot()['waiting'])
        guard.probe = lambda: sample()
        self.assertTrue(guard.check('filesystem.read_sample.v1'))
        with self.assertRaises(CoreError): guard.check('unknown')

    def test_profile_rejects_invalid_thresholds_and_missing_capability(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'profile.json'
            for field, value in [('retry_seconds', 0), ('recovery_seconds', True),
                                 ('task_memory_mib', {}), ('foreground_reserve_mib', -1)]:
                profile = load_profile();profile[field] = value
                path.write_text(json.dumps(profile), encoding='utf-8')
                with self.assertRaises(CoreError): ResourceAdmission(profile_path=path)

    @unittest.skipUnless(os.name == 'nt', 'Windows telemetry')
    def test_real_os_memory_counters(self):
        value = memory_snapshot()
        self.assertGreater(value['total_bytes'], 0)
        self.assertLessEqual(value['available_bytes'], value['total_bytes'])
        self.assertGreaterEqual(value['commit_available_bytes'], 0)


class ResourceQueueTests(unittest.TestCase):
    setUp = queue_helpers.QueueTests.setUp
    make_queue = queue_helpers.QueueTests.make_queue
    options = queue_helpers.QueueTests.options
    enqueue = queue_helpers.QueueTests.enqueue
    wait_for = queue_helpers.QueueTests.wait_for

    def test_wait_cancel_and_fifo_resume_once(self):
        self.queue.set_paused(True)
        memory, clock = [sample(0)], [0]
        self.queue.resources = ResourceAdmission(probe=lambda: memory[0], clock=lambda: clock[0])
        first, second = self.enqueue(), self.enqueue()
        self.queue.set_paused(False)
        self.wait_for(lambda: self.queue.snapshot()['resources']['waiting'])
        self.assertEqual(self.executor.calls, [])
        self.assertFalse(self.queue.snapshot()['paused'])
        self.assertEqual(self.core.ledger.record(task_id=first['task_id'])['action']['status'], 'PREPARED')
        self.core.cancel(first['task_id'])
        memory[0] = sample();self.queue.wake.set()
        self.wait_for(lambda: self.queue.snapshot()['resources']['reason'] == 'resource_recovering')
        clock[0] = 3;self.queue.wake.set()
        self.wait_for(lambda: len(self.executor.calls) == 1)
        self.assertEqual(self.executor.calls, [second['request_id']])
        self.assertEqual(self.core.ledger.record(task_id=first['task_id'])['action']['status'], 'CANCELLED')

    def test_pressure_between_precheck_and_dispatch_keeps_prepared(self):
        self.queue.set_paused(True)
        samples = iter([sample(), sample(0)])
        guard = ResourceAdmission(probe=lambda: next(samples, sample(0)))
        self.queue.resources = guard
        item = self.enqueue();self.queue.set_paused(False)
        self.wait_for(lambda: guard.snapshot()['waiting'])
        self.assertEqual(self.executor.calls, [])
        self.assertEqual(self.core.ledger.record(task_id=item['task_id'])['action']['status'], 'PREPARED')
        self.assertIsNone(self.queue.snapshot()['error'])

    def test_resource_recovery_never_overrides_manual_pause_or_restart(self):
        self.queue.set_paused(True)
        self.queue.resources = ResourceAdmission(probe=lambda: sample(0))
        item = self.enqueue();self.queue.set_paused(False)
        self.wait_for(lambda: self.queue.snapshot()['resources']['waiting'])
        self.queue.set_paused(True)
        self.queue.resources.probe = lambda: sample()
        self.queue.wake.set();time.sleep(.05)
        self.assertEqual(self.executor.calls, [])
        self.queue.close();self.queue = self.make_queue()
        self.assertTrue(self.queue.snapshot()['paused'])
        self.assertEqual(self.core.ledger.record(task_id=item['task_id'])['action']['status'], 'PREPARED')


class ResourceWebTests(unittest.TestCase):
    setUp = web_helpers.ComputerWebTests.setUp
    request = web_helpers.ComputerWebTests.request
    get = web_helpers.ComputerWebTests.get

    def test_chat_status_and_cancel_stay_available_during_resource_wait(self):
        self.manager.queue.resources = ResourceAdmission(probe=lambda: sample(0))
        payload = {'mode': 'inventory', 'request_id': 'web-' + uuid.uuid4().hex}
        response = self.request('POST', '/api/tasks', payload)
        self.assertEqual(response[0], 202)
        task = json.loads(response[2])['task_id']
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            state = json.loads(self.get('/api/tasks')[2])
            if state['queue']['resources']['waiting']: break
            time.sleep(.02)
        self.assertEqual(state['queue']['resources']['reason'], 'memory_pressure')
        self.assertEqual(self.request('POST', '/api/chat', {'message': 'synthetic foreground'})[0], 200)
        self.assertEqual(self.request('GET', '/api/status')[0], 200)
        self.assertEqual(self.request('POST', '/api/tasks/' + task + '/cancel', {})[0], 200)
        self.assertEqual(self.core.ledger.record(task_id=task)['action']['status'], 'CANCELLED')
        self.assertFalse(self.core.ledger.control()['stopped'])


if __name__ == '__main__': unittest.main()
