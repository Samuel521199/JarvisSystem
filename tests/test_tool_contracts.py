"""Drafts are suggestions; reviewed contracts bind independent K3 execution."""
import copy
import json
import time
import threading
import unittest
import uuid
from unittest.mock import patch

from test_project_tools import ProjectToolTests
from test_coding_workflow import GOOD
from jarvis_core import policy
from jarvis_core.coding_demand import CodingDemands
from jarvis_core.evolution.tool_intent import ToolIntents
from jarvis_core.evolution.tool_contract import ToolContracts, decode

DRAFT = {'input_contract':'整数数组，包括空数组。','output_contract':'返回元素之和的十进制整数字符串，不带换行。',
         'non_goals':['不接受浮点数或字符串。'], 'public_cases':[{'input':[1,2],'expected':'3'},{'input':[],'expected':'0'}],
         'questions':['空数组应返回零吗？']}


class DraftProvider:
    def __init__(self):self.calls=[];self.responses=[]
    def contract(self,goal,route,cancel,checkpoint,reasoning=None):
        checkpoint();self.calls.append({'goal':goal,'route':route,'reasoning':reasoning})
        return self.responses.pop(0) if self.responses else (copy.deepcopy(DRAFT),{'status':'SUCCEEDED','dispatched':True})


class ContractParserTests(unittest.TestCase):
    def test_strict_model_shape_never_accepts_executable_or_approval(self):
        self.assertEqual(decode(json.dumps(DRAFT)),DRAFT)
        self.assertEqual(decode('```json\n'+json.dumps(DRAFT)+'\n```'),DRAFT)
        with self.assertRaises(ValueError):decode('extra instruction\n```json\n'+json.dumps(DRAFT)+'\n```')
        for value in [{**DRAFT,'approved':True},{**DRAFT,'code':'import os'},{**DRAFT,'heldout_cases':[]},
                      {**DRAFT,'public_cases':DRAFT['public_cases']*2},{**DRAFT,'public_cases':[{'input':float('nan'),'expected':'0'}]}]:
            with self.assertRaises((ValueError,policy.CoreError)):decode(json.dumps(value))
        with self.assertRaises(ValueError):decode('{"input_contract":"a","input_contract":"b"}')


