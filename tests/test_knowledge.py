"""Real bounded file retrieval, scope and freshness; no real model or credentials."""
from contextlib import closing
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

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'runtime/node-host'))
from jarvis_core.knowledge import KnowledgeStore, KnowledgeError, chunks, validate
from jarvis_core.service import CoreService
from jarvis_core.workspace import WorkspaceService
from jarvis_core.chat import ChatService
from jarvis_core.conversations import validate_document, ConversationError


class KnowledgeTests(unittest.TestCase):
    def setUp(self):
        tmp=tempfile.TemporaryDirectory();self.addCleanup(tmp.cleanup);self.base=Path(tmp.name)
        self.folder=self.base/'project';self.folder.mkdir();(self.folder/'docs').mkdir()
        self.file=self.folder/'docs/design.md'
        self.file.write_text('# 系统设计\n总览。\n## 离线部署\n断网时使用本机资料。\n## 状态\n此项为 proposed，尚未实现。\n',encoding='utf-8')
        self.core=CoreService(self.base/'data');self.core.initialize(self.folder)
        self.project=WorkspaceService(self.core).open_project({'path':str(self.folder)})['id']
        self.store=KnowledgeStore(self.core);self.id=uuid.uuid4().hex
        self.ctx={'enabled':True,'project_id':self.project}

    def put(self,providers=None,revision=0,path='docs/design.md',ident=None):
        return self.store.put(ident or self.id,{'revision':revision,'document':{'project_id':self.project,'path':path,'providers':providers or []}})

    def view(self,provider='local',query='离线部署',**kwargs):
        return self.store.context(self.store.snapshot(self.ctx,provider),query,**kwargs)

    def test_registration_restart_retry_and_no_body_copy(self):
        first=self.put();self.assertEqual(self.put(),first)
        self.assertEqual(KnowledgeStore(self.core).list(self.project)['sources'],[first])
        self.assertNotIn('断网时'.encode(),self.store.path.read_bytes())
        self.assertEqual(self.put(['vertex'],1)['revision'],2)
        with self.assertRaises(KnowledgeError):self.put(['openai'],1)
        with self.assertRaises(KnowledgeError):self.put(ident=uuid.uuid4().hex)

    def test_sections_chinese_citations_and_literal_preview(self):
        self.put();text,result=self.view(query='断网时如何离线部署')
        self.assertIn('断网时使用本机资料',text)
        cite=result['citations'][0];self.assertEqual(cite['start_line'],3);self.assertEqual(cite['end_line'],4)
        validate('citations',result['citations'])
        read=self.store.read_excerpt({'project_id':self.project,**{k:cite[k] for k in ('reference','start_line','end_line')}})
        self.assertEqual(read['text'],'## 离线部署\n断网时使用本机资料。')
        _,missing=self.view(query='zzzzUnmatched');self.assertEqual(missing['citations'],[])
        self.assertIn('proposed',self.view(query='状态')[0])

    def test_provider_scope_precedes_disk_reads(self):
        self.put(['vertex'])
        with patch.object(self.store,'read_file',side_effect=AssertionError('private read')):
            self.assertEqual(self.view('openai')[1]['citations'],[])
            self.assertFalse(self.store.snapshot(dict(self.ctx,enabled=False),'local')['documents'])
        self.assertTrue(self.view('vertex')[1]['citations'])
        other=self.base/'other';other.mkdir();pid=WorkspaceService(self.core).open_project({'path':str(other)})['id']
        self.assertEqual(self.store.snapshot(dict(self.ctx,project_id=pid),'local')['documents'],[])

    def test_file_digest_detects_change_even_same_stat_size_and_time(self):
        self.put();old=self.view()[1]['citations'][0];before=self.file.stat()
        self.file.write_text(self.file.read_text(encoding='utf-8').replace('本机','离线'),encoding='utf-8')
        os.utime(self.file,ns=(before.st_atime_ns,before.st_mtime_ns))
        self.assertNotEqual(self.view()[1]['references'][0]['digest'],old['reference']['digest'])
        with self.assertRaises(KnowledgeError):self.store.read_excerpt({'project_id':self.project,**{k:old[k] for k in ('reference','start_line','end_line')}})

    def test_remove_tombstone_preserves_original_and_blocks_stale_save(self):
        original=self.file.read_bytes();self.put()
        self.store.delete(self.id,{'revision':1});self.store.delete(self.id,{'revision':1})
        self.assertEqual(self.file.read_bytes(),original);self.assertEqual(self.store.list(self.project)['sources'],[])
        with self.assertRaises(KnowledgeError):self.put(revision=1)

    def test_missing_sources_do_not_reuse_content(self):
        self.put();self.file.unlink();snapshot=self.store.snapshot(self.ctx,'local')
        self.assertFalse(snapshot['documents']);self.assertEqual(len(snapshot['issues']),1)
        self.assertEqual(self.store.context(snapshot,'离线')[1]['citations'],[])

    def test_paths_encoding_hardlinks_and_limits(self):
        for path in ('../outside.md','/absolute.md','C:/outside.md','docs/../design.md','docs/design.md:stream','.git/readme.md','node_modules/a.md','docs/x.json','docs/a?.md'):
            with self.subTest(path=path),self.assertRaises(KnowledgeError):self.put(path=path)
        self.file.write_bytes(b'\xff\xfe bad')
        with self.assertRaises(KnowledgeError):self.put()
        self.file.write_bytes(b'x'*(256*1024+1))
        with self.assertRaises(KnowledgeError):self.put()
        self.file.write_bytes(b'valid')
        link=self.folder/'alias.md';os.link(self.file,link)
        with self.assertRaises(KnowledgeError):self.put(path='alias.md')

    def test_schema_unknown_database_and_registration_limits(self):
        for value in ({'enabled':'yes','project_id':self.project},{'enabled':True,'project_id':self.project,'all_projects':True}):
            with self.assertRaises(KnowledgeError):validate('context',value)
        self.put();(self.folder/'b.txt').write_text('text',encoding='utf-8')
        with patch('jarvis_core.knowledge.MAX_SOURCES',1):
            with self.assertRaises(KnowledgeError):self.put(path='b.txt',ident=uuid.uuid4().hex)
        with closing(sqlite3.connect(self.store.path)) as db:db.execute('PRAGMA user_version=99')
        with self.assertRaises(KnowledgeError):self.store.list(self.project)
        with closing(sqlite3.connect(self.store.path)) as db:self.assertEqual(db.execute('PRAGMA user_version').fetchone()[0],99)

    def test_history_invalidated_on_revision_digest_scope_and_removal(self):
        self.put(['vertex']);snapshot=self.store.snapshot(self.ctx,'vertex');ref=snapshot['documents'][0]['reference']
        history=[{'role':'user','content':'old'},{'role':'assistant','content':'private'}];refs=[[],[ref]]
        self.assertEqual(self.store.filter_history(history,refs,snapshot)[0],history)
        self.assertEqual(self.store.filter_history(history,refs,self.store.snapshot(self.ctx,'openai'))[0],[])
        self.file.write_text('# 离线部署\n新的内容\n',encoding='utf-8')
        self.assertEqual(self.store.filter_history(history,refs,self.store.snapshot(self.ctx,'vertex'))[0],[])
        self.put(['vertex','openai'],1)
        self.assertEqual(self.store.filter_history(history,refs,self.store.snapshot(self.ctx,'vertex'))[0],[])
        self.store.delete(self.id,{'revision':2})
        self.assertEqual(self.store.filter_history(history,refs,self.store.snapshot(self.ctx,'local'))[0],[])

    def test_budgets_do_not_slice_evidence_or_overread(self):
        self.put();self.assertEqual(self.view(max_bytes=20)[1]['citations'],[])
        with patch('jarvis_core.knowledge.MAX_READ_BYTES',1):
            with patch.object(self.store,'read_file',side_effect=AssertionError('over budget')):
                self.assertEqual(self.store.snapshot(self.ctx,'local')['issues'][0]['code'],'read_budget')
        for chunk in chunks('a\nb\n## title\nc'):
            self.assertEqual(chunk['text'],'\n'.join('a\nb\n## title\nc'.splitlines()[chunk['start_line']-1:chunk['end_line']]))
        with patch('jarvis_core.knowledge.MAX_CHUNKS',1):
            self.assertEqual(self.view()[1]['issues'][0]['code'],'chunk_budget')

    def test_chat_fallback_history_and_input_budget(self):
        self.put(['vertex']);ref=self.view()[1]['references'][0]
        config=json.loads((ROOT/'config/model-profiles/providers.json').read_text(encoding='utf-8'))
        config.update(default_provider='vertex',automatic_fallback=True,fallback_order=['openai'])
        path=self.base/'providers.json';path.write_text(json.dumps(config),encoding='utf-8');chat=ChatService(self.core,path)
        calls=[]
        def probe(conf,provider,message,*args,**kwargs):
            calls.append((provider,message,kwargs))
            return {'status':'FAILED','error_category':'quota_exhausted','outcome_uncertain':False} if provider=='vertex' else {'status':'SUCCEEDED','text':'ok','outcome_uncertain':False}
        with patch('jarvis_core.chat.gateway.probe',side_effect=probe):
            result=chat.reply('离线部署',knowledge_context=self.ctx,history=[{'role':'user','content':'previous'},{'role':'assistant','content':'SOURCE_PRIVATE'}],history_knowledge=[[],[ref]])
        self.assertEqual(result['status'],'SUCCEEDED');self.assertIn('断网时',calls[0][1]);self.assertNotIn('断网时',calls[1][1]);self.assertEqual(calls[1][2]['history'],[])
        self.assertEqual(result['history_info']['kept_indexes'],[])
        with patch('jarvis_core.chat.gateway.probe',return_value={'status':'SUCCEEDED','text':'ok','outcome_uncertain':False}) as gateway:
            result=chat.reply('离线部署'+'x'*2900,provider='local',knowledge_context=self.ctx)
        self.assertEqual(result['status'],'SUCCEEDED')
        self.assertLessEqual(len(gateway.call_args.args[2].encode())+len(gateway.call_args.kwargs['instructions'].encode()),4096)

    def test_archive_metadata_validates_and_keeps_no_excerpt_copy(self):
        self.put();_,result=self.view()
        row={'role':'assistant','content':'answer','meta':'','short_meta':'','attachments_omitted':False,'incomplete':False,'knowledge_refs':result['references'],'knowledge_citations':result['citations']}
        doc={'title':'test','project_id':self.project,'context_note':'','messages':[row]}
        encoded,_,_=validate_document(doc);self.assertNotIn('断网时',encoded)
        row['knowledge_citations'][0]['text']='hidden copy'
        with self.assertRaises(ConversationError):validate_document(doc)

    def test_http_requires_nonce_origin_and_only_registered_read(self):
        sys.path.insert(0,str(ROOT/'adapters/computer-use'))
        spec=importlib.util.spec_from_file_location('knowledge_test_web',ROOT/'apps/web/server.py');web=importlib.util.module_from_spec(spec);spec.loader.exec_module(web)
        server=web.create_server(core=self.core,chat=ChatService(self.core),port=0)
        thread=threading.Thread(target=server.serve_forever,kwargs={'poll_interval':.01},daemon=True);thread.start()
        def request(method,path,payload=None,token=True,origin=True):
            connection=http.client.HTTPConnection('127.0.0.1',server.server_port,timeout=3)
            headers={'Content-Type':'application/json'}
            if token:headers['X-Jarvis-Nonce']=server.nonce
            if origin:headers['Origin']='http://127.0.0.1:'+str(server.server_port)
            connection.request(method,path,None if payload is None else json.dumps(payload),headers)
            response=connection.getresponse();result=(response.status,json.loads(response.read()));connection.close();return result
        try:
            self.assertEqual(request('GET','/api/knowledge?project_id='+self.project,token=False)[0],403)
            self.assertEqual(request('POST','/api/knowledge/search',{'project_id':self.project,'query':'离线'},origin=False)[0],403)
            payload={'revision':0,'document':{'project_id':self.project,'path':'docs/design.md','providers':[]}}
            self.assertEqual(request('POST','/api/knowledge/'+self.id,payload)[0],200)
            code,result=request('POST','/api/knowledge/search',{'project_id':self.project,'query':'离线部署'});self.assertEqual(code,200);self.assertTrue(result['citations'])
            self.assertEqual(request('GET','/api/knowledge?project_id='+self.project+'&project_id='+self.project)[0],400)
            self.assertEqual(request('POST','/api/knowledge/'+self.id+'/delete',{'revision':1})[0],200)
        finally:server.shutdown();server.server_close();thread.join(3)
