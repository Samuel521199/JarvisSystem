"""Local files, portable project documents and dormant extensions."""
import http.client
import importlib.util
import json
import os
from pathlib import Path
import sys
import tempfile
import threading
import unittest
import uuid
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'runtime/node-host'))
from jarvis_core.service import CoreService
from jarvis_core.workspace import WorkspaceService
from jarvis_core.policy import CoreError
from jarvis_core.project_files import ProjectFiles, MAX_FILE
from jarvis_core.extensions import ExtensionCatalog


class ResourceTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory(); self.addCleanup(temp.cleanup)
        self.base = Path(temp.name); self.folder = self.base/'project'; self.folder.mkdir()
        self.core = CoreService(self.base/'data'); self.core.initialize(self.folder)
        self.project = WorkspaceService(self.core).open_project({'path': str(self.folder)})
        self.files = ProjectFiles(self.core); self.ext = ExtensionCatalog(self.core)

    def request(self, path='', **kwargs):
        return {'project_id': self.project['id'], 'path': path, **kwargs}

    def write(self, path, content, digest=None, bom=False):
        return self.files.write(self.request(path, content=content, digest=digest, bom=bom))

    def document(self):
        return {'schema_version': 1, 'folders': [{'path': '.'}],
                'view': {'open_files': ['main.py'], 'active_file': 'main.py', 'exclude': ['logs', '*.log']}}

    def test_lazy_tree_filters_links_dependencies_and_exclusions(self):
        (self.folder/'src').mkdir(); (self.folder/'src'/'main.py').write_text('pass')
        (self.folder/'node_modules').mkdir(); (self.folder/'.env').write_text('SECRET')
        (self.folder/'x.log').write_text('log'); (self.folder/'image.png').write_bytes(b'png')
        with patch.object(Path, 'read_bytes', side_effect=AssertionError('tree must not read content')):
            tree = self.files.tree(self.request(exclude=['*.log']))
        self.assertEqual([x['name'] for x in tree['entries']], ['src', 'image.png'])
        self.assertFalse(tree['entries'][1]['editable'])
        self.assertEqual(tree['excluded'], 3)
        self.assertEqual(self.files.tree(self.request('src'))['entries'][0]['path'], 'src/main.py')

    def test_tree_limit_and_missing_directory(self):
        for i in range(503): (self.folder/f'{i}.txt').touch()
        tree = self.files.tree(self.request())
        self.assertTrue(tree['truncated']); self.assertEqual(len(tree['entries']), 500)
        with self.assertRaises(CoreError): self.files.tree(self.request('missing'))

    def test_edit_preserves_bom_crlf_and_detects_external_change(self):
        path = self.folder/'main.py'; path.write_bytes(b'\xef\xbb\xbfprint(1)\r\n')
        read = self.files.read(self.request('main.py'))
        self.assertTrue(read['bom']); self.assertEqual(read['content'], 'print(1)\r\n')
        result = self.write('main.py', 'print(2)\r\n', read['digest'], True)
        self.assertEqual(path.read_bytes(), b'\xef\xbb\xbfprint(2)\r\n')
        # A lost response can retry the same desired bytes without a second edit.
        self.assertEqual(self.write('main.py', 'print(2)\r\n', read['digest'], True), result)
        path.write_text('outside')
        with self.assertRaisesRegex(CoreError, '已经变化'):
            self.write('main.py', 'print(3)', result['digest'])
        self.assertEqual(path.read_text(), 'outside')

    def test_new_file_is_exclusive_and_empty_files_are_supported(self):
        result = self.write('empty.py', '')
        self.assertEqual(result['size_bytes'], 0)
        with self.assertRaises(CoreError): self.write('empty.py', 'overwrite')
        self.assertEqual((self.folder/'empty.py').read_bytes(), b'')

    def test_file_type_size_encoding_and_traversal(self):
        for name in ['../escape.py', '.git/config', '.env', 'x.key', 'NUL.txt', 'a:ads', str(self.base/'escape.py')]:
            with self.subTest(name=name), self.assertRaises(CoreError): self.write(name, 'bad')
        for name, body in [('binary.py', b'a\x00b'), ('bad.py', b'\xff'), ('big.txt', b'a'*(MAX_FILE+1)), ('x.png', b'abc')]:
            (self.folder/name).write_bytes(body)
            with self.assertRaises(CoreError): self.files.read(self.request(name))
        with self.assertRaises(CoreError): self.write('new.py', 'a'*(MAX_FILE+1))
        self.assertFalse((self.folder/'new.py').exists())

    def test_hardlink_and_replaced_root_rejected(self):
        source = self.folder/'a.py'; source.write_text('original')
        os.link(source, self.folder/'b.py')
        with self.assertRaises(CoreError): self.files.read(self.request('a.py'))
        self.folder.rename(self.base/'old'); self.folder.mkdir()
        with self.assertRaises(CoreError): self.files.tree(self.request())

    def test_failed_replace_keeps_original_and_removes_staging(self):
        old = self.write('main.py', 'old')
        with patch('jarvis_core.project_files.os.replace', side_effect=OSError('synthetic disk failure')):
            with self.assertRaises(OSError): self.write('main.py', 'new', old['digest'])
        self.assertEqual((self.folder/'main.py').read_text(), 'old')
        self.assertEqual(list(self.folder.glob('.jarvis-edit-*')), [])

    def test_workspace_portability_no_commands_and_conflict(self):
        doc = self.document()
        saved = self.files.save_project(self.request('demo.jarvis-workspace', document=doc, digest=None))
        opened = self.files.open_project({'path': str(self.folder/'demo.jarvis-workspace')})
        self.assertEqual(opened['document'], doc); self.assertEqual(opened['project']['id'], self.project['id'])
        self.assertNotIn(str(self.folder), saved['content'])
        doc['view']['active_file'] = None
        with self.assertRaises(CoreError): self.files.save_project(self.request('demo.jarvis-workspace', document=doc, digest=None))
        for invalid in [{**doc, 'command': 'run'}, {**doc, 'folders': [{'path': '../'}]}, {**doc, 'schema_version': True}, {**doc, 'view': {**doc['view'], 'open_files': ['../bad']}}]:
            with self.assertRaises(CoreError): self.files.project_document(invalid)
        other=self.base/'portable'; other.mkdir(); (other/'copy.jarvis-workspace').write_text(saved['content'], encoding='utf-8')
        moved=self.files.open_project({'path':str(other/'copy.jarvis-workspace')})
        self.assertEqual(moved['project']['path'],str(other))

    def test_invalid_workspace_does_not_register_folder(self):
        other = self.base/'other'; other.mkdir(); target=other/'bad.jarvis-workspace'; target.write_text('{"schema_version":1,"schema_version":2}')
        with self.assertRaises(CoreError): self.files.open_project({'path': str(target)})
        self.assertEqual(len(WorkspaceService(self.core).projects()['projects']),1)

    def mcp(self):
        return {'kind': 'mcp', 'name': 'test', 'config': {'transport': 'stdio', 'command': 'python', 'args': ['server.py']}}

    def test_mcp_registration_restart_retry_and_revision(self):
        entry_id = uuid.uuid4().hex; payload = {'revision': 0, 'document': self.mcp()}
        with patch('subprocess.Popen', side_effect=AssertionError('must not launch')):
            saved = self.ext.put(entry_id, payload)
            self.assertEqual(saved, self.ext.put(entry_id, payload))
            self.assertFalse(saved['runtime_available'])
            self.assertEqual(self.ext.inspect(entry_id, {})['status'], 'configuration_valid')
        fresh = ExtensionCatalog(self.core); self.assertEqual(fresh.list()['entries'][0], saved)
        changed=self.mcp(); changed['name']='new'
        with self.assertRaises(CoreError): self.ext.put(entry_id, {'revision': 0, 'document': changed})
        self.ext.delete(entry_id, {'revision': 1}); self.assertEqual(self.ext.list()['entries'], [])
        with self.assertRaises(CoreError): self.ext.put(entry_id, payload)

    def test_extension_fields_and_endpoints(self):
        for url in ['http://example.com/mcp','https://u:p@example.com/mcp','https://example.com/?key=a','file:///tmp/x','https://example.com:BAD/mcp']:
            with self.subTest(url=url), self.assertRaises(CoreError):
                self.ext.validate({'kind':'mcp','name':'x','config':{'transport':'streamable-http','url':url}})
        for url in ['https://example.com/mcp','http://127.0.0.1:8000/mcp']:
            self.ext.validate({'kind':'mcp','name':'x','config':{'transport':'streamable-http','url':url}})
        for config in [{'transport':'stdio','command':'python','env':{'KEY':'secret'}}, {'transport':'stdio','command':'python','args':'--run'}, {'transport':'other'}, {'transport':'stdio','command':'x','credential_ref':'sk/bad'}]:
            with self.assertRaises(CoreError): self.ext.validate({'kind':'mcp','name':'x','config':config})

    def test_skill_preview_changes_and_remove_keeps_source(self):
        folder=self.base/'skill'; folder.mkdir(); source=folder/'SKILL.md'; source.write_text('# Demo\nDo something.',encoding='utf-8')
        entry_id=uuid.uuid4().hex; doc={'kind':'skill','name':'Demo','config':{'path':str(folder)}}
        self.ext.put(entry_id, {'revision':0,'document':doc})
        self.assertEqual(self.ext.inspect(entry_id,{})['status'],'unchanged')
        source.write_text('# Changed\n<script>text only</script>',encoding='utf-8')
        result=self.ext.inspect(entry_id,{}); self.assertEqual(result['status'],'changed'); self.assertIn('<script>',result['content'])
        self.ext.put(entry_id, {'revision':1,'document':doc})
        self.assertEqual(self.ext.inspect(entry_id,{})['status'],'unchanged')
        self.ext.delete(entry_id, {'revision':2}); self.assertTrue(source.is_file())

    def test_stop_blocks_mutations(self):
        self.core.stop('test')
        with self.assertRaises(CoreError): self.write('stopped.py', 'x')
        with self.assertRaises(CoreError): self.ext.put(uuid.uuid4().hex, {'revision':0,'document':self.mcp()})
        self.assertFalse((self.folder/'stopped.py').exists())


