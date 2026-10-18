"""Frozen case repair, LPAC execution, source guards and reversible application."""
import json
import sys
import threading
import time
import unittest
import uuid
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).parent))
import test_skills as fixture
from jarvis_core import policy
from jarvis_core.coding_workflow import apply_result, check_code
from jarvis_core.conversation_tasks import ConversationTasks
from jarvis_computer.web import ComputerWeb
from jarvis_core.skill_tasks import validate_request

BAD="def transform(data):\n    return 'wrong'\n"
GOOD="def transform(data):\n    return str(sum(data))\n"
CASES=[{'input':[2,4],'expected':'6'},{'input':[],'expected':'0'}]

class CodingTests(fixture.Fixture):
    def setUp(self):
        super().setUp();(self.source/'calc.py').write_bytes(b'\xef\xbb\xbf'+BAD.encode())
        self.manager=ComputerWeb(self.core,fixture.FakeChat());self.addCleanup(self.manager.close)
        self.bridge=ConversationTasks(self.core,self.manager);self.calls=[];self.sources=[GOOD]
        def generate(prompt,instructions,guard):
            self.assertIn('security_epoch',guard());self.assertLessEqual(len(instructions.encode()),4096);self.calls.append(json.loads(prompt))
            code=self.sources.pop(0) if len(self.sources)>1 else self.sources[0]
            return {'status':'UNKNOWN','outcome_uncertain':True} if code is None else {'status':'SUCCEEDED','text':json.dumps({'code':code,'notes':'fixture'}),'usage':{}}
        self.manager.skills.coding_generate=generate
    def submit(self,**kw):
        return self.bridge.submit(self.cid,{'mode':'skill','request_id':'web-'+uuid.uuid4().hex,'prompt':'修复求和，保留空表结果为0','project_id':self.project['id'],'skill_id':fixture.REVIEW,'paths':['calc.py'],'coding':True,'cases':CASES,'model':'vertex::gemini-3.8-flash',**kw})
    def wait(self,item):
        until=time.monotonic()+45
        while time.monotonic()<until:
            d=self.bridge.detail(self.cid,item['task_id'])
            if d['task']['status'] not in {'READY','RUNNING','CANCELLING'}:return d
            time.sleep(.05)
        self.fail('timeout')
    def report(self,item):
        d=self.wait(item);self.assertEqual(d['action_status'],'CONFIRMED',d)
        return json.loads(self.bridge.artifact(self.cid,item['task_id']))
    def test_actual_lpac_repair_apply_rollback_bom(self):
        self.sources=[BAD,GOOD];r=self.report(self.submit());v=r['coding']
        self.assertTrue(v['passed']);self.assertEqual(len(v['attempts']),2);self.assertEqual(len(v['composition']),4)
        self.assertTrue(v['validation']['worker']['lpac']);self.assertEqual((self.source/'calc.py').read_bytes(),b'\xef\xbb\xbf'+BAD.encode())
        self.assertEqual(apply_result(self.core,r,'apply')['status'],'applied')
        self.assertEqual((self.source/'calc.py').read_bytes(),b'\xef\xbb\xbf'+GOOD.encode())
        self.assertEqual(apply_result(self.core,r,'apply')['status'],'already_applied')
        self.assertEqual(apply_result(self.core,r,'rollback')['status'],'restored')
        self.assertEqual(apply_result(self.core,r,'rollback')['status'],'already_restored')
    def test_failed_candidate_and_unknown_never_apply(self):
        self.sources=[BAD];r=self.report(self.submit());self.assertFalse(r['coding']['passed']);self.assertEqual(len(self.calls),2)
        with self.assertRaises(policy.CoreError):apply_result(self.core,r,'apply')
        self.sources=[None];d=self.wait(self.submit());self.assertEqual(d['task']['status'],'UNKNOWN');self.assertEqual(len(self.calls),3)
    def test_passing_baseline_no_paid_call(self):
        (self.source/'calc.py').write_text(GOOD,encoding='utf-8');r=self.report(self.submit());self.assertFalse(self.calls);self.assertEqual(r['coding']['diff'],'')
    def test_invalid_candidate_repaired_without_host_execution(self):
        self.sources=['import os\ndef transform(data):\n    return str(os.system("bad"))\n',GOOD]
        r=self.report(self.submit());self.assertTrue(r['coding']['passed']);self.assertEqual(self.calls[1]['test_feedback']['error'],'candidate_invalid')
    def test_source_conflict_no_overwrite(self):
        r=self.report(self.submit());(self.source/'calc.py').write_text('external',encoding='utf-8')
        with self.assertRaises(policy.CoreError):apply_result(self.core,r,'apply')
        with self.assertRaises(policy.CoreError):apply_result(self.core,r,'rollback')
        self.assertEqual((self.source/'calc.py').read_text(),'external')
    def test_cancellation_and_source_change_during_model(self):
        entered=threading.Event();release=threading.Event()
        def blocked(*a):
            entered.set()
            while not release.wait(.02):a[-1]()
            a[-1]();return {'status':'UNKNOWN'}
        self.manager.skills.coding_generate=blocked
        item=self.submit();self.assertTrue(entered.wait(15));self.bridge.cancel(self.cid,item['task_id'],{});release.set()
        self.assertEqual(self.wait(item)['task']['status'],'CANCELLED')
        entered.clear();release.clear();item=self.submit();self.assertTrue(entered.wait(15));(self.source/'calc.py').write_text(GOOD);release.set()
        self.assertEqual(self.wait(item)['error']['code'],'skill_source_changed')
    def test_all_composed_skills_must_be_available(self):
        self.skills.put_policy({'skill_id':'matt-pocock.tdd','scope':'global','revision':0,'mode':'disabled'})
        with self.assertRaises(policy.CoreError):self.submit()
        self.assertFalse(self.calls)
    def test_receipt_interrupted_after_write_reconciles_without_rewrite(self):
        from jarvis_core.project_files import ProjectFiles
        r=self.report(self.submit());write=ProjectFiles.write
        def lost(files,args):
            write(files,args);raise policy.CoreError('injected_receipt_loss','injected')
        with patch.object(ProjectFiles,'write',lost),self.assertRaises(policy.CoreError):apply_result(self.core,r,'apply')
        with patch.object(ProjectFiles,'write',side_effect=AssertionError('must not replay')):
            self.assertEqual(apply_result(self.core,r,'apply')['status'],'already_applied')
        with self.core.ledger.connection() as db:self.assertEqual(db.execute('SELECT state FROM coding_changes').fetchone()[0],'CONFIRMED_OBSERVED')
    def test_single_json_fence_normalization_is_still_strict(self):
        self.manager.skills.coding_generate=lambda *a:{'status':'SUCCEEDED','text':'```json\n'+json.dumps({'code':GOOD,'notes':'fixture'})+'\n```'}
        r=self.report(self.submit());self.assertTrue(r['coding']['passed']);self.assertEqual(len(r['coding']['attempts']),1)
    def test_validation_boundaries(self):
        for change in ({'cases':[]},{'cases':[{'input':1,'expected':1}]*2},{'paths':['calc.py','x.py']},{'model':'auto'},{'skill_id':'matt-pocock.teach'},{'coding':False},{'output_path':'out.txt'},{'cases':[{'input':float('nan'),'expected':'x'}]*2}):
            with self.subTest(change=change),self.assertRaises(policy.CoreError):self.submit(**change)
    def test_worker_cannot_omit_cases(self):
        class Runner:
            def run(self,*a):return [],{}
        self.assertFalse(check_code(Runner(),GOOD,CASES,lambda:None)['passed'])

if __name__=='__main__':unittest.main()
