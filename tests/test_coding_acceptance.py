"""Acceptance faults against temporary projects; no real owner data or models."""
import errno
import http.client
import json
from pathlib import Path
import subprocess
import sys
import threading
import time
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT/'tests')]
import test_coding_bundle as fixture
from test_web import FakeChat, web
from jarvis_core import policy
from jarvis_core.coding_build import ZIPAPP
from jarvis_core.coding_workflow import apply_result
from jarvis_core.evolution.runner import validate_code
from jarvis_core.service import CoreService
from jarvis_core.worker_recovery import StageLease
from test_worker import process_alive


class AcceptanceTests(fixture.BundleTests):
    def test_missing_builtin_is_diagnosed_before_execution_and_repaired(self):
        bad = {**fixture.GOOD_FILES, 'helper.py':
            'def total(data):\n    return divmod(sum(data), 1)[0]\n'}
        self.bundles = [bad, fixture.GOOD_FILES]
        generated = self.manager.skills.coding_generate
        def capture(prompt, instructions, guard):
            self.assertIn('Available builtins only:', instructions)
            return generated(prompt, instructions, guard)
        self.manager.skills.coding_generate = capture
        report = self.report(self.submit(build_recipe=ZIPAPP))
        self.assertTrue(report['coding']['passed']); self.assertEqual(len(self.calls), 2)
        self.assertIn('divmod', self.calls[1]['test_feedback']['static_reason'])
        self.assertFalse(report['coding']['attempts'][0]['validation']['executed'])
        validate_code('def transform(divmod):\n    return str(divmod)\n')

    def start_http(self):
        server = web.LocalChatServer(('127.0.0.1', 0), self.core, FakeChat(), workspace=self.workspace)
        thread = threading.Thread(target=server.serve_forever, kwargs={'poll_interval': .01}, daemon=True)
        thread.start()
        self.addCleanup(server.server_close); self.addCleanup(server.shutdown)
        return server

    def chat(self, server):
        connection = http.client.HTTPConnection('127.0.0.1', server.server_port, timeout=2)
        started = time.monotonic()
        try:
            connection.request('POST', '/api/chat', json.dumps({'message':'hello'}),
                {'Origin':f'http://127.0.0.1:{server.server_port}', 'X-Jarvis-Nonce':server.nonce,
                 'Content-Type':'application/json'})
            response = connection.getresponse(); body = response.read()
            self.assertEqual(response.status, 200, body)
            self.assertLess(time.monotonic()-started, 2)
        finally: connection.close()

    def test_process_death_mid_apply_can_restore_with_fresh_core(self):
        report = self.report(self.submit())
        saved = self.root/'report.json'; saved.write_text(json.dumps(report), encoding='utf-8')
        script = r'''
import json, os, sys
from pathlib import Path
sys.path.insert(0, sys.argv[1])
from jarvis_core.service import CoreService
from jarvis_core.project_files import ProjectFiles
from jarvis_core.coding_workflow import apply_result
original = ProjectFiles.write
def interrupted(self, args):
    original(self, args)
    os._exit(77)
ProjectFiles.write = interrupted
apply_result(CoreService(Path(sys.argv[2])), json.loads(Path(sys.argv[3]).read_text()), 'apply')
'''
        process = subprocess.run([sys.executable, '-X', 'utf8', '-B', '-c', script,
            str(ROOT/'runtime/node-host'), str(self.core.data_dir), str(saved)],
            capture_output=True, timeout=15)
        self.assertEqual(process.returncode, 77, process.stderr)
        self.assertEqual((self.source/'calc.py').read_text(), fixture.GOOD_FILES['calc.py'])
        self.assertEqual((self.source/'helper.py').read_text(), fixture.BAD_FILES['helper.py'])
        reopened = CoreService(self.core.data_dir)
        self.assertEqual(apply_result(reopened, report, 'rollback')['status'], 'restored')
        for name, source in fixture.BAD_FILES.items():
            self.assertEqual((self.source/name).read_text(), source)

    def test_archive_staging_disk_full_does_not_deliver_or_block_chat(self):
        server = self.start_http(); write = Path.write_bytes; injected = []
        def full(path, body):
            if path.name == 'candidate.pyz':
                injected.append(str(path)); raise OSError(errno.ENOSPC, 'synthetic disk full')
            return write(path, body)
        with patch.object(Path, 'write_bytes', full):
            item = self.submit(build_recipe=ZIPAPP)
            detail = self.wait(item)
        self.assertTrue(injected); self.assertNotEqual(detail['action_status'], 'CONFIRMED')
        self.assertEqual(len(self.calls), 1)
        with self.assertRaises(policy.CoreError): self.bridge.artifact(self.cid, item['task_id'])
        for name, source in fixture.BAD_FILES.items():
            self.assertEqual((self.source/name).read_text(), source)
        self.assertTrue(all(not Path(p).parent.exists() for p in injected))
        self.chat(server)

    def test_cancel_busy_coding_worker_keeps_chat_and_kills_process(self):
        server = self.start_http(); entered = threading.Event(); pids = []
        (self.source/'calc.py').write_text('def transform(data):\n    while True:\n        pass\n', encoding='utf-8')
        started = StageLease.started
        def observed(lease, pid):
            started(lease, pid); pids.append(pid); entered.set()
        with patch.object(StageLease, 'started', observed):
            item = self.submit(build_recipe=ZIPAPP)
            self.assertTrue(entered.wait(12))
            self.chat(server)
            self.bridge.cancel(self.cid, item['task_id'], {})
            detail = self.wait(item)
        self.assertEqual(detail['task']['status'], 'CANCELLED')
        self.assertFalse(self.calls)
        self.assertTrue(pids); self.assertTrue(all(not process_alive(pid) for pid in pids))
        with self.assertRaises(policy.CoreError): self.bridge.artifact(self.cid, item['task_id'])
        self.chat(server)


for name in dir(fixture.BundleTests):
    if name.startswith('test_') and name not in AcceptanceTests.__dict__:
        setattr(AcceptanceTests, name, None)

if __name__ == '__main__': unittest.main()
