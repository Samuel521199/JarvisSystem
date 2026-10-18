"""Bounded static evidence, cited explanations and one-call task lifecycle."""
import json
from pathlib import Path
import sys
import time
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'tests'),str(ROOT/'runtime/node-host'),str(ROOT/'adapters/computer-use')]
import test_skills
from test_rea import fixture
from jarvis_core import rea_explanation as explanation
from jarvis_core.policy import CoreError


class Model(test_skills.ReportModel):
    invalid=False
    mutate=None
    def reply(self,message,**kwargs):
        reply=super().reply(message,**kwargs)
        data=json.loads(message)
        reply['text']=json.dumps({'findings':[{'kind':'observation','text':'静态证据包含通道关系。',
            'refs':['FAKE' if self.invalid else data['sources'][0]['ref']]}],
            'unknowns':['未运行目标软件，无法确认实际运行结果。']},ensure_ascii=False)
        if self.mutate:self.mutate()
        return reply


class ValidationTests(unittest.TestCase):
    def test_validate_shape_refs_and_limits(self):
        valid={'findings':[{'kind':'inference','text':'推断','refs':['E1']}],'unknowns':['未运行']}
        self.assertEqual(explanation.validate(json.dumps(valid),[{'ref':'E1'}]),valid)
        self.assertEqual(explanation.validate('```json\n'+json.dumps(valid)+'\n```',[{'ref':'E1'}]),valid)
        self.assertEqual(explanation.validate('```json\n'+json.dumps(valid)+'```',[{'ref':'E1'}]),valid)
        with self.assertRaises(ValueError):explanation.validate('```json\n'+json.dumps(valid)+'``` additional text',[{'ref':'E1'}])
        for bad in [dict(valid,unknowns=[]),dict(valid,extra=True),dict(valid,findings=[{'kind':'fact','text':'x','refs':['E1']}]),
                    dict(valid,findings=[{'kind':'inference','text':'x','refs':['E9']}]),
                    dict(valid,findings=[{'kind':'inference','text':'x','refs':['E1','E1']}])]:
            with self.assertRaises(ValueError):explanation.validate(json.dumps(bad),[{'ref':'E1'}])
        with self.assertRaises(ValueError):explanation.validate('{"findings":[],"findings":[],"unknowns":["x"]}',[])

    def test_packet_bounds_and_focus(self):
        links=[{'relation':'calls','edge_id':str(i),'properties':{'literal':'x'*1000}} for i in range(100)]
        report={'analysis':{'key_links':links,'key_links_omitted':0},'input_manifest':{'files':[],'omitted':[]}}
        value,raw=explanation.packet(report,{'prompt':'分析'})
        self.assertLessEqual(len(raw.encode()),24576);self.assertLessEqual(len(value['sources']),24)
        self.assertGreater(value['coverage']['omitted_links'],0)
        report['analysis']['focus']={'query':'none','links':[],'link_count':0}
        self.assertEqual(explanation.packet(report,{'prompt':'分析'})[0]['sources'],[])


