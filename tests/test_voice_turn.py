"""Automatic voice cannot turn recognition mistakes into personal/task changes."""
from unittest import TestCase
from unittest.mock import Mock, patch

import test_chat
import test_dialogue_turns
from jarvis_core.work_admission import WorkAdmission


class VoiceAuthorityTests(TestCase):
    setUp = test_chat.ChatTests.setUp
    success = test_chat.ChatTests.success

    def test_personal_effects_are_blocked_before_model_or_write(self):
        for text in ('记住：饮品=喜欢无糖茶', '设置交流风格：温暖', '忘记：饮品',
                     '保存接续：下次继续讨论'):
            with self.subTest(text=text):
                result = self.chat.reply(text, provider='local', voice_mode='conversation',
                                         personal_context={'temporary': False},
                                         memory_context={'enabled': True, 'project_id': None})
                self.assertEqual(result['voice_mode'], 'conversation')
                self.assertNotIn('personal', result)
        self.provider.assert_not_called()
        self.assertEqual(self.chat.memory.list()['facts'], [])

    def test_chat_keeps_persona_context_but_cannot_enable_intent_or_skills(self):
        with patch.object(self.chat.skills, 'select') as select:
            result = self.chat.reply('聊聊今天的计划', provider='local',
                                     voice_mode='conversation', _intent_shadow=True)
            self.assertEqual(result['status'], 'SUCCEEDED')
            select.assert_not_called()
            self.assertIn('no action authority', self.provider.call_args.kwargs['instructions'])
            self.assertNotIn('intent_decision', result)

    def test_admission_defends_against_an_untrusted_action_result(self):
        admission = WorkAdmission.__new__(WorkAdmission)
        admission.documentation = Mock()
        result = {'status': 'SUCCEEDED', 'text': 'pretend done', 'intent_decision': {'intents': []}}
        self.assertIs(admission.admit({}, {'voice_mode': 'conversation', 'message': '生成文件'}, result), result)
        admission.documentation.admit.assert_not_called()


class VoiceHTTPTests(TestCase):
    setUp = test_dialogue_turns.DialogueTests.setUp
    request = test_dialogue_turns.DialogueTests.request
    envelope = test_dialogue_turns.DialogueTests.envelope
    post = test_dialogue_turns.DialogueTests.post
    poll = test_dialogue_turns.DialogueTests.poll
    finished = test_dialogue_turns.DialogueTests.finished

    def test_mode_validated_and_receipted_without_work_admission(self):
        value = self.envelope()
        value['chat']['voice_mode'] = 'conversation'
        original = self.chat.reply
        def reply(message, voice_mode=None, **kwargs):
            self.assertEqual(voice_mode, 'conversation')
            return original(message, **kwargs)
        self.chat.reply = reply
        admission = Mock()
        self.server.dialogue.work_admission = admission
        self.assertEqual(self.post(value)[0], 202)
        result = self.finished(value)
        self.assertEqual(result['status'], 'SUCCEEDED')
        admission.admit.assert_not_called()
        for bad in ('execute', True, [], {}):
            invalid = self.envelope()
            invalid['chat']['voice_mode'] = bad
            self.assertEqual(self.post(invalid)[0], 400)
        self.assertEqual(self.request('GET', '/voice-session.js')[0], 200)
        self.assertEqual(self.request('GET', '/voice-session-capture.js')[0], 200)
