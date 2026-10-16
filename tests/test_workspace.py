"""Real filesystem and loopback project exports; synthetic text, no model calls."""
from concurrent.futures import ThreadPoolExecutor
import hashlib
import http.client
import importlib.util
import json
import os
from pathlib import Path
import sqlite3
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch
import uuid

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'runtime/node-host'))
from jarvis_core.service import CoreService
from jarvis_core.policy import CoreError
from jarvis_core.workspace import WorkspaceService, MAX_TEXT_BYTES


class WorkspaceTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix='jarvis-project-test-')
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name)
        self.folder = self.base / '中文 project';self.folder.mkdir()
        self.second = self.base / 'second';self.second.mkdir()
        self.core = CoreService(self.base / 'data');self.core.initialize(self.folder)
        self.ws = WorkspaceService(self.core)
        self.project = self.ws.open_project({'path': str(self.folder)})

    def prepare(self, path='', project=None, request_id=None):
        return self.ws.prepare({'project_id': (project or self.project)['id'], 'request_id': request_id or uuid.uuid4().hex, 'path': path})

    def save(self, ticket, text='这是生成的正文。\n'):
        return self.ws.save(ticket['request_id'], {'content': text})

    def test_root_default_nested_and_explicit_absolute_paths(self):
        for value, parent in [('', self.folder), ('报告.md', self.folder), ('docs/笔记.txt', self.folder/'docs'), (str(self.second/'other.py'), self.second)]:
            with self.subTest(path=value):
                ticket = self.prepare(value)
                self.assertEqual(Path(ticket['path']).parent, parent)
                self.assertFalse(Path(ticket['path']).exists())
                result = self.save(ticket)
                self.assertEqual(result['status'], 'SAVED')
                self.assertEqual(Path(ticket['path']).read_text(encoding='utf-8'), '这是生成的正文。\n')
                self.assertEqual(result['digest'], 'sha256:'+hashlib.sha256(Path(ticket['path']).read_bytes()).hexdigest())
        self.assertFalse((self.folder/'.git').exists())

    def test_projects_persist_and_duplicate_open_keeps_identity(self):
        again = self.ws.open_project({'path': str(self.folder)})
        fresh = WorkspaceService(CoreService(self.core.data_dir))
        self.assertEqual(again['id'], self.project['id'])
        self.assertEqual(len(fresh.projects()['projects']), 1)
        self.assertEqual(fresh.projects()['projects'][0]['path'], str(self.folder))

    def test_prepared_path_stays_with_original_project_across_switch_and_restart(self):
        ticket = self.prepare('original.md')
        second = self.ws.open_project({'path': str(self.second)})
        self.assertNotEqual(second['id'], self.project['id'])
        self.ws = WorkspaceService(CoreService(self.core.data_dir))
        self.save(ticket)
        self.assertTrue((self.folder/'original.md').is_file())
        self.assertFalse((self.second/'original.md').exists())

    def test_request_id_is_bound_to_project_path_and_content(self):
        ticket = self.prepare('one.md')
        self.assertEqual(self.prepare('one.md', request_id=ticket['request_id']), ticket)
        with self.assertRaises(CoreError):self.prepare('two.md', request_id=ticket['request_id'])
        other = self.ws.open_project({'path': str(self.second)})
        with self.assertRaises(CoreError):self.prepare('one.md', other, ticket['request_id'])
        saved = self.save(ticket)
        self.assertEqual(self.save(ticket), saved)
        with self.assertRaises(CoreError):self.save(ticket, 'changed')
        (self.folder/'one.md').write_text('user change', encoding='utf-8')
        with self.assertRaises(CoreError):self.save(ticket)
        self.assertEqual((self.folder/'one.md').read_text(), 'user change')

    def test_existing_file_and_competing_saves_never_overwrite(self):
        (self.folder/'existing.md').write_text('keep', encoding='utf-8')
        with self.assertRaises(CoreError):self.prepare('existing.md')
        a,b = self.prepare('race.md'),self.prepare('race.md')
        def attempt(t):
            try:return self.save(t, t['request_id'])['status']
            except CoreError:return 'FAILED'
        with ThreadPoolExecutor(max_workers=2) as pool:states=list(pool.map(attempt,[a,b]))
        self.assertEqual(sorted(states), ['FAILED','SAVED'])
        self.assertIn((self.folder/'race.md').read_text(), [a['request_id'],b['request_id']])
        self.assertEqual((self.folder/'existing.md').read_text(), 'keep')

    def test_lost_root_and_replaced_output_parent_are_not_rebound(self):
        ticket = self.prepare('file.md')
        self.folder.rename(self.base/'old')
        with self.assertRaises(CoreError):self.save(ticket)
        self.assertFalse((self.second/'file.md').exists())
        self.folder.mkdir()
        with self.assertRaises(CoreError):self.ws.open_project({'path': str(self.folder)})
        self.assertFalse(self.ws.projects()['projects'][0]['available'])

    def test_external_parent_replacement_is_detected(self):
        ticket = self.prepare(str(self.second/'file.md'))
        self.second.rename(self.base/'old-second');self.second.mkdir()
        with self.assertRaises(CoreError):self.save(ticket)
        self.assertFalse((self.second/'file.md').exists())

    def test_stop_after_prepare_prevents_write_and_preserves_control(self):
        ticket = self.prepare('stopped.md');self.core.stop('workspace test')
        with self.assertRaises(CoreError):self.save(ticket)
        self.assertFalse((self.folder/'stopped.md').exists())
        self.assertTrue(self.core.status()['stopped'])

    def test_unknown_write_is_not_replayed(self):
        ticket = self.prepare('partial.md')
        with patch('jarvis_core.workspace.os.fsync', side_effect=OSError('disk failure')):
            with self.assertRaises(CoreError):self.save(ticket)
        self.assertEqual(self.ws.outputs()['outputs'][0]['status'], 'UNKNOWN')
        before=(self.folder/'partial.md').read_bytes()
        with self.assertRaises(CoreError):self.save(ticket)
        self.assertEqual((self.folder/'partial.md').read_bytes(), before)

    def test_permission_denied_has_no_fallback_or_success_receipt(self):
        ticket = self.prepare('denied.md')
        original = Path.open
        def denied(path, *args, **kwargs):
            if path == self.folder/'denied.md' and args and args[0] == 'xb':
                raise PermissionError('synthetic access denied')
            return original(path, *args, **kwargs)
        with patch.object(Path, 'open', denied):
            with self.assertRaises(CoreError):self.save(ticket)
        self.assertEqual(self.ws.outputs()['outputs'][0]['status'], 'FAILED')
        self.assertFalse((self.folder/'denied.md').exists())
        self.assertFalse((self.second/'denied.md').exists())

    def test_crash_intent_is_unknown_after_restart(self):
        ticket = self.prepare('crash.md')
        with self.ws.connection() as db:db.execute("UPDATE outputs SET state='WRITING' WHERE id=?", (ticket['request_id'],))
        self.ws=WorkspaceService(CoreService(self.core.data_dir))
        self.assertEqual(self.ws.outputs()['outputs'][0]['status'],'UNKNOWN')
        with self.assertRaises(CoreError):self.save(ticket)
        self.assertFalse((self.folder/'crash.md').exists())

    def test_path_validation_and_content_bounds(self):
        for path in ['../escape.md','docs/../../escape.md','file:stream','NUL.txt','file.','file ','\\\\server\\share\\a','C:relative.txt',str(self.core.data_dir/'control.db'),'docs/','x/.git/config',[],False,None]:
            with self.subTest(path=path),self.assertRaises(CoreError):self.prepare(path)
        ticket=self.prepare('big.txt')
        for content in ['', [], 'nul\x00', 'x'*(MAX_TEXT_BYTES+1)]:
            with self.subTest(type=type(content)),self.assertRaises(CoreError):self.save(ticket,content)
        self.assertFalse((self.folder/'big.txt').exists())
        for path in ['relative',str(self.base/'missing'),str(self.core.data_dir)]:
            with self.assertRaises(CoreError):self.ws.open_project({'path':path})

    def test_linked_output_component_is_denied(self):
        link=self.folder/'linked'
        try:link.symlink_to(self.second,target_is_directory=True)
        except OSError:self.skipTest('OS does not grant symlink creation')
        with self.assertRaises(CoreError):self.prepare('linked/escape.md')
        self.assertFalse((self.second/'escape.md').exists())

    def test_folder_picker_cancel_and_selection(self):
        self.ws.picker=lambda:''
        self.assertEqual(self.ws.choose_project({}), {'cancelled':True})
        self.ws.picker=lambda:str(self.second)
        self.assertEqual(self.ws.choose_project({})['project']['path'],str(self.second))
        with self.assertRaises(CoreError):self.ws.choose_project({'command':'bad'})


