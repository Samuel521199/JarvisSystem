"""No paid calls: real pinned CLI against a loopback model, plus lifecycle checks."""
import json
import os
from pathlib import Path
import sys
import tempfile
import threading
import unittest
from types import SimpleNamespace
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'runtime/node-host'))
from jarvis_core import policy
from jarvis_core.coding_codex import CodexCodingProvider, command, executable, parse_events
from jarvis_core.coding_settings import CodingSettings
from jarvis_core.network_policy import NetworkPolicy
from jarvis_core.rea_process import run


class CodexTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(prefix='jarvis-codex-test-');self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name);self.core=SimpleNamespace(data_dir=self.root,assert_running=lambda:None)
    def test_settings_cas_and_offline_before_executable(self):
        settings=CodingSettings(self.core);v=settings.read();self.assertFalse(v['enabled'])
        settings.write({**v,'enabled':True})
        with self.assertRaises(policy.CoreError):settings.write(v)
        NetworkPolicy(self.root).change(True,0)
        with patch('jarvis_core.coding_codex.executable',side_effect=AssertionError('must not launch')),self.assertRaises(policy.CoreError) as e:
            CodexCodingProvider(self.core).preflight()
        self.assertEqual(e.exception.code,'network_offline')
    def test_unknown_or_tool_event_cannot_be_a_success(self):
        complete={'type':'turn.completed','usage':{'input_tokens':10,'output_tokens':5}}
        good=[{'type':'thread.started','thread_id':'test'},{'type':'item.completed','item':{'type':'agent_message','text':'{}'}},complete]
        raw=lambda items:('\n'.join(json.dumps(v) for v in items)).encode()
        self.assertEqual(parse_events(raw(good),0)['usage']['input_tokens'],10)
        for events,code in [(good,1),(good[:-1],0),([{'type':'turn.failed'}],0),([{'type':'item.started','item':{'type':'command_execution'}}]+good,0)]:
            with self.assertRaises(policy.CoreError):parse_events(raw(events),code)
    def test_unknown_settings_schema_blocks_writes_and_older_runtime(self):
        import sqlite3
        from contextlib import closing
        from jarvis_core.releases import RuntimeSlots
        settings=CodingSettings(self.core);value=settings.read();settings.write(value)
        with closing(sqlite3.connect(settings.path())) as db: db.execute('PRAGMA user_version=99')
        with self.assertRaises(policy.CoreError):settings.write({**value,'revision':1})
        with closing(sqlite3.connect(settings.path())) as db:self.assertEqual(db.execute('PRAGMA user_version').fetchone()[0],99)
        format={'optional_versions':{'coding-settings.db':1}}
        self.assertTrue(RuntimeSlots._compatible('0.1.65',format))
        self.assertFalse(RuntimeSlots._compatible('0.1.64',format))
    def test_process_stdin_isolated_env_and_cancellation(self):
        source=self.root/'request.txt';source.write_text('bounded input',encoding='utf-8')
        result=run([sys.executable,'-I','-c','import os,sys;print(sys.stdin.read());print(os.getenv("JARVIS_TEST_SECRET"))'],self.root,lambda:None,stdin_file=source)
        self.assertEqual(result['exit_code'],0);self.assertIn(b'bounded input',result['stdout']);self.assertIn(b'None',result['stdout'])
        self.assertTrue(result['process']['kill_on_close'])
        ticks=[0]
        def cancel():
            ticks[0]+=1
            if ticks[0]>5:raise policy.CoreError('task_cancelled','test')
        with self.assertRaises(policy.CoreError):run([sys.executable,'-I','-c','import time;time.sleep(30)'],self.root,cancel)
    def test_pinned_cli_rejects_file_read_and_execution_tools(self):
        captured=[];tool='view_image'
        class Handler(BaseHTTPRequestHandler):
            def log_message(self,*args):pass
            def do_POST(self):
                value=json.loads(self.rfile.read(int(self.headers['Content-Length'])))
                captured.append(value)
                if len(captured)==1:
                    self.send_response(200);self.send_header('Content-Type','text/event-stream');self.end_headers()
                    for event in [
                        {'type':'response.output_item.done','item':{'type':'function_call','id':'fc_probe','call_id':'call_probe','name':tool,'arguments':json.dumps({'path':str(sentinel),'command':'echo forbidden','input':'forbidden'})}},
                        {'type':'response.completed','response':{'id':'resp_probe','usage':{'input_tokens':1,'output_tokens':1,'total_tokens':2,'input_tokens_details':{'cached_tokens':0},'output_tokens_details':{'reasoning_tokens':0}}}}]:
                        self.wfile.write(('data: '+json.dumps(event)+'\n\n').encode());self.wfile.flush()
                else:
                    self.send_response(400);self.send_header('Content-Type','application/json');self.end_headers()
                    self.wfile.write(b'{"error":{"message":"local probe completed","type":"invalid_request_error"}}')
        server=ThreadingHTTPServer(('127.0.0.1',0),Handler);self.addCleanup(server.server_close);self.addCleanup(server.shutdown)
        threading.Thread(target=server.serve_forever,daemon=True).start()
        # A real image, private to the fixture. Sending its pixels is a failure.
        import base64
        sentinel=self.root/'sentinel.png';sentinel.write_bytes(base64.b64decode('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+jF2QAAAAASUVORK5CYII='))
        schema=self.root/'schema.json';schema.write_text('{"type":"object"}',encoding='utf-8')
        model=json.loads((policy.REPOSITORY_ROOT/'config/codex-proposal-model.json').read_text())
        (self.root/'models.json').write_text(json.dumps({'models':[model]}),encoding='utf-8')
        source=self.root/'request.txt';source.write_text('Return code only. No tools.',encoding='utf-8')
        for tool in ['view_image','exec_command','apply_patch','spawn_agent']:
            with self.subTest(tool=tool):
                captured.clear()
                args=command(executable(),self.root,{'model':model['slug'],'reasoning':'low'},schema)[:-1]+[
                    '-c','model_provider="fixture"','-c','model_providers.fixture.name="fixture"',
                    '-c','model_providers.fixture.base_url='+json.dumps(f'http://127.0.0.1:{server.server_port}'),
                    '-c','model_providers.fixture.wire_api="responses"','-c','model_providers.fixture.request_max_retries=0',
                    '-c','model_providers.fixture.stream_max_retries=0','-c','features.enable_request_compression=false','-']
                result=run(args,self.root,lambda:None,seconds=20,stdin_file=source,
                           environment_extra={'CODEX_HOME':str(self.root),'NO_PROXY':'127.0.0.1,localhost'})
                self.assertEqual(len(captured),2,result['stdout'].decode(errors='replace'))
                self.assertEqual({t.get('name') for t in captured[0]['tools']},{'update_plan','request_user_input','view_image'})
                outgoing=json.dumps(captured[1]['input'])
                self.assertNotIn('input_image',outgoing);self.assertNotIn('data:image',outgoing)
                self.assertTrue('not allowed' in outgoing or 'unknown tool' in outgoing or 'unsupported' in outgoing,outgoing[-1200:])
                self.assertNotIn('image_url',outgoing)
                with self.assertRaises(policy.CoreError):parse_events(result['stdout'],result['exit_code'])

if __name__=='__main__':unittest.main()
