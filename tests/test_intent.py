"""Trust boundaries and failure recovery; semantic accuracy is evaluated separately."""
from copy import deepcopy
import json
import threading
import unittest
import uuid
from unittest.mock import patch

from jarvis_core.intent import ENGINE, INSTRUCTIONS, bind, unwrap, validate
from jarvis_core.turns import invoke_reply
import test_chat as fixtures


def envelope(text='你好', kind='chat', **extra):
    return {'schema_version': 1, 'reply': '我在这里。', 'interaction_style': 'warm',
            'intents': [{'kind': kind, 'quote': text, 'disposition': 'requested',
                         'capability': None, 'arguments': {}, 'missing_fields': [], **extra}]}


def response(value):
    return {'status': 'SUCCEEDED', 'text': json.dumps(value, ensure_ascii=False),
            'provider': 'fixture', 'model': 'fake', 'usage': {'input_tokens': 5, 'output_tokens': 9}}


class IntentValidationTests(unittest.TestCase):
    def test_mixed_multilingual_source_and_stable_host_ids(self):
        text = '😢我很难过，陪我聊聊；please export a report.'
        value = envelope('我很难过，陪我聊聊', 'emotion')
        value['intents'] += envelope('please export a report.', 'action')['intents']
        value['interaction_style'] = 'empathetic'
        first = bind(unwrap(response(value), text), 'a'*32)
        second = bind(unwrap(response(value), text), 'a'*32)
        self.assertEqual(first, second)
        self.assertNotEqual(first['intent_decision']['decision_id'], bind(unwrap(response(value),text),'b'*32)['intent_decision']['decision_id'])
        for item in first['intent_decision']['intents']:
            span = item['source_span']
            self.assertEqual(text[span['start']:span['end']], item['quote'])
            self.assertEqual(item['execution'], 'not_submitted')
        self.assertFalse(first['intent_decision']['automatic_execution'])

    def test_forged_source_repeated_quote_unknown_fields_and_capabilities(self):
        valid = envelope()
        variants = []
        for key, bad in [('kind','shell'), ('quote','from previous private history'),
                         ('capability','shell.execute'), ('arguments',{'path':'C:/private'}),
                         ('source_span',{'start':0,'end':1}), ('missing_fields',['x'*129])]:
            value=deepcopy(valid);value['intents'][0][key]=bad;variants.append(value)
        for bad in [[], [valid['intents'][0]]*9, valid['intents']*2]:
            value=deepcopy(valid);value['intents']=bad;variants.append(value)
        for bad in [True,2,'1']:
            value=deepcopy(valid);value['schema_version']=bad;variants.append(value)
        for value in variants:
            with self.subTest(value=value), self.assertRaises(ValueError):validate(value,'你好')
        with self.assertRaises(ValueError):validate(valid,'你好你好')

    def test_documentation_arguments_must_belong_to_current_intent(self):
        text='查 React 的 useEffect 文档'
        value=envelope(text,'action',capability='mcp.documentation',arguments={'library':'React','query':'useEffect'})
        self.assertEqual(validate(value,text)['state'],'recognized')
        for arguments in [{'library':'React','query':'private history'}, {'library':'React','query':'useEffect','execute':True}]:
            value['intents'][0]['arguments']=arguments
            with self.assertRaises(ValueError):validate(value,text)

    def test_invalid_decision_keeps_answer_without_claiming_recognition(self):
        value=envelope('nonexistent','action');result=unwrap(response(value),'你好')
        self.assertEqual(result['text'],'我在这里。')
        self.assertEqual(result['intent_decision']['state'],'invalid')
        self.assertEqual(result['intent_decision']['intents'],[])
        self.assertEqual(result['usage']['output_tokens'],9)

    def test_duplicate_keys_incomplete_oversized_and_non_json_never_dispatch(self):
        for text in ['{"reply":"x","reply":"y"}', '{"reply":', '['+' '*140000, '```json\n{"reply":']:
            value=unwrap({'text':text},'你好')
            self.assertTrue(value['output_incomplete'])
            self.assertEqual(value['intent_decision']['intents'],[])
            self.assertNotIn('{',value['text'])
        value=unwrap({**response(envelope()),'output_incomplete':True},'你好')
        self.assertEqual(value['intent_decision']['state'],'invalid')
        self.assertEqual(value['text'],'我在这里。')
        value=unwrap({'text':'普通回答仍可阅读'},'你好')
        self.assertEqual(value['text'],'普通回答仍可阅读')
        self.assertEqual(value['intent_decision']['state'],'unavailable')

    def test_negation_quotation_and_uncertainty_are_not_authority(self):
        for disposition in ['requested','discussed','negated','uncertain']:
            result=unwrap(response(envelope('删除目录','action',disposition=disposition)),'删除目录')
            self.assertFalse(result['intent_decision']['automatic_execution'])
            self.assertEqual(result['intent_decision']['intents'][0]['execution'],'not_submitted')


