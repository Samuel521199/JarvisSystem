"""Bounded timing, real HTTP concurrency, timeout slot retention and recovery."""
from concurrent.futures import ThreadPoolExecutor
import http.client
import importlib.util
import json
import os
from pathlib import Path
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch
import uuid

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT/'runtime/node-host'),str(ROOT/'tests')]
from jarvis_core.runtime_metrics import RuntimeMetrics
from jarvis_core.process_usage import process_usage
from jarvis_core.service import CoreService
from jarvis_core.resources import ResourceAdmission, MIB
from test_computer_queue import Executor, TASK, HTML
from jarvis_computer.task_queue import ComputerQueue


class MetricsTests(unittest.TestCase):
    def test_monotonic_overlap_percentiles_bounded_window_and_no_body(self):
        clock=[0];metrics=RuntimeMetrics(clock=lambda:clock[0],capacity=3)
        chat=metrics.begin('chat');clock[0]=1;task=metrics.begin('task',queue_wait_ms=2000)
        clock[0]=3;metrics.finish(chat,'SUCCEEDED');clock[0]=4;metrics.finish(task,'CONFIRMED')
        self.assertEqual(metrics.snapshot()['overlap_seconds'],2)
        for delay in (1,2,3,4):
            token=metrics.begin('chat');clock[0]+=delay;metrics.finish(token,'FAILED');metrics.finish(token,'SUCCEEDED')
        data=metrics.snapshot();self.assertEqual(data['lanes']['chat']['duration'],{'samples':3,'p50_ms':3000,'p95_ms':4000,'max_ms':4000})
        self.assertEqual(data['counters']['chat_finished'],5);self.assertEqual(data['lanes']['task']['duration']['samples'],0)
        self.assertNotIn('token',json.dumps(data));self.assertNotIn('content',json.dumps(data))
        self.assertEqual(RuntimeMetrics().snapshot()['counters'],{})

    @unittest.skipUnless(os.name=='nt','Windows process counters')
    def test_real_process_counters(self):
        value=process_usage(os.getpid());self.assertGreater(value['working_set_bytes'],0)
        self.assertGreater(value['private_bytes'],0);self.assertGreater(value['created'],0)

    def test_real_queue_wait_is_measured_once_after_dispatch(self):
        with tempfile.TemporaryDirectory() as temp:
            base=Path(temp);source=base/'sample';source.mkdir();core=CoreService(base/'data');core.initialize(source)
            metrics=RuntimeMetrics();executor=Executor(core);queue=ComputerQueue(core,lambda:executor,metrics=metrics)
            try:
                queue.set_paused(True)
                options={'request_id':'web-'+uuid.uuid4().hex,'model':'auto','scripted':True,'demo_html':HTML}
                item=queue.enqueue(TASK,options);time.sleep(.03)
                self.assertEqual(metrics.snapshot()['lanes']['task']['active'],0)
                queue.set_paused(False)
                limit=time.monotonic()+5
                while metrics.snapshot()['counters'].get('task_finished',0)<1 and time.monotonic()<limit:time.sleep(.01)
                data=metrics.snapshot()['lanes']['task'];self.assertEqual(data['duration']['samples'],1)
                self.assertGreaterEqual(data['queue_wait']['p50_ms'],30)
                self.assertEqual(queue.enqueue(TASK,options),item);time.sleep(.05)
                self.assertEqual(metrics.snapshot()['counters']['task_started'],1)
            finally:queue.close()