class ExplanationTasks(test_skills.TaskTests):
    def setUp(self):
        super().setUp();fixture(self.source/'application');self.model=Model()
        self.manager.skills.chat_factory=lambda *a,**kw:self.model
        self.addCleanup(self.model.release.set)

    def submit(self,**kwargs):
        return super().submit(**{'skill_id':'rea.software-analysis','paths':[],
            'target_path':'application','prompt':'解释 jarvis:sum 的调用关系','focus':'jarvis:sum',
            'explain':True,'model':'test::synthetic',**kwargs})

    def wait(self,item):
        # Functional completion follows the production task budget. Three full
        # bundle integrity scans can exceed the generic skill fixture's 35s on
        # a busy PC; this is not a 35s performance acceptance test.
        from jarvis_core.skill_tasks import TIMEOUT_SECONDS
        return super().wait(item,timeout_seconds=TIMEOUT_SECONDS+5)

    def test_delivery_bound_citations_and_idempotence(self):
        item=self.submit();detail=self.wait(item);self.assertEqual(detail['action_status'],'CONFIRMED',detail.get('error'))
        report=detail['report'];result=report['explanation']
        self.assertTrue(result['citations_verified']);self.assertFalse(result['semantics_verified'])
        self.assertEqual(report['checks']['model_calls'],1);self.assertFalse(report['checks']['target_executed'])
        self.assertIn('模型调用 1 次',report['text']);self.assertNotIn('没有模型调用',report['text'])
        self.assertEqual(result['input_digest'],report['input_manifest']['digest'])
        self.assertEqual(result['evidence_id'],report['evidence_ref']['evidence_id'])
        message,args=self.model.calls[0];self.assertEqual(args['_purpose'],'rea_explanation');self.assertEqual(args['_route_attempt_limit'],1)
        self.assertFalse(any(k in args for k in ('history','attachments','memory_context','skill_context')))
        self.manager.skills.run(self.core.ledger.record(task_id=item['task_id'])['action']['action_id'])
        self.assertEqual(len(self.model.calls),1)

    def test_no_evidence_and_default_make_zero_calls(self):
        detail=self.wait(self.submit(focus='missing:channel'))
        self.assertEqual(detail['action_status'],'CONFIRMED',detail.get('error'))
        self.assertEqual(detail['report']['explanation']['status'],'INSUFFICIENT_EVIDENCE')
        detail=self.wait(self.submit(explain=False,model='auto'))
        self.assertEqual(detail['action_status'],'CONFIRMED',detail.get('error'))
        self.assertNotIn('explanation',detail['report']);self.assertFalse(self.model.calls)

    def test_invalid_citation_not_delivered(self):
        self.model.invalid=True
        detail=self.wait(self.submit());self.assertEqual(detail['task']['status'],'FAILED')
        self.assertEqual(len(self.model.calls),1)
        with self.assertRaises(CoreError):self.bridge.artifact(self.cid,detail['task']['task_id'])

    def test_source_change_not_delivered(self):
        self.model.mutate=lambda:(self.source/'application/main.js').write_text('exports.changed=1;',encoding='utf-8')
        detail=self.wait(self.submit());self.assertEqual(detail['task']['status'],'FAILED')

    def test_unknown_no_retry(self):
        self.model.status='UNKNOWN'
        detail=self.wait(self.submit());self.assertEqual(detail['task']['status'],'UNKNOWN')
        self.assertEqual(len(self.model.calls),1)

    def test_policy_change_before_dispatch(self):
        from jarvis_core import rea
        original=rea.analyze
        def disable(*args,**kwargs):
            report=original(*args,**kwargs)
            self.skills.put_policy({'skill_id':'rea.software-analysis','scope':'global','revision':0,'mode':'disabled'})
            return report
        with patch.object(rea,'analyze',side_effect=disable):detail=self.wait(self.submit())
        self.assertEqual(detail['task']['status'],'FAILED');self.assertFalse(self.model.calls)

    def test_cancel_no_retry(self):
        from jarvis_core.skill_tasks import TIMEOUT_SECONDS
        self.model.release.clear();item=self.submit();self.assertTrue(self.model.entered.wait(TIMEOUT_SECONDS))
        self.bridge.cancel(self.cid,item['task_id'],{});detail=self.wait(item)
        self.assertEqual(detail['task']['status'],'CANCELLED');self.assertEqual(len(self.model.calls),1)

    def test_reject_implicit_model(self):
        for value in ('auto','auto::default',None):
            with self.assertRaises(CoreError):self.submit(model=value)

    def test_purpose_cannot_inherit_context_or_trigger_other_skills(self):
        from jarvis_core.chat import ChatService
        chat=ChatService(self.core)
        with self.assertRaises(ValueError):chat.reply('请记住秘密',provider='openai',_purpose='rea_explanation',context_note='inherited')
        def provider(*a,**kw):
            self.assertEqual(kw['instructions'],explanation.INSTRUCTIONS)
            self.assertLess(len(kw['instructions'].encode()),4096)
            return {'status':'SUCCEEDED','text':'{"findings":[],"unknowns":["没有运行"]}','provider':'openai','model':'fixture','usage':{}}
        with patch('jarvis_core.chat.gateway.probe',side_effect=provider) as call:
            result=chat.reply('请记住测试：审阅代码',provider='openai',_purpose='rea_explanation',_route_attempt_limit=1)
            self.assertEqual(result['status'],'SUCCEEDED',result);self.assertEqual(call.call_count,1)


for name in list(test_skills.TaskTests.__dict__):
    if name.startswith('test_'):setattr(ExplanationTasks,name,None)


if __name__=='__main__':unittest.main()
