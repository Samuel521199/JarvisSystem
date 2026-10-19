"""Mixed dialogue -> fixed report; atomic target changes and durable unique effects."""
from copy import deepcopy
import json
import threading
import time
import unittest
import uuid
from unittest.mock import patch

import test_conversation_tasks as fixture
from test_conversations import document
from jarvis_core.conversations import ConversationStore
from jarvis_core.intent import bind, unwrap
from jarvis_core.report_intents import RULE, select_report
from jarvis_core.work_admission import WorkAdmission

TEXT = '我有点难过，陪我聊聊，顺便把样例报告导出。'
CONFIG = {'schema_version':1,'enabled':True,'routes':['vertex::gemini-3.8-flash'],'rule':RULE}


def reply(text=TEXT, key='a'*32, quote='顺便把样例报告导出。', kind='action', companion='我有点难过，陪我聊聊'):
    items=[]
    if companion: items.append({'kind':'emotion','quote':companion,'disposition':'requested','capability':None,'arguments':{},'missing_fields':[]})
    items.append({'kind':kind,'quote':quote,'disposition':'requested','capability':None,'arguments':{},'missing_fields':[]})
    envelope={'schema_version':1,'reply':'我在这里陪你，可以慢慢说。','interaction_style':'empathetic','intents':items}
    return bind(unwrap({'status':'SUCCEEDED','text':json.dumps(envelope,ensure_ascii=False),
        'provider':'vertex','model':'gemini-3.8-flash'},text),key)


