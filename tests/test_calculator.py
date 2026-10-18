"""Exact arithmetic, negative routing, budgets and no-model integration."""
from decimal import Decimal
from fractions import Fraction
import hashlib
import json
from pathlib import Path
import random
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'runtime/node-host'))
from jarvis_core.calculator import select_request,calculate,evaluate,CalculationError
from jarvis_core.chat import ChatService
from jarvis_core.service import CoreService


class CalculatorTests(unittest.TestCase):
    def value(self,text):return calculate(select_request(text))[1]['value']

    def test_exact_decimals_fractions_precedence_negative_and_power(self):
        cases={'17 加 25 等于多少？只回答计算结果。':'42','0.1+0.2':'0.3',
            '请计算 (12.5 + 7.5) / 4':'5','1/3':'1/3','(1/3)*3':'1',
            '-5 + 2':'-3','2^3^2':'512','2**-3':'0.125','3 × 7':'21',
            '1e-3 + 0.009':'0.01','/计算 1/3，保留2位小数':'0.33',
            '/calc -1.005，保留2位小数':'-1.01','/计算 2.5，保留0位小数':'3'}
        for text,expected in cases.items():
            with self.subTest(text=text):self.assertEqual(self.value(text),expected)

    def test_numeric_format_receipt_digest_and_schema(self):
        text,receipt=calculate(select_request('17 加 25 等于多少？只回答计算结果。'))
        self.assertEqual(text,'42');self.assertEqual(receipt['exact'],{'numerator':'42','denominator':'1'})
        self.assertFalse(receipt['model_used'])
        data={k:v for k,v in receipt.items() if k!='digest'}
        self.assertEqual(receipt['digest'],hashlib.sha256(json.dumps(data,ensure_ascii=False,sort_keys=True,separators=(',',':')).encode()).hexdigest())
        from jsonschema import Draft202012Validator
        schema=json.loads((ROOT/'contracts/schemas/calculation.schema.json').read_text(encoding='utf-8'))
        Draft202012Validator(schema).validate(receipt)

    def test_unrelated_translation_code_dates_quotes_and_mixed_tasks_not_intercepted(self):
        for text in ['2026-10-17','42','你好','翻译：17 加 25 等于多少？','请解释这段源码：x=17+25',
            '把“17+25”翻译成英文','计算17+25，然后帮我删除文件','17加25等于多少？用JSON回答',
            '这张图片里的价格相加是多少？','继续算上面的数','__import__("os").system("echo bad")',
            '1+1;open("secret")','17+25=27 是不是对的？']:
            with self.subTest(text=text):self.assertIsNone(select_request(text))

    def test_explicit_invalid_requests_never_execute_python_or_exhaust_resources(self):
        for text in ['/计算 __import__("os")','/计算 (1).__class__','/计算 [1]*999999999',
            '/计算 2**999999999','/计算 2**0.5','/计算 1/0','/计算 0**0',
            '/计算 1e999','/计算 '+'('*17+'1'+')'*17,'/计算 '+'1+'*64+'1',
            '/计算 '+'9'*65+'+1','/计算 1/3，保留99位小数','/计算 2//3']:
            with self.subTest(text=text),self.assertRaises(CalculationError):calculate(select_request(text))

    def test_deterministic_reference_cases_with_generated_operands(self):
        rng=random.Random(17025)
        for _ in range(100):
            a,b,c=[rng.randint(-99999,99999) for _ in range(3)]
            value,steps=evaluate(f'({a}+{b})*({c}-2)')
            self.assertEqual(value,Fraction((a+b)*(c-2)));self.assertEqual(steps,3)
        for a,b in [('0.11','0.29'),('1000000000.01','0.99'),('-0.0001','0.0003')]:
            self.assertEqual(Decimal(self.value(a+'+'+b)),Decimal(a)+Decimal(b))


class CalculationChatTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        base=Path(self.tmp.name);source=base/'sample';source.mkdir();self.core=CoreService(base/'data');self.core.initialize(source)
        self.chat=ChatService(self.core)
    def test_core_ready_calculation_needs_no_model_config_credential_or_memory(self):
        with patch('jarvis_core.chat.effective_config',side_effect=AssertionError('model config read')),patch('jarvis_core.chat.gateway.probe',side_effect=AssertionError('model call')),patch.object(self.chat.memory,'view_facts',side_effect=AssertionError('memory read')):
            result=self.chat.reply('17 加 25 等于多少？只回答计算结果。',provider='local',history=[{'role':'user','content':'earlier'},{'role':'assistant','content':'private'}])
        self.assertEqual(result['text'],'42');self.assertEqual(result['provider'],'builtin');self.assertEqual(result['attempts'],[])
        self.assertFalse(result['history_info']['calculation']['history_used'])
    def test_automatic_errors_stay_local_and_explicit_context_conflict_does_not_fall_back(self):
        with patch('jarvis_core.chat.gateway.probe',side_effect=AssertionError('model fallback')):
            self.assertEqual(self.chat.reply('1/0')['error'],'division_by_zero')
            self.assertEqual(self.chat.reply('/计算 17+25',context_note='输出JSON')['error'],'calculation_context_conflict')
    def test_normal_context_attachment_and_explicit_skill_defer_to_original_route(self):
        for kwargs in ({'context_note':'请用英文解释'}, {'attachments':[{'kind':'text','name':'note.txt','text':'source'}]},
                       {'skill_context':{'explicit':'matt-pocock.teach'}}):
            with self.subTest(kwargs=kwargs),patch('jarvis_core.chat.gateway.probe',return_value={'status':'SUCCEEDED','text':'ordinary','outcome_uncertain':False}) as gateway:
                result=self.chat.reply('17+25',provider='local',**kwargs)
                self.assertNotIn('calculation',result);self.assertTrue(gateway.called)
    def test_guard_and_cancellation_still_apply(self):
        event=threading.Event();event.set()
        self.assertEqual(self.chat.reply('17+25',cancel_event=event)['status'],'CANCELLED')
        with patch.object(self.core,'assert_running',side_effect=RuntimeError('stopped')):
            self.assertEqual(self.chat.reply('17+25')['error'],'core_unavailable')
    def test_internal_planning_is_never_intercepted(self):
        with patch('jarvis_core.chat.gateway.probe',return_value={'status':'SUCCEEDED','text':'plan','outcome_uncertain':False}) as gateway:
            result=self.chat.reply('17+25',provider='local',_purpose='sample_report')
        self.assertTrue(gateway.called);self.assertNotIn('calculation',result)


if __name__=='__main__':unittest.main()
