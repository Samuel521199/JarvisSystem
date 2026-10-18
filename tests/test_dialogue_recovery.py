"""Persistent receipt outcomes, no replay, deletion and bounded failure isolation."""
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import time
import unittest
import uuid
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT/'runtime/node-host'), str(ROOT/'tests')]

from jarvis_core.conversations import ConversationStore, validate_document
from jarvis_core.dialogue_journal import DialogueJournal
from jarvis_core.turns import DialogueTurns, TurnError
from jarvis_core.runtime_metrics import RuntimeMetrics
from test_web import web
from test_conversations import document
from jarvis_core.service import CoreService


class RecoveryTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        root=Path(self.tmp.name);(root/'input').mkdir()
        self.core=CoreService(root/'data');self.core.initialize(root/'input')
        self.store=ConversationStore(self.core);self.conv=uuid.uuid4().hex
        self.store.put(self.conv,{'revision':0,'document':document()})
        self.owner=uuid.uuid4().hex;self.id=uuid.uuid4().hex
        self.now=time.time();self.journal=DialogueJournal(self.store,self.owner,clock=lambda:self.now)

    def get(self):return self.journal.get(self.conv,self.id)
    def admit(self):self.journal.admit(self.conv,self.id,'digest')
    def finish(self):self.journal.finish(self.conv,self.id,{'status':'SUCCEEDED','text':'恢复测试正文'})

    def test_completed_survives_restart_and_inflight_becomes_unknown(self):
        self.admit();self.finish()
        newer=DialogueJournal(self.store,uuid.uuid4().hex)
        self.assertEqual(newer.lookup(self.conv,self.id,'digest')['result']['text'],'恢复测试正文')
        with self.assertRaises(TurnError):newer.lookup(self.conv,self.id,'different')
        other=uuid.uuid4().hex;newer.admit(self.conv,other,'next')
        newest=DialogueJournal(self.store,uuid.uuid4().hex)
        row=newest.get(self.conv,other)
        self.assertEqual(row['status'],'UNKNOWN');self.assertTrue(row['result']['outcome_uncertain'])
        with self.assertRaises(TurnError):newer.finish(self.conv,other,{'status':'SUCCEEDED','text':'late'})

    def test_process_exit_retains_admission_without_replay(self):
        self.admit();self.finish()
        ident=uuid.uuid4().hex;owner=uuid.uuid4().hex
        code="""import os,sys
sys.path.insert(0,sys.argv[5])
from types import SimpleNamespace
from jarvis_core.conversations import ConversationStore
from jarvis_core.dialogue_journal import DialogueJournal
j=DialogueJournal(ConversationStore(SimpleNamespace(data_dir=sys.argv[1])),sys.argv[2])
j.admit(sys.argv[3],sys.argv[4],'child')
os._exit(23)
"""
        result=subprocess.run([sys.executable,'-c',code,str(self.core.data_dir),owner,self.conv,ident,
                               str(ROOT/'runtime/node-host')],capture_output=True,timeout=10)
        self.assertEqual(result.returncode,23,result.stderr)
        newer=DialogueJournal(self.store,uuid.uuid4().hex)
        self.assertEqual(newer.get(self.conv,ident)['status'],'UNKNOWN')
        self.assertEqual(newer.get(self.conv,self.id)['status'],'SUCCEEDED')

    def test_deleted_conversation_purges_results_and_rejects_late_writer(self):
        self.admit();self.finish();other=uuid.uuid4().hex;self.journal.admit(self.conv,other,'other')
        self.store.delete(self.conv,{'revision':1})
        with self.store.connection() as db:
            rows=db.execute('SELECT result,size,deleted FROM dialogue_receipts').fetchall()
            self.assertTrue(all(tuple(row)==(None,0,1) for row in rows))
        with self.assertRaises(TurnError):self.get()
        with self.assertRaises(TurnError):self.journal.finish(self.conv,other,{'status':'SUCCEEDED','text':'resurrect'})
        with self.assertRaises(TurnError):self.journal.admit(self.conv,uuid.uuid4().hex,'new')

    def test_capacity_expiration_and_scope(self):
        self.admit();self.finish()
        with self.assertRaises(TurnError):self.journal.get(uuid.uuid4().hex,self.id)
        self.journal.MAX_IDS=1
        with self.assertRaises(TurnError):self.journal.admit(self.conv,uuid.uuid4().hex,'full')
        self.now+=86401;row=self.get();self.assertTrue(row['expired']);self.assertNotIn('result',row)
        self.assertIsNotNone(self.journal.lookup(self.conv,self.id,'digest'))
        self.now+=7*86400;self.assertIsNone(self.get())

    def test_cache_byte_limit_drops_content_without_dropping_id(self):
        self.journal.MAX_BYTES=1;self.admit();self.finish()
        self.assertTrue(self.get()['expired'])
        self.assertIsNotNone(self.journal.lookup(self.conv,self.id,'digest'))

    def engine(self):
        calls=[]
        class Chat:
            def reply(self,message,**kw):calls.append(message);return {'status':'SUCCEEDED','text':'answer'}
        engine=DialogueTurns(self.core,Chat(),self.owner,threading.BoundedSemaphore(2),web.ChatRequests(),RuntimeMetrics())
        engine.journal=self.journal
        return engine,calls

    def wait(self,engine,ident):
        end=time.monotonic()+2
        while time.monotonic()<end:
            row=engine.recover(self.conv,ident)
            if row['finished']:return row
            time.sleep(.01)
        self.fail('worker did not finish')

    def test_temporary_input_never_enters_journal(self):
        engine,calls=self.engine()
        engine.submit(self.owner,self.conv,self.id,{'message':'temporary secret','personal_context':{'temporary':True}})
        row=self.wait(engine,self.id);self.assertFalse(row['durable'])
        self.assertIsNone(self.get());self.assertEqual(calls,['temporary secret'])
        with self.store.connection() as db:self.assertEqual(db.execute('SELECT count(*) FROM dialogue_receipts').fetchone()[0],0)

    def test_admission_storage_failure_never_calls_model_and_keeps_slots(self):
        engine,calls=self.engine()
        with patch.object(self.journal,'admit',side_effect=OSError('disk full')):
            with self.assertRaises(OSError):engine.submit(self.owner,self.conv,self.id,{'message':'input','personal_context':{'temporary':False}})
        self.assertEqual(calls,[]);self.assertEqual(engine.requests.active,0)
        self.assertTrue(engine.slots.acquire(False));self.assertTrue(engine.slots.acquire(False));self.assertFalse(engine.slots.acquire(False))

    def test_finish_storage_failure_reports_unknown_and_frees_slot(self):
        engine,calls=self.engine()
        with patch.object(self.journal,'finish',side_effect=OSError('disk full')):
            engine.submit(self.owner,self.conv,self.id,{'message':'input','personal_context':{'temporary':False}})
            row=self.wait(engine,self.id)
        self.assertEqual(row['status'],'UNKNOWN');self.assertNotIn('text',row['result']);self.assertEqual(calls,['input'])
        self.assertEqual(engine.requests.active,0)

    def test_repeated_admission_after_restart_returns_old_receipt(self):
        engine,calls=self.engine();payload={'message':'input','personal_context':{'temporary':False}}
        engine.submit(self.owner,self.conv,self.id,payload);self.wait(engine,self.id)
        newer=uuid.uuid4().hex;engine.instance_id=newer;engine.rows={};engine.journal=DialogueJournal(self.store,newer)
        self.assertEqual(engine.submit(newer,self.conv,self.id,payload)['result']['text'],'answer')
        self.assertEqual(calls,['input'])

    def test_archive_reply_reference_is_strict(self):
        value=document();value['messages'][0]['reply_ref']=self.id;validate_document(value)
        value['messages'][0]['reply_ref']='../../bad'
        with self.assertRaises(ValueError):validate_document(value)

    def test_locked_archive_fails_promptly_but_temporary_reply_still_works(self):
        engine,calls=self.engine()
        with self.store.connection() as db:
            db.execute('BEGIN IMMEDIATE');start=time.monotonic()
            with self.assertRaises(Exception):engine.submit(self.owner,self.conv,self.id,{'message':'ordinary','personal_context':{'temporary':False}})
            self.assertLess(time.monotonic()-start,1)
            other=uuid.uuid4().hex
            engine.submit(self.owner,self.conv,other,{'message':'temporary','personal_context':{'temporary':True}})
            self.assertEqual(self.wait(engine,other)['status'],'SUCCEEDED')
        self.assertEqual(calls,['temporary'])


if __name__=='__main__':unittest.main()