class ToolContractTests(ProjectToolTests):
    def setUp(self):
        super().setUp();self.intents=ToolIntents(self.tools);self.contracts=ToolContracts(self.tools)
        self.provider=DraftProvider();self.evolution.provider=self.provider
        self.plan=self.intents.propose(self.cid,{'request_id':uuid.uuid4().hex,'message':'/工具 计算整数数组之和'})

    def draft(self,key=None):
        item=self.contracts.submit(self.cid,self.plan['id'],{'request_id':key or uuid.uuid4().hex})
        deadline=time.monotonic()+10
        while self.evolution.busy and time.monotonic()<deadline:time.sleep(.02)
        return self.contracts.bound(self.cid,self.plan['id'],item['id'])

    def review_payload(self,job):
        return {'request_id':self.plan['id'],'prompt':self.plan['message'],'draft_digest':job['result']['digest'],
            'contract':copy.deepcopy(DRAFT),'answers':['是，空数组返回字符串零。'],
            'oracle_note':'private-oracle-note: 人工按整数加法核算留出案例。','reviewed':True,
            'coding':{'paths':['calc.py'],'model':'vertex::gemini-3.8-flash','coding_provider':'gateway',
            'build_recipe':'python-zipapp-v1','cases':copy.deepcopy(DRAFT['public_cases']),
            'heldout_cases':[{'input':[3,8],'expected':'11'},{'input':[-4,4],'expected':'0'}]}}

    def test_draft_to_review_code_publish_and_actual_use(self):
        key=uuid.uuid4().hex;draft=self.draft(key);self.assertEqual(draft['status'],'SUCCEEDED')
        self.assertFalse(draft['result']['independently_verified'])
        self.assertEqual(self.draft(key)['id'],draft['id']);self.assertEqual(len(self.provider.calls),1)
        self.assertEqual(self.provider.calls[0]['goal'],self.plan['message'])
        payload=self.review_payload(draft);job=self.contracts.review(self.cid,self.plan['id'],draft['id'],payload)
        self.assertEqual(job['status'],'PROPOSED');self.assertFalse(self.calls)
        self.assertNotIn('private-oracle-note',job['request']['origin']['goal'])
        self.sources=[GOOD];demands=CodingDemands(self.core,self.bridge);job=demands.start(self.cid,job['id'],{})
        self.report({'task_id':job['task_id']});self.assertTrue(demands.bound(self.cid,job['id'])['result']['verified'])
        self.completed(self.request(task_id=job['task_id']))
        plan=self.intents.propose(self.cid,{'request_id':uuid.uuid4().hex,'message':'请用求和工具处理 [20,22]'})
        call=self.intents.start(self.cid,plan['id'],{});deadline=time.monotonic()+20
        while self.evolution.busy and time.monotonic()<deadline:time.sleep(.03)
        self.assertEqual(self.evolution.store.job(call['id'])['result']['text'],'42')
        self.assertEqual(self.contracts.review(self.cid,self.plan['id'],draft['id'],payload)['id'],job['id'])

    def test_review_requires_answers_nonoverlapping_oracle_and_exact_contract(self):
        draft=self.draft();payload=self.review_payload(draft)
        for field,value in [('reviewed',False),('answers',[]),('oracle_note',''),('draft_digest','bad')]:
            changed=copy.deepcopy(payload);changed[field]=value
            with self.assertRaises(policy.CoreError):self.contracts.review(self.cid,self.plan['id'],draft['id'],changed)
        for mutate in [lambda p:p['coding'].update(cases=[{'input':0,'expected':'0'},{'input':1,'expected':'1'}]),
                       lambda p:p['coding'].update(heldout_cases=DRAFT['public_cases']),
                       lambda p:p['contract'].update(questions=[])]:
            changed=copy.deepcopy(payload);mutate(changed)
            with self.assertRaises(policy.CoreError):self.contracts.review(self.cid,self.plan['id'],draft['id'],changed)
        self.assertNotIn('review',self.contracts.bound(self.cid,self.plan['id'],draft['id']))

    def test_crash_between_review_and_handoff_reconciles_or_blocks_changed_source(self):
        draft=self.draft();payload=self.review_payload(draft)
        with patch.object(CodingDemands,'propose',side_effect=RuntimeError('simulated crash')):
            with self.assertRaises(RuntimeError):self.contracts.review(self.cid,self.plan['id'],draft['id'],payload)
        self.assertIn('review',self.contracts.bound(self.cid,self.plan['id'],draft['id']))
        original=(self.source/'calc.py').read_bytes();(self.source/'calc.py').write_bytes(original+b'\n# changed\n')
        with self.assertRaises(policy.CoreError):self.contracts.review(self.cid,self.plan['id'],draft['id'],payload)
        (self.source/'calc.py').write_bytes(original)
        job=ToolContracts(self.tools).review(self.cid,self.plan['id'],draft['id'],payload)
        self.assertEqual(self.intents.view(self.cid,self.plan['id'])['coding']['id'],job['id'])
        changed=copy.deepcopy(payload);changed['oracle_note']='changed independent basis'
        with self.assertRaises(policy.CoreError):self.contracts.review(self.cid,self.plan['id'],draft['id'],changed)

    def test_scope_stale_directory_runtime_and_cancel_block_acceptance(self):
        draft=self.draft();payload=self.review_payload(draft)
        with self.assertRaises(policy.CoreError):self.contracts.bound(uuid.uuid4().hex,self.plan['id'],draft['id'])
        with patch('jarvis_core.evolution.tool_contract.runtime_binding',return_value='changed'),self.assertRaises(policy.CoreError):
            self.contracts.review(self.cid,self.plan['id'],draft['id'],payload)
        with patch.object(self.contracts.intents,'catalog',return_value=[{'changed':True}]),self.assertRaises(policy.CoreError):
            self.contracts.review(self.cid,self.plan['id'],draft['id'],payload)
        self.intents.cancel(self.cid,self.plan['id'])
        with self.assertRaises(policy.CoreError):self.contracts.review(self.cid,self.plan['id'],draft['id'],payload)

    def test_fallback_and_unknown_are_bounded_and_recorded(self):
        settings=self.evolution.store.settings();settings['models']['evolve']['fallback']={'route':'backup::test','reasoning':'low'}
        self.evolution.store.configure(settings)
        self.provider.responses=[(None,{'status':'FAILED','error_category':'quota_exhausted','dispatched':False})]
        draft=self.draft();self.assertEqual(draft['status'],'SUCCEEDED');self.assertEqual(len(draft['attempts']),2)
        self.assertEqual(self.provider.calls[-1]['route'],'backup::test')
        self.provider.responses=[(None,{'status':'UNKNOWN','outcome_uncertain':True,'dispatched':True})]
        draft=self.draft();self.assertEqual(draft['status'],'UNKNOWN');self.assertEqual(len(draft['attempts']),1)
        self.assertEqual(len(self.provider.calls),3)

    def test_capacity_and_same_request_wrong_plan_rejected(self):
        key=uuid.uuid4().hex;draft=self.draft(key)
        other=self.intents.propose(self.cid,{'request_id':uuid.uuid4().hex,'message':'/工具 转换温度'})
        with self.assertRaises(policy.CoreError):self.contracts.submit(self.cid,other['id'],{'request_id':key})
        for _ in range(3):self.draft()
        with self.assertRaises(policy.CoreError):self.draft()
        self.assertEqual(len(self.provider.calls),4)

    def test_parent_cancel_stops_inflight_draft_and_restart_does_not_replay(self):
        entered=threading.Event()
        def wait_call(goal,route,cancel,checkpoint,reasoning=None):
            entered.set();cancel.wait(5);checkpoint();return DRAFT,{'status':'SUCCEEDED'}
        self.provider.contract=wait_call
        job=self.contracts.submit(self.cid,self.plan['id'],{'request_id':uuid.uuid4().hex})
        self.assertTrue(entered.wait(3));self.intents.cancel(self.cid,self.plan['id'])
        deadline=time.monotonic()+5
        while self.evolution.busy and time.monotonic()<deadline:time.sleep(.02)
        self.assertEqual(self.evolution.store.job(job['id'])['status'],'CANCELLED')
        self.assertIsNone(self.evolution.store.job(job['id'])['result'])
        # Simulated persisted job from a dead process, with no live worker.
        parent=self.intents.propose(self.cid,{'request_id':uuid.uuid4().hex,'message':'/工具 新的转换'})
        request={**job['request'],'plan_id':parent['id'],'request_id':'tool-contract-'+uuid.uuid4().hex}
        saved,_=self.evolution.store.create_job(request);self.evolution.store.update(saved,status='RUNNING')
        self.evolution.store.recover()
        resumed=self.contracts.submit(self.cid,parent['id'],{'request_id':request['request_id'][14:]})
        self.assertEqual(resumed['status'],'INTERRUPTED');self.assertFalse(self.evolution.busy)


for name in dir(ProjectToolTests):
    if name.startswith('test_') and name not in ToolContractTests.__dict__:setattr(ToolContractTests,name,None)
del ProjectToolTests
if __name__=='__main__':unittest.main()
