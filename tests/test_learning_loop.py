"""Real K3/LPAC/K4 handoff and rollback; model replies are deterministic fixtures."""
import time
import unittest
import uuid
from unittest.mock import patch

from test_growth_cycles import GrowthCycleTests
from jarvis_core import policy
from jarvis_core.evolution.learning_loop import LearningLoop


class LearningTests(GrowthCycleTests):
    def setUp(self):
        super().setUp()
        self.learning=LearningLoop(self.evolution,self.bridge)
        self.lid=uuid.uuid4().hex
        self.learning.create(dict(id=self.lid,goal='每天清理并去重购物清单，减少重复操作。',conversation_id=self.cid))

    def reviewed(self):
        self.learning.evidence(self.lid,dict(source='明确输入输出契约与本机对照样例',
            notes='保留首次出现顺序；去除空白项；保留大小写差异。外部资料只作为参考。',task_id=None))
        return self.learning.review(self.lid,'已核对需求、来源适用范围及独立留出案例，沿用原契约。')

    def request(self):
        return dict(target='tool',model='',domain='clean-lines',
                    policy_revision=self.cycles.snapshot(self.cid)['policy']['revision'])

    def test_real_learning_tool_benefit_withdrawal_and_restart_provenance(self):
        self.grant();self.reviewed()
        row=self.learning.start(self.lid,self.request());cid=row['handoff']['result_id']
        with patch('jarvis_core.evolution.growth_cycle.baseline',side_effect=self.normal_baseline):
            result=self.drive(cid)
        self.assertEqual(result['status'],'COMPLETE',result.get('stop_reason'))
        observed=self.learning.view(self.lid)
        self.assertTrue(observed['outcome']['assessment']['verified'])
        self.assertEqual(observed['outcome']['assessment']['calls_saved'],5)
        self.learning.feedback(self.lid,True,'在购物清单实际重复工作中减少了手工处理。')
        self.assertEqual(LearningLoop(self.evolution,self.bridge).read(self.lid)['evidence'],
                         observed['evidence'])
        self.learning.withdraw(self.lid)
        result=self.drive(cid,until='CANCELLED')
        self.assertEqual(result['status'],'CANCELLED')
        self.assertIsNone(self.tools.selected(self.project['id'],result['tool_id'])['active'])
        with self.assertRaises(policy.CoreError):self.learning.start(self.lid,self.request())

    def test_unreviewed_and_changed_evidence_cannot_generate(self):
        self.grant()
        with self.assertRaises(policy.CoreError):self.learning.start(self.lid,self.request())
        self.reviewed()
        self.learning.evidence(self.lid,dict(source='修订资料',notes='新资料与原理解矛盾，需要重新审阅。',task_id=None))
        with self.assertRaises(policy.CoreError):self.learning.start(self.lid,self.request())
        self.assertFalse(self.calls)
        self.assertEqual(self.learning.view(self.lid)['state'],'EVIDENCE_READY')

    def test_research_is_bound_to_same_request_and_conversation(self):
        submitted=[]
        with patch.object(self.bridge,'submit',side_effect=lambda cid,payload:submitted.append((cid,payload))),patch.object(
                self.bridge,'lookup',side_effect=policy.CoreError('not_found','pending')):
            self.learning.research(self.lid,'python')
            self.learning.research(self.lid,'python')
            with self.assertRaises(policy.CoreError):self.learning.research(self.lid,'different')
        self.assertEqual(submitted[0],submitted[1])
        self.assertEqual(submitted[0][0],self.cid)
        self.assertEqual(submitted[0][1]['mode'],'mcp')

    def test_failed_receipts_propose_learning_unknown_does_not(self):
        args={'prompt':'请改善这次重复报告的失败原因。','conversation_id':self.cid}
        prepared=self.core.ledger.prepare(uuid.uuid4().hex,args,capability='team.analysis.v1',runtime_seconds=180)
        aid=prepared['action']['action_id']
        self.core.ledger.begin_dispatch(aid,self.core.host_instance_id)
        self.core.ledger.finish_without_receipt(aid,'FAILED',{'code':'fixture_failure','message':'fixture'})
        opportunities=self.learning.opportunities()
        self.assertEqual(len(opportunities),1)
        captured=self.learning.capture(prepared['task']['task_id'])
        self.assertEqual(captured['origin']['task_id'],prepared['task']['task_id'])
        self.assertEqual(captured['state'],'DRAFT')
        unknown=self.core.ledger.prepare(uuid.uuid4().hex,dict(args,prompt='另一个未知任务。'),capability='team.analysis.v1',runtime_seconds=180)
        self.core.ledger.begin_dispatch(unknown['action']['action_id'],self.core.host_instance_id)
        self.core.ledger.finish_without_receipt(unknown['action']['action_id'],'UNKNOWN',{'code':'fixture_unknown','message':'fixture'})
        self.assertEqual(len(self.learning.opportunities()),1)

    def test_real_mcp_resolve_query_and_collect_preserve_untrusted_provenance(self):
        import httpx
        from test_mcp_runtime import Protocol
        from jarvis_core.mcp_client import Context7Client, ENDPOINT
        from jarvis_core.mcp_tasks import McpTaskService
        from jarvis_core.extensions import ExtensionCatalog
        ExtensionCatalog(self.core).put(uuid.uuid4().hex,{'revision':0,'document':{
            'kind':'mcp','name':'Context7','catalog_id':'context7',
            'config':{'transport':'streamable-http','url':ENDPOINT}}})
        protocol=Protocol()
        service=McpTaskService(self.core,client_factory=lambda check:Context7Client(check,transport=httpx.MockTransport(protocol)))
        self.manager.queue.mcp_executor=lambda:service
        def wait_research():
            end=time.monotonic()+10
            while time.monotonic()<end:
                row=self.learning.view(self.lid)
                if row.get('research_receipt',{}).get('action_status')=='CONFIRMED':return row
                time.sleep(.04)
            self.fail('documentation receipt not confirmed')
        self.learning.research(self.lid,'Electron')
        self.assertEqual(wait_research()['research_candidates'],['/electron/electron'])
        with self.assertRaises(policy.CoreError):self.learning.collect(self.lid)
        self.learning.research(self.lid,'/electron/electron')
        wait_research()
        candidate=self.learning.collect(self.lid)
        self.assertEqual(candidate['evidence']['trust'],'untrusted_reference')
        self.assertTrue(candidate['evidence']['artifact']['digest'].startswith('sha256:'))
        self.assertIn('<script>',candidate['evidence']['notes'])  # Kept as data, never executed.
        self.assertEqual(candidate['state'],'EVIDENCE_READY')
        self.assertIsNone(candidate['review'])


def load_tests(loader,tests,pattern):
    return unittest.TestSuite(LearningTests(n) for n in LearningTests.__dict__ if n.startswith('test_'))
