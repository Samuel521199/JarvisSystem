"""Offline resource sampling and HTTP isolation; never calls a paid model."""
import http.client
import importlib.util
import json
from pathlib import Path
import sys
import threading
import time
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'runtime/node-host'))
from jarvis_core.resource_usage import ResourceUsage, busiest_engine, cpu_percent, percent


class UsageTests(unittest.TestCase):
    def wait_sample(self, sampler):
        deadline = time.monotonic() + 2
        while time.monotonic() < deadline:
            value = sampler.snapshot()
            if not value['refreshing']:
                return value
            time.sleep(.01)
        self.fail('sample did not finish')

    def test_cpu_delta_and_unknown_values(self):
        self.assertEqual(cpu_percent((100, 200, 100), (150, 280, 120)), 50)
        self.assertIsNone(cpu_percent((1, 2, 3), (1, 2, 3)))
        self.assertIsNone(cpu_percent((2, 3, 4), (1, 4, 5)))
        self.assertEqual(percent(140, 100), 100)
        self.assertIsNone(percent(0, 0))

    def test_gpu_sums_processes_per_engine_not_across_engines(self):
        base = 'luid_0x00000000_0x00000001_phys_0_eng_'
        self.assertEqual(busiest_engine({f'pid_1_{base}0_engtype_3D': 30,
                                        f'pid_2_{base}0_engtype_3D': 40,
                                        f'pid_1_{base}1_engtype_Copy': 50}), 70)
        self.assertIsNone(busiest_engine({'bad': 0, f'pid_1_{base}0': float('nan')}))
        self.assertEqual(busiest_engine({f'pid_1_{base}0': 0}), 0)

    def test_slow_sampler_is_single_flight_and_cache_expires(self):
        started, release = threading.Event(), threading.Event()
        calls = []
        clock = [100.0]
        def collect():
            calls.append(1)
            started.set()
            release.wait(2)
            return {'cpu_percent': 17}
        sampler = ResourceUsage(collect, clock=lambda: clock[0])
        try:
            first = sampler.snapshot()
            self.assertTrue(started.wait(1))
            self.assertIsNone(first['cpu_percent'])
            self.assertTrue(first['stale'])
            for _ in range(10):
                self.assertTrue(sampler.snapshot()['refreshing'])
            self.assertEqual(len(calls), 1)
            release.set()
            value = self.wait_sample(sampler)
            self.assertEqual(value['cpu_percent'], 17)
            self.assertFalse(value['stale'])
            self.assertEqual(len(calls), 1)
            sampler.close()
            clock[0] += 16
            self.assertTrue(sampler.snapshot()['stale'])
            self.assertEqual(len(calls), 1)
        finally:
            release.set()
            sampler.close()

    def test_failed_refresh_does_not_relabel_old_values_as_current(self):
        clock = [0]
        sampler = ResourceUsage(lambda: {'cpu_percent': 50}, clock=lambda: clock[0])
        try:
            self.assertEqual(self.wait_sample(sampler)['cpu_percent'], 50)
            def fail():
                raise OSError('private driver detail')
            sampler.collector = fail
            clock[0] += 4
            value = self.wait_sample(sampler)
            self.assertIsNone(value['sampled_at'])
            self.assertIsNone(value['cpu_percent'])
            self.assertNotIn('private', json.dumps(value))
        finally:
            sampler.close()


class UsageHttpTests(unittest.TestCase):
    def test_http_boundary_and_chat_independence(self):
        spec = importlib.util.spec_from_file_location('usage_web', ROOT / 'apps/web/server.py')
        web = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(web)
        class Core:
            def assert_running(self): return {'config': {}}
        class Chat:
            def reply(self, *args, **kwargs): return {'status': 'SUCCEEDED', 'text': 'offline reply'}
        server = web.LocalChatServer(('127.0.0.1', 0), Core(), Chat())
        blocker = threading.Event()
        def sample():
            blocker.wait(4)
            return {'cpu_percent': 5}
        server.resource_usage.close()
        server.resource_usage = ResourceUsage(sample)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        port = server.server_address[1]
        def request(path, method='GET', payload=None, headers=None):
            conn = http.client.HTTPConnection('127.0.0.1', port, timeout=2)
            try:
                conn.request(method, path, json.dumps(payload) if payload else None, headers or {})
                response = conn.getresponse()
                return response.status, response.read()
            finally: conn.close()
        token = {'X-Jarvis-Nonce': server.nonce}
        try:
            self.assertEqual(request('/api/resources')[0], 403)
            self.assertEqual(request('/api/resources', headers={**token, 'Origin':'https://example.com'})[0], 403)
            self.assertEqual(request('/api/resources?path=private', headers=token)[0], 404)
            status, body = request('/api/resources', headers=token)
            self.assertEqual(status, 200)
            self.assertTrue(json.loads(body)['refreshing'])
            status, body = request('/api/chat', 'POST', {'message':'resource isolation'},
                                   {**token, 'Origin':f'http://127.0.0.1:{port}', 'Content-Type':'application/json'})
            self.assertEqual(status, 200)
            self.assertEqual(json.loads(body)['status'], 'SUCCEEDED')
            self.assertEqual(request('/resources.js')[0], 200)
            status, body = request('/settings')
            self.assertEqual(status, 200)
            self.assertIn(b'data-appearance-previews', body)
            self.assertIn(b'id="resource-usage"', body)
        finally:
            blocker.set()
            server.shutdown()
            server.server_close()
            thread.join(2)


if __name__ == '__main__':
    unittest.main()
