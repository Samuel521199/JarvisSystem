"""Explicit memory durability, scope, forget and route provenance; no real models."""
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
import http.client
import importlib.util
import json
from pathlib import Path
import sqlite3
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch
import uuid

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'runtime/node-host'))
from jarvis_core.memory import MemoryStore, MemoryError, validate
from jarvis_core.service import CoreService
from jarvis_core.workspace import WorkspaceService
from jarvis_core.chat import ChatService
from jarvis_core.conversations import ConversationStore


def document(content='请用简洁中文回答', project=None, providers=None):
    return {'title': '回复偏好', 'content': content, 'project_id': project, 'providers': providers or []}


class MemoryTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name);self.folder = self.base/'sample';self.folder.mkdir()
        self.core = CoreService(self.base/'data');self.core.initialize(self.folder)
        self.store = MemoryStore(self.core);self.id = uuid.uuid4().hex
        workspace = WorkspaceService(self.core)
        self.project = workspace.open_project({'path': str(self.folder)})['id']
        other = self.base/'other';other.mkdir()
        self.other = workspace.open_project({'path': str(other)})['id']

    def put(self, doc=None, revision=0, ident=None):
        return self.store.put(ident or self.id, {'revision': revision, 'document': doc or document()})

    def context(self, provider='local', project=None, **kwargs):
        return self.store.context({'enabled': True, 'project_id': project}, provider, **kwargs)

    def test_restart_correction_receipts_and_literal_chinese_search(self):
        self.put(document('支持离线记忆，路径 foo_bar。'))
        self.assertEqual(len(MemoryStore(self.core).list(query='离线')['facts']), 1)
        self.assertEqual(len(self.store.list(query='FOO_BAR')['facts']), 1)
        self.assertEqual(self.store.list(query='%')['facts'], [])
        self.put(document('已经纠正'), 1)
        self.assertEqual(self.store.list(query='离线')['facts'], [])
        with self.store.connection() as db:
            receipts = db.execute('SELECT operation,source FROM receipts').fetchall()
            self.assertEqual([tuple(r) for r in receipts], [('remember','owner_explicit'),('correct','owner_explicit')])
        self.assertEqual(self.store.list()['facts'][0]['revision'], 2)

    def test_retry_conflict_and_concurrent_writers(self):
        first = self.put();self.assertEqual(first, self.put())
        def update(text):
            try:return self.put(document(text), 1)['revision']
            except MemoryError:return 'conflict'
        with ThreadPoolExecutor(2) as pool:results = list(pool.map(update, ['版本甲','版本乙']))
        self.assertCountEqual(results,[2,'conflict'])
        with self.assertRaises(MemoryError):self.put(document('迟到'),0)

    def test_forget_erases_current_search_digest_and_blocks_resurrection(self):
        self.put(document('PRIVATE_OLD_BODY'))
        self.store.delete(self.id, {'revision':1})
        self.assertEqual(self.store.list()['facts'], [])
        self.assertEqual(self.context()[0], '')
        with self.store.connection() as db:
            row = db.execute('SELECT document,digest,search_text,project_id FROM facts').fetchone()
            self.assertEqual(tuple(row),(None,None,None,None))
        self.assertNotIn(b'PRIVATE_OLD_BODY',self.store.path.read_bytes())
        for revision in (0,1,2):
            with self.assertRaisesRegex(MemoryError,'已忘记'):self.put(revision=revision)
        self.assertEqual(self.store.delete(self.id,{'revision':1})['status'],'forgotten')

    def test_scope_and_provider_filter_before_budget(self):
        self.put(document('GLOBAL'))
        self.put(document('PROJECT_A', self.project, ['vertex']),ident=uuid.uuid4().hex)
        self.put(document('PROJECT_B', self.other, ['vertex']),ident=uuid.uuid4().hex)
        local,_ = self.context(project=self.project)
        self.assertIn('GLOBAL',local);self.assertIn('PROJECT_A',local);self.assertNotIn('PROJECT_B',local)
        cloud,_ = self.context('vertex',self.project)
        self.assertNotIn('GLOBAL',cloud);self.assertIn('PROJECT_A',cloud);self.assertNotIn('PROJECT_B',cloud)
        self.assertEqual(self.context('openai',self.project)[0],'')
        self.assertEqual(self.store.context({'enabled':False,'project_id':self.project},'local')[0],'')

    def test_limits_and_whole_fact_budget(self):
        self.put(document('长'*500))
        text,report = self.context(max_bytes=100)
        self.assertEqual(text,'');self.assertEqual(report['omitted'],1)
        with patch('jarvis_core.memory.MAX_FACTS',1):
            with self.assertRaises(MemoryError):self.put(ident=uuid.uuid4().hex)
            self.put(document('更新'),1)
        with patch('jarvis_core.memory.MAX_RECEIPTS',0):
            with self.assertRaises(MemoryError):self.put(document('再更新'),2)
            self.store.delete(self.id,{'revision':2})

    def test_schema_rejects_unknown_fields_and_unknown_projects(self):
        invalid = [dict(document(),project_id='../escape'),dict(document(),providers=['auto']),
                   dict(document(),providers=['vertex','vertex']),dict(document(),content=' '),
                   dict(document(),title='t'*121),dict(document(),content='x'*2049),
                   dict(document(),source='model_confirmed'),dict(document(),project_id=uuid.uuid4().hex)]
        for doc in invalid:
            with self.assertRaises(MemoryError):self.put(doc)
        for version in (True,-1,'1'):
            with self.assertRaises(MemoryError):self.put(revision=version)
        self.assertFalse(self.store.path.exists())

    def test_incompatible_store_is_not_rewritten(self):
        self.put()
        with closing(sqlite3.connect(self.store.path)) as db:db.execute('PRAGMA user_version=9')
        with self.assertRaisesRegex(MemoryError,'不兼容'):self.store.list()
        with closing(sqlite3.connect(self.store.path)) as db:self.assertEqual(db.execute('PRAGMA user_version').fetchone()[0],9)

    def test_history_fences_scope_provider_correction_forget_and_disabled_mode(self):
        self.put(document('PRIVATE',self.project,['vertex']))
        rows=[{'role':'user','content':'问候'},{'role':'assistant','content':'你好'},
              {'role':'user','content':'回忆'},{'role':'assistant','content':'PRIVATE'}]
        refs=[[],[],[],[{'id':self.id,'revision':1}]];ctx={'enabled':True,'project_id':self.project}
        self.assertEqual(len(self.store.filter_history(rows,refs,ctx,'vertex')[0]),4)
        self.assertEqual(self.store.filter_history(rows,refs,ctx,'openai')[0],rows[:2])
        self.assertEqual(self.store.filter_history(rows,refs,dict(ctx,enabled=False),'local')[0],rows[:2])
        self.assertEqual(self.store.filter_history(rows,refs,dict(ctx,project_id=self.other),'local')[0],rows[:2])
        self.put(document('NEW',self.project,['vertex']),1)
        self.assertEqual(self.store.filter_history(rows,refs,ctx,'vertex')[0],rows[:2])
        self.store.delete(self.id,{'revision':2})
        self.assertEqual(self.store.filter_history(rows,refs,ctx,'local')[0],rows[:2])

    def test_chat_fallback_rechecks_memory_and_history(self):
        config=json.loads((ROOT/'config/model-profiles/providers.json').read_text(encoding='utf-8'))
        config.update(default_provider='vertex',automatic_fallback=True,fallback_order=['openai'])
        path=self.base/'providers.json';path.write_text(json.dumps(config),encoding='utf-8')
        chat=ChatService(self.core,path)
        self.put(document('ROUTE_PRIVATE',providers=['vertex']))
        self.put(document('BOTH_ALLOWED',providers=['vertex','openai']),ident=uuid.uuid4().hex)
        calls=[]
        def probe(conf,provider,message,*args,**kwargs):
            calls.append((provider,message,kwargs['history']))
            if provider=='vertex':return {'status':'FAILED','error_category':'quota_exhausted','outcome_uncertain':False}
            return {'status':'SUCCEEDED','text':'ok','outcome_uncertain':False}
        history=[{'role':'user','content':'previous'},{'role':'assistant','content':'ROUTE_PRIVATE'}]
        with patch('jarvis_core.chat.gateway.probe',side_effect=probe):
            result=chat.reply('继续',history=history,memory_context={'enabled':True,'project_id':None},history_memory=[[],[{'id':self.id,'revision':1}]])
        self.assertEqual(result['status'],'SUCCEEDED')
        self.assertIn('ROUTE_PRIVATE',calls[0][1]);self.assertIn('BOTH_ALLOWED',calls[1][1])
        self.assertNotIn('ROUTE_PRIVATE',calls[1][1]);self.assertEqual(calls[1][2],[])
        self.assertEqual(result['history_info']['memory']['dropped_history_messages'],2)
        self.assertEqual(result['history_info']['context']['kept_indexes'],[])
        validate('references',result['history_info']['memory']['references'])

    def test_chat_memory_failure_is_visible_and_no_prompt_dispatched(self):
        chat=ChatService(self.core)
        with patch.object(chat.memory,'context',side_effect=sqlite3.DatabaseError),patch('jarvis_core.chat.gateway.probe') as gateway:
            result=chat.reply('hello',provider='local',memory_context={'enabled':True,'project_id':None})
        self.assertEqual(result['error_category'],'memory_unavailable');gateway.assert_not_called()

    def test_archive_retains_only_memory_references_not_another_fact_copy(self):
        from jarvis_core.conversations import validate_document
        row={'role':'assistant','content':'回答','meta':'','short_meta':'','attachments_omitted':False,'incomplete':False,
             'memory_refs':[{'id':self.id,'revision':1}]}
        doc={'title':'test','project_id':None,'context_note':'','messages':[row]}
        validate_document(doc)
        store=ConversationStore(self.core);store.put(self.id,{'revision':0,'document':doc})
        self.assertEqual(store.get(self.id)['document'],doc)
        row['memory_refs'][0]['content']='hidden'
        with self.assertRaises(ValueError):validate_document(doc)

    def test_http_nonce_origin_scope_conflict_and_delete(self):
        spec=importlib.util.spec_from_file_location('memory_web',ROOT/'apps/web/server.py')
        web=importlib.util.module_from_spec(spec);spec.loader.exec_module(web)
        server=web.LocalChatServer(('127.0.0.1',0),self.core,object());server.memory=self.store
        thread=threading.Thread(target=server.serve_forever,kwargs={'poll_interval':.02},daemon=True);thread.start()
        self.addCleanup(lambda:(server.shutdown(),server.server_close(),thread.join(3)))
        origin='http://127.0.0.1:'+str(server.server_port)
        def req(method,path,payload=None,nonce=True,source=None):
            connection=http.client.HTTPConnection('127.0.0.1',server.server_port,timeout=5)
            headers={'Origin':source or origin,'Content-Type':'application/json'}
            if nonce:headers['X-Jarvis-Nonce']=server.nonce
            connection.request(method,path,None if payload is None else json.dumps(payload).encode(),headers)
            response=connection.getresponse();body=response.read();code=response.status;connection.close();return code,json.loads(body)
        path='/api/memory/'+self.id
        self.assertEqual(req('GET','/api/memory',nonce=False)[0],403)
        self.assertEqual(req('POST',path,{},source='http://example.test')[0],403)
        self.assertEqual(req('POST',path,{'revision':0,'document':document()})[0],200)
        self.assertEqual(req('GET','/api/memory?q=%E7%AE%80%E6%B4%81')[1]['facts'][0]['id'],self.id)
        self.assertEqual(req('GET','/api/memory?extra=1')[0],400)
        self.assertEqual(req('POST',path,{'revision':0,'document':document('stale')})[0],409)
        self.assertEqual(req('POST',path+'/delete',{'revision':1})[0],200)
        self.assertEqual(req('POST',path,{'revision':0,'document':document()})[0],409)


if __name__=='__main__':unittest.main()