class ResourceHTTPTests(unittest.TestCase):
    def setUp(self):
        ResourceTests.setUp(self)
        spec=importlib.util.spec_from_file_location('resources_web',ROOT/'apps/web/server.py')
        web=importlib.util.module_from_spec(spec);spec.loader.exec_module(web)
        self.server=web.LocalChatServer(('127.0.0.1',0),self.core,object(),workspace=WorkspaceService(self.core))
        self.server.project_files=self.files
        self.server.extensions=self.ext
        threading.Thread(target=self.server.serve_forever,kwargs={'poll_interval':.01},daemon=True).start()
        self.addCleanup(self.server.server_close);self.addCleanup(self.server.shutdown)

    def call(self, path, body=None, nonce=True, origin=None):
        host='127.0.0.1:'+str(self.server.server_port);connection=http.client.HTTPConnection(host,timeout=10)
        headers={'Origin':origin or 'http://'+host}
        if nonce:headers['X-Jarvis-Nonce']=self.server.nonce
        if body is not None:headers['Content-Type']='application/json'
        try:
            connection.request('GET' if body is None else 'POST',path,json.dumps(body) if body is not None else None,headers)
            response=connection.getresponse();return response.status,json.loads(response.read())
        finally:connection.close()

    def test_nonce_origin_crud_conflict_and_no_execution(self):
        payload={'project_id':self.project['id'],'path':''}
        for path,body in [('/api/project-files/tree',payload),('/api/extensions',None),('/api/extensions/'+uuid.uuid4().hex,{'revision':0,'document':ResourceTests.mcp(self)})]:
            self.assertEqual(self.call(path,body,nonce=False)[0],403)
            self.assertEqual(self.call(path,body,origin='https://evil.test')[0],403)
        self.assertEqual(self.call('/api/project-files/tree',payload)[0],200)
        body={**payload,'path':'http.py','content':'你好','digest':None,'bom':False}
        self.assertEqual(self.call('/api/project-files/write',body)[0],200)
        self.assertEqual(self.call('/api/project-files/write',{**body,'content':'new'})[0],409)
        entry=uuid.uuid4().hex
        self.assertEqual(self.call('/api/extensions/'+entry,{'revision':0,'document':ResourceTests.mcp(self)})[0],200)
        self.assertEqual(self.call('/api/extensions/'+entry+'/inspect',{})[1]['status'],'configuration_valid')
        self.assertFalse(self.call('/api/extensions')[1]['runtime_available'])

    def test_reconnect_markup_keeps_origin_boundary_and_stale_writes_rejected(self):
        import re
        host='127.0.0.1:'+str(self.server.server_port)
        def get_page(path='/', origin=None):
            connection=http.client.HTTPConnection(host,timeout=10)
            try:
                connection.request('GET',path,headers={'Origin':origin or 'http://'+host})
                r=connection.getresponse();return r.status,r.read(),dict(r.getheaders())
            finally:connection.close()
        status,html,headers=get_page()
        self.assertEqual(status,200)
        token=re.search(rb'<meta name="jarvis-page-session" content="([A-Za-z0-9_-]+)">',html)[1].decode()
        self.assertEqual(token,self.server.nonce)
        self.assertEqual(headers['Cache-Control'],'no-store')
        self.assertNotIn('Access-Control-Allow-Origin',headers)
        self.assertEqual(get_page(origin='https://evil.test')[0],403)
        self.assertEqual(get_page('/workbench.js')[0],200)
        self.server.nonce='rotated-session-for-test'
        connection=http.client.HTTPConnection(host,timeout=10)
        body=json.dumps({'project_id':self.project['id'],'path':'stale.py','content':'bad','digest':None,'bom':False})
        try:
            connection.request('POST','/api/project-files/write',body,{'Origin':'http://'+host,'X-Jarvis-Nonce':token,'Content-Type':'application/json'})
            response=connection.getresponse();self.assertEqual(response.status,403);response.read()
        finally:connection.close()
        self.assertFalse((self.folder/'stale.py').exists())


if __name__=='__main__':unittest.main()
