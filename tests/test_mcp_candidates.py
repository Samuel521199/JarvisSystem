"""Document suggestions are locally checked drafts, never task authorization."""
import http.client
import json
import threading
import unittest
import uuid
from unittest.mock import patch

import test_mcp_runtime as runtime_fixture
from test_mcp_runtime import ComputerWeb, FakeChat, ConversationTasks, CoreError
from test_conversations import document
from test_web import web
from jarvis_core.conversations import ConversationStore
from jarvis_core.workspace import WorkspaceService


class CandidateTests(unittest.TestCase):
    setUp = runtime_fixture.TaskTests.setUp
    prepare = runtime_fixture.TaskTests.prepare
    text = '请查询 Electron 文档中的 ipcMain.handle 示例'
    candidate = {'library': 'Electron', 'query': 'ipcMain.handle 示例'}

    def assess(self, candidate=None, **kwargs):
        return self.service.assess_candidate(self.candidate if candidate is None else candidate,
            text=kwargs.pop('text', self.text), conversation_id=self.cid, **kwargs)

    def policy(self, mode, *, scope='global', scope_id='', revision=0):
        return self.service.manager.put_policy(dict(mcp_id='context7', mode=mode, scope=scope, scope_id=scope_id, revision=revision))

    def save(self, project=None, revision=0):
        return ConversationStore(self.core).put(self.cid, {'revision': revision, 'document': {**document(), 'project_id': project}})

    def project(self):
        folder = self.root/uuid.uuid4().hex; folder.mkdir()
        return WorkspaceService(self.core).open_project({'path': str(folder)})['id']

    def test_auto_candidate_is_only_draft_no_network_models_or_task(self):
        with patch('httpx.AsyncClient', side_effect=AssertionError('no network')):
            row = self.assess()
        self.assertTrue(row['eligible']); self.assertTrue(row['auto_eligible'])
        self.assertFalse(row['automatic_execution']); self.assertEqual(row['next_action'], 'review_draft')
        self.assertEqual(row['context'], {'conversation_id': self.cid})
        with self.core.ledger.connection() as db:
            self.assertEqual(db.execute('SELECT count(*) FROM tasks').fetchone()[0], 0)
        self.assertEqual(self.protocol.calls, [])

    def test_manual_only_offers_explicit_draft_disabled_offers_none(self):
        self.policy('manual'); row = self.assess()
        self.assertTrue(row['eligible']); self.assertFalse(row['auto_eligible'])
        self.policy('disabled', revision=1); row = self.assess()
        self.assertFalse(row['eligible']); self.assertEqual(row['reason_code'], 'mcp_disabled')
        self.assertEqual(row['policy']['mode'], 'disabled')
        self.assertNotIn('query', row)

    def test_missing_invented_partial_source_and_extra_parameters_rejected(self):
        cases = [None, {}, {'library': 'Electron'}, {**self.candidate, 'url': 'https://example.com'},
                 {**self.candidate, 'library': 'React'}, {**self.candidate, 'library': 'Elect'},
                 {**self.candidate, 'query': 'private memory'}, {**self.candidate, 'query': ''},
                 {**self.candidate, 'query': 'ipcMain.handle\n示例'}, {**self.candidate, 'library': 42}]
        for candidate in cases:
            with self.subTest(candidate=candidate):
                row = self.service.assess_candidate(candidate, text=self.text)
                self.assertFalse(row['eligible']); self.assertEqual(row['next_action'], 'none')
        self.assertFalse(self.assess(text='x'*16385)['eligible'])
        self.assertFalse(self.assess(text=None)['eligible'])

    def test_library_id_and_version_are_not_invented_or_auto_resolved(self):
        row = self.assess({'library': '/electron/electron/42', 'query': 'ipcMain.handle'}, text='查询 /electron/electron/42 的 ipcMain.handle')
        self.assertTrue(row['eligible']); self.assertEqual(row['library'], '/electron/electron/42')
        self.assertFalse(self.assess({'library': '/electron/electron', 'query': 'ipcMain.handle'})['eligible'])
        self.assertEqual(self.protocol.calls, [])

    def test_project_disabled_applies_when_request_omits_project(self):
        project = self.project(); self.save(project); self.policy('disabled', scope='project', scope_id=project)
        self.assertEqual(self.assess()['reason_code'], 'mcp_disabled')
        with self.assertRaises(CoreError) as exc: self.service.admit(self.payload)
        self.assertEqual(exc.exception.code, 'mcp_disabled')

    def test_conversation_override_and_inherit_use_saved_membership(self):
        project = self.project(); self.save(project); self.policy('disabled', scope='project', scope_id=project)
        self.policy('auto', scope='conversation', scope_id=self.cid)
        row = self.assess(); self.assertTrue(row['eligible']); self.assertEqual(row['context']['project_id'], project)
        self.policy(None, scope='conversation', scope_id=self.cid, revision=1)
        self.assertEqual(self.assess()['reason_code'], 'mcp_disabled')

    def test_wrong_project_and_deleted_conversation_rejected(self):
        project = self.project(); other = self.project(); self.save(project)
        self.assertEqual(self.assess(project_id=other)['reason_code'], 'mcp_scope_changed')
        ConversationStore(self.core).delete(self.cid, {'revision': 1})
        self.assertEqual(self.assess()['reason_code'], 'conversation_deleted')
        with self.assertRaises(CoreError): self.service.admit(self.payload)

    def test_membership_change_after_admission_stops_before_network(self):
        self.save(); record = self.prepare(); self.save(self.project(), revision=1)
        result = self.service.run(record['action']['action_id'])
        self.assertEqual(result['action']['status'], 'FAILED'); self.assertEqual(self.protocol.calls, [])

    def test_policy_change_after_draft_does_not_authorize_submission(self):
        self.assertTrue(self.assess()['eligible']); self.policy('disabled')
        with self.assertRaises(CoreError): self.service.admit(self.payload)
        self.assertEqual(self.protocol.calls, [])

    def test_unconfigured_and_ambiguous_connections_never_offer_draft(self):
        self.extensions.put(self.rid, {'revision': 1, 'document': {**self.doc, 'config': {'transport': 'streamable-http', 'url': 'https://example.com'}}})
        self.assertEqual(self.assess()['reason_code'], 'mcp_not_configured')
        self.extensions.put(self.rid, {'revision': 2, 'document': self.doc})
        self.extensions.put(uuid.uuid4().hex, {'revision': 0, 'document': self.doc})
        self.assertEqual(self.assess()['reason_code'], 'mcp_not_configured')

    def test_bridge_rejects_hidden_execution_fields(self):
        manager = ComputerWeb(self.core, FakeChat()); self.addCleanup(manager.close)
        bridge = ConversationTasks(self.core, manager)
        payload = {'candidate': self.candidate, 'text': self.text}
        self.assertTrue(bridge.documentation_candidate(self.cid, payload)['eligible'])
        for extra in ({'request_id': 'web-'+uuid.uuid4().hex}, {'execute': True}, {'model': 'auto'}):
            with self.assertRaises(CoreError): bridge.documentation_candidate(self.cid, {**payload, **extra})

    def test_http_nonce_origin_and_no_task(self):
        server = web.create_server(core=self.core, chat=FakeChat(), port=0)
        thread = threading.Thread(target=server.serve_forever, kwargs={'poll_interval': .02}, daemon=True); thread.start()
        port = server.server_address[1]
        def call(*, nonce=True, origin=True, extra=None):
            conn = http.client.HTTPConnection('127.0.0.1', port, timeout=10)
            headers = {'Content-Type': 'application/json'}
            if nonce: headers['X-Jarvis-Nonce'] = server.nonce
            if origin: headers['Origin'] = 'http://127.0.0.1:'+str(port)
            conn.request('POST', '/api/conversation-tasks/'+self.cid+'/documentation-candidate', json.dumps({'candidate': self.candidate, 'text': self.text, **(extra or {})}), headers)
            response = conn.getresponse(); status = response.status; body = json.loads(response.read()); conn.close()
            return status, body
        try:
            self.assertEqual(call(nonce=False)[0], 403); self.assertEqual(call(origin=False)[0], 403)
            status, body = call(); self.assertEqual(status, 200); self.assertTrue(body['eligible'])
            self.assertEqual(call(extra={'execute': True})[0], 400)
            self.assertEqual(server.conversation_tasks.list(self.cid)['tasks'], [])
        finally:
            server.shutdown(); server.server_close(); thread.join(3)


if __name__ == '__main__': unittest.main()
