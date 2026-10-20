"""Cross the real process boundary for use-grant checks, without paid requests."""
import sys
import threading
import unittest

import test_federation_access as access_tests
from jarvis_core.dialogue_process import DialogueProcesses
from jarvis_core.turns import invoke_reply


class SharedProcessTests(unittest.TestCase):
    setUp = access_tests.AccessTests.setUp
    pair = access_tests.AccessTests.pair
    state = access_tests.AccessTests.state
    card = access_tests.AccessTests.card
    edit = access_tests.AccessTests.edit
    ready = access_tests.AccessTests.ready
    grant = access_tests.AccessTests.grant
    issue = access_tests.AccessTests.issue

    def pool(self, mode):
        pool = DialogueProcesses(self.a.core)
        self.addCleanup(pool.close)
        pool._command = [sys._base_executable, '-u', str(access_tests.fixtures.ROOT/'tests/shared_dialogue_fixture.py'), mode]
        return pool

    def test_full_reply_child_materializes_only_permitted_reference(self):
        ctx = self.ready(('local',))
        self.chat.dialogue_models = self.pool('normal')
        result = invoke_reply(self.a.core, self.chat, {
            'message': '请说明资料', 'provider': 'local', 'shared_context': ctx},
            threading.Event(), self.scope['conversation_id'])
        self.assertEqual(result['status'], 'SUCCEEDED', result)
        self.assertEqual(result['text'], '共享资料测试回答')
        self.assertTrue(result['history_info']['shared']['used'])
        self.assertEqual(self.chat.dialogue_models.snapshot()['active'], 0)

    def test_nested_probe_carries_guard_across_ipc(self):
        ctx = self.ready(('local',))
        pool = self.pool('normal')
        result = pool.probe(self.config, 'local', 'SYNTHETIC_SHARED_DATA_85', self.a.core.data_dir,
                            self.a.core.assert_running, shared_dispatch={
                                'scope': ctx['scope'], 'references': ctx['references'],
                                'config_path': str(self.config_path)})
        self.assertEqual(result['text'], '共享资料测试回答', result)
        self.grant(())
        result = pool.probe(self.config, 'local', 'SYNTHETIC_SHARED_DATA_85', self.a.core.data_dir,
                            self.a.core.assert_running, shared_dispatch={
                                'scope': ctx['scope'], 'references': ctx['references'],
                                'config_path': str(self.config_path)})
        self.assertNotIn('text', result)
        self.assertFalse(result.get('dispatch_admitted'))

    def test_revocation_before_and_during_real_gateway_withholds_text(self):
        ctx = self.ready(('local',))
        for mode in ('before', 'inflight'):
            with self.subTest(mode=mode):
                if mode == 'inflight':
                    self.grant(('local',)); ctx['references'] = [self.issue()]
                self.chat.dialogue_models = self.pool(mode)
                result = invoke_reply(self.a.core, self.chat, {
                    'message': '请说明资料', 'provider': 'local', 'shared_context': ctx},
                    threading.Event(), self.scope['conversation_id'])
                self.assertNotIn('text', result, result)
                self.assertNotEqual(result['status'], 'SUCCEEDED', result)
                self.assertEqual(bool(result.get('dispatch_admitted')), mode == 'inflight', result)
                self.assertEqual(self.chat.dialogue_models.snapshot()['active'], 0)


if __name__ == '__main__':
    unittest.main()
