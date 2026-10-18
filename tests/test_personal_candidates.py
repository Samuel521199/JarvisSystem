"""Candidate review writes only after confirmation; source, retry and scope tests."""
import copy
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
sys.path[:0] = [str(ROOT/'tests'), str(ROOT/'runtime/node-host')]
from jarvis_core.service import CoreService
from jarvis_core.personal_candidates import PersonalCandidates, extract
from jarvis_core.memory import MemoryStore, MemoryError
from jarvis_core.continuity import ContinuityStore
from jarvis_core.chat import ChatService
from jarvis_core.conversations import ConversationStore
from jarvis_core.workspace import WorkspaceService
from test_conversations import document


class CandidateTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name); (self.base/'source').mkdir()
        self.core = CoreService(self.base/'data'); self.core.initialize(self.base/'source')
        self.service = PersonalCandidates(self.core); self.archives = ConversationStore(self.core)
        self.cid = uuid.uuid4().hex; self.project = None
        self.doc = document(); self.doc['messages'][0]['content'] = '我平时喜欢无糖茶。我们下次继续讨论旅行安排。'
        self.archives.put(self.cid, {'revision': 0, 'document': self.doc})
        self.query = {'source': {'conversation_id': self.cid, 'message_index': 0}, 'project_id': None}

    def payload(self, index=0):
        data = self.service.suggest(self.query)
        return {k:data[k] for k in ('source', 'project_id', 'source_digest')} | {'candidate':data['candidates'][index], 'scope':'current'}

    def test_rule_positive_and_quoted_hypothetical_sensitive_negative(self):
        for text in ('我更喜欢简洁回答', '以后叫我老王', '我习惯晚上学习', '我不喜欢甜食', '下次我们继续讨论方案', '我还没完成读书笔记'):
            self.assertEqual(len(extract(text)), 1, text)
        for text in ('假如我喜欢咖啡', '他说我喜欢咖啡', '“我喜欢咖啡”', 'NPC 我喜欢咖啡', '我喜欢咖啡，但不要记住', '记住：密钥=sk-secret', '今天下雨了', '```我喜欢茶```', '请替我订机票'):
            self.assertEqual(extract(text), [], text)
        self.assertEqual(extract('我喜欢茶。'*10).__len__(), 3)

    def test_preview_has_no_write_or_model_and_confirm_defaults_local(self):
        with patch('jarvis_core.chat.gateway.probe') as model:
            data = self.service.suggest(self.query)
            self.assertEqual(len(data['candidates']), 2)
            self.assertFalse((self.core.data_dir/'memory.db').exists())
            self.assertFalse((self.core.data_dir/'continuity.db').exists())
            result = self.service.confirm(self.payload())
            self.assertTrue(result['receipt']['committed']); model.assert_not_called()
        row = MemoryStore(self.core).list()['facts'][0]
        self.assertEqual(row['document']['providers'], [])
        self.assertEqual(row['document']['content'], '我平时喜欢无糖茶')

    def test_questions_and_one_off_instructions_are_not_durable_preferences(self):
        for text in ('我喜欢喝茶吗？', '我喜欢喝茶吗', '我希望你这一次回答只写三行。',
                     '我希望你今天讲详细一点', '我喜欢今天的菜单'):
            self.assertEqual(extract(text), [], text)
        for text in ('我希望你以后用中文解释代码', '我通常喜欢简短回答', '我不喜欢咖啡'):
            self.assertEqual(len(extract(text)), 1, text)
        self.assertEqual([x['kind'] for x in extract('我希望你本次简短回答。明天继续讨论计划。')], ['continuity'])

    def test_edit_confirmation_replay_after_forget_does_not_resurrect(self):
        body = self.payload(); body['candidate'].update(title='饮品', content='喜欢黑咖啡')
        first = self.service.confirm(body)
        memory = MemoryStore(self.core); memory.command('forget', first['receipt']['id'], None, request_id=uuid.uuid4().hex)
        replay = PersonalCandidates(CoreService(self.core.data_dir)).confirm(body)
        self.assertTrue(replay['receipt']['replayed']); self.assertEqual(memory.list()['facts'], [])

    def test_same_title_conflict_does_not_overwrite(self):
        self.service.confirm(self.payload())
        other = self.payload(); other['candidate']['content'] = '喜欢糖'
        with self.assertRaises(MemoryError) as exc: self.service.confirm(other)
        self.assertEqual(exc.exception.code, 'memory_conflict')
        self.assertIn('无糖茶', MemoryStore(self.core).list()['facts'][0]['document']['content'])

    def test_note_source_is_explicitly_confirmed_and_ordinary_chat_deletion_invalidates(self):
        result = self.service.confirm(self.payload(1)); store = ContinuityStore(self.core)
        row = store.list()['records'][0]
        self.assertTrue(row['document']['source']['owner_confirmed_candidate'])
        ctx = {'enabled': True, 'ids': [row['id']]}
        self.assertEqual(len(store.snapshot(ctx, None, 'local')[0]), 1)
        self.assertEqual(store.snapshot(ctx, None, 'vertex')[0], [])
        self.archives.delete(self.cid, {'revision':1})
        self.assertEqual(store.snapshot(ctx, None, 'local')[0], [])
        self.assertTrue(result['receipt']['committed'])

    def test_source_change_missing_scope_and_assistant_rejected(self):
        body = self.payload(); self.doc['messages'][0]['content'] = '我喜欢咖啡'
        self.archives.put(self.cid, {'revision':1, 'document':self.doc})
        with self.assertRaises(MemoryError) as exc: self.service.confirm(body)
        self.assertEqual(exc.exception.code, 'candidate_source_changed')
        for query in ({**self.query,'source':{'conversation_id':uuid.uuid4().hex,'message_index':0}},
                      {**self.query,'source':{'conversation_id':self.cid,'message_index':1}},
                      {**self.query,'project_id':uuid.uuid4().hex}):
            with self.assertRaises(MemoryError): self.service.suggest(query)

    def test_project_fact_scope_choice_and_note_cannot_be_promoted(self):
        project = WorkspaceService(self.core).open_project({'path':str(self.base/'source')})['id']
        self.doc['project_id'] = project; self.archives.put(self.cid, {'revision':1, 'document':self.doc}); self.query['project_id'] = project
        body = self.payload(); self.service.confirm(body)
        self.assertEqual(MemoryStore(self.core).list(project_id=project)['facts'][0]['document']['project_id'], project)
        body['scope'] = 'global'; self.service.confirm(body)
        self.assertEqual(len(MemoryStore(self.core).list()['facts']), 1)
        note = self.payload(1); note['scope'] = 'global'
        with self.assertRaises(MemoryError): self.service.confirm(note)

    def test_strict_confirmation_fields_and_legacy_note_source_not_relaxed(self):
        for change in ({'scope':'invalid'}, {'scope':[]}, {'extra':1}, {'candidate':{'kind':'executor'}}, {'source_digest':'wrong'}):
            with self.assertRaises((MemoryError, ValueError)): self.service.confirm(self.payload() | change)
        with self.assertRaises(MemoryError):
            ContinuityStore(self.core).change('save', target='test', progress='a', next_step='b', source=self.query['source'], message=self.doc['messages'][0]['content'], request_id=uuid.uuid4().hex)

    def test_candidate_source_flag_change_invalidates_same_text(self):
        self.service.confirm(self.payload(1));store=ContinuityStore(self.core)
        row=store.list()['records'][0];context={'enabled':True,'ids':[row['id']]}
        self.doc['messages'][0]['task_control']=True
        self.archives.put(self.cid,{'revision':1,'document':self.doc})
        self.assertEqual(store.snapshot(context,None,'local')[0],[])
        with self.assertRaises(MemoryError):self.service.suggest(self.query)

    def test_http_nonce_and_end_to_end_confirm(self):
        spec=importlib.util.spec_from_file_location('candidate_web', ROOT/'apps/web/server.py')
        web=importlib.util.module_from_spec(spec);spec.loader.exec_module(web)
        server=web.create_server(core=self.core, chat=ChatService(self.core), port=0)
        thread=threading.Thread(target=server.serve_forever, daemon=True);thread.start()
        try:
            def call(path, body, nonce):
                conn=http.client.HTTPConnection('127.0.0.1', server.server_port, timeout=8)
                conn.request('POST',path,json.dumps(body),headers={'Content-Type':'application/json','X-Jarvis-Nonce':nonce,'Origin':'http://127.0.0.1:'+str(server.server_port)})
                response=conn.getresponse();data=json.loads(response.read());status=response.status;conn.close();return status,data
            self.assertEqual(call('/api/personal-candidates/suggest',self.query,'bad')[0],403)
            status,data=call('/api/personal-candidates/suggest',self.query,server.nonce)
            self.assertEqual(status,200);self.assertEqual(len(data['candidates']),2)
            self.assertEqual(call('/api/personal-candidates/confirm',self.payload(),server.nonce)[0],200)
        finally:server.shutdown();server.server_close();thread.join(3)
