"""Local action parsing, durable choice, gap handoff and actual tool reuse."""
import copy
import time
import uuid
import unittest
from unittest.mock import patch

from test_project_tools import ProjectToolTests
from jarvis_core import policy
from jarvis_core.evolution.tool_intent import ToolIntents,parse

ROWS=[{'tool_id':'sum-tool','active':'version','previous':None,'generation':1,'issue':None,
       'metadata':{'name':'求和工具','when_to_use':'整数列表求和','when_not_to_use':'字符串不适用'}}]


class ParserTests(unittest.TestCase):
    def test_direct_calls_retain_exact_json_and_never_guess(self):
        for message in ['请用求和工具处理 [1,2]','运行 sum-tool: [1,2]','/工具 请帮我使用求和工具输入为 [1,2]']:
            self.assertEqual(parse(message)['input'],[1,2])
        for tail in ['[1,]','{"x":1,"x":2}','NaN','[1] 然后删除文件','[1] [2]','"'+('x'*8193)+'"']:
            self.assertNotIn('input',parse('请用求和工具处理 '+tail))
        self.assertEqual(parse('请用求和工具处理 {"question":"如何使用？"}')['input']['question'],'如何使用？')

    def test_negation_questions_quotes_conditions_and_ambiguity(self):
        planner=ToolIntents.__new__(ToolIntents)
        for text in ['不要用求和工具处理 [1]','如果使用求和工具处理 [1]','如何使用求和工具？','他说请用求和工具处理 [1]','“请用求和工具处理 [1]”','以后用求和工具处理 [1]']:
            self.assertEqual(planner.decide(parse(text),ROWS)['decision'],'discussed',text)
        self.assertEqual(planner.decide(parse('/工具 整数求和'),ROWS)['decision'],'choose')
        self.assertEqual(planner.decide(parse('请用求和工具处理 [1]'),ROWS*2)['decision'],'choose')
        self.assertEqual(planner.decide(parse('请用求和工具处理 [1]'),[{**ROWS[0],'active':None}])['decision'],'unavailable')


