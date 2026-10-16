"""Real ledger/HTTP boundary tests; browser integration uses no cloud calls."""
import json
from pathlib import Path
import sys
import tempfile
import threading
import time
import unittest
import uuid
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'runtime/node-host'),str(ROOT/'adapters/computer-use')]
from jarvis_core.service import CoreService
from jarvis_computer.web import ComputerWeb
from jarvis_computer.service import ComputerService
from jarvis_computer.planner import ScriptedDemoPlanner
import test_web as helpers
web,FakeChat=helpers.web,helpers.FakeChat
from test_computer import HAS_BROWSER,TASK

class ComputerWebTests(unittest.TestCase):
    request=helpers.WebTests.request

    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(prefix='jarvis-web-computer-')
        self.addCleanup(self.temp.cleanup)
        base=Path(self.temp.name);(base/'input').mkdir()
        self.core=CoreService(base/'data');self.core.initialize(base/'input')
        self.chat=FakeChat()
        self.chat.models=lambda:{'models':[{'model':'test-model','provider':'openai','label':'Test'}],'providers':[]}
        self.manager=ComputerWeb(self.core,self.chat)
        self.server=web.LocalChatServer(('127.0.0.1',0),self.core,self.chat,computer=self.manager)
        self.thread=threading.Thread(target=self.server.serve_forever,kwargs={'poll_interval':.01},daemon=True);self.thread.start()
        self.addCleanup(self.server.server_close);self.addCleanup(self.server.shutdown)
        self.host='127.0.0.1:'+str(self.server.server_address[1]);self.origin='http://'+self.host

    def payload(self,mode='scripted'):
        return {'request_id':'web-'+uuid.uuid4().hex,'mode':mode,'model':'auto' if mode=='scripted' else 'test-model'}

    def get(self,path):
        return self.request('GET',path,headers={'X-Jarvis-Nonce':self.server.nonce})

    def wait_done(self,task_id):
        deadline=time.monotonic()+20
        while time.monotonic()<deadline:
            status,_,raw=self.get('/api/computer/tasks/'+task_id)
            self.assertEqual(status,200,raw)
            data=json.loads(raw)
            if data['task']['status'] not in {'READY','RUNNING','CANCELLING'}:return data
            time.sleep(.05)
        self.fail('Task did not finish')

    def test_task_reads_and_writes_require_nonce_and_local_origin(self):
        for path in ('/api/computer/tasks','/api/computer/tasks/task_'+'0'*32+'/screenshot'):
            self.assertEqual(self.request('GET',path)[0],403)
            self.assertEqual(self.request('GET',path,headers={'X-Jarvis-Nonce':self.server.nonce,'Origin':'https://evil.example'})[0],403)
        self.assertEqual(self.request('POST','/api/computer/tasks',self.payload(),headers={'X-Jarvis-Nonce':None})[0],403)
        self.assertEqual(json.loads(self.get('/api/computer/tasks')[2])['tasks'],[])

    def test_reject_invalid_scope_and_transport_fields_before_admission(self):
        bad=[{**self.payload(),'shell':'cmd'},{**self.payload(),'headed':True},{**self.payload(),'model':'unregistered'},
             {**self.payload(),'task':TASK},{**self.payload('custom'),'task':{'url':'file:///C:/'}},
             {**self.payload(),'request_id':'../../file'}]
        for payload in bad:
            self.assertEqual(self.request('POST','/api/computer/tasks',payload)[0],400)
        self.assertEqual(self.core.status()['tasks'],[])
        self.assertEqual(self.get('/api/computer/tasks/../../file')[0],404)

    def test_prepared_task_detail_and_cancel_does_not_require_step_table(self):
        args={'task':TASK,'model':'auto','scripted':True,'demo':True}
        record=self.core.ledger.prepare('prepared',args,capability='browser.operate.v1')
        path='/api/computer/tasks/'+record['task']['task_id']
        data=json.loads(self.get(path)[2]);self.assertEqual(data['steps'],[])
        self.assertEqual(data['task']['status'],'READY')
        result=self.request('POST',path+'/cancel',{})
        self.assertEqual(json.loads(result[2])['task']['status'],'CANCELLED')
        self.core.stop('test')
        self.assertEqual(self.get(path)[0],200)
        self.assertEqual(self.get('/api/computer/tasks')[0],200)
        self.assertEqual(self.request('POST','/api/computer/tasks',self.payload())[0],503)

    def test_cannot_cancel_inventory_through_computer_endpoint(self):
        record=self.core.prepare_inventory(request_id='inventory')
        self.assertEqual(self.request('POST','/api/computer/tasks/'+record['task']['task_id']+'/cancel',{})[0],400)
        self.assertFalse(self.core.status(record['task']['task_id'])['record']['cancel_requested'])

    @unittest.skipUnless(HAS_BROWSER,'Optional Edge backend unavailable')
    def test_real_async_task_receipt_replay_and_artifact_tamper(self):
        payload=self.payload();status,_,raw=self.request('POST','/api/computer/tasks',payload)
        self.assertEqual(status,202,raw);task_id=json.loads(raw)['task_id']
        data=self.wait_done(task_id);self.assertEqual(data['task']['status'],'SUCCEEDED',data)
        self.assertEqual(len(data['steps']),4)
        path='/api/computer/tasks/'+task_id+'/screenshot'
        status,headers,raw=self.get(path);self.assertEqual(status,200);self.assertEqual(headers['Content-Type'],'image/png');self.assertTrue(raw.startswith(b'\x89PNG'))
        with patch.object(self.manager.service,'browser_factory',side_effect=AssertionError('Replay')):
            repeat=self.request('POST','/api/computer/tasks',payload)
            self.assertEqual(json.loads(repeat[2])['task_id'],task_id)
        changed={**payload,'model':'test-model'}
        self.assertEqual(self.request('POST','/api/computer/tasks',changed)[0],409)
        report=self.manager.service.inspect(task_id)['report']
        (self.core.ledger.artifact_dir/report['screenshot']['path']).write_bytes(b'bad')
        self.assertEqual(self.get(path)[0],400)

    @unittest.skipUnless(HAS_BROWSER,'Optional Edge backend unavailable')
    def test_running_task_allows_chat_queues_second_task_and_cancels(self):
        entered=threading.Event();release=threading.Event()
        class Slow:
            last_metadata={}
            def __init__(self,*args):pass
            def plan(self,task,obs):
                entered.set();release.wait(15);return ScriptedDemoPlanner().plan(task,obs)
        self.manager.service=ComputerService(self.core,planner_factory=Slow)
        payload=self.payload('demo')
        try:
            status,_,raw=self.request('POST','/api/computer/tasks',payload)
            self.assertEqual(status,202,raw);task_id=json.loads(raw)['task_id']
            self.assertTrue(entered.wait(12))
            self.assertEqual(self.request('POST','/api/chat',{'message':'still here'})[0],200)
            queued=self.request('POST','/api/computer/tasks',self.payload())
            self.assertEqual(queued[0],202)
            queued_id=json.loads(queued[2])['task_id']
            self.assertEqual(self.core.ledger.record(task_id=queued_id)['action']['status'],'PREPARED')
            self.assertEqual(self.request('POST','/api/computer/tasks/'+queued_id+'/cancel',{})[0],200)
            self.assertEqual(self.request('POST','/api/computer/tasks',payload)[0],202)
            self.assertEqual(self.request('POST','/api/computer/tasks/'+task_id+'/cancel',{})[0],200)
            self.assertEqual(self.wait_done(task_id)['task']['status'],'CANCELLED')
        finally:release.set()

    @unittest.skipUnless(HAS_BROWSER,'Optional Edge backend unavailable')
    def test_graceful_server_close_cancels_running_browser(self):
        entered=threading.Event();release=threading.Event()
        class Slow:
            last_metadata={}
            def __init__(self,*args):pass
            def plan(self,task,obs):entered.set();release.wait(15);return ScriptedDemoPlanner().plan(task,obs)
        self.manager.service=ComputerService(self.core,planner_factory=Slow)
        try:
            result=self.manager.submit(self.payload('demo'));self.assertTrue(entered.wait(12))
            self.manager.close()
            self.assertFalse(self.manager.queue.thread.is_alive())
            self.assertEqual(self.core.status(result['task_id'])['record']['task']['status'],'CANCELLED')
        finally:release.set()

    def test_queue_control_boundary_and_capacity(self):
        path='/api/computer/queue'
        self.assertEqual(self.request('POST',path,{'paused':True},headers={'X-Jarvis-Nonce':None})[0],403)
        for payload in ({},{'paused':'true'},{'paused':True,'command':'run'}):
            self.assertEqual(self.request('POST',path,payload)[0],400)
        self.assertEqual(self.request('POST',path,{'paused':True})[0],200)

        self.manager.queue.capacity=1
        first=self.payload()
        self.assertEqual(self.request('POST','/api/computer/tasks',first)[0],202)
        self.assertEqual(self.request('POST','/api/computer/tasks',first)[0],202)
        self.assertEqual(self.request('POST','/api/computer/tasks',self.payload())[0],409)
        self.assertEqual(json.loads(self.get('/api/computer/tasks')[2])['queue']['waiting'],1)
        self.core.stop('test')
        self.assertEqual(self.request('POST',path,{'paused':False})[0],503)
        self.assertEqual(self.request('POST',path,{'paused':True})[0],200)


    def test_duplicate_port_launch_does_not_take_queue_ownership(self):
        with self.assertRaises(OSError):
            web.create_server(core=self.core,chat=self.chat,port=self.server.server_address[1])
        self.assertTrue(self.manager.queue.snapshot()['owned'])

    def test_cli_cannot_dispatch_paused_queue_task(self):
        self.manager.queue.set_paused(True)
        payload=self.payload();task,options=self.manager._validate(payload)
        item=self.manager.submit(payload)
        from jarvis_computer.protocol import ComputerError
        with self.assertRaisesRegex(ComputerError,'持久队列'):
            self.manager.service.run(task,**options)
        self.assertEqual(self.core.ledger.record(task_id=item['task_id'])['action']['status'],'PREPARED')

if __name__=='__main__':unittest.main()
