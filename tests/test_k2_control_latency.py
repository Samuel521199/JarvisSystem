"""K2 control requests must bound storage contention, never fabricate success."""
from contextlib import closing
from pathlib import Path
import sqlite3
import tempfile
import time
import threading
import uuid
import unittest

from jarvis_core.policy import CoreError
from jarvis_core.service import CoreService
from jarvis_core.conversations import ConversationStore
from jarvis_core.turns import DialogueTurns
from jarvis_core.runtime_metrics import RuntimeMetrics
from test_conversations import document
from test_web import web


class ControlContentionTests(unittest.TestCase):
    def test_saved_dialogue_busy_writer_keeps_control_and_temporary_chat_available(self):
        with tempfile.TemporaryDirectory() as temp:
            base=Path(temp);sample=base/'sample';sample.mkdir()
            core=CoreService(base/'data');core.initialize(sample)
            store=ConversationStore(core);conversation=uuid.uuid4().hex
            store.put(conversation,{'revision':0,'document':document()})
            owner=uuid.uuid4().hex;ident=uuid.uuid4().hex
            entered=threading.Event();release=threading.Event();cancelled=threading.Event();calls=[]
            class Chat:
                def reply(self,message,**kw):
                    calls.append(message)
                    if message=='slow':
                        entered.set()
                        while not release.wait(.005):
                            if kw['cancel_event'].is_set():cancelled.set()
                    return {'status':'SUCCEEDED','text':'reply'}
            engine=DialogueTurns(core,Chat(),owner,threading.BoundedSemaphore(2),web.ChatRequests(),RuntimeMetrics())
            engine.enable_recovery(store)
            try:
                engine.submit(owner,conversation,ident,{'message':'slow','personal_context':{'temporary':False}})
                self.assertTrue(entered.wait(1))
                with closing(sqlite3.connect(store.path,isolation_level=None)) as writer:
                    writer.execute('BEGIN IMMEDIATE')
                    tick=time.monotonic();row=engine.cancel(owner,conversation,ident)
                    self.assertLess(time.monotonic()-tick,.2)
                    self.assertTrue(cancelled.wait(.1));self.assertTrue(row['cancel_requested'])
                    self.assertEqual(row['status'],'CANCELLING');self.assertFalse(row['durable'])
                    other=uuid.uuid4().hex;other_id=uuid.uuid4().hex
                    tick=time.monotonic();engine.submit(owner,other,other_id,{'message':'temporary','personal_context':{'temporary':True}})
                    self.assertLess(time.monotonic()-tick,.2)
                    release.set()
                    until=time.monotonic()+2
                    while engine.snapshot()['active'] and time.monotonic()<until:time.sleep(.01)
                    self.assertEqual(engine.snapshot()['active'],0)
                    row=engine.view(owner,conversation,ident)
                    self.assertEqual(row['status'],'UNKNOWN');self.assertTrue(row['result']['outcome_uncertain'])
                    self.assertEqual(engine.view(owner,other,other_id)['status'],'SUCCEEDED')
                    writer.rollback()
                # An uncertain durable finish is not resubmitted, even after the lock clears.
                engine.submit(owner,conversation,ident,{'message':'slow','personal_context':{'temporary':False}})
                self.assertEqual(calls.count('slow'),1)
            finally:
                release.set();engine.close()
                until=time.monotonic()+2
                while engine.snapshot()['active'] and time.monotonic()<until:time.sleep(.01)

    def test_task_cancel_write_contention_is_bounded_and_retry_is_safe(self):
        with tempfile.TemporaryDirectory() as temp:
            base=Path(temp);sample=base/'sample';sample.mkdir()
            core=CoreService(base/'data');core.initialize(sample)
            record=core.prepare_inventory(request_id='contention-task')
            ident=record['task']['task_id']
            with closing(sqlite3.connect(core.ledger.db_path,isolation_level=None)) as writer:
                writer.execute('BEGIN IMMEDIATE')
                start=time.monotonic()
                try:
                    with self.assertRaises(CoreError):core.cancel(ident)
                    elapsed=time.monotonic()-start
                    self.assertLess(elapsed,.2,'Cancellation blocked on the business writer')
                finally:writer.rollback()
            self.assertEqual(core.ledger.record(task_id=ident)['action']['status'],'PREPARED')
            self.assertEqual(core.cancel(ident)['action']['status'],'CANCELLED')
            self.assertEqual(core.cancel(ident)['action']['status'],'CANCELLED')


if __name__=='__main__':unittest.main()
