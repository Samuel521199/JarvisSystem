"""Shared queue admission, real inventory artifacts and restart boundaries."""
import json
from pathlib import Path
import sys
import threading
import time
import unittest
import uuid
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT/'runtime/node-host'), str(ROOT/'adapters/computer-use')]
from jarvis_core import worker
from jarvis_core.policy import CoreError
import test_computer_queue as queue_helpers
import test_computer_web as web_helpers


class SharedQueueTests(unittest.TestCase):
    setUp = queue_helpers.QueueTests.setUp
    make_queue = queue_helpers.QueueTests.make_queue
    options = queue_helpers.QueueTests.options
    enqueue = queue_helpers.QueueTests.enqueue
    wait_for = queue_helpers.QueueTests.wait_for
    def inventory(self, key=None, **kwargs):
        return self.queue.enqueue_inventory(request_id=key or 'web-'+uuid.uuid4().hex, **kwargs)

    def test_real_inventory_receipt_and_repeat_do_not_reexecute(self):
        (self.base/'input'/'sample.txt').write_text('sample')
        key='inventory-real'
        item=self.inventory(key)
        self.wait_for(lambda:self.core.ledger.record(task_id=item['task_id'])['action']['status']=='CONFIRMED')
        record=self.core.ledger.record(task_id=item['task_id'])
        self.core._verify_artifact(record['artifact'])
        self.assertEqual(self.inventory(key),item)
        self.assertEqual(self.core.ledger.record(task_id=item['task_id']),record)
        self.assertTrue(self.core.last_worker_evidence['lpac'])

    def test_mixed_fifo_and_cancel_pending_inventory(self):
        self.queue.set_paused(True)
        first=self.inventory(); browser=self.enqueue(); cancelled=self.inventory()
        self.core.cancel(cancelled['task_id'])
        calls=[]
        original_run=self.core.run; original_browser=self.executor.run
        def inventory(*args,**kwargs):
            calls.append('inventory');return original_run(*args,**kwargs)
        def browser_run(*args,**kwargs):
            calls.append('browser');return original_browser(*args,**kwargs)
        with patch.object(self.core,'run',inventory),patch.object(self.executor,'run',browser_run):
            self.queue.set_paused(False)
            self.wait_for(lambda:self.core.ledger.record(task_id=browser['task_id'])['action']['status']=='FAILED')
        self.assertEqual(calls,['inventory','browser'])
        self.assertEqual(self.core.ledger.record(task_id=cancelled['task_id'])['action']['status'],'CANCELLED')

    def test_mixed_capacity_rollback_and_idempotency(self):
        self.queue.set_paused(True);self.queue.capacity=2
        item=self.inventory('same');self.enqueue()
        self.assertEqual(self.inventory('same'),item)
        with self.assertRaisesRegex(CoreError,'different arguments'):self.inventory('same',relative_path='sub')
        with self.assertRaises(Exception):self.inventory()
        self.assertEqual(len(self.core.status()['tasks']),2)

    def test_paused_inventory_cannot_be_dispatched_by_cli(self):
        self.queue.set_paused(True);item=self.inventory('managed')
        with self.assertRaises(CoreError) as error:self.core.inventory(request_id='managed')
        self.assertEqual(error.exception.code,'queue_managed')
        self.assertEqual(self.core.ledger.record(task_id=item['task_id'])['action']['status'],'PREPARED')

    def test_inventory_restart_paused_and_source_pin_rejected(self):
        self.queue.set_paused(True);item=self.inventory();self.queue.close()
        self.queue=self.make_queue()
        self.assertTrue(self.queue.snapshot()['paused'])
        with patch.object(self.queue,'inventory_digest',return_value='changed'):
            with self.assertRaises(Exception):self.queue.set_paused(False)
        self.assertEqual(self.core.ledger.record(task_id=item['task_id'])['action']['status'],'PREPARED')
        self.queue.set_paused(False)
        self.wait_for(lambda:self.core.ledger.record(task_id=item['task_id'])['action']['status']=='CONFIRMED')

    def test_cancel_real_running_inventory_and_next_request(self):
        entered=threading.Event()
        original=worker.run
        def slow(runtime,stage,**kwargs):
            (stage/'worker.py').write_text('import time;time.sleep(30)')
            checkpoint=kwargs['checkpoint']
            def check(): entered.set();checkpoint()
            return original(runtime,stage,checkpoint=check)
        with patch.object(worker,'run',slow):
            item=self.inventory();self.assertTrue(entered.wait(5))
            self.core.cancel(item['task_id'])
            self.wait_for(lambda:self.core.ledger.record(task_id=item['task_id'])['action']['status']=='CANCELLED')
        self.assertIsNone(self.core.ledger.record(task_id=item['task_id'])['artifact'])
        next_item=self.inventory()
        self.wait_for(lambda:self.core.ledger.record(task_id=next_item['task_id'])['action']['status']=='CONFIRMED')


class TaskWebTests(unittest.TestCase):
    setUp = web_helpers.ComputerWebTests.setUp
    request = web_helpers.ComputerWebTests.request
    get = web_helpers.ComputerWebTests.get
    def test_inventory_endpoint_boundaries_and_verified_artifact(self):
        self.assertEqual(self.request('GET','/api/tasks')[0],403)
        for payload in ({'mode':'inventory','request_id':'bad'},
                        {'mode':'inventory','request_id':'web-'+uuid.uuid4().hex,'relative_path':'../'},
                        {'mode':'inventory','request_id':'web-'+uuid.uuid4().hex,'path':str(ROOT)}):
            self.assertEqual(self.request('POST','/api/tasks',payload)[0],400)
        payload={'mode':'inventory','request_id':'web-'+uuid.uuid4().hex,'relative_path':'.'}
        status,_,raw=self.request('POST','/api/tasks',payload)
        self.assertEqual(status,202);item=json.loads(raw)
        path='/api/tasks/'+item['task_id']
        end=time.monotonic()+8
        while time.monotonic()<end:
            data=json.loads(self.get(path)[2])
            if data['task']['status']=='SUCCEEDED':break
            time.sleep(.02)
        self.assertEqual(data['task']['status'],'SUCCEEDED')
        self.assertEqual(data['kind'],'inventory');self.assertIsNotNone(data['report'])
        self.assertEqual(self.get('/api/computer/tasks')[0],200)
        self.assertFalse(any(t['task_id']==item['task_id'] for t in json.loads(self.get('/api/computer/tasks')[2])['tasks']))
        self.assertTrue(any(t['task_id']==item['task_id'] for t in json.loads(self.get('/api/tasks')[2])['tasks']))
        artifact=Path(data['artifact_path']);artifact.write_text('tampered')
        self.assertNotEqual(self.get(path)[0],200)

    def test_general_queue_cancel_does_not_clear_stop(self):
        self.request('POST','/api/tasks/queue',{'paused':True})
        item=json.loads(self.request('POST','/api/tasks',{'mode':'inventory','request_id':'web-'+uuid.uuid4().hex})[2])
        self.core.stop('test')
        self.assertEqual(self.request('POST','/api/tasks/'+item['task_id']+'/cancel',{})[0],200)
        self.assertNotEqual(self.request('POST','/api/tasks/queue',{'paused':False})[0],200)
        self.assertTrue(self.core.ledger.control()['stopped'])


if __name__=='__main__':unittest.main()
