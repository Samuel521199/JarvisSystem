"""Project metadata and reversible archive tests; no native programs launched."""
import http.client
from contextlib import closing
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

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'runtime/node-host'))
from jarvis_core.service import CoreService
from jarvis_core.workspace import WorkspaceService
from jarvis_core.conversations import ConversationStore
from jarvis_core.project_catalog import ProjectCatalog
from jarvis_core.policy import CoreError


class CatalogTests(unittest.TestCase):
    def setUp(self):
        tmp=tempfile.TemporaryDirectory();self.addCleanup(tmp.cleanup)
        self.base=Path(tmp.name);self.folder=self.base/'project & sample';self.folder.mkdir()
        self.file=self.folder/'keep.txt';self.file.write_text('keep',encoding='utf-8')
        self.core=CoreService(self.base/'data');self.core.initialize(self.folder)
        self.workspace=WorkspaceService(self.core);self.project=self.workspace.open_project({'path':str(self.folder)})
        self.conversations=ConversationStore(self.core);self.catalog=ProjectCatalog(self.core,self.workspace,self.conversations)

    def update(self,revision=0,**changes):
        return self.catalog.update(self.project['id'],{'revision':revision,'document':{**self.catalog.default(),**changes}})

    def chat(self,project=None):
        ident=uuid.uuid4().hex
        document={'title':'Test chat','project_id':project or self.project['id'],'context_note':'','messages':[{'role':'user','content':'hello','meta':'','short_meta':'','attachments_omitted':False,'incomplete':False}]}
        self.conversations.put(ident,{'revision':0,'document':document})
        return ident,document

    def test_edit_pin_section_remove_restore_survives_restart_and_preserves_roots(self):
        before=self.workspace.projects();saved=self.update(name='自定义项目',description='Notes',pinned=True,section='研发')
        self.assertEqual(saved['revision'],1)
        self.assertEqual(self.update(name='自定义项目',description='Notes',pinned=True,section='研发'),saved)
        with self.assertRaisesRegex(CoreError,'另一页面'):self.update(name='stale')
        saved=self.update(revision=1,name='自定义项目',removed=True)
        fresh=ProjectCatalog(self.core,self.workspace,self.conversations)
        self.assertTrue(fresh.snapshot()['profiles'][self.project['id']]['removed'])
        self.update(revision=2,name='自定义项目',removed=False)
        self.assertEqual(self.workspace.projects(),before)
        self.assertEqual(self.file.read_text(),'keep')
        self.assertEqual(self.project['id'],self.workspace.open_project({'path':str(self.folder)})['id'])

    def test_archive_explicit_snapshot_retry_restore_and_other_project_isolation(self):
        first,doc=self.chat();self.catalog.archive(self.project['id'],{'archived':True,'chat_ids':[first]})
        second,_=self.chat()
        self.catalog.archive(self.project['id'],{'archived':True,'chat_ids':[first]})
        self.assertEqual([r['id'] for r in self.catalog.snapshot()['archived_chats']],[first])
        # A normal autosave does not undo the archive flag or alter the body.
        self.conversations.put(first,{'revision':1,'document':{**doc,'title':'Updated'}})
        self.assertEqual(self.catalog.snapshot()['archived_chats'][0]['id'],first)
        other=self.base/'other';other.mkdir();p=self.workspace.open_project({'path':str(other)})
        foreign,_=self.chat(p['id'])
        with self.assertRaises(CoreError):self.catalog.archive(self.project['id'],{'archived':True,'chat_ids':[second,foreign]})
        self.assertEqual(len(self.catalog.snapshot()['archived_chats']),1)
        self.catalog.archive(self.project['id'],{'archived':False,'chat_ids':[first]})
        self.assertEqual(self.catalog.snapshot()['archived_chats'],[])
        self.assertEqual(len(self.conversations.list()['conversations']),3)
        self.assertEqual(self.file.read_text(),'keep')

    def test_strict_metadata_ids_sections_and_archive_validation(self):
        for changes in [{'name':'x'*121},{'name':'bad\nname'},{'section':'x'*65},{'description':'\x00'},{'pinned':1},{'removed':'true'}]:
            with self.subTest(changes=changes),self.assertRaises(CoreError):self.update(**changes)
        with self.assertRaises(CoreError):self.catalog.update(uuid.uuid4().hex,{'revision':0,'document':self.catalog.default()})
        for ids in [[{}],['../escape'],[uuid.uuid4().hex]*2,[],[uuid.uuid4().hex]]:
            if ids==[]:continue
            with self.subTest(ids=ids),self.assertRaises(CoreError):self.catalog.archive(self.project['id'],{'archived':True,'chat_ids':ids})
        with self.assertRaises(CoreError):self.catalog.update(self.project['id'],{'revision':False,'document':self.catalog.default()})
        with self.assertRaises(CoreError):self.catalog.reveal(self.project['id'],{'path':'elsewhere'})

    def test_reveal_uses_registered_root_without_shell_and_rejects_replaced_directory(self):
        with patch('jarvis_core.project_catalog.subprocess.Popen') as launch:
            self.assertEqual(self.catalog.reveal(self.project['id'],{})['status'],'opened')
            args,kwargs=launch.call_args
            self.assertEqual(args[0][-1],str(self.folder));self.assertFalse(kwargs['shell'])
        self.folder.rename(self.base/'moved');self.folder.mkdir()
        with patch('jarvis_core.project_catalog.subprocess.Popen') as launch:
            with self.assertRaises(CoreError):self.catalog.reveal(self.project['id'],{})
            launch.assert_not_called()

    def test_catalog_future_version_hardlink_and_core_stop_are_rejected(self):
        self.catalog.snapshot()
        with closing(sqlite3.connect(self.catalog.path)) as db:db.execute('PRAGMA user_version=999')
        with self.assertRaises(CoreError):self.catalog.snapshot()
        with closing(sqlite3.connect(self.catalog.path)) as db:db.execute('PRAGMA user_version=1')
        link=self.base/'catalog-link.db'
        try:os.link(self.catalog.path,link)
        except OSError:pass
        else:
            with self.assertRaises(CoreError):self.catalog.snapshot()
            link.unlink()
        self.core.stop('test')
        with self.assertRaises(CoreError):self.update(name='forbidden')
        with self.assertRaises(CoreError):self.catalog.archive(self.project['id'],{'archived':True,'chat_ids':[]})


