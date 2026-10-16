"""Durable queue fault, ordering and fencing tests without cloud or browser I/O."""
import json
import os
from pathlib import Path
import subprocess
import signal
import sys
import tempfile
import threading
import time
import unittest
import uuid

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'runtime/node-host'),str(ROOT/'adapters/computer-use')]
from jarvis_core.service import CoreService
from jarvis_core.policy import CoreError
from jarvis_computer.protocol import ComputerError
from jarvis_computer.task_queue import ComputerQueue
TASK=json.loads((ROOT/'config/computer-use/demo-task.json').read_text(encoding='utf-8'))
HTML=(ROOT/'apps/computer-use/demo.html').read_text(encoding='utf-8')


class Executor:
    def __init__(self, core):
        self.core=core;self.calls=[];self.outcome='FAILED'
        self.entered=threading.Event();self.release=threading.Event();self.release.set()

    def run(self, task, *, request_id, model, scripted, demo_html, _before_dispatch):
        ledger=self.core.ledger
        with ledger.worker_lock():
            ledger.recover_orphans()
            record=ledger.prepare(request_id,{'task':task,'model':model,'scripted':scripted,'demo':demo_html is not None},capability='browser.operate.v1')
            if record['action']['status']!='PREPARED':return record
            ledger.begin_dispatch(record['action']['action_id'],self.core.host_instance_id,_admission=_before_dispatch)
            self.calls.append(request_id);self.entered.set()
            while not self.release.wait(.02):
                try:ledger.assert_admitted(record['task']['task_id'])
                except CoreError:break
            outcome='CANCELLED' if ledger.record(task_id=record['task']['task_id'])['cancel_requested'] else self.outcome
            ledger.finish_without_receipt(record['action']['action_id'],outcome,{'code':'test_outcome','message':'Synthetic outcome'})
            return ledger.record(task_id=record['task']['task_id'])