class RuntimeHttpTests(unittest.TestCase):
    def setUp(self):
        spec=importlib.util.spec_from_file_location('runtime_metrics_web',ROOT/'apps/web/server.py');self.web=importlib.util.module_from_spec(spec);spec.loader.exec_module(self.web)
        class Core:
            def assert_running(self):return {'config':{}}
        self.entered=threading.Event();self.release=threading.Event()
        test=self
        class Chat:
            def reply(self,*args,cancel_event=None,**kwargs):
                test.entered.set()
                while not test.release.wait(.01):
                    if cancel_event and cancel_event.is_set():return {'status':'CANCELLED','outcome_uncertain':False}
                return {'status':'SUCCEEDED','text':'ok','outcome_uncertain':False}
        self.server=self.web.LocalChatServer(('127.0.0.1',0),Core(),Chat(),reply_timeout=.15)
        self.thread=threading.Thread(target=self.server.serve_forever,kwargs={'poll_interval':.01},daemon=True);self.thread.start()
        self.addCleanup(self.cleanup)
    def cleanup(self):
        self.release.set();self.server.shutdown();self.server.server_close();self.thread.join(2)
    def request(self,path,method='GET',payload=None,request_id=None):
        connection=http.client.HTTPConnection('127.0.0.1',self.server.server_port,timeout=3)
        headers={'X-Jarvis-Nonce':self.server.nonce,'Origin':'http://127.0.0.1:'+str(self.server.server_port),'Content-Type':'application/json'}
        if request_id:headers['X-Jarvis-Request']=request_id
        connection.request(method,path,json.dumps(payload) if payload is not None else None,headers)
        response=connection.getresponse();status=response.status;body=json.loads(response.read());connection.close();return status,body
    def wait_idle(self):
        end=time.monotonic()+3
        while time.monotonic()<end:
            if self.server.metrics.snapshot()['lanes']['chat']['active']==0:return
            time.sleep(.01)
        self.fail('Chat slot not reclaimed')
    def test_two_timed_out_requests_retain_slots_and_control_is_responsive(self):
        ids=[uuid.uuid4().hex for _ in range(2)]
        with ThreadPoolExecutor(2) as pool:
            futures=[pool.submit(self.request,'/api/chat','POST',{'message':'fixture'},ident) for ident in ids]
            self.assertTrue(self.entered.wait(1))
            self.assertTrue(all(f.result()[0]==504 for f in futures))
        data=self.request('/api/resources')[1]['runtime'];self.assertEqual(data['lanes']['chat']['active'],2)
        self.assertEqual(data['counters']['http_wait_timeout'],2)
        self.assertEqual(self.request('/api/chat','POST',{'message':'third'})[0],429)
        self.assertEqual(self.request('/api/chat/cancel','POST',{'request_id':ids[0]})[0],200)
        self.release.set();self.wait_idle()
        self.assertEqual(self.request('/api/chat','POST',{'message':'after'})[0],200)
        self.assertEqual(self.server.metrics.snapshot()['counters']['chat_busy'],1)
    def test_thread_launch_failure_reclaims_slot_and_cancellation_handle(self):
        real=threading.Thread.start
        def start(thread):
            if thread.name=='jarvis-web-chat':raise RuntimeError('synthetic private failure')
            return real(thread)
        with patch.object(threading.Thread,'start',start):
            code,body=self.request('/api/chat','POST',{'message':'thread failure'},uuid.uuid4().hex)
        self.assertEqual(code,503);self.assertNotIn('private',json.dumps(body));self.wait_idle()
        self.assertEqual(self.server.chat_requests.active,0)
        self.release.set()
        self.assertEqual(self.request('/api/chat','POST',{'message':'recovered'})[0],200)
        self.assertEqual(self.server.metrics.snapshot()['counters']['chat_thread_failed'],1)
    def test_cancel_before_admission_has_zero_model_work_and_finished_timing(self):
        ident=uuid.uuid4().hex;self.request('/api/chat/cancel','POST',{'request_id':ident})
        code,result=self.request('/api/chat','POST',{'message':'cancelled'},ident)
        self.assertEqual(code,200);self.assertEqual(result['status'],'CANCELLED');self.assertFalse(self.entered.is_set())
        self.wait_idle();self.assertEqual(self.server.metrics.snapshot()['lanes']['chat']['outcomes'],{'CANCELLED':1})

    def test_missing_optional_menu_assets_do_not_prevent_startup(self):
        original=Path.read_bytes
        def read(path):
            if path.name in {'project_menu.js','project_menu.css'}:raise FileNotFoundError('missing optional fixture')
            return original(path)
        with patch.object(Path,'read_bytes',read):
            candidate=self.web.LocalChatServer(('127.0.0.1',0),self.server.core,self.server.chat)
        try:
            self.assertEqual(candidate.project_menu_script,b'')
            self.assertNotIn(b'__JARVIS_PROJECT_MENU_STYLE__',candidate.html)
            with self.assertRaises(ValueError):candidate.ui_assets.optional('index.html')
            self.assertEqual(candidate.ui_assets.snapshot()['status'],'degraded')
        finally:candidate.server_close()


if __name__=='__main__':unittest.main()