class CatalogHTTPTests(CatalogTests):
    def setUp(self):
        super().setUp()
        spec=importlib.util.spec_from_file_location('project_catalog_web',ROOT/'apps/web/server.py');web=importlib.util.module_from_spec(spec);spec.loader.exec_module(web)
        self.server=web.LocalChatServer(('127.0.0.1',0),self.core,object(),workspace=self.workspace)
        self.server.project_catalog=self.catalog
        threading.Thread(target=self.server.serve_forever,kwargs={'poll_interval':.01},daemon=True).start()
        self.addCleanup(self.server.server_close);self.addCleanup(self.server.shutdown)

    def request(self,path,payload=None,nonce=True,origin=None):
        host='127.0.0.1:'+str(self.server.server_port);connection=http.client.HTTPConnection(host,timeout=5)
        headers={'Origin':origin or 'http://'+host}
        if nonce:headers['X-Jarvis-Nonce']=self.server.nonce
        if payload is not None:headers['Content-Type']='application/json'
        try:
            connection.request('GET' if payload is None else 'POST',path,json.dumps(payload) if payload is not None else None,headers)
            r=connection.getresponse();return r.status,r.read()
        finally:connection.close()

    def test_http_nonce_origin_edit_conflict_archive_and_assets(self):
        path='/api/workspace/projects/'+self.project['id']+'/edit';payload={'revision':0,'document':{**self.catalog.default(),'pinned':True}}
        for url,body in [('/api/workspace/organization',None),(path,payload)]:
            self.assertEqual(self.request(url,body,nonce=False)[0],403)
            self.assertEqual(self.request(url,body,origin='https://evil.test')[0],403)
        self.assertEqual(self.request(path,payload)[0],200)
        payload['document']['pinned']=False;self.assertEqual(self.request(path,payload)[0],409)
        chat,_=self.chat();archive='/api/workspace/projects/'+self.project['id']+'/archive'
        self.assertEqual(self.request(archive,{'archived':True,'chat_ids':[chat]})[0],200)
        status,body=self.request('/api/workspace/organization');self.assertEqual(status,200);self.assertEqual(json.loads(body)['archived_chats'][0]['id'],chat)
        self.assertEqual(self.request('/project_menu.js')[0],200)
        self.assertEqual(self.request('/project_menu.js?path=../../config')[0],404)


if __name__=='__main__':unittest.main()