class WorkspaceHTTPTests(unittest.TestCase):
    def setUp(self):
        WorkspaceTests.setUp(self)
        spec=importlib.util.spec_from_file_location('workspace_web_test',ROOT/'apps/web/server.py')
        module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
        self.server=module.LocalChatServer(('127.0.0.1',0),self.core,object(),workspace=self.ws)
        thread=threading.Thread(target=self.server.serve_forever,kwargs={'poll_interval':.01},daemon=True);thread.start()
        self.addCleanup(self.server.server_close);self.addCleanup(self.server.shutdown)
        self.port=self.server.server_address[1]

    def request(self,path,payload=None,nonce=True,origin=None):
        connection=http.client.HTTPConnection('127.0.0.1',self.port,timeout=5)
        host=f'127.0.0.1:{self.port}'
        headers={'Host':host,'Origin':origin or 'http://'+host}
        if nonce:headers['X-Jarvis-Nonce']=self.server.nonce
        if payload is not None:headers['Content-Type']='application/json'
        try:
            connection.request('GET' if payload is None else 'POST',path,body=None if payload is None else json.dumps(payload).encode('utf-8'),headers=headers)
            result=connection.getresponse();return result.status,json.loads(result.read())
        finally:connection.close()

    def test_http_origin_nonce_strict_fields_and_round_trip(self):
        for path,payload in [('/api/workspace/projects',None),('/api/workspace/outputs',None),('/api/workspace/projects',{'path':str(self.second)})]:
            self.assertEqual(self.request(path,payload,nonce=False)[0],403)
            self.assertEqual(self.request(path,payload,origin='https://evil.example')[0],403)
        self.assertEqual(self.request('/api/workspace/projects',{'path':str(self.second),'shell':'bad'})[0],400)
        status,ticket=self.request('/api/workspace/outputs/prepare',{'project_id':self.project['id'],'request_id':uuid.uuid4().hex,'path':'http.md'})
        self.assertEqual(status,200)
        status,saved=self.request('/api/workspace/outputs/'+ticket['request_id'],{'content':'通过 HTTP 保存'})
        self.assertEqual((status,saved['status']),(200,'SAVED'))
        self.assertEqual((self.folder/'http.md').read_text(encoding='utf-8'),'通过 HTTP 保存')
        self.assertEqual(self.request('/api/workspace/outputs/'+ticket['request_id'],{'content':'same','path':str(self.second/'evil')})[0],400)


if __name__=='__main__':unittest.main()
