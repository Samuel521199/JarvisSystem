"""Two isolated cores, real DPAPI identities and pinned loopback TLS; no cloud calls."""
import base64
from contextlib import closing
import copy
import json
from pathlib import Path
import sqlite3
import sys
import tempfile
import unittest
from unittest.mock import patch
import uuid

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT/'runtime/node-host'), str(ROOT/'adapters/models/provider-native')]
from jarvis_core.service import CoreService
from jarvis_core.policy import CoreError
from jarvis_core.federation import Federation
from jarvis_core import federation_protocol as p
from jarvis_core.federation_transport import exchange


class FederationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix='jarvis-federation-')
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        source = self.root/'source'; source.mkdir()
        self.nodes = []
        for name in ('a', 'b'):
            core = CoreService(self.root/name)
            core.initialize(source)
            service = Federation(core)
            self.nodes.append(service)
            self.addCleanup(service.close)
        self.a, self.b = self.nodes

    def pair(self):
        self.a.initialize(); self.b.initialize()
        self.a.listen('127.0.0.1', 0)
        result = self.a.invite('共同计划')
        self.code, self.sid = result['invitation'], result['space']
        self.b.join(self.code)
        return self.sid

    def state(self, node):
        return node.store.read(node.node)['spaces'][self.sid]

    def card(self, node, item):
        return self.state(node)['items'].get(item, [])

    def edit(self, node, item=None, title='计划', text='一起完善助手', deleted=False):
        item = item or uuid.uuid4().hex
        node.edit(self.sid, item, p.heads_token(self.card(node, item)), title, text, deleted)
        return item

    def test_read_only_default_no_database_key_listener_or_memory(self):
        state = self.a.status()
        self.assertFalse(state['initialized'])
        self.assertIsNone(state['endpoint'])
        self.assertFalse((self.a.core.data_dir/'federation.db').exists())
        self.assertFalse((self.a.core.data_dir/'federation').exists())
        self.assertFalse((self.a.core.data_dir/'memory.db').exists())

    def test_real_tls_pair_bidirectional_offline_edits_and_replay(self):
        self.pair()
        first = self.edit(self.a)
        second = self.edit(self.b, text='另一设备的计划')
        self.b.sync(self.sid)
        self.assertEqual(self.card(self.a, second), self.card(self.b, second))
        self.assertEqual(self.card(self.a, first), self.card(self.b, first))
        seen = len(self.state(self.b)['seen'])
        self.b.sync(self.sid)
        self.assertEqual(len(self.state(self.b)['seen']), seen)
        policy = self.b.network
        policy.change(True, 0)
        self.edit(self.b, first, text='离线改写')
        with self.assertRaises(CoreError): self.b.sync(self.sid)
        policy.change(False, 1)
        self.b.sync(self.sid)
        self.assertEqual(self.card(self.a, first)[0]['body']['text'], '离线改写')

    def test_conflict_keeps_both_and_explicit_merge_converges(self):
        self.pair()
        item = self.edit(self.a)
        self.b.sync(self.sid)
        self.edit(self.a, item, text='A 离线修改')
        self.edit(self.b, item, text='B 离线修改')
        self.b.sync(self.sid)
        self.assertEqual(len(self.card(self.a, item)), 2)
        self.assertEqual(self.card(self.a, item), self.card(self.b, item))
        self.edit(self.b, item, text='主人合并的内容')
        self.b.sync(self.sid)
        self.assertEqual(len(self.card(self.a, item)), 1)
        self.assertEqual(self.card(self.a, item)[0]['body']['text'], '主人合并的内容')

    def test_stale_ui_cas_preserves_original(self):
        self.pair()
        item = self.edit(self.a)
        old = p.heads_token(self.card(self.a, item))
        self.edit(self.a, item, text='较新内容')
        with self.assertRaisesRegex(CoreError, '资料已改变'):
            self.a.edit(self.sid, item, old, '过期标题', '过期草稿')
        self.assertEqual(self.card(self.a, item)[0]['body']['text'], '较新内容')

    def test_delete_wins_concurrent_and_stale_copy_cannot_resurrect(self):
        self.pair()
        item = self.edit(self.a, text='删除后不留正文')
        self.b.sync(self.sid)
        old = copy.deepcopy(p.snapshot(self.state(self.b), self.b.node))
        self.edit(self.a, item, deleted=True)
        self.edit(self.b, item, text='并发旧副本')
        self.b.sync(self.sid)
        self.assertTrue(self.card(self.b, item)[0]['body']['deleted'])
        with self.assertRaises(CoreError): self.edit(self.b, item, text='试图复活')
        with self.assertRaises(CoreError):
            self.a.store.change(self.a.node, lambda s: p.merge(s['spaces'][self.sid], old, self.a.node))
        self.b.sync(self.sid)
        self.assertNotIn('删除后不留正文', json.dumps(self.state(self.a), ensure_ascii=False))
        self.assertNotIn('并发旧副本', json.dumps(self.state(self.b), ensure_ascii=False))

    def test_wrong_pin_sends_no_pair_or_data(self):
        self.pair()
        with patch.object(self.a, 'receive', wraps=self.a.receive) as receive:
            with self.assertRaises(CoreError) as error:
                exchange(self.a.status()['endpoint'], '0'*64, '/sync', {'secret': 'fixture'},
                         self.b.online)
            self.assertEqual(error.exception.code, 'federation_pin')
            self.assertEqual(receive.call_count, 0)

    def test_wrong_token_or_signature_not_admitted(self):
        self.a.initialize(); self.b.initialize(); self.a.listen('127.0.0.1', 0)
        invite = self.a.invite('受限空间')
        data = json.loads(base64.urlsafe_b64decode(invite['invitation']))
        data['token'] = 'x'*43
        bad = base64.urlsafe_b64encode(p.encode(data)).decode('ascii')
        with self.assertRaises(CoreError): self.b.join(bad)
        self.assertEqual(self.a.status()['spaces'][0]['state'], 'inviting')
        self.assertEqual(self.b.status()['spaces'][0]['state'], 'pending')

    def test_lost_pair_ack_retry_uses_same_identity_and_request(self):
        from jarvis_core import federation
        self.a.initialize(); self.b.initialize(); self.a.listen('127.0.0.1', 0)
        invitation = self.a.invite('重试空间')
        original = federation.exchange
        def lost(*args, **kwargs):
            original(*args, **kwargs)
            p.fail('synthetic acknowledgement loss')
        with patch.object(federation, 'exchange', lost):
            with self.assertRaises(CoreError): self.b.join(invitation['invitation'])
        self.sid = invitation['space']
        request_id = self.state(self.b)['request_id']
        self.b.retry(self.sid)
        self.assertEqual(self.state(self.a)['request_id'], request_id)
        self.assertEqual(self.state(self.b)['state'], 'active')
        self.assertFalse(self.b._identity().path('join-' + self.sid + '.dpapi').exists())

    def test_revoke_blocks_inflight_apply_and_retains_local_cards(self):
        from jarvis_core import federation
        self.pair()
        item = self.edit(self.a)
        original = federation.exchange
        def revoke_before_apply(*args, **kwargs):
            response = original(*args, **kwargs)
            self.b.revoke(self.sid)
            return response
        with patch.object(federation, 'exchange', revoke_before_apply):
            with self.assertRaises(CoreError): self.b.sync(self.sid)
        self.assertFalse(self.card(self.b, item))
        self.assertTrue(self.card(self.a, item))

    def test_global_stop_after_remote_apply_blocks_local_commit(self):
        from jarvis_core import federation
        self.pair()
        self.edit(self.a)
        original = federation.exchange
        def stop(*args, **kwargs):
            result = original(*args, **kwargs)
            self.b.core.stop('synthetic')
            return result
        with patch.object(federation, 'exchange', stop):
            with self.assertRaises(CoreError): self.b.sync(self.sid)

    def test_listener_restart_off_pending_invite_expired_pair_preserved(self):
        self.pair()
        self.a.close()
        restarted = Federation(CoreService(self.a.core.data_dir))
        self.addCleanup(restarted.close)
        self.assertIsNone(restarted.status()['endpoint'])
        self.assertEqual(restarted.status()['spaces'][0]['state'], 'active')
        self.assertEqual(restarted.status()['fingerprint'], self.a.status()['fingerprint'])
        # Successful pairing persisted, yet old join retries cannot extend the invitation after restart.
        data = json.loads(base64.urlsafe_b64decode(self.code))
        body = {'protocol': p.PROTOCOL, 'space': self.sid, 'sender': self.b.node, 'target': restarted.node,
                'request_id': self.state(self.b)['request_id'], 'certificate': self.b._identity().pem,
                'token': data['token']}
        with self.assertRaises(CoreError): restarted.receive('/pair', p.sign(body, self.b._identity().key))

    def test_tampered_signature_and_cross_space_atomic(self):
        self.pair()
        item = self.edit(self.b)
        snap = copy.deepcopy(p.snapshot(self.state(self.b), self.b.node))
        snap['items'][item][0]['body']['text'] = '篡改'
        before = self.state(self.a)
        with self.assertRaises(CoreError):
            self.a.store.change(self.a.node, lambda s: p.merge(s['spaces'][self.sid], snap, self.a.node))
        self.assertEqual(self.state(self.a), before)
        snap['space'] = uuid.uuid4().hex
        with self.assertRaises(CoreError):
            p.merge(copy.deepcopy(before), snap, self.a.node)

    def test_counter_reuse_detected_even_with_valid_signature(self):
        self.pair()
        item = self.edit(self.b)
        self.b.sync(self.sid)
        snapshot = copy.deepcopy(p.snapshot(self.state(self.b), self.b.node))
        body = snapshot['items'][item][0]['body']
        body['text'] = '同版本号不同正文'
        snapshot['items'][item] = [p.sign(body, self.b._identity().key)]
        with self.assertRaises(CoreError) as error:
            p.merge(copy.deepcopy(self.state(self.a)), snapshot, self.a.node)
        self.assertEqual(error.exception.code, 'federation_rollback')

    def test_quota_merge_is_atomic(self):
        self.pair()
        for _ in range(17):
            self.edit(self.a)
            self.edit(self.b)
        before = self.state(self.a)
        with self.assertRaises(CoreError): self.b.sync(self.sid)
        self.assertEqual(self.state(self.a), before)

    def test_restricted_endpoints_and_no_commands(self):
        self.a.initialize()
        for value in ['https://0.0.0.0:18182', 'https://example.com:443',
                      'https://8.8.8.8:443', 'http://127.0.0.1:1', 'https://127.0.0.1:1/path',
                      'https://user@127.0.0.1:1', 'https://[::1]:1']:
            with self.assertRaises(CoreError): p.endpoint(value)
        with self.assertRaises(CoreError): self.a.action({'action': 'execute', 'command': 'fixture'})
        with self.assertRaises(CoreError): self.a.action({'action': 'initialize', 'project_root': 'fixture'})

    def test_offline_incoming_denied_but_local_edit_available(self):
        self.pair()
        self.a.network.change(True, 0)
        self.edit(self.a)
        with self.assertRaises(CoreError): self.b.sync(self.sid)

    def test_db_identity_mismatch_fails_closed(self):
        self.pair()
        with closing(sqlite3.connect(self.a.store.path)) as db, db:
            db.execute('UPDATE shared_state SET node=?', (self.b.node,))
        with self.assertRaises(CoreError): self.a.status()

    def test_duplicate_json_keys_and_nonfinite_numbers_rejected(self):
        for value in (b'{"a":1,"a":2}', b'{"a":NaN}', b'[]'*(p.MAX_WIRE//2+1)):
            with self.assertRaises(CoreError): p.decode(value)

    def test_database_only_restore_detected_by_independent_frontier(self):
        self.pair()
        previous = self.a.store.path.read_bytes()
        self.edit(self.a)
        self.a.store.path.write_bytes(previous)
        with self.assertRaises(CoreError) as error: self.a.status()
        self.assertEqual(error.exception.code, 'federation_storage')
        with self.assertRaises(CoreError): self.b.sync(self.sid)

    def test_historical_managed_runtime_rejects_sharing_schema(self):
        from jarvis_core.releases import RuntimeSlots
        data = {'optional_versions': {'federation.db': 1}}
        self.assertFalse(RuntimeSlots._compatible('0.1.82', data))
        self.assertTrue(RuntimeSlots._compatible('0.1.83', data))


if __name__ == '__main__':
    unittest.main()