class QueueTests(unittest.TestCase):
    def setUp(self):
        temp=tempfile.TemporaryDirectory(prefix='jarvis-queue-');self.addCleanup(temp.cleanup)
        self.base=Path(temp.name);(self.base/'input').mkdir()
        self.core=CoreService(self.base/'data');self.core.initialize(self.base/'input')
        self.executor=Executor(self.core)
        self.queue=self.make_queue()

    def make_queue(self):
        queue=ComputerQueue(self.core,lambda:self.executor);self.addCleanup(queue.close)
        return queue

    def options(self):
        return dict(request_id='web-'+uuid.uuid4().hex,model='auto',scripted=True,demo_html=HTML)

    def enqueue(self,options=None):
        return self.queue.enqueue(TASK,options or self.options())

    def wait_for(self,predicate):
        end=time.monotonic()+8
        while time.monotonic()<end:
            if predicate():return
            time.sleep(.02)
        self.fail('Queue condition timed out')

    def test_capacity_atomic_idempotency_and_changed_arguments(self):
        self.queue.set_paused(True);self.queue.capacity=2
        options=self.options();first=self.enqueue(options);self.enqueue()
        self.assertEqual(self.enqueue(options),first)
        with self.assertRaisesRegex(CoreError,'different arguments'):self.enqueue({**options,'model':'changed'})
        with self.assertRaisesRegex(ComputerError,'等待队列已满'):self.enqueue()
        self.assertEqual(len(self.core.status()['tasks']),2)
        self.assertEqual(self.executor.calls,[])

    def test_fifo_and_cancel_queued_task_never_dispatches(self):
        self.queue.set_paused(True)
        options=[self.options() for _ in range(3)]
        results=[self.enqueue(o) for o in options]
        self.core.cancel(results[1]['task_id']);self.queue.set_paused(False)
        self.wait_for(lambda:len(self.executor.calls)==2)
        self.assertEqual(self.executor.calls,[options[0]['request_id'],options[2]['request_id']])

    def test_restart_keeps_prepared_paused_then_explicit_resume(self):
        self.queue.set_paused(True);item=self.enqueue();self.queue.close()
        self.queue=self.make_queue()
        self.assertTrue(self.queue.snapshot()['paused']);self.assertEqual(self.executor.calls,[])
        self.assertEqual(self.queue.snapshot()['positions'][item['task_id']],1)
        self.queue.set_paused(False);self.wait_for(lambda:len(self.executor.calls)==1)

    def test_new_owner_fences_old_dispatcher_and_serializes_inflight(self):
        self.executor.release.clear();first=self.enqueue()
        self.assertTrue(self.executor.entered.wait(5));second=self.enqueue()
        old=self.queue;self.queue=self.make_queue()
        with self.assertRaisesRegex(ComputerError,'新服务接管'):old.enqueue(TASK,self.options())
        self.queue.set_paused(False)
        time.sleep(.35);self.assertEqual(len(self.executor.calls),1)
        self.executor.release.set();self.wait_for(lambda:len(self.executor.calls)==2)
        self.assertEqual(len(set(self.executor.calls)),2)
        self.assertFalse(old.snapshot()['owned'])

    def test_unknown_pauses_following_tasks_and_never_replays(self):
        self.queue.set_paused(True);self.executor.outcome='UNKNOWN'
        first=self.enqueue();second=self.enqueue();self.queue.set_paused(False)
        self.wait_for(lambda:self.queue.snapshot()['error']=='result_unknown')
        self.assertEqual(len(self.executor.calls),1)
        self.assertEqual(self.core.ledger.record(task_id=second['task_id'])['action']['status'],'PREPARED')
        self.executor.outcome='FAILED';self.queue.set_paused(False)
        self.wait_for(lambda:len(self.executor.calls)==2)
        self.assertEqual(self.core.ledger.record(task_id=first['task_id'])['action']['status'],'UNKNOWN')

    def test_old_host_unknown_after_resume_blocks_new_owner(self):
        self.executor.release.clear();self.executor.outcome='UNKNOWN'
        first=self.enqueue();self.assertTrue(self.executor.entered.wait(5));second=self.enqueue()
        self.queue=self.make_queue();self.queue.set_paused(False)
        self.executor.release.set()
        self.wait_for(lambda:self.queue.snapshot()['error']=='result_unknown')
        self.assertEqual(len(self.executor.calls),1)
        self.assertEqual(self.core.ledger.record(task_id=second['task_id'])['action']['status'],'PREPARED')

    def test_stop_cannot_be_cleared_by_queue_resume(self):
        self.queue.set_paused(True);item=self.enqueue();self.core.stop('test')
        with self.assertRaises(CoreError):self.queue.set_paused(False)
        self.assertEqual(self.executor.calls,[])
        self.assertEqual(self.core.ledger.record(task_id=item['task_id'])['action']['status'],'CANCELLED')

    def test_version_and_content_bindings_must_still_match(self):
        self.queue.set_paused(True);item=self.enqueue()
        with self.core.ledger.transaction() as db:db.execute("UPDATE computer_queue SET version='old'")
        with self.assertRaisesRegex(ComputerError,'旧版本任务'):self.queue.set_paused(False)
        from jarvis_core import __version__
        with self.core.ledger.transaction() as db:db.execute("UPDATE computer_queue SET version=?,demo_digest='changed'",(__version__,))
        with self.assertRaisesRegex(ComputerError,'演示页面已改变'):self.queue.set_paused(False)
        self.assertEqual(self.executor.calls,[])

    def test_pause_race_checked_inside_dispatch_transaction(self):
        entered=threading.Event();release=threading.Event();original=self.executor.run
        def delayed(*args,**kwargs):
            entered.set();release.wait(5);return original(*args,**kwargs)
        self.executor.run=delayed
        item=self.enqueue();self.assertTrue(entered.wait(5))
        self.queue.set_paused(True);release.set();time.sleep(.35)
        self.assertEqual(self.executor.calls,[])
        self.assertEqual(self.core.ledger.record(task_id=item['task_id'])['action']['status'],'PREPARED')

    def test_process_crash_reconciles_inflight_and_preserves_waiting(self):
        self.queue.close()
        script=self.base/'crash_host.py'
        script.write_text('''import sys,time,json,threading,os
from pathlib import Path
sys.path[:0]=[str(Path(sys.argv[1])/'tests'),str(Path(sys.argv[1])/'runtime/node-host'),str(Path(sys.argv[1])/'adapters/computer-use')]
from test_computer_queue import Executor,TASK,HTML
from jarvis_core.service import CoreService
from jarvis_computer.task_queue import ComputerQueue
core=CoreService(Path(sys.argv[2])/'data');executor=Executor(core);executor.release.clear()
queue=ComputerQueue(core,lambda:executor);queue.set_paused(True)
items=[queue.enqueue(TASK,dict(request_id='crash-'+str(i),model='auto',scripted=True,demo_html=HTML)) for i in range(2)]
queue.set_paused(False)
assert executor.entered.wait(8)
(Path(sys.argv[2])/'ready.json').write_text(json.dumps({'items':items,'pid':os.getpid()}))
time.sleep(15)
os._exit(97)
''',encoding='utf-8')
        process=subprocess.Popen([sys.executable,'-B',str(script),str(ROOT),str(self.base)],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
        try:
            self.wait_for(lambda:(self.base/'ready.json').exists())
            state=json.loads((self.base/'ready.json').read_text());items=state['items']
            # The Windows venv launcher is a parent, not the process holding
            # worker.lock. Kill the exact PID reported by this test host.
            os.kill(state['pid'],signal.SIGTERM)
            process.wait(timeout=5)
        finally:
            if process.poll() is None:process.kill();process.wait(timeout=5)
        self.queue=self.make_queue()
        self.assertEqual(self.core.ledger.record(task_id=items[0]['task_id'])['action']['status'],'UNKNOWN')
        self.assertEqual(self.core.ledger.record(task_id=items[1]['task_id'])['action']['status'],'PREPARED')
        self.assertTrue(self.queue.snapshot()['paused']);self.assertEqual(self.executor.calls,[])
        self.queue.set_paused(False);self.wait_for(lambda:len(self.executor.calls)==1)
        self.assertEqual(self.executor.calls,['crash-1'])


if __name__=='__main__':unittest.main()
