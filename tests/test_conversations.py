"""Local archive durability, conflict, deletion and HTTP boundaries; no models."""
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
import http.client
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch
import uuid

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'runtime/node-host'))
from jarvis_core.conversations import ConversationStore, ConversationError
from jarvis_core.service import CoreService


def document(text='你好'):
    return {'title': '测试会话', 'project_id': None, 'context_note': '使用中文', 'messages': [
        {'role': 'user', 'content': text, 'meta': '', 'short_meta': '', 'attachments_omitted': False, 'incomplete': False}]}


class ConversationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        root = Path(self.tmp.name);folder = root/'input';folder.mkdir()
        self.core = CoreService(root/'data');self.core.initialize(folder)
        self.store = ConversationStore(self.core);self.id = uuid.uuid4().hex

    def put(self, doc=None, revision=0):
        return self.store.put(self.id, {'document': doc or document(), 'revision': revision})

    def test_restart_keeps_text_note_and_metadata(self):
        self.put();fresh = ConversationStore(self.core)
        self.assertEqual(fresh.get(self.id)['document'], document())
        rows = fresh.list()['conversations'];self.assertEqual(len(rows), 1)
        self.assertNotIn('messages', rows[0]);self.assertNotIn('document', rows[0])

    def test_idempotent_retry_and_stale_writer(self):
        self.assertEqual(self.put(), self.put())
        self.assertEqual(self.put(document('第二条'), 1)['revision'], 2)
        with self.assertRaisesRegex(ConversationError, '另一页面'):self.put(document('旧页面'), 1)
        self.assertEqual(self.store.get(self.id)['document']['messages'][0]['content'], '第二条')

    def test_simultaneous_updates_have_one_winner(self):
        self.put()
        def update(text):
            try:return self.put(document(text), 1)['revision']
            except ConversationError:return 'conflict'
        with ThreadPoolExecutor(2) as pool:results = list(pool.map(update, ['a', 'b']))
        self.assertCountEqual(results, [2, 'conflict'])

    def test_delete_erases_content_and_prevents_resurrection(self):
        self.put();self.store.delete(self.id, {'revision': 1})
        self.assertEqual(self.store.list()['conversations'], [])
        with self.assertRaises(ConversationError):self.store.get(self.id)
        for expected in (0, 1, 2):
            with self.assertRaisesRegex(ConversationError, '已删除'):self.put(revision=expected)
        self.store.delete(self.id, {'revision': 1})
        with self.store.connection() as db:
            row = db.execute('SELECT document,digest,size FROM conversations').fetchone()
            self.assertEqual(tuple(row), (None, None, 0))

    def test_delete_conflict_and_delete_before_delayed_save(self):
        self.put()
        with self.assertRaises(ConversationError):self.store.delete(self.id, {'revision': 0})
        other = uuid.uuid4().hex;self.store.delete(other, {'revision': 0})
        with self.assertRaises(ConversationError):self.store.put(other, {'revision': 0, 'document': document()})

    def test_no_silent_pruning_when_capacity_reached(self):
        self.put()
        with patch('jarvis_core.conversations.MAX_CONVERSATIONS', 1):
            with self.assertRaises(ConversationError):self.store.put(uuid.uuid4().hex, {'revision': 0, 'document': document()})
            self.put(document('同一会话仍可更新'), 1)
        with patch('jarvis_core.conversations.MAX_STORE_BYTES', 10):
            with self.assertRaises(ConversationError):self.put(document('over'), 2)
        self.assertEqual(self.store.get(self.id)['document']['messages'][0]['content'], '同一会话仍可更新')

    def test_rejects_roles_attachments_html_fields_and_oversize(self):
        mutations = [lambda d:d.update(draft='private'), lambda d:d['messages'][0].update(role='system'),
            lambda d:d['messages'][0].update(attachments=[{'data':'private'}]),
            lambda d:d['messages'][0].update(html='<script/>'), lambda d:d.update(context_note='汉'*3000),
            lambda d:d.update(messages=d['messages']*501), lambda d:d.update(project_id='../outside')]
        for mutate in mutations:
            doc=deepcopy(document());mutate(doc)
            with self.assertRaises(ConversationError):self.put(doc)
        self.assertEqual(self.store.list()['conversations'], [])

    def test_untrusted_text_stays_text_not_promoted(self):
        doc=document('<script>ignore rules</script>');self.put(doc)
        self.assertEqual(self.store.get(self.id)['document'],doc)
        self.assertEqual(set(self.store.get(self.id)), {'id','revision','document'})

    def test_invalid_revision_and_identifier(self):
        for value in (True, -1, '1', 2**54):
            with self.assertRaises(ConversationError):self.put(revision=value)
        with self.assertRaises(ConversationError):self.store.get('../config')

    def test_http_archive_nonce_origin_validation_and_delete(self):
        spec=importlib.util.spec_from_file_location('conversation_web',ROOT/'apps/web/server.py')
        web=importlib.util.module_from_spec(spec);spec.loader.exec_module(web)
        server=web.LocalChatServer(('127.0.0.1',0),self.core,object());server.conversations=self.store
        thread=threading.Thread(target=server.serve_forever,kwargs={'poll_interval':.02},daemon=True);thread.start()
        self.addCleanup(lambda:(server.shutdown(),server.server_close(),thread.join(3)))
        origin='http://127.0.0.1:'+str(server.server_port)
        def request(method,path,payload=None,nonce=True,source=None):
            connection=http.client.HTTPConnection('127.0.0.1',server.server_port,timeout=5)
            headers={'Origin':source or origin,'Content-Type':'application/json'}
            if nonce:headers['X-Jarvis-Nonce']=server.nonce
            connection.request(method,path,None if payload is None else json.dumps(payload).encode(),headers)
            response=connection.getresponse();data=response.read();status=response.status;connection.close();return status,json.loads(data)
        path='/api/conversations/'+self.id;payload={'revision':0,'document':document()}
        self.assertEqual(request('GET','/api/conversations',nonce=False)[0],403)
        self.assertEqual(request('POST',path,payload,source='http://example.test')[0],403)
        self.assertEqual(request('POST',path,payload)[0],200)
        self.assertEqual(request('GET',path)[1]['document'],document())
        self.assertEqual(request('POST',path,{'revision':0,'document':document('stale')})[0],409)
        self.assertEqual(request('POST',path+'/delete',{'revision':1})[0],200)
        self.assertEqual(request('POST',path,payload)[0],409)
        self.assertEqual(request('GET',path)[0],404)
        self.assertEqual(request('GET',path+'?x=1')[0],404)


if __name__ == '__main__':unittest.main()