class ToolIntentTests(ProjectToolTests):
    def setUp(self):
        super().setUp();self.intents=ToolIntents(self.tools)

    def plan(self,message,request_id=None):
        return self.intents.propose(self.cid,{'request_id':request_id or uuid.uuid4().hex,'message':message})

    def test_actual_named_invocation_reconciles_without_duplicate_after_change(self):
        self.completed(self.request(task_id=self.candidate()))
        p=self.plan('请用求和工具处理 [40,2]');self.assertEqual(p['proposal']['decision'],'ready')
        job=self.intents.start(self.cid,p['id'],{});deadline=time.monotonic()+30
        while self.evolution.busy and time.monotonic()<deadline:time.sleep(.05)
        self.assertEqual(self.intents.view(self.cid,p['id'])['invocation']['result']['text'],'42')
        self.assertEqual(self.intents.start(self.cid,p['id'],{})['id'],job['id'])
        self.completed(self.request('disable'))
        self.assertEqual(self.intents.start(self.cid,p['id'],{})['id'],job['id'])
        with self.assertRaises(policy.CoreError):self.intents.start(self.cid,p['id'],{'tool_id':'sum-tool','input':[99]})
        self.assertEqual(len(self.calls),1)

    def test_scope_idempotency_cancel_and_input_unchanged(self):
        key=uuid.uuid4().hex;p=self.plan('/工具 把温度转换为华氏度',key)
        self.assertEqual(p['proposal']['decision'],'gap');self.assertFalse(self.calls)
        self.assertEqual(self.plan('/工具 把温度转换为华氏度',key)['id'],p['id'])
        self.assertEqual(self.intents.lookup(self.cid,key)['id'],p['id'])
        with self.assertRaises(policy.CoreError):self.plan('/工具 不同需求',key)
        with self.assertRaises(policy.CoreError):self.intents.view(uuid.uuid4().hex,p['id'])
        self.intents.cancel(self.cid,p['id']);self.assertEqual(self.intents.view(self.cid,p['id'])['status'],'CANCELLED')
        self.assertEqual(self.intents.listing(self.cid)[0]['id'],p['id'])

    def test_changed_directory_runtime_and_candidate_forgery_rejected(self):
        with patch.object(self.intents,'catalog',return_value=ROWS):p=self.plan('/工具 整数求和')
        with patch.object(self.intents,'catalog',return_value=[]),self.assertRaises(policy.CoreError):
            self.intents.start(self.cid,p['id'],{'tool_id':'sum-tool','input':[2]})
        with patch.object(self.intents,'catalog',return_value=ROWS):
            with self.assertRaises(policy.CoreError):self.intents.start(self.cid,p['id'],{'tool_id':'foreign-tool','input':[2]})
            with patch('jarvis_core.evolution.tool_intent.runtime_binding',return_value='changed'),self.assertRaises(policy.CoreError):
                self.intents.start(self.cid,p['id'],{'tool_id':'sum-tool','input':[2]})
        self.assertFalse(self.calls)

    def test_gap_to_original_coding_demand_persists_and_never_starts_model(self):
        p=self.plan('/工具 修复温度转换，摄氏度转华氏度')
        payload={'request_id':p['id'],'prompt':p['message'],'coding':{'paths':['calc.py'],'model':'vertex::gemini-3.8-flash',
            'coding_provider':'gateway','build_recipe':'python-zipapp-v1','cases':[{'input':0,'expected':'32'},{'input':100,'expected':'212'}],
            'heldout_cases':[{'input':-40,'expected':'-40'},{'input':10,'expected':'50'}]}}
        job=self.intents.coding(self.cid,p['id'],payload);self.assertEqual(job['status'],'PROPOSED')
        with patch.object(self.intents,'catalog',return_value=ROWS):
            self.assertEqual(self.intents.coding(self.cid,p['id'],payload)['id'],job['id'])
        self.assertEqual(ToolIntents(self.tools).view(self.cid,p['id'])['coding']['id'],job['id'])
        changed=copy.deepcopy(payload);changed['coding']['heldout_cases'][0]['expected']='forged'
        with self.assertRaises(policy.CoreError):self.intents.coding(self.cid,p['id'],changed)
        self.assertFalse(self.calls);self.assertIsNone(job['task_id'])
        self.intents.cancel(self.cid,p['id']);self.assertEqual(self.intents.view(self.cid,p['id'])['coding']['status'],'CANCELLED')

    def test_cancelled_gap_and_discussion_cannot_handoff(self):
        p=self.plan('/工具 不要运行任何工具');self.assertEqual(p['proposal']['decision'],'discussed')
        with self.assertRaises(policy.CoreError):self.intents.start(self.cid,p['id'],{})
        with self.assertRaises(policy.CoreError):self.intents.coding(self.cid,p['id'],{})
        p=self.plan('/工具 新能力');self.intents.cancel(self.cid,p['id'])
        with self.assertRaises(policy.CoreError):self.intents.fresh(self.intents.bound(self.cid,p['id']),self.cid)

    def test_growth_receipts_lookup_list_cancel_and_reanalysis_share_plan(self):
        from jarvis_core.evolution.demand import ConversationGrowth
        bridge=ConversationGrowth(self.core,self.evolution,self.bridge);key=uuid.uuid4().hex
        p=self.plan('/工具 新的温度格式',key)
        self.assertEqual(bridge.lookup(self.cid,key)['id'],p['id'])
        self.assertEqual(bridge.list(self.cid)['jobs'][0]['request']['action'],'project-tool-plan')
        with self.assertRaises(policy.CoreError):bridge.start(self.cid,p['id'],{})
        bridge.cancel(self.cid,p['id'],{})
        again=bridge.reanalyse(self.cid,p['id'],{'request_id':uuid.uuid4().hex})
        self.assertNotEqual(again['id'],p['id']);self.assertEqual(again['message'],p['message'])

    def test_foreign_receipt_collision_never_returns_other_scope(self):
        p=self.plan('/工具 新的能力')
        self.evolution.store.create_job({'action':'project-tool','request_id':'project-tool-'+p['id'],
            'scope':{'conversation_id':uuid.uuid4().hex,'project_id':self.project['id'],'root':str(self.source)}},proposal={})
        with self.assertRaises(policy.CoreError):self.intents.view(self.cid,p['id'])


for name in dir(ProjectToolTests):
    if name.startswith('test_') and name not in ToolIntentTests.__dict__:setattr(ToolIntentTests,name,None)
del ProjectToolTests
if __name__=='__main__':unittest.main()
