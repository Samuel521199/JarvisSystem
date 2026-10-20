"""Research -> independent analysis -> code candidate on existing real executors."""
import json
import time
import unittest
import uuid

from test_coding_workflow import CodingTests, CASES, GOOD, BAD, fixture
from test_team_tasks import Calls, Provider, REVIEW
from test_mcp_runtime import Protocol
from jarvis_core.assistant_plans import AssistantPlans
from jarvis_core.conversations import ConversationStore
from jarvis_core.mcp_tasks import McpTaskService
from jarvis_core.mcp_client import Context7Client, ENDPOINT
from jarvis_core.extensions import ExtensionCatalog
from jarvis_core.team_tasks import TeamTaskService
from test_conversations import document
import httpx


class ExecutionTests(CodingTests):
    def setUp(self):
        super().setUp()
        doc=document('研究、分析，再生成求和代码候选');doc['project_id']=self.project['id']
        ConversationStore(self.core).put(self.cid,{'revision':0,'document':doc})
        self.plans=AssistantPlans(self.core,self.bridge,start=False);self.addCleanup(self.plans.close)
        ExtensionCatalog(self.core).put(uuid.uuid4().hex,{'revision':0,'document':{
            'kind':'mcp','name':'Context7','catalog_id':'context7',
            'config':{'transport':'streamable-http','url':ENDPOINT}}})
        protocol=Protocol()
        mcp=McpTaskService(self.core,client_factory=lambda check:Context7Client(check,transport=httpx.MockTransport(protocol)))
        self.manager.mcp=mcp;self.manager.queue.mcp_executor=lambda:mcp
        self.team_calls=Calls()
        team=TeamTaskService(self.core,model_calls=self.team_calls,provider=Provider())
        self.manager.team=team;self.manager.queue.team_executor=lambda:team

    def plan(self):
        ids=[uuid.uuid4().hex for _ in range(3)]
        payloads=[
            {'mode':'mcp','library':'python','prompt':'sum list'},
            {'mode':'team','prompt':'分析求和方案','criteria':['资源占用有实测'],'planner_model':'local::planner','reviewer_model':'local::reviewer'},
            {'mode':'skill','prompt':'修复求和，保留空表结果为0','project_id':self.project['id'],'skill_id':fixture.REVIEW,
             'paths':['calc.py'],'coding':True,'cases':CASES,'model':'vertex::gemini-3.8-flash'}]
        row=self.plans.create(self.cid,{'goal':'研究求和并交付通过检查的代码候选',
            'steps':[{'id':ids[i],'title':str(i+1),'payload':p,'depends_on':[ids[i-1]] if i else []}
                     for i,p in enumerate(payloads)]})
        return self.plans.change(row['id'],{'action':'start','revision':row['revision']})

    def drive_plan(self,row):
        end=time.monotonic()+45
        while time.monotonic()<end:
            self.plans.tick();state=self.plans.view(row['id'])
            if state['state'] in {'COMPLETE','BLOCKED'}:return state
            time.sleep(.05)
        self.fail(str(state))

    def test_research_team_code_real_artifacts_and_scoped_result(self):
        state=self.drive_plan(self.plan())
        self.assertEqual(state['state'],'COMPLETE',state)
        self.assertEqual(len(self.team_calls.requests),2)
        self.assertEqual(len(self.calls),1)
        code=self.bridge.detail(self.cid,state['steps'][2]['task_id'])['report']['coding']
        self.assertTrue(code['passed'])
        self.assertIn(BAD,(self.source/'calc.py').read_text(encoding='utf-8-sig'))
        # Independent source application is intentionally still a separate existing operation.
        self.assertEqual(len(state['candidate']['evidence']),3)
        state=self.plans.change(state['id'],{'action':'accept','revision':state['revision'],'kind':'knowledge','providers':[]})
        from jarvis_core.memory import MemoryStore
        fact=MemoryStore(self.core).list(project_id=self.project['id'])['facts'][0]
        self.assertEqual(fact['document']['classification']['uses'],['work_assist'])
        self.assertEqual(fact['document']['project_id'],self.project['id'])

    def test_failed_code_checks_block_result_promotion_and_replan_preserves_completed(self):
        self.sources=[BAD]
        state=self.drive_plan(self.plan())
        self.assertEqual(state['state'],'BLOCKED',state)
        self.assertEqual(state['steps'][-1]['state'],'FAILED')
        self.assertIsNone(state['candidate'])
        fresh=self.plans.change(state['id'],{'action':'replan','revision':state['revision']})
        self.assertEqual([s['state'] for s in fresh['steps']],['SUCCEEDED','SUCCEEDED','DRAFT'])
        self.assertEqual(fresh['steps'][0]['task_id'],state['steps'][0]['task_id'])
        self.assertNotEqual(fresh['steps'][2]['request_id'],state['steps'][2]['request_id'])
        self.assertEqual(fresh['parent_plan'],state['id'])


def load_tests(loader,tests,pattern):
    return unittest.TestSuite(ExecutionTests(n) for n in ExecutionTests.__dict__ if n.startswith('test_'))
