"""Real Windows tray and Host lifecycle integration, with synthetic HTTP state."""
import json
from concurrent.futures import ThreadPoolExecutor
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import time
import unittest
import uuid
from urllib.request import Request, urlopen

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'apps/tray'),str(ROOT/'apps/web')]
from companion import TrayCompanion, NamedEvent
from server import LocalChatServer
from test_web import FakeCore, FakeChat


@unittest.skipUnless(os.name=='nt','Windows notification-area integration')
class TrayTests(unittest.TestCase):
    def setUp(self):
        self.temporary=tempfile.TemporaryDirectory(prefix='jarvis-tray-test-')
        self.addCleanup(self.temporary.cleanup)
        self.core=FakeCore()
        self.server=LocalChatServer(('127.0.0.1',0),self.core,FakeChat(),version='test')
        self.thread=threading.Thread(target=self.server.serve_forever,kwargs={'poll_interval':.05},daemon=True)
        self.thread.start()
        self.addCleanup(self.server.server_close)
        self.addCleanup(self.server.shutdown)
        self.tray=TrayCompanion(self.server,Path(self.temporary.name))
        self.addCleanup(self.tray.close)

    def wait_state(self,expected):
        deadline=time.monotonic()+10
        while time.monotonic()<deadline:
            try:
                result=json.loads(self.tray.state_path.read_text(encoding='utf-8'))
                if result['state']==expected:
                    self.assertTrue(result['icon_visible']); return result
            except (OSError,ValueError): pass
            time.sleep(.1)
        self.fail('Tray did not reach '+expected)

    def test_real_icon_tracks_idle_busy_and_unready_without_stopping_host(self):
        self.wait_state('standby')
        request=uuid.uuid4().hex
        self.server.chat.hook=lambda: self.server.chat.cancel_event.wait(15)
        url=f'http://127.0.0.1:{self.server.server_address[1]}'
        def post(route,payload):
            headers={'Origin':url,'Content-Type':'application/json','X-Jarvis-Nonce':self.server.nonce,
                     'X-Jarvis-Request':request}
            with urlopen(Request(url+route,json.dumps(payload).encode(),headers),timeout=20) as response:
                return json.load(response)
        with ThreadPoolExecutor(max_workers=1) as pool:
            response=pool.submit(post,'/api/chat',{'message':'synthetic tray check'})
            try:
                self.wait_state('working')
                post('/api/chat/cancel',{'request_id':request})
                self.assertEqual(response.result(timeout=5)['status'],'CANCELLED')
            finally: self.server.chat_requests.cancel_all()
        self.wait_state('standby')
        self.core.stopped=True; self.wait_state('needs_attention')
        self.core.stopped=False; self.wait_state('standby')
        self.assertTrue(self.thread.is_alive())

    def test_wrong_instance_and_connection_loss_never_look_like_standby(self):
        self.wait_state('standby')
        original=self.server.instance_id; self.server.instance_id=uuid.uuid4().hex
        self.wait_state('offline')
        self.server.instance_id=original; self.wait_state('standby')
        self.server.shutdown(); self.server.server_close(); self.wait_state('offline')
        self.assertIsNone(self.tray.process.poll())

    def test_explicit_app_exit_only_closes_its_own_host(self):
        other=LocalChatServer(('127.0.0.1',0),FakeCore(),FakeChat(),version='other')
        other_thread=threading.Thread(target=other.serve_forever,kwargs={'poll_interval':.05},daemon=True)
        other_thread.start(); self.addCleanup(other.server_close); self.addCleanup(other.shutdown)
        self.wait_state('standby'); self.tray.quit_event.set(); self.thread.join(timeout=3)
        self.assertFalse(self.thread.is_alive()); self.assertTrue(other_thread.is_alive())
        self.assertFalse(self.core.stopped)
        self.tray.close(); self.assertEqual(self.tray.process.returncode,0)

    def test_companion_close_keeps_host_and_cleans_notify_process(self):
        self.wait_state('standby'); self.tray.close()
        self.assertEqual(self.tray.process.returncode,0)
        self.assertTrue(self.thread.is_alive()); self.assertFalse(self.core.stopped)


@unittest.skipUnless(os.name=='nt','Windows notification-area integration')
class TrayMenuTests(unittest.TestCase):
    def test_actual_exit_handler_signals_only_its_instance(self):
        with tempfile.TemporaryDirectory(prefix='jarvis-tray-menu-') as directory:
            ident=uuid.uuid4().hex
            events=[NamedEvent('Local\\Jarvis.Tray.'+ident+'.'+s) for s in ('quit','close','ready')]
            try:
                script="""$ErrorActionPreference='Stop'
Add-Type -AssemblyName System.Windows.Forms,System.Drawing,System.Net.Http,System.Web.Extensions
Add-Type -Path $env:JARVIS_TRAY_SOURCE -ReferencedAssemblies System.Windows.Forms,System.Drawing,System.Net.Http,System.Web.Extensions
$app=[Jarvis.TrayApplication]::new(18180,[int]$env:JARVIS_TEST_PID,$env:JARVIS_TEST_ID,'test',$env:JARVIS_TEST_STATE)
try { $app.RequestExit() } finally { $app.Dispose() }
"""
                result=subprocess.run(['powershell.exe','-NoProfile','-NonInteractive','-STA','-Command',script],
                    capture_output=True,timeout=25,creationflags=subprocess.CREATE_NO_WINDOW,
                    env={**os.environ,'JARVIS_TRAY_SOURCE':str(ROOT/'apps/tray/TrayApplication.cs'),
                         'JARVIS_TEST_PID':str(os.getpid()),'JARVIS_TEST_ID':ident,
                         'JARVIS_TEST_STATE':str(Path(directory)/'state.json')})
                self.assertEqual(result.returncode,0,result.stderr.decode(errors='replace'))
                self.assertTrue(events[0].wait(0)); self.assertFalse(events[1].wait(0))
                self.assertEqual(json.loads((Path(directory)/'state.json').read_text(encoding='utf-8'))['state'],'exiting')
            finally:
                for event in events: event.close()