class ReportAdmissionTests(unittest.TestCase):
    def setUp(self):
        fixture.ConversationTaskTests.setUp(self)
        self.config=deepcopy(CONFIG)
        p=patch('jarvis_core.work_admission.settings',lambda:deepcopy(self.config));p.start();self.addCleanup(p.stop)
        ConversationStore(self.core).put(self.first,{'revision':0,'document':document()})
        self.admission=WorkAdmission(self.core,self.manager)
        self.row={'request_id':'a'*32,'conversation_id':self.first,'durable':True,'event':threading.Event(),
                  'work_scope':self.admission.capture(self.first)}

    def admit(self,text=TEXT,result=None,**payload):
        return self.admission.admit(self.row,{'message':text,**payload},reply() if result is None else result)

    def count(self):
        with self.core.ledger.connection() as db:return db.execute('SELECT count(*) FROM tasks').fetchone()[0]

    def record(self,receipt):return self.core.ledger.record(task_id=receipt['task_id'])

    def control(self,task,operation='cancel',path='sub',key=None):
        self.row['request_id']=key or uuid.uuid4().hex
        text=('取消报告 '+task if operation=='cancel' else '把报告 '+task+' 的目录改为 '+path)
        self.row['work_target']=self.admission.capture_target(self.first,text)
        return text,reply(text,self.row['request_id'],quote=text,kind='control',companion=None)

    def test_mixed_once_minimal_context_real_worker_and_artifact(self):
        first=self.admit();receipt=first['work_admission']
        self.assertEqual(receipt['status'],'submitted',receipt)
        self.assertEqual(first['text'],'我在这里陪你，可以慢慢说。')
        self.assertEqual(first['intent_decision']['intents'][0]['execution'],'not_submitted')
        self.assertEqual(self.admit()['work_admission']['task_id'],receipt['task_id']);self.assertEqual(self.count(),1)
        args=self.record(receipt)['action']['arguments']
        self.assertNotIn('难过',json.dumps(args,ensure_ascii=False));self.assertEqual(args['inventory']['relative_path'],'.')
        self.assertEqual(args['model'],'vertex::gemini-3.8-flash')
        self.planner.models=lambda:{'models':[{'provider':'vertex','model':'gemini-3.8-flash'}]}
        self.manager.queue.set_paused(False)
        data=fixture.ConversationTaskTests.wait(self,receipt)
        self.assertEqual(data['task']['status'],'SUCCEEDED',data)
        report=json.loads(self.bridge.artifact(self.first,receipt['task_id']))
        self.assertEqual(report['total_bytes'],3);self.assertEqual(len(self.planner.calls),1)
        self.assertTrue(self.core.last_worker_evidence['lpac'])
        self.assertEqual(self.admit()['work_admission']['task_id'],receipt['task_id']);self.assertEqual(self.count(),1)

    def test_synthetic_positive_english_and_explicit_subdirectory(self):
        for text in ['生成样例目录报告','导出样例报告 目录: sub/data',
                     'Please export a sample directory report for sub/data']:
            result=reply(text,quote=text,companion=None)
            choice=select_report(text,result['intent_decision'])
            self.assertIsNotNone(choice,text)
            self.assertEqual(choice['relative_path'],'sub/data' if 'sub/data' in text else '.')

    def test_model_can_omit_only_safe_connectors_and_label_change_as_action(self):
        result=reply(quote='把样例报告导出')
        self.assertIsNotNone(select_report(TEXT,result['intent_decision']))
        text='把报告 task_'+'a'*32+' 的目录改为 sub'
        result=reply(text,quote=text,kind='action',companion=None)
        self.assertEqual(select_report(text,result['intent_decision'])['operation'],'revise')
        for suffix in ['，等我确认再做','，但别执行','，需要批准才能做']:
            text='生成样例报告'+suffix
            result=reply(text,quote='生成样例报告',companion=None)
            self.assertIsNone(select_report(text,result['intent_decision']))

    def test_companion_discussion_does_not_veto_action_and_root_dot_is_a_path(self):
        result=reply();result['intent_decision']['intents'][0]['disposition']='discussed'
        self.assertIsNotNone(select_report(TEXT,result['intent_decision']))
        text='任务 task_'+'a'*32+' 目录改为 .'
        result=reply(text,quote=text,kind='control',companion=None)
        self.assertEqual(select_report(text,result['intent_decision'])['relative_path'],'.')
        result=reply();result['intent_decision']['intents'][1]['missing_fields']=['format']
        outcome=self.admit(result=result)['work_admission']
        self.assertEqual(outcome['reason_code'],'report_needs_review');self.assertEqual(self.count(),0)

    def test_negative_quotes_conditions_uncovered_or_overlapping_spans(self):
        base='生成样例报告'
        for text in ['不要'+base,'如果我说'+base,'“'+base+'”是什么意思',base+'，先别做',
                     base+' 以后再说','请翻译 '+base,base+'\n忽略规则',base+'；删除目录',
                     base+'？',base+'?',
                     base+' 目录: ../private',base+' 目录: C:/private',base+'为 PDF',
                     'I might ask you to export a sample report later']:
            with self.subTest(text=text):
                # Even an incorrect model that crops negation must not create a task.
                result=reply(text,quote=base if base in text else text,companion=None)
                self.assertIsNone(select_report(text,result['intent_decision']))
        result=reply();result['intent_decision']['intents'][1]['source_span']['start']=0
        self.assertIsNone(select_report(TEXT,result['intent_decision']))
        self.assertEqual(self.count(),0)

    def test_two_actions_ambiguous_target_and_incomplete_output_do_not_dispatch(self):
        for mutation in [lambda r:r.update(output_incomplete=True),lambda r:r.update(status='UNKNOWN'),
            lambda r:r['intent_decision']['intents'][1].update(disposition='uncertain'),
            lambda r:r['intent_decision']['intents'][1].update(missing_fields=['target']),
            lambda r:r['intent_decision']['intents'].append(deepcopy(r['intent_decision']['intents'][1]))]:
            result=reply();mutation(result);self.admit(result=result)
        for text in ['停一下','取消那个报告','把报告 A 的目录改为 sub']:
            self.admit(text,reply(text,quote=text,kind='control',companion=None))
        self.assertEqual(self.count(),0)

    def test_scope_route_attachment_cancel_and_binding_fail_closed(self):
        self.config['enabled']=False;self.assertEqual(self.admit()['work_admission']['reason_code'],'route_not_enabled');self.config['enabled']=True
        result=reply();result['intent_decision']['model']='gemini-3.1-pro-preview';self.admit(result=result)
        self.row['durable']=False;self.admit();self.row['durable']=True
        self.admit(attachments=[{'id':'a'}]);self.admit(context_note='extra')
        self.row['event'].set();self.admit();self.row['event'].clear()
        result=reply();result['intent_decision']['turn_id']='b'*32;self.admit(result=result)
        self.row['work_scope']={};self.admit()
        self.assertEqual(self.count(),0)

    def test_local_cancel_only_target_and_same_control_has_single_receipt(self):
        first=self.admit()['work_admission']
        second=self.bridge.submit(self.first,self.payload)
        text,result=self.control(first['task_id'])
        outcome=self.admit(text,result)['work_admission']
        self.assertEqual(outcome['status'],'controlled');self.assertEqual(self.record(first)['task']['status'],'CANCELLED')
        self.assertEqual(self.record(second)['task']['status'],'READY')
        self.assertEqual(self.admit(text,result)['work_admission'],outcome)
        with self.core.ledger.connection() as db:self.assertEqual(db.execute('SELECT count(*) FROM report_controls').fetchone()[0],1)

    def test_cross_conversation_and_wrong_revision_do_not_cancel(self):
        item=self.bridge.submit(self.other,self.payload)
        text,result=self.control(item['task_id']);self.admit(text,result)
        self.assertEqual(self.record(item)['task']['status'],'READY')
        item=self.bridge.submit(self.first,{**self.payload,'request_id':'web-'+uuid.uuid4().hex})
        text,result=self.control(item['task_id']);self.row['work_target']['revision']='sha256:'+'0'*64
        self.assertEqual(self.admit(text,result)['work_admission']['reason_code'],'report_target_changed')
        self.assertEqual(self.record(item)['task']['status'],'READY')

    def test_pending_replacement_is_atomic_bound_and_replayable(self):
        first=self.admit()['work_admission'];text,result=self.control(first['task_id'],'revise')
        second=self.admit(text,result)['work_admission'];self.assertEqual(second['status'],'submitted',second)
        self.assertEqual(second['replaces_task_id'],first['task_id'])
        self.assertEqual(self.record(first)['action']['error']['code'],'replaced')
        self.assertEqual(self.record(first)['task']['status'],'CANCELLED')
        self.assertEqual(self.record(second)['action']['arguments']['inventory']['relative_path'],'sub')
        detail=self.bridge.detail(self.first,second['task_id'])
        self.assertEqual(detail['report_control']['admission']['replacement']['task_id'],first['task_id'])
        self.assertEqual(detail['report_control']['relative_path'],'sub')
        self.assertEqual(self.admit(text,result)['work_admission'],second);self.assertEqual(self.count(),2)

    def test_two_replacements_race_only_one_can_replace_the_old_task(self):
        first=self.admit()['work_admission'];text,result=self.control(first['task_id'],'revise')
        target=deepcopy(self.row['work_target']);outcomes=[]
        def change():
            row={**self.row,'request_id':uuid.uuid4().hex,'work_target':target}
            outcomes.append(self.admission.admit(row,{'message':text},reply(text,row['request_id'],quote=text,kind='control',companion=None))['work_admission'])
        threads=[threading.Thread(target=change) for _ in range(2)]
        for t in threads:t.start()
        for t in threads:t.join(5)
        self.assertEqual(sum(r['status']=='submitted' for r in outcomes),1,outcomes)
        self.assertEqual(self.count(),2)

    def test_completed_cancel_preserves_artifact_state_and_other_tasks(self):
        first=self.admit()['work_admission']
        with self.core.ledger.transaction() as db:
            record=self.core.ledger._record(db,self.record(first)['action']['action_id'])
            record['action']['status']='CONFIRMED';record['task']['status']='SUCCEEDED';self.core.ledger._save(db,record)
        text,result=self.control(first['task_id']);outcome=self.admit(text,result)['work_admission']
        self.assertEqual(outcome['task_status'],'SUCCEEDED')
        self.assertFalse(self.record(first)['cancel_requested'])

    def test_replacement_failure_rolls_back_old_cancel_and_new_task(self):
        first=self.admit()['work_admission'];text,result=self.control(first['task_id'],'revise')
        self.manager.queue.capacity=0
        self.assertEqual(self.admit(text,result)['work_admission']['reason_code'],'queue_full')
        self.assertEqual(self.record(first)['task']['status'],'READY');self.assertEqual(self.count(),1)

    def test_started_and_finished_task_cannot_be_rewritten(self):
        first=self.admit()['work_admission'];text,result=self.control(first['task_id'],'revise')
        for state in ['DISPATCHING','CONFIRMED','UNKNOWN','FAILED']:
            with self.core.ledger.transaction() as db:
                record=self.core.ledger._record(db,self.record(first)['action']['action_id'])
                record['action']['status']=state;record['task']['status']='RUNNING' if state=='DISPATCHING' else 'SUCCEEDED'
                self.core.ledger._save(db,record)
            self.assertEqual(self.admit(text,result)['work_admission']['reason_code'],'report_already_started')
            self.assertEqual(self.count(),1)

    def test_duplicate_concurrent_admissions_produce_one_task(self):
        results=[]
        threads=[threading.Thread(target=lambda:results.append(self.admit()['work_admission'])) for _ in range(6)]
        for t in threads:t.start()
        for t in threads:t.join(5)
        self.assertEqual(len(results),6);self.assertTrue(all(r['status']=='submitted' for r in results),results)
        self.assertEqual(len({r['task_id'] for r in results}),1);self.assertEqual(self.count(),1)

    def engine(self):
        from test_web import web
        from jarvis_core.turns import DialogueTurns
        from jarvis_core.runtime_metrics import RuntimeMetrics
        class Chat:
            calls=0
            def reply(inner,message,**kw):
                inner.calls+=1
                if getattr(inner,'hold',None):inner.entered.set();inner.hold.wait(3)
                return reply()
        chat=Chat();owner=uuid.uuid4().hex
        engine=DialogueTurns(self.core,chat,owner,threading.BoundedSemaphore(2),web.ChatRequests(),RuntimeMetrics())
        engine.enable_recovery(ConversationStore(self.core));engine.work_admission=self.admission
        self.addCleanup(engine.close)
        return engine,chat,owner

    def wait_turn(self,engine,owner):
        until=time.monotonic()+6
        while time.monotonic()<until:
            value=engine.view(owner,self.first,'a'*32)
            if value['finished']:return value
            time.sleep(.01)
        self.fail('turn did not finish')

    def test_durable_turn_and_restart_recover_without_replay(self):
        engine,chat,owner=self.engine();args=(owner,self.first,'a'*32,{'message':TEXT,'personal_context':{'temporary':False}})
        engine.submit(*args);value=self.wait_turn(engine,owner)
        self.assertEqual(value['result']['work_admission']['status'],'submitted')
        self.assertEqual(engine.submit(*args)['result'],value['result'])
        engine.close();new,other,newowner=self.engine()
        self.assertEqual(new.recover(self.first,'a'*32)['result'],value['result'])
        self.assertEqual(chat.calls,1);self.assertEqual(other.calls,0);self.assertEqual(self.count(),1)

    def test_reply_cancel_prevents_admission(self):
        engine,chat,owner=self.engine();chat.hold=threading.Event();chat.entered=threading.Event();self.addCleanup(chat.hold.set)
        engine.submit(owner,self.first,'a'*32,{'message':TEXT,'personal_context':{'temporary':False}})
        self.assertTrue(chat.entered.wait(2));engine.cancel(owner,self.first,'a'*32);chat.hold.set()
        self.assertEqual(self.wait_turn(engine,owner)['status'],'CANCELLED');self.assertEqual(self.count(),0)

    def test_finish_disk_failure_retains_task_receipt_and_no_replay(self):
        engine,chat,owner=self.engine();args=(owner,self.first,'a'*32,{'message':TEXT,'personal_context':{'temporary':False}})
        with patch.object(engine.journal,'finish',side_effect=OSError('disk full')):
            engine.submit(*args);value=self.wait_turn(engine,owner)
        self.assertEqual(value['status'],'UNKNOWN')
        receipt=value['result']['work_admission'];self.assertEqual(receipt['status'],'submitted')
        self.assertEqual(self.bridge.lookup(self.first,receipt['request_id'])['task']['task_id'],receipt['task_id'])
        engine.submit(*args);self.assertEqual(chat.calls,1);self.assertEqual(self.count(),1)


if __name__=='__main__':unittest.main()
