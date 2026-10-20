"""Personal plans use real ledgers, FIFO and Worker; model output is a fixture."""
from copy import deepcopy
from datetime import datetime, timezone
import json
import sqlite3
import time
import unittest
import uuid
from unittest.mock import patch

from test_conversation_tasks import ConversationTaskTests
from test_conversations import document
from jarvis_core.assistant_plans import AssistantPlans, DEFAULT_POLICY, quiet
from jarvis_core.assistant_plan_store import connection, read, save
from jarvis_core.conversations import ConversationStore
from jarvis_core.memory import MemoryStore
from jarvis_core.memory_sources import usable
from jarvis_core.policy import CoreError
from jarvis_core.plan_budget import reserve, current_task, settle
from jarvis_core.runtime_admission import RuntimeAdmission
from jarvis_core.resources import MIB


class PersonalPlanTests(ConversationTaskTests):
    def setUp(self):
        super().setUp()
        ConversationStore(self.core).put(self.first,{'revision':0,'document':document('整理目录，再检查结果')})
        self.now=datetime(2026,10,21,4,tzinfo=timezone.utc).timestamp()
        self.plans=AssistantPlans(self.core,self.bridge,clock=lambda:self.now,start=False)
        self.addCleanup(self.plans.close)

    def create(self,count=2):
        steps=[];previous=None
        for i in range(count):
            ident=uuid.uuid4().hex
            steps.append({'id':ident,'title':'整理样例目录 '+str(i),'payload':{
                'mode':'natural','prompt':'列举样例并统计保存报告','model':'auto'},
                'depends_on':[previous] if previous else []})
            previous=ident
        return self.plans.create(self.first,{'id':uuid.uuid4().hex,'goal':'整理资料并核对结果','steps':steps})

    def change(self,row,action,**kwargs):
        return self.plans.change(row['id'],{'action':action,'revision':row['revision'],**kwargs})

    def drive(self,row):
        self.manager.queue.set_paused(False)
        deadline=time.monotonic()+15
        while time.monotonic()<deadline:
            self.plans.tick()
            value=self.plans.view(row['id'])
            if value['state'] in {'COMPLETE','BLOCKED','CANCELLED'}:return value
            time.sleep(.02)
        self.fail('Plan not finished: '+str(value))

    def test_real_two_step_worker_results_and_no_replay(self):
        row=self.create();row=self.change(row,'start')
        row=self.drive(row)
        self.assertEqual(row['state'],'COMPLETE',row)
        self.assertTrue(all(s['result']['digest'] for s in row['steps']))
        self.assertEqual(len(self.planner.calls),2)
        self.assertEqual(row['candidate']['state'],'pending')
        self.plans.tick();self.plans.tick()
        self.assertEqual(len(self.planner.calls),2)
        self.assertEqual(len(self.bridge.list(self.first)['tasks']),2)

    def test_draft_chat_intents_are_source_bound_no_execution_and_no_negation(self):
        result={'status':'SUCCEEDED','intent_decision':{'state':'recognized','intents':[
            {'kind':'action','disposition':'requested','quote':'整理目录','capability':None,'arguments':{}},
            {'kind':'action','disposition':'negated','quote':'不要删除','capability':None,'arguments':{}}]}}
        turn={'durable':True,'request_id':uuid.uuid4().hex,'conversation_id':self.first}
        data=self.plans.propose_turn(turn,{'message':'整理目录，不要删除'},result)
        self.assertEqual(data['steps'],1);self.assertEqual(data['state'],'DRAFT')
        self.assertEqual(self.bridge.list(self.first)['tasks'],[])
        again=self.plans.propose_turn(turn,{'message':'整理目录，不要删除'},result)
        self.assertEqual(data['id'],again['id'])
        self.assertEqual(len(self.plans.list(self.first)['plans']),1)

    def test_restart_pauses_and_uses_original_task_receipt(self):
        row=self.change(self.create(),'start');self.plans.tick()
        old=self.plans.view(row['id']);task_id=old['steps'][0]['task_id']
        other=AssistantPlans(self.core,self.bridge,clock=lambda:self.now,start=False)
        self.addCleanup(other.close)
        self.assertEqual(other.view(row['id'])['state'],'PAUSED')
        other.tick()
        self.assertEqual(other.view(row['id'])['steps'][0]['task_id'],task_id)
        self.assertEqual(len(self.bridge.list(self.first)['tasks']),1)
        with self.assertRaises(CoreError):
            self.plans.change(row['id'],{'action':'start','revision':other.view(row['id'])['revision']})

    def test_unfinished_import_invalidates_on_source_change(self):
        from jarvis_core.continuity import ContinuityStore
        message='保存接续：资料整理=确认范围｜整理样例目录'
        archives=ConversationStore(self.core)
        doc=document(message);doc['messages'][0]['personal_control']=True
        archives.put(self.first,{'revision':1,'document':doc})
        store=ContinuityStore(self.core)
        receipt=store.change('save',request_id=uuid.uuid4().hex,target='资料整理',
            progress='确认范围',next_step='整理样例目录',message=message,
            source={'conversation_id':self.first,'message_index':0})
        source={'id':receipt['id'],'revision':receipt['revision']}
        self.assertEqual(self.plans.list(self.first)['unfinished'][0]['id'],receipt['id'])
        row=self.plans.create(self.first,{'goal':'完成未结资料整理','continuity_source':source,
            'steps':[{'title':'整理样例','payload':{'mode':'natural','prompt':'列举样例并统计保存报告','model':'auto'}}]})
        row=self.drive(self.change(row,'start'))
        row=self.change(row,'accept',kind='knowledge',providers=[])
        self.assertTrue(usable(MemoryStore(self.core).list()['facts'][0]))
        store.change('close',request_id=uuid.uuid4().hex,target=receipt['id'],revision=receipt['revision'])
        self.assertFalse(self.plans.view(row['id'])['scope_valid'])
        self.assertFalse(usable(MemoryStore(self.core).list()['facts'][0]))
        self.assertEqual(self.plans.list(self.first)['unfinished'],[])

    def test_supplement_completed_plan_requires_new_candidate_confirmation(self):
        row=self.drive(self.change(self.create(1),'start'))
        row=self.change(row,'accept',kind='knowledge',providers=[])
        original=row['candidate']['revision']
        steps=[{k:s[k] for k in ('id','title','payload','depends_on','include_results')} for s in row['steps']]
        steps.append({'title':'补充检查','payload':{'mode':'natural','prompt':'列举样例并统计保存报告','model':'auto'},
                      'depends_on':[steps[0]['id']]})
        row=self.change(row,'edit',steps=steps)
        self.assertFalse(usable(MemoryStore(self.core).list()['facts'][0]))
        row=self.drive(self.change(row,'start'))
        self.assertEqual(len(self.planner.calls),2)
        self.assertEqual(row['candidate']['state'],'pending')
        self.assertGreater(row['candidate']['revision'],original)
        row=self.change(row,'accept',kind='knowledge',providers=[])
        self.assertTrue(usable(MemoryStore(self.core).list()['facts'][0]))

    def test_cancel_paused_child_and_unsubmitted_step(self):
        row=self.change(self.create(),'start');self.plans.tick()
        row=self.change(self.plans.view(row['id']),'cancel')
        self.plans.tick();row=self.plans.view(row['id'])
        self.assertEqual(row['state'],'CANCELLED')
        self.assertEqual(self.planner.calls,[])
        with self.assertRaises(CoreError):self.change(row,'start')

    def test_unknown_submission_is_not_retried(self):
        row=self.change(self.create(1),'start')
        with patch.object(self.bridge,'submit',side_effect=OSError('connection lost')) as submit:
            self.plans.tick();self.plans.tick();self.plans.tick()
            self.assertEqual(submit.call_count,1)
        row=self.plans.view(row['id'])
        self.assertEqual(row['steps'][0]['state'],'UNKNOWN')
        with self.assertRaises(CoreError):self.change(row,'start')

    def test_followup_quiet_frequency_daily_limit_and_zero_model_calls(self):
        row=self.create(1);p={**DEFAULT_POLICY,'followup':True,'daily_limit':1}
        row=self.change(row,'edit',policy=p)
        self.plans.tick();row=self.plans.view(row['id'])
        self.assertEqual(len(row['notifications']),1)
        row=self.change(row,'ack');self.now+=7200;self.plans.tick()
        self.assertEqual(len(self.plans.view(row['id'])['notifications']),1)
        self.assertTrue(quiet(p,datetime(2026,10,21,15,tzinfo=timezone.utc).timestamp()))
        self.assertFalse(quiet(p,datetime(2026,10,21,4,tzinfo=timezone.utc).timestamp()))
        self.assertEqual(self.planner.calls,[])

    def test_result_candidate_correction_withdrawal_and_no_image_inference(self):
        row=self.drive(self.change(self.create(1),'start'))
        row=self.change(row,'accept',kind='personal',providers=[])
        fact=MemoryStore(self.core).list()['facts'][0]
        self.assertTrue(usable(fact));self.assertEqual(fact['document']['classification']['kind'],'episode')
        request={'enabled':True,'project_id':None}
        snapshot=MemoryStore(self.core).view_facts(request,'local')
        self.assertTrue(MemoryStore(self.core).context(request,'local',facts=snapshot)[0])
        row=self.change(row,'candidate',content='主人纠正：只完成样例，真实资料仍未整理。')
        self.assertFalse(usable(MemoryStore(self.core).list()['facts'][0]))
        self.assertEqual(MemoryStore(self.core).context(request,'local',facts=snapshot)[0],'')
        row=self.change(row,'accept',kind='personal',providers=[])
        self.assertTrue(usable(MemoryStore(self.core).list()['facts'][0]))
        row=self.change(row,'withdraw')
        self.assertFalse(usable(MemoryStore(self.core).list()['facts'][0]))
        self.assertEqual(MemoryStore(self.core).context(request,'local')[0],'')
        with self.assertRaises(CoreError):self.change(row,'accept',kind='personal',providers=[])

    def test_budget_atomic_reservation_unknown_no_refund_and_missing_price(self):
        row=self.change(self.create(1),'start',policy={**DEFAULT_POLICY,'max_calls':1})
        self.plans.tick();row=self.plans.view(row['id'])
        token=current_task.set(row['steps'][0]['task_id'])
        try:
            with self.assertRaises(CoreError):reserve(self.core.data_dir,'missing',{'model':'test'},'cloud',100,100)
            item={'model':'test','price':{'currency':'USD','input':1,'output':1}}
            reserve(self.core.data_dir,'call1',item,'cloud',100,100)
            settle(self.core.data_dir,'call1',{'amount':None},'UNKNOWN')
            with self.assertRaises(CoreError):reserve(self.core.data_dir,'call2',item,'cloud',100,100)
        finally:current_task.reset(token)
        self.assertEqual(self.plans.view(row['id'])['usage']['calls'],1)

    def test_revision_cycle_scope_and_stale_controls(self):
        row=self.create(1)
        with self.assertRaises(CoreError):
            self.change(row,'edit',steps=[{'id':row['steps'][0]['id'],'title':'cycle','depends_on':[row['steps'][0]['id']]}])
        updated=self.change(row,'edit',goal='新目标')
        with self.assertRaises(CoreError):self.change(row,'start')
        archive=ConversationStore(self.core).get(self.first)
        ConversationStore(self.core).delete(self.first,{'revision':archive['revision']})
        with self.assertRaises(ValueError):self.change(updated,'start')
        self.assertFalse(self.plans.view(row['id'])['scope_valid'])

    def test_future_schema_is_never_downgraded(self):
        self.create(1)
        with connection(self.core.data_dir,write=True) as db:db.execute('PRAGMA user_version=2')
        with self.assertRaises(CoreError):
            with connection(self.core.data_dir,write=True):pass
        db=sqlite3.connect(self.core.data_dir/'assistant-plans.db')
        try:self.assertEqual(db.execute('PRAGMA user_version').fetchone()[0],2)
        finally:db.close()


