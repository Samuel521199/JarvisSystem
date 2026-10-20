"""Real pinned TLS, separate durable nodes, no paid model or user data."""
import copy
import sys
import unittest
import uuid
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_federation import FederationTests
from jarvis_core.federation import Federation
from jarvis_core.federation_tasks import report
from jarvis_core.policy import CoreError


class DelegationTests(FederationTests):
    # Reuse only fixture methods; do not duplicate inherited regression tests.
    def setup_task(self):
        self.pair()
        self.a.delegation.configure(self.sid, 0, True)
        self.b.delegation.configure(self.sid, 0, True)
        self.tid = uuid.uuid4().hex
        self.b.delegation.create(self.sid, self.tid, '资料清单', 'hello world\n共同计划\n')

    def row(self, node):
        return node.delegation.view(self.sid)['tasks'][self.tid]

    def test_task_requires_receiver_approval_then_verified_receipt(self):
        self.setup_task()
        self.b.delegation.sync(self.sid)
        self.assertEqual(self.row(self.a)['state'], 'WAITING_APPROVAL')
        self.assertIsNone(self.row(self.a)['result'])
        self.a.delegation.run(self.sid, self.tid)
        self.b.delegation.sync(self.sid)
        self.assertEqual(self.row(self.b)['result'], report('hello world\n共同计划\n'))
        self.assertEqual(self.row(self.b)['state'], 'SUCCEEDED')
        before = copy.deepcopy(self.row(self.a))
        self.b.delegation.sync(self.sid)
        self.assertEqual(before, self.row(self.a))
        with self.assertRaises(CoreError): self.a.delegation.run(self.sid, self.tid)

    def test_default_denial_and_changed_task_rejected(self):
        self.setup_task()
        self.a.delegation.configure(self.sid, 1, False)
        with self.assertRaises(CoreError): self.b.delegation.sync(self.sid)
        self.assertEqual(len(self.a.delegation.view(self.sid)['tasks']), 0)
        with self.assertRaises(CoreError):
            self.b.delegation.create(self.sid, self.tid, '更换内容', 'evil')

    def test_offline_cancel_is_pending_until_ack(self):
        self.setup_task(); self.b.delegation.sync(self.sid)
        self.b.network.change(True, 0)
        self.b.delegation.cancel(self.sid, self.tid)
        self.assertEqual(self.row(self.b)['state'], 'WAITING_APPROVAL')
        self.assertTrue(self.b.delegation.continuation(self.sid)['items'][0]['cancel_pending'])
        with self.assertRaises(CoreError): self.b.delegation.sync(self.sid)
        self.b.network.change(False, 1)
        self.b.delegation.sync(self.sid)
        self.assertEqual(self.row(self.b)['state'], 'CANCELLED')
        with self.assertRaises(CoreError): self.a.delegation.run(self.sid, self.tid)

    def test_restart_inflight_is_unknown_no_replay(self):
        self.setup_task(); self.b.delegation.sync(self.sid)
        def interrupted(data):
            row=data['spaces'][self.sid]['delegation']['tasks'][self.tid]
            row.update(state='RUNNING', host='old-process', version=2)
        self.a.store.change(self.a.node, interrupted)
        self.b.delegation.sync(self.sid)
        self.assertEqual(self.row(self.b)['state'], 'UNKNOWN')
        with self.assertRaises(CoreError): self.a.delegation.run(self.sid, self.tid)

    def test_cancel_during_compute_does_not_publish(self):
        self.setup_task(); self.b.delegation.sync(self.sid)
        def revoked(text):
            self.a.delegation.configure(self.sid, 1, False)
            return report(text)
        with patch('jarvis_core.federation_tasks.report', side_effect=revoked):
            with self.assertRaises(CoreError): self.a.delegation.run(self.sid, self.tid)
        self.assertEqual(self.row(self.a)['state'], 'CANCELLED')
        self.assertIsNone(self.row(self.a)['result'])

    def test_result_corruption_rejected_and_no_memory_writes(self):
        self.setup_task(); self.b.delegation.sync(self.sid); self.a.delegation.run(self.sid, self.tid)
        def corrupt(data):
            data['spaces'][self.sid]['delegation']['tasks'][self.tid]['result']['words']=999
        self.a.store.change(self.a.node, corrupt)
        with self.assertRaises(CoreError): self.b.delegation.sync(self.sid)
        for node in (self.a,self.b):
            self.assertFalse((node.core.data_dir/'memory.db').exists())

    def test_task_retention_and_old_runtime_rejection(self):
        self.setup_task();self.b.delegation.sync(self.sid)
        with self.assertRaises(CoreError):self.a.lifecycle.preview(self.sid)
        from jarvis_core.releases import RuntimeSlots
        for data in ({'optional_versions':{'federation.db':5}},
                     {'optional_versions':{'evolution/evolution.db':9}},
                     {'optional_versions':{},'dynamic_team_present':True}):
            self.assertFalse(RuntimeSlots._compatible('0.1.87',data))
            self.assertTrue(RuntimeSlots._compatible('0.1.88',data))


# Only the new tests run here; the base suite runs independently.
def load_tests(loader, tests, pattern):
    return unittest.TestSuite(DelegationTests(name) for name in DelegationTests.__dict__ if name.startswith('test_'))


if __name__ == '__main__': unittest.main()