class IntentChatTests(unittest.TestCase):
    def setUp(self):
        fixtures.ChatTests.setUp(self)
        enabled=patch('jarvis_core.intent.supported',return_value=True)
        enabled.start();self.addCleanup(enabled.stop)
    success=fixtures.ChatTests.success
    failure=fixtures.ChatTests.failure

    def test_same_call_returns_natural_reply_and_host_bound_candidate(self):
        self.provider.return_value=None
        self.provider.side_effect=lambda *a,**kw:response(envelope('帮我整理报告','action'))
        result=invoke_reply(self.core,self.chat,{'message':'帮我整理报告'},threading.Event(),'d'*32)
        self.assertEqual(self.provider.call_count,1)
        self.assertIn(INSTRUCTIONS,self.provider.call_args.kwargs['instructions'])
        self.assertEqual(result['text'],'我在这里。')
        self.assertEqual(result['intent_decision']['turn_id'],'d'*32)
        self.assertEqual(result['intent_decision']['engine'],ENGINE)
        with self.core.ledger.connection() as db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM tasks').fetchone()[0],0)

    def test_background_purposes_and_builtin_commands_do_not_use_classifier(self):
        result=invoke_reply(self.core,self.chat,{'message':'/计算 6*7'},None,'a'*32)
        self.assertEqual(result['calculation']['exact']['numerator'],'42')
        self.provider.assert_not_called();self.assertNotIn('intent_decision',result)
        self.chat.reply('fixed planning',_purpose='sample_report')
        self.assertNotIn(INSTRUCTIONS,self.provider.call_args.kwargs['instructions'])
        with self.assertRaises(ValueError):self.chat.reply('x',_purpose='sample_report',_intent_shadow=True)

    def test_small_local_context_falls_back_without_extra_call(self):
        result=self.chat.reply('x'*1800,provider='local',_intent_shadow=True)
        self.assertEqual(result['status'],'SUCCEEDED')
        self.assertEqual(result['text'],'模拟回答')
        self.assertEqual(result['intent_decision']['state'],'skipped_budget')
        self.assertEqual(self.provider.call_count,1)
        self.assertNotIn(INSTRUCTIONS,self.provider.call_args.kwargs['instructions'])

    def test_unevaluated_route_keeps_original_reply_protocol(self):
        with patch('jarvis_core.intent.supported',return_value=False):
            result=invoke_reply(self.core,self.chat,{'message':'你好','provider':'local'},None,'f'*32)
        self.assertEqual(result['text'],'模拟回答')
        self.assertEqual(result['intent_decision']['state'],'not_evaluated')
        self.assertNotIn(INSTRUCTIONS,self.provider.call_args.kwargs['instructions'])
        self.assertEqual(self.provider.call_count,1)

    def test_host_instruction_cap_skips_protocol_before_call(self):
        with patch('jarvis_core.intent.INSTRUCTIONS','X'*4100):
            result=self.chat.reply('hello',_intent_shadow=True)
        self.assertEqual(result['status'],'SUCCEEDED')
        self.assertEqual(result['intent_decision']['state'],'skipped_budget')
        self.assertEqual(self.provider.call_count,1)
        self.assertLessEqual(len(self.provider.call_args.kwargs['instructions'].encode('utf-8')),4096)

    def test_model_ignored_protocol_keeps_one_call_and_cancel_drops_candidates(self):
        result=invoke_reply(self.core,self.chat,{'message':'你好'},None,'c'*32)
        self.assertEqual(result['text'],'模拟回答')
        self.assertEqual(result['intent_decision']['state'],'unavailable')
        self.assertEqual(self.provider.call_count,1)
        event=threading.Event()
        def late(*a,**kw):
            event.set();return response(envelope())
        self.provider.side_effect=late
        result=invoke_reply(self.core,self.chat,{'message':'你好'},event,'e'*32)
        self.assertEqual(result['status'],'CANCELLED')
        self.assertNotIn('intent_decision',result)


if __name__ == '__main__':unittest.main()