class AdmissionTests(unittest.TestCase):
    def test_background_fifo_and_cancelled_waiter_cleanup(self):
        resources=RuntimeAdmission(lambda:{'available_bytes':8192*MIB,'commit_available_bytes':8192*MIB})
        active=resources.acquire('task',512,owner='first')
        with self.assertRaises(CoreError):resources.acquire('growth',512,owner='growth')
        with self.assertRaises(CoreError):resources.acquire('task',512,owner='second')
        resources.release(active)
        with self.assertRaises(CoreError):resources.acquire('task',512,owner='second')
        with resources.lease('growth',512,owner='growth'):
            with resources.lease('chat',256):pass
        resources.clear_waiters('task')
        with resources.lease('growth',512,owner='next'):pass
        self.assertEqual(resources.snapshot()['background_wait_order'],[])

    def test_shared_background_slot_foreground_and_crash_cleanup(self):
        resources=RuntimeAdmission(lambda:{'available_bytes':8192*MIB,'commit_available_bytes':8192*MIB})
        with resources.lease('task',512):
            with self.assertRaises(CoreError):resources.acquire('growth',512)
            with resources.lease('chat',256):
                self.assertEqual(len(resources.snapshot()['active']),2)
        self.assertEqual(resources.snapshot()['active'],[])
        try:
            with resources.lease('growth',512):raise ValueError('crash')
        except ValueError:pass
        self.assertEqual(resources.snapshot()['active'],[])
        resources.probe=lambda:{'available_bytes':1200*MIB,'commit_available_bytes':1200*MIB}
        with self.assertRaises(CoreError):resources.acquire('task',512)
        with resources.lease('chat',256):pass


def load_tests(loader,tests,pattern):
    return unittest.TestSuite([*(PersonalPlanTests(n) for n in PersonalPlanTests.__dict__ if n.startswith('test_')),
                              *loader.loadTestsFromTestCase(AdmissionTests)])
