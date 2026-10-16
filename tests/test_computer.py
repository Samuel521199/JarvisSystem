"""Scoped browser behavior, lifecycle and ledger tests; no paid model requests."""
import copy
import ctypes as C
from ctypes import wintypes as W
import importlib.util
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'runtime/node-host'),str(ROOT/'adapters/computer-use')]
from jarvis_core.service import CoreService, CoreError
from jarvis_computer.protocol import ComputerError,validate_task,validate_action,strict_json
from jarvis_computer.browser import EdgeBrowser
from jarvis_computer.planner import ScriptedDemoPlanner
from jarvis_computer.service import ComputerService

TASK=json.loads((ROOT/'config/computer-use/demo-task.json').read_text(encoding='utf-8'))
HTML=(ROOT/'apps/computer-use/demo.html').read_text(encoding='utf-8')
HAS_BROWSER=os.name=='nt' and importlib.util.find_spec('playwright') is not None

class ProtocolTests(unittest.TestCase):
    def test_reject_untrusted_task_expansion(self):
        variants=[]
        for url in ('file:///C:/Windows','https://user:secret@example.org','https://jarvis-demo.invalid.evil/','https://jarvis-demo.invalid/\n'):
            task=copy.deepcopy(TASK);task['url']=url;variants.append(task)
        task=copy.deepcopy(TASK);task['script']='evil';variants.append(task)
        task=copy.deepcopy(TASK);task['max_steps']=1.0;variants.append(task)
        task=copy.deepcopy(TASK);task['targets'][1]['id']='project';variants.append(task)
        task=copy.deepcopy(TASK);task['targets'][0]['actions']=['click'];variants.append(task)
        for task in variants:
            with self.subTest(task=task),self.assertRaises(ComputerError):validate_task(task)

    def test_strict_json(self):
        for raw in ('{"a":1,"a":2}','{"a":NaN}','```json\n{}\n```'):
            with self.assertRaises(ComputerError):strict_json(raw)

    def test_actions_cannot_expand_scope_or_reuse_observations(self):
        observation={'id':'a'*32,'targets':[{'id':'project','available':True}]}
        good={'observation_id':'a'*32,'op':'fill','target':'project','value':'Jarvis Demo'}
        self.assertEqual(validate_action(good,TASK,observation),good)
        for fields in ({'observation_id':'b'*32},{'target':'unlisted'},{'value':'exfiltrate'},{'script':'run'},{'op':'click','value':None}):
            with self.assertRaises(ComputerError):validate_action({**good,**fields},TASK,observation)
        observation['targets'][0]['available']=False
        with self.assertRaises(ComputerError):validate_action(good,TASK,observation)

