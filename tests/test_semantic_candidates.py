"""Synthetic extraction boundary tests; no real model or owner data."""
import copy
import json
import sys
import threading
import uuid
import unittest
import http.client
import importlib.util
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT/'tests'), str(ROOT/'runtime/node-host')]
import test_personal_candidates as legacy
from jarvis_core.semantic_candidates import SemanticCandidates, segments
from jarvis_core.memory import MemoryStore, MemoryError
from jarvis_core.chat import ChatService
from jarvis_core.workspace import WorkspaceService


class SemanticTests(unittest.TestCase):
    payload = legacy.CandidateTests.payload
    def setUp(self):
        legacy.CandidateTests.setUp(self)
        self.semantic = SemanticCandidates(self.core, ChatService(self.core))
        self.request = {**self.query, 'provider': 'vertex', 'model': 'gemini-3.1-pro-preview',
                        'reasoning': None, 'request_id': uuid.uuid4().hex}
        self.answer = {'candidates': [{'segment': 0, 'title': '饮品偏好', 'content': '主人平时喜欢无糖茶',
                                      'category': 'preference', 'subject_label': ''}]}

    def preview(self, answer=None, **result):
        def model(config, provider, prompt, *args, **kwargs):
            self.calls.append({'prompt': prompt, 'instructions': kwargs.get('instructions'),
                               'history': kwargs.get('history'), 'provider': provider,
                               'max_output': config['providers'][provider].get('max_output_tokens')})
            return {'status': 'SUCCEEDED', 'text': json.dumps(answer or self.answer, ensure_ascii=False),
                    'provider': provider, 'model': config['providers'][provider]['model'], **result}
        self.calls = []
        with patch('jarvis_core.chat.gateway.probe', side_effect=model):
            return self.semantic.suggest(self.request)

    @staticmethod
    def confirmation(preview):
        item = preview['candidates'][0]
        return {k: copy.deepcopy(item[k]) for k in ('candidate_id', 'title', 'content', 'classification')} | {
                'preview_token': preview['preview_token'], 'scope': 'current'}

    def test_model_preview_isolated_single_destination_no_writes(self):
        memory = MemoryStore(self.core)
        memory.command('remember', '隐私', 'PRIVATE_SENTINEL', request_id=uuid.uuid4().hex)
        before = memory.list()
        preview = self.preview()
        self.assertFalse(preview['committed']); self.assertEqual(len(self.calls), 1)
        self.assertNotIn('PRIVATE_SENTINEL', str(self.calls))
        self.assertEqual(self.calls[0]['history'], [])
        self.assertIn('review-only', self.calls[0]['instructions'])
        self.assertLessEqual(self.calls[0]['max_output'], 1024)
        self.assertEqual(memory.list(), before)
        self.assertFalse((self.core.data_dir/'continuity.db').exists())

    def test_confirm_classification_provenance_idempotence_and_provider_default(self):
        preview = self.preview(); payload = self.confirmation(preview)
        first = self.semantic.confirm(payload); second = self.semantic.confirm(payload)
        self.assertEqual(first['receipt']['id'], second['receipt']['id']); self.assertTrue(second['receipt']['replayed'])
        row = MemoryStore(self.core).list()['facts'][0]
        self.assertEqual(row['document']['classification']['kind'], 'preference')
        self.assertEqual(row['document']['classification']['uses'], ['personal_chat'])
        self.assertEqual(row['document']['providers'], [])
        self.assertEqual(row['provenance']['state'], 'current')
        self.assertEqual(row['provenance']['excerpt'], self.doc['messages'][0]['content'])

    def test_forget_fences_model_paraphrases_and_rules(self):
        preview = self.preview(); original = self.confirmation(preview)
        first = self.semantic.confirm(original); memory = MemoryStore(self.core)
        memory.delete(first['receipt']['id'], {'revision': 1})
        self.assertTrue(self.semantic.confirm(original)['receipt']['replayed'])
        self.answer['candidates'][0].update(title='新标题', content='主人偏好无糖饮品')
        with self.assertRaises(MemoryError) as exc: self.semantic.confirm(self.confirmation(self.preview()))
        self.assertEqual(exc.exception.code, 'candidate_suppressed')
        with self.assertRaises(MemoryError) as exc: self.service.confirm(self.payload())
        self.assertEqual(exc.exception.code, 'candidate_suppressed')
        self.assertEqual(memory.list()['facts'], [])

    def test_non_rule_sentence_identity_survives_paraphrase(self):
        self.doc['messages'][0]['content'] = '长篇答复读着累，给我的结论请尽量简洁。'
        self.archives.put(self.cid, {'revision': 1, 'document': self.doc})
        first = self.semantic.confirm(self.confirmation(self.preview()))
        memory = MemoryStore(self.core); row = memory.list()['facts'][0]
        memory.put(row['id'], {'revision': row['revision'], 'document': {**row['document'], 'content': '更正后的独立内容'}})
        self.answer['candidates'][0]['title'] = '另一种说法'
        with self.assertRaises(MemoryError) as exc: self.semantic.confirm(self.confirmation(self.preview()))
        self.assertEqual(exc.exception.code, 'candidate_suppressed')
        self.assertEqual(len(memory.list()['facts']), 1)

    def test_invalid_model_output_never_writes_or_signs(self):
        variants = [{'candidates': []}, {'candidates': [dict(self.answer['candidates'][0], segment=55)]},
                    {'candidates': self.answer['candidates'] * 2},
                    {'candidates': [dict(self.answer['candidates'][0], category='executor')]},
                    {'candidates': [dict(self.answer['candidates'][0], category='third_party')]},
                    {'candidates': [dict(self.answer['candidates'][0], category='project_fact')]},
                    {'candidates': [dict(self.answer['candidates'][0], content='x'*1025)]},
                    {'candidates': [dict(self.answer['candidates'][0], classification={})]}]
        for answer in variants:
            preview = self.preview(answer)
            self.assertEqual(preview['candidates'], [], str(answer))
            self.assertNotIn('preview_token', preview)
        for raw in ('```json\n{}\n```', '{"candidates":[],"candidates":[]}', 'x'*16385):
            preview = self.preview(text=raw); self.assertEqual(preview['result']['status'], 'FAILED')
        preview = self.preview(output_incomplete=True); self.assertNotIn('preview_token', preview)
        self.assertFalse((self.core.data_dir/'memory.db').exists())

    def test_complete_json_fence_only_not_partial_or_surrounding_prose(self):
        valid = '```json\n'+json.dumps(self.answer)+'\n```'
        self.assertEqual(len(self.preview(text=valid)['candidates']), 1)
        for raw in ('解释如下\n'+valid, valid+'\n已完成', valid[:-3], '```python\n'+json.dumps(self.answer)+'\n```'):
            self.assertEqual(self.preview(text=raw)['result']['status'], 'FAILED')

    def test_signed_preview_tampering_expiry_restart_and_source_change(self):
        preview = self.preview(); payload = self.confirmation(preview)
        for bad in ({'preview_token': payload['preview_token']+'x'}, {'candidate_id': 'f'*64},
                    {'classification': None}, {'content': None}, {'scope': 'external'}):
            with self.assertRaises((MemoryError, ValueError)): self.semantic.confirm(payload | bad)
        with patch('jarvis_core.semantic_candidates.time.time', return_value=10**12):
            with self.assertRaises(MemoryError): self.semantic.confirm(payload)
        with self.assertRaises(MemoryError): SemanticCandidates(self.core, ChatService(self.core)).confirm(payload)
        self.doc['messages'][0]['content'] += '更正来源。'
        self.archives.put(self.cid, {'revision': 1, 'document': self.doc})
        with self.assertRaises(MemoryError) as exc: self.semantic.confirm(payload)
        self.assertEqual(exc.exception.code, 'candidate_source_changed')

    def test_preflight_excludes_credentials_nonretention_and_oversized_no_call(self):
        for text in ('我喜欢茶，不要记住', 'password=private-value', 'xai-abcdefghijklm', 'a'*801, '短句。'*33):
            row = self.archives.get(self.cid); self.doc['messages'][0]['content'] = text
            self.archives.put(self.cid, {'revision': row['revision'], 'document': self.doc})
            with patch.object(self.semantic.chat, 'reply') as model:
                with self.assertRaises(MemoryError): self.semantic.suggest(self.request)
                model.assert_not_called()

    def test_cryptography_preference_is_not_itself_a_credential(self):
        self.doc['messages'][0]['content'] = '我喜欢研究密码学。'
        self.archives.put(self.cid, {'revision': 1, 'document': self.doc})
        self.answer['candidates'][0]['content'] = '喜欢研究密码学'
        self.assertEqual(self.preview()['result']['status'], 'SUCCEEDED')
        row = self.archives.get(self.cid)
        self.doc['messages'][0]['content'] += '密码=synthetic-only。'
        self.archives.put(self.cid, {'revision': row['revision'], 'document': self.doc})
        with patch.object(self.semantic.chat, 'reply') as model:
            with self.assertRaises(MemoryError): self.semantic.suggest(self.request)
            model.assert_not_called()

    def test_first_person_role_is_not_owner_identity_but_roleplay_hobby_is(self):
        self.doc['messages'][0]['content'] = '在这次角色扮演中，我扮演机器人零号，它守护虚构的月球基地。'
        self.archives.put(self.cid, {'revision': 1, 'document': self.doc})
        self.answer['candidates'][0].update(content='我扮演机器人零号', category='personal_fact')
        preview = self.preview()
        self.assertEqual(preview['result']['error_category'], 'candidate_subject_conflict')
        self.assertEqual(preview['candidates'], []); self.assertNotIn('preview_token', preview)
        self.assertEqual(MemoryStore(self.core).list()['facts'], [])
        self.answer['candidates'][0].update(category='fiction', subject_label='零号')
        self.assertEqual(self.preview()['result']['status'], 'SUCCEEDED')
        self.doc['messages'][0]['content'] = '我喜欢角色扮演游戏。'
        self.archives.put(self.cid, {'revision': 2, 'document': self.doc})
        self.answer['candidates'][0].update(content='喜欢角色扮演游戏', category='preference', subject_label='')
        self.assertEqual(self.preview()['result']['status'], 'SUCCEEDED')

    def test_filter_upgrade_keeps_old_identity_after_forget(self):
        # A fact wrongly suggested by v1 must remain suppressed after tightening eligibility.
        from jarvis_core.personal_candidates import identity_candidates_v1
        from jarvis_core.memory_sources import candidate_id
        self.doc['messages'][0]['content'] = '我希望你这一次回答只写三行。'
        self.archives.put(self.cid, {'revision': 1, 'document': self.doc})
        old = identity_candidates_v1(self.doc['messages'][0]['content'])[0]
        text, digest = self.semantic.local.source(self.query['source'], None)
        origin = {**self.query['source'], 'project_id': None, 'sha256': digest,
                  'candidate_id': candidate_id(old), 'archive_revision': 2}
        memory = MemoryStore(self.core)
        receipt = memory.command('remember', old['title'], old['content'], request_id=uuid.uuid4().hex,
                                 candidate_source=origin)
        memory.delete(receipt['id'], {'revision': 1})
        self.assertEqual(self.service.suggest(self.query)['candidates'], [])
        self.answer['candidates'][0].update(content='主人偏好三行回复')
        preview = self.preview()
        self.assertEqual(preview['candidates'][0]['candidate_id'], origin['candidate_id'])
        with self.assertRaises(MemoryError) as exc:
            self.semantic.confirm(self.confirmation(preview))
        self.assertEqual(exc.exception.code, 'candidate_suppressed')
        self.assertEqual(memory.list()['facts'], [])

    def test_future_task_is_not_promoted_to_a_durable_fact(self):
        project = WorkspaceService(self.core).open_project({'path': str(self.base/'source')})['id']
        self.doc['project_id'] = project
        self.doc['messages'][0]['content'] = '我明天打算测试这个项目的导出功能。'
        self.archives.put(self.cid, {'revision': 1, 'document': self.doc})
        self.request['project_id'] = project
        self.answer['candidates'][0].update(content='明天打算测试项目导出功能', category='project_fact')
        result = self.preview()
        self.assertEqual(result['result']['error_category'], 'candidate_pending_work')
        self.assertEqual(result['candidates'], []); self.assertNotIn('preview_token', result)
        self.assertEqual(MemoryStore(self.core).list()['facts'], [])
        self.doc['messages'][0]['content'] = '我已经完成了计划中的测试，项目导出功能通过了。'
        self.archives.put(self.cid, {'revision': 2, 'document': self.doc})
        self.answer['candidates'][0].update(content='主人表示已经测试通过了项目导出功能', category='work_result')
        self.assertEqual(self.preview()['result']['status'], 'SUCCEEDED')

    def test_project_statement_cannot_be_relabelled_as_owner_without_scope(self):
        self.doc['messages'][0]['content'] = '这个项目确定使用 Rust。'
        self.archives.put(self.cid, {'revision': 1, 'document': self.doc})
        self.answer['candidates'][0].update(content='这个项目使用 Rust', category='personal_fact')
        preview = self.preview()
        self.assertEqual(preview['result']['error_category'], 'candidate_scope_conflict')
        self.assertEqual(preview['candidates'], []); self.assertNotIn('preview_token', preview)
        self.doc['messages'][0]['content'] = '我喜欢用 Rust。'
        self.archives.put(self.cid, {'revision': 2, 'document': self.doc})
        self.answer['candidates'][0].update(content='喜欢使用 Rust', category='preference')
        self.assertEqual(self.preview()['result']['status'], 'SUCCEEDED')

    def test_project_customer_fiction_separation_and_owner_edited_use(self):
        project = WorkspaceService(self.core).open_project({'path': str(self.base/'source')})['id']
        self.doc['project_id'] = project; self.doc['messages'][0]['content'] = '客户老王喜欢咖啡。游戏角色阿明是法师。这个项目使用 Python。'
        self.archives.put(self.cid, {'revision': 1, 'document': self.doc}); self.request['project_id'] = project
        answer = {'candidates': [
            {'segment': 0, 'title': '客户饮品', 'content': '老王喜欢咖啡', 'category': 'third_party', 'subject_label': '老王'},
            {'segment': 1, 'title': '角色职业', 'content': '阿明是法师', 'category': 'fiction', 'subject_label': '阿明'},
            {'segment': 2, 'title': '开发语言', 'content': '项目使用 Python', 'category': 'project_fact', 'subject_label': ''}]}
        preview = self.preview(answer)
        self.assertEqual([x['classification']['subject'] for x in preview['candidates']], ['other','character','project'])
        for item in preview['candidates']:
            payload = self.confirmation({**preview, 'candidates': [item]})
            self.semantic.confirm(payload)
        memory = MemoryStore(self.core); ctx = {'enabled': True, 'project_id': project, 'purpose': 'work_assist'}
        facts = memory.view_facts(ctx, 'local')
        self.assertEqual([f['document']['title'] for f in facts], ['开发语言'])
        self.assertEqual(memory.view_facts({**ctx,'purpose':'personal_chat'}, 'local'), [])
        self.assertEqual(memory.view_facts({**ctx,'project_id':None}, 'local'), [])
        payload = self.confirmation({**preview, 'candidates': [preview['candidates'][2]]}); payload['scope'] = 'global'
        with self.assertRaises(MemoryError): self.semantic.confirm(payload)

    def test_no_fallback_cancellation_and_internal_context_rejected(self):
        preview = self.preview(status='FAILED', error_category='quota_exhausted', outcome_uncertain=False)
        self.assertEqual(len(self.calls), 1); self.assertEqual(preview['candidates'], [])
        event = threading.Event(); event.set()
        with patch('jarvis_core.chat.gateway.probe') as model:
            result = self.semantic.suggest(self.request, cancel_event=event)
            model.assert_not_called(); self.assertEqual(result['result']['status'], 'CANCELLED')
        with self.assertRaises(ValueError): self.semantic.chat.reply('x', _purpose='memory_candidates', history=[{'role':'user','content':'private'}])
        with self.assertRaises(MemoryError): self.semantic.suggest({**self.request, 'provider': 'auto'})

    def test_confirm_retry_ignores_policy_dictionary_order(self):
        body = self.confirmation(self.preview()); self.semantic.confirm(body)
        body['classification'] = dict(reversed(list(body['classification'].items())))
        self.assertTrue(self.semantic.confirm(body)['receipt']['replayed'])

    def test_http_timeout_retains_slot_cancellation_and_duplicate_no_resend(self):
        spec = importlib.util.spec_from_file_location('semantic_web', ROOT/'apps/web/server.py')
        web = importlib.util.module_from_spec(spec); spec.loader.exec_module(web)
        server = web.create_server(core=self.core, chat=ChatService(self.core), port=0)
        # Allow context admission on a loaded PC before exercising the HTTP
        # timeout. The held transport below remains pending beyond this budget.
        server.reply_timeout = 1
        if server.evolution: server.evolution.close()
        thread = threading.Thread(target=server.serve_forever, kwargs={'poll_interval': .01}, daemon=True); thread.start()
        entered, release = threading.Event(), threading.Event()
        def call(path, body, nonce=None):
            connection = http.client.HTTPConnection('127.0.0.1', server.server_port, timeout=5)
            connection.request('POST', path, json.dumps(body), headers={'Content-Type':'application/json','X-Jarvis-Nonce':nonce or server.nonce,
                'Origin':'http://127.0.0.1:'+str(server.server_port)})
            response=connection.getresponse(); data=json.loads(response.read()); status=response.status; connection.close()
            return status, data
        def held(*args, **kwargs):
            entered.set(); release.wait(5)
            return {'status':'SUCCEEDED','text':json.dumps(self.answer)}
        try:
            with patch('jarvis_core.chat.gateway.probe', side_effect=held) as model:
                self.assertEqual(call('/api/personal-candidates/semantic', self.request, 'bad')[0], 403)
                self.assertEqual(call('/api/personal-candidates/semantic', self.request)[0], 504)
                self.assertTrue(entered.is_set()); self.assertEqual(server.chat_requests.active, 1)
                self.assertTrue(server.slots.acquire(blocking=False)); self.assertFalse(server.slots.acquire(blocking=False))
                server.slots.release()
                self.assertEqual(call('/api/personal-candidates/semantic', self.request)[0], 409)
                self.assertEqual(call('/api/chat/cancel', {'request_id':self.request['request_id']})[0], 200)
                self.assertEqual(model.call_count, 1)
                release.set()
                # The registry event is not a completion signal; wait on admission.
                self.assertTrue(server.slots.acquire(timeout=3)); self.assertTrue(server.slots.acquire(timeout=3))
                server.slots.release(); server.slots.release()
                self.assertEqual(server.chat_requests.active, 0)
                self.assertEqual(MemoryStore(self.core).list()['facts'], [])
                self.assertEqual(call('/api/personal-candidates/semantic', self.request)[0], 409)
                early = {**self.request, 'request_id':uuid.uuid4().hex}
                call('/api/chat/cancel', {'request_id':early['request_id']})
                status, body = call('/api/personal-candidates/semantic', early)
                self.assertEqual(status, 200); self.assertEqual(body['result']['status'], 'CANCELLED')
                self.assertEqual(model.call_count, 1)
        finally:
            release.set(); server.shutdown(); server.server_close(); thread.join(3)
            # Even a failed assertion must join the admitted extraction before
            # TemporaryDirectory removes its SQLite files on Windows.
            acquired = 0
            try:
                for _ in range(2):
                    if server.slots.acquire(timeout=5): acquired += 1
            finally:
                for _ in range(acquired): server.slots.release()
