"""MCP discovery must preserve registrations and never imply tool execution."""
import http.client
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import threading
import unittest
import uuid
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT/'runtime/node-host'), str(ROOT/'adapters/computer-use')]
from jarvis_core.service import CoreService
from jarvis_core.policy import CoreError
from jarvis_core.extensions import ExtensionCatalog
from jarvis_core.mcp_catalog import McpManager, catalog


class McpTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory(); self.addCleanup(temp.cleanup)
        root = Path(temp.name); project = root/'project'; project.mkdir()
        self.core = CoreService(root/'data'); self.core.initialize(project)
        self.manager = McpManager(self.core); self.extensions = ExtensionCatalog(self.core)

    def policy(self, mode='disabled', revision=0, scope='global', scope_id=''):
        return self.manager.put_policy(dict(mcp_id='context7', scope=scope, scope_id=scope_id, mode=mode, revision=revision))

    def item(self, context=None, ident='context7'):
        return next(x for x in self.manager.snapshot(context)['entries'] if x['id'] == ident)

    def register(self, ident=None):
        doc = {'kind': 'mcp', 'name': '<script>custom</script>', 'config': {'transport': 'streamable-http', 'url': 'https://example.com/mcp'}}
        if ident: doc['catalog_id'] = ident
        return self.extensions.put(uuid.uuid4().hex, {'revision': 0, 'document': doc})

    def test_discovery_and_configuration_never_execute_or_claim_ready(self):
        with patch('subprocess.Popen', side_effect=AssertionError('no process')), patch('httpx.Client', side_effect=AssertionError('no network')):
            self.register('context7'); snapshot = self.manager.snapshot()
            self.assertEqual(len(snapshot['entries']), 10)
            self.assertTrue(all(x['policy']['mode'] == 'auto' and not x['callable'] and not x['runtime_available'] for x in snapshot['entries']))
            self.assertEqual(self.item()['status'], 'registered')
            self.assertFalse(snapshot['runtime_available'])
            self.policy('manual')
        self.assertEqual(self.item()['policy']['mode'], 'manual')

    def test_existing_custom_entries_and_multiple_connections_survive(self):
        row = self.register(); self.register('context7'); self.register('context7')
        self.assertEqual(len(self.item()['registrations']), 2)
        self.assertEqual(len(self.manager.snapshot()['entries']), 11)
        custom = self.item(ident='custom.' + row['id'])
        self.assertEqual(custom['name'], '<script>custom</script>')
        self.assertEqual(ExtensionCatalog(self.core).list()['entries'][-1], row)
        self.assertEqual(len(McpManager(self.core).snapshot()['entries']), 11)

    def test_scopes_inheritance_and_stale_write_after_restore(self):
        project, conversation = uuid.uuid4().hex, uuid.uuid4().hex
        self.policy('disabled'); self.policy('manual', scope='project', scope_id=project)
        self.policy('auto', scope='conversation', scope_id=conversation)
        self.assertEqual(self.item({'project_id': project})['policy']['mode'], 'manual')
        self.assertEqual(self.item({'project_id': project, 'conversation_id': conversation})['policy']['mode'], 'auto')
        self.policy(None, 1, 'conversation', conversation)
        self.assertEqual(self.item({'project_id': project, 'conversation_id': conversation})['policy']['mode'], 'manual')
        with self.assertRaises(CoreError) as error: self.policy('auto', 0, 'conversation', conversation)
        self.assertEqual(error.exception.code, 'mcp_policy_conflict')
        self.assertEqual(McpManager(self.core).snapshot()['entries'][0]['policy']['mode'], 'disabled')

    def test_invalid_policy_affiliation_and_stopped_mutation(self):
        for change in [{'mcp_id': 'unknown'}, {'revision': True}, {'revision': 2**53}, {'mode': []}, {'scope': []}, {'scope_id': 'other'}]:
            value = dict(mcp_id='context7', scope='global', revision=0); value.update(change)
            with self.subTest(change=change), self.assertRaises(CoreError): self.manager.put_policy(value)
        for ident in ('unknown', []):
            with self.assertRaises(CoreError): self.register(ident or ['invalid'])
        self.core.stop('test')
        with self.assertRaises(CoreError): self.policy()

    def test_templates_and_skill_references_are_valid(self):
        from jarvis_core.skills import catalog as skills
        admitted = {x['id'] for x in skills()[0]['skills']}
        for item in catalog()[0]['servers']:
            self.extensions.validate({'kind': 'mcp', 'name': item['name'], 'catalog_id': item['id'], 'config': item['template']})
            self.assertTrue(set(item['skills']) <= admitted)


class McpHTTPTests(unittest.TestCase):
    setUp = McpTests.setUp
    def test_http_nonce_origin_and_conflict(self):
        spec = importlib.util.spec_from_file_location('mcp_web', ROOT/'apps/web/server.py')
        web = importlib.util.module_from_spec(spec); spec.loader.exec_module(web)
        class Chat:
            def models(self): return {'providers': []}
        server = web.create_server(core=self.core, chat=Chat(), port=0)
        thread = threading.Thread(target=server.serve_forever, kwargs={'poll_interval': .02}, daemon=True); thread.start()
        port = server.server_address[1]
        def request(path, body=None, nonce=True, origin=True):
            c = http.client.HTTPConnection('127.0.0.1', port, timeout=10)
            headers = {}
            if nonce: headers['X-Jarvis-Nonce'] = server.nonce
            if origin: headers['Origin'] = 'http://127.0.0.1:' + str(port)
            if body is not None: headers['Content-Type'] = 'application/json'
            c.request('GET' if body is None else 'POST', path, body=None if body is None else json.dumps(body), headers=headers)
            r = c.getresponse(); status = r.status; raw = r.read(); c.close(); return status, raw
        try:
            self.assertEqual(request('/api/mcp/catalog', nonce=False)[0], 403)
            self.assertEqual(request('/api/mcp/catalog')[0], 200)
            value = dict(mcp_id='context7', scope='global', revision=0, mode='manual')
            self.assertEqual(request('/api/mcp/policy', value, origin=False)[0], 403)
            self.assertEqual(request('/api/mcp/policy', value)[0], 200)
            self.assertEqual(request('/api/mcp/policy', value)[0], 409)
            self.assertEqual(request('/api/mcp/view', {'project_id': uuid.uuid4().hex})[0], 200)
            self.assertEqual(request('/mcp_manager.js')[0], 200)
            self.assertEqual(request('/api/mcp/call', {})[0], 404)
        finally:
            server.shutdown(); server.server_close(); thread.join(3)


if __name__ == '__main__': unittest.main()