@unittest.skipUnless(HAS_BROWSER,'Optional Playwright/Windows browser backend unavailable')
class BrowserTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(prefix='jarvis-computer-test-')
        self.base=Path(self.temp.name);(self.base/'input').mkdir()
        self.core=CoreService(self.base/'data');self.core.initialize(self.base/'input')
        self.service=ComputerService(self.core)

    def tearDown(self):self.temp.cleanup()

    def test_real_demo_receipt_idempotency_schema_and_tamper(self):
        from jsonschema import validate
        result=self.service.run(TASK,scripted=True,demo_html=HTML,request_id='stable')
        self.assertEqual(result['task']['status'],'SUCCEEDED',result)
        for key,name in (('task','Task'),('action','Action'),('artifact','Artifact')):
            validate(result[key],json.loads((ROOT/f'contracts/schemas/{name}.schema.json').read_text()))
        detail=self.service.inspect(result['task']['task_id'])
        self.assertEqual(len(detail['steps']),4)
        with patch.object(self.service,'browser_factory',side_effect=AssertionError('replayed')):
            self.assertEqual(self.service.run(TASK,scripted=True,demo_html=HTML,request_id='stable'),result)
        with self.assertRaises(CoreError):self.service.run(TASK,model='other',scripted=True,demo_html=HTML,request_id='stable')
        with self.assertRaises(CoreError) as captured:self.core.run(result['action']['action_id'])
        self.assertEqual(captured.exception.code,'wrong_executor')
        (self.core.ledger.artifact_dir/detail['report']['screenshot']['path']).write_bytes(b'tampered')
        with self.assertRaises(CoreError):self.service.inspect(result['task']['task_id'])

    def test_page_change_rejected_before_action(self):
        browser=EdgeBrowser(TASK,demo_html=HTML)
        try:
            browser.start();observation=browser.observe()
            browser.page.get_by_role('textbox',name='项目名称',exact=True).fill('changed')
            with self.assertRaises(ComputerError):browser.check_fresh(observation)
        finally:browser.close()

    def test_blocked_network_and_sensitive_input(self):
        browser=EdgeBrowser(TASK,demo_html=HTML.replace('type="text"','type="password"'))
        try:
            browser.start()
            browser.page.evaluate("fetch('https://outside.invalid/canary').catch(()=>null)")
            self.assertGreater(browser.blocked_requests,0)
            browser.page.locator('input').first.evaluate("e=>e.type='password'")
            self.assertFalse(browser.observe()['targets'][0]['available'])
        finally:browser.close()

    def test_invalid_model_action_never_dispatches(self):
        class Bad:
            last_metadata={}
            def __init__(self,*args):pass
            def plan(self,task,obs):return {'observation_id':obs['id'],'op':'fill','target':'project','value':'not permitted'}
        service=ComputerService(self.core,planner_factory=Bad)
        result=service.run(TASK,demo_html=HTML)
        self.assertEqual(result['task']['status'],'FAILED')
        self.assertEqual(service.inspect(result['task']['task_id'])['steps'],[])

    def test_real_network_scope_blocks_subresources_and_redirects(self):
        hits=[]
        class Outside(BaseHTTPRequestHandler):
            def log_message(self,*args):pass
            def do_GET(self):
                hits.append(self.path);self.send_response(200);self.end_headers();self.wfile.write(b'outside')
        outside=ThreadingHTTPServer(('127.0.0.1',0),Outside)
        outside_url=f'http://127.0.0.1:{outside.server_port}'
        class Inside(BaseHTTPRequestHandler):
            def log_message(self,*args):pass
            def do_GET(self):
                if self.path=='/redirect':
                    self.send_response(302);self.send_header('Location',outside_url+'/redirected');self.end_headers()
                else:
                    self.send_response(200);self.send_header('Content-Type','text/html; charset=utf-8');self.end_headers()
                    self.wfile.write((HTML+f'<img src="{outside_url}/image"><script>fetch("/redirect").catch(()=>null)</script>').encode())
        inside=ThreadingHTTPServer(('127.0.0.1',0),Inside)
        threads=[threading.Thread(target=s.serve_forever,daemon=True) for s in (inside,outside)]
        for thread in threads:thread.start()
        task=copy.deepcopy(TASK);task['allowed_origins']=[f'http://127.0.0.1:{inside.server_port}'];task['url']=task['allowed_origins'][0]+'/'
        browser=EdgeBrowser(task)
        try:
            browser.start();browser.page.wait_for_timeout(500)
            self.assertEqual(hits,[])
            self.assertGreaterEqual(browser.blocked_requests,2)
        finally:
            browser.close()
            for server in (inside,outside):server.shutdown();server.server_close()
            for thread in threads:thread.join(3)

    def test_cancel_or_stop_while_model_waits(self):
        for stop in (False,True):
            entered=threading.Event();release=threading.Event()
            class Slow:
                last_metadata={}
                def __init__(self,*args):pass
                def plan(self,task,obs):
                    entered.set();release.wait(15)
                    return ScriptedDemoPlanner().plan(task,obs)
            service=ComputerService(self.core,planner_factory=Slow)
            def cancel():
                if entered.wait(15):
                    if stop:self.core.stop('test')
                    else:self.core.cancel(self.core.status()['tasks'][-1]['task_id'])
            thread=threading.Thread(target=cancel);thread.start()
            started=time.monotonic()
            try:result=service.run(TASK,demo_html=HTML)
            finally:release.set();thread.join(20)
            self.assertEqual(result['task']['status'],'CANCELLED',result)
            self.assertLess(time.monotonic()-started,15)
            self.assertIsNone(result['artifact'])

    def test_failure_after_action_unknown_and_never_replayed(self):
        class Fails:
            last_metadata={}
            def __init__(self,*args):self.calls=0
            def plan(self,task,obs):
                self.calls+=1
                if self.calls>1:raise ComputerError('model_failed','Injected failure')
                return ScriptedDemoPlanner().plan(task,obs)
        service=ComputerService(self.core,planner_factory=Fails)
        result=service.run(TASK,demo_html=HTML,request_id='uncertain')
        self.assertEqual(result['action']['status'],'UNKNOWN')
        self.assertEqual(service.inspect(result['task']['task_id'])['steps'][0]['state'],'CONFIRMED')
        with patch.object(service,'browser_factory',side_effect=AssertionError('replayed')):
            self.assertEqual(service.run(TASK,demo_html=HTML,request_id='uncertain'),result)

    def test_host_crash_kills_private_browser_tree(self):
        source='''import json,os,sys
from pathlib import Path
from jarvis_core.service import CoreService
from jarvis_computer.browser import EdgeBrowser
root=Path(sys.argv[1]); task=json.loads((root/'config/computer-use/demo-task.json').read_text(encoding='utf-8'))
parent=Path(sys.argv[2]).parent/'browser-staging';parent.mkdir()
b=EdgeBrowser(task,demo_html=(root/'apps/computer-use/demo.html').read_text(encoding='utf-8'),scratch_parent=parent);b.start()
pids=[p['id'] for p in b.browser.new_browser_cdp_session().send('SystemInfo.getProcessInfo')['processInfo']]
pids.append(b.playwright._impl_obj._connection._transport._proc.pid)
Path(sys.argv[2]).write_text(json.dumps(pids));os._exit(77)
'''
        path=self.base/'pids.json'
        result=subprocess.run([sys.executable,'-c',source,str(ROOT),str(path)],env={**os.environ,'PYTHONPATH':os.pathsep.join([str(ROOT/'runtime/node-host'),str(ROOT/'adapters/computer-use')]),'PYTHONUTF8':'1'},capture_output=True,timeout=30)
        self.assertEqual(result.returncode,77,result.stderr)
        pids=json.loads(path.read_text());self.assertGreater(len(pids),2)
        kernel=C.WinDLL('kernel32',use_last_error=True)
        kernel.OpenProcess.argtypes=[W.DWORD,W.BOOL,W.DWORD];kernel.OpenProcess.restype=W.HANDLE
        kernel.WaitForSingleObject.argtypes=[W.HANDLE,W.DWORD];kernel.CloseHandle.argtypes=[W.HANDLE]
        for pid in pids:
            handle=kernel.OpenProcess(0x100000,False,pid)
            if handle:
                try:self.assertEqual(kernel.WaitForSingleObject(handle,5000),0,f'Process {pid} survived Host crash')
                finally:kernel.CloseHandle(handle)
        from jarvis_core.browser_recovery import recover
        parent=self.base/'browser-staging'
        stages=[p for p in parent.iterdir() if p.name.startswith('browser-')]
        self.assertEqual(len(stages),1)
        self.assertTrue((stages[0]/'profile').exists())
        for _ in range(30):
            recovery=recover(parent)
            if recovery['removed']:break
            time.sleep(.1)
        self.assertEqual(recovery['removed'],[stages[0].name],recovery)
        self.assertFalse(stages[0].exists())

if __name__=='__main__':unittest.main()
