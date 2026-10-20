"""Identity-preserving recovery, real pinned TLS and disposable device stores."""
import copy
import json
import unittest
from unittest.mock import patch
import uuid

import test_federation as fixtures
from jarvis_core import federation_connection as connection
from jarvis_core import federation_protocol as p
from jarvis_core.federation import Federation
from jarvis_core.federation_access import destination
from jarvis_core.policy import CoreError


class ConnectionTests(unittest.TestCase):
    setUp = fixtures.FederationTests.setUp
    pair = fixtures.FederationTests.pair
    state = fixtures.FederationTests.state
    card = fixtures.FederationTests.card
    edit = fixtures.FederationTests.edit

    def move(self):
        self.a.close(); self.a.listen('127.0.0.1', 0)
        return self.a.status()['endpoint']

    def preview(self):
        return self.b.connection.preview(self.sid, self.move())

    def test_diagnosis_is_read_only_and_never_sends_card_text(self):
        self.pair(); self.edit(self.b, text='PRIVATE_CARD_SENTINEL')
        before = [s.store.read(s.node) for s in self.nodes]
        original = connection.exchange
        def capture(endpoint, pin, route, payload, guard):
            self.assertEqual(route, '/inspect')
            self.assertNotIn('PRIVATE_CARD_SENTINEL', json.dumps(payload))
            self.assertNotIn('snapshot', payload['body'])
            return original(endpoint, pin, route, payload, guard)
        with patch.object(connection, 'exchange', side_effect=capture):
            result = self.b.connection.check(self.sid)
        self.assertTrue(result['identity_verified']); self.assertTrue(result['reachable'])
        self.assertEqual(before, [s.store.read(s.node) for s in self.nodes])

    def test_preview_confirm_preserves_data_permissions_and_then_syncs(self):
        self.pair(); item = self.edit(self.b)
        config = json.loads((fixtures.ROOT/'config/model-profiles/providers.json').read_text(encoding='utf-8'))
        self.b.access.change(self.sid, 0, [item], {'local':destination(config, 'local')}, None)
        before = self.state(self.b)
        plan = self.preview()
        self.assertEqual(self.state(self.b), before)
        receipt = self.b.connection.apply(self.sid, plan['token'])
        after = self.state(self.b)
        self.assertEqual({k:v for k,v in after.items() if k!='endpoint'}, {k:v for k,v in before.items() if k!='endpoint'})
        self.assertEqual(after['endpoint'], plan['endpoint']); self.assertTrue(receipt['changed'])
        with patch.object(connection, 'exchange', side_effect=AssertionError('No repeat network call')):
            self.assertEqual(self.b.connection.apply(self.sid, plan['token']), receipt)
        self.b.sync(self.sid)
        self.assertEqual(self.card(self.a,item), self.card(self.b,item))
        self.assertEqual(Federation(self.b.core).status()['spaces'][0]['endpoint'], plan['endpoint'])

    def test_wrong_certificate_sends_no_signed_request(self):
        self.pair(); self.b.listen('127.0.0.1',0)
        before = self.state(self.b)
        with patch.object(self.b, 'receive', wraps=self.b.receive) as receiver:
            with self.assertRaises(CoreError) as caught:
                self.b.connection.preview(self.sid, self.b.status()['endpoint'])
            self.assertEqual(caught.exception.code,'federation_pin')
            receiver.assert_not_called()
        self.assertEqual(self.state(self.b), before)

    def test_public_dns_credentials_path_and_invalid_input_rejected_before_socket(self):
        self.pair()
        with patch.object(connection, 'exchange', side_effect=AssertionError('No network')):
            for value in ('https://8.8.8.8:443', 'https://example.com:18182', 'http://127.0.0.1:18182',
                          'https://u:p@127.0.0.1:18182', 'https://127.0.0.1:18182/data', None):
                with self.subTest(value=value), self.assertRaises(CoreError):
                    self.b.connection.preview(self.sid, value)

    def test_reply_wrong_nonce_target_space_or_signature_is_rejected(self):
        self.pair()
        original = connection.exchange
        for field in ('request_id', 'target', 'space', 'signature'):
            def altered(*args, **kwargs):
                reply = original(*args, **kwargs)
                if field == 'signature':
                    reply['signature'] = 'bad'
                    return reply
                body = copy.deepcopy(reply['body']); body[field] = uuid.uuid4().hex
                return p.sign(body, self.a._identity().key)
            with self.subTest(field=field), patch.object(connection,'exchange',side_effect=altered):
                with self.assertRaises(CoreError):
                    self.b.connection.preview(self.sid, self.state(self.b)['endpoint'])
        self.assertFalse(self.b.connection.previews)

    def test_revoked_peer_or_unsupported_endpoint_not_diagnosed_as_connected(self):
        self.pair(); self.a.revoke(self.sid)
        result = self.b.connection.check(self.sid)
        self.assertFalse(result['reachable']); self.assertEqual(result['code'],'federation_peer_rejected')
        with self.assertRaises(CoreError):
            self.b.connection.preview(self.sid, self.state(self.b)['endpoint'])

    def test_offline_stops_checks_without_network_and_toggle_invalidates_preview(self):
        self.pair(); plan = self.preview()
        self.b.network.change(True, 0)
        with patch.object(connection,'exchange',side_effect=AssertionError('No network')):
            self.assertEqual(self.b.connection.check(self.sid)['code'],'network_offline')
            with self.assertRaises(CoreError): self.b.connection.apply(self.sid,plan['token'])
        self.b.network.change(False, 1)
        with self.assertRaises(CoreError): self.b.connection.apply(self.sid,plan['token'])

    def test_expiry_close_restart_and_replaced_preview_are_rejected(self):
        self.pair(); plan = self.preview()
        with self.b.connection.lock:
            self.b.connection.previews[plan['token']]['expires'] = 0
        with self.assertRaises(CoreError): self.b.connection.apply(self.sid,plan['token'])
        plan = self.b.connection.preview(self.sid, self.a.status()['endpoint'])
        replacement = self.b.connection.preview(self.sid, self.a.status()['endpoint'])
        self.assertNotEqual(plan['token'],replacement['token'])
        with self.assertRaises(CoreError): self.b.connection.apply(self.sid,plan['token'])
        with self.assertRaises(CoreError): Federation(self.b.core).connection.apply(self.sid,replacement['token'])
        self.b.close()
        with self.assertRaises(CoreError): self.b.connection.apply(self.sid,replacement['token'])

    def test_unreachable_at_confirmation_keeps_old_address_and_data(self):
        self.pair(); plan = self.preview(); before = self.state(self.b); self.a.close()
        with self.assertRaises(CoreError):
            self.b.connection.apply(self.sid,plan['token'])
        self.assertEqual(self.state(self.b),before)

    def test_local_revoke_during_network_proof_cannot_commit(self):
        self.pair(); plan = self.preview(); original = connection.exchange
        before = self.state(self.b)['endpoint']
        def revoke(*args, **kwargs):
            reply = original(*args, **kwargs); self.b.revoke(self.sid); return reply
        with patch.object(connection,'exchange',side_effect=revoke), self.assertRaises(CoreError):
            self.b.connection.apply(self.sid,plan['token'])
        self.assertEqual(self.state(self.b)['endpoint'],before)
        self.assertEqual(self.state(self.b)['state'],'revoked')

    def test_close_or_expiry_during_confirmation_cannot_commit(self):
        self.pair(); plan = self.preview(); before = self.state(self.b); original = connection.exchange
        def expire(*args, **kwargs):
            reply = original(*args, **kwargs)
            self.b.connection.previews[plan['token']]['expires'] = 0
            return reply
        with patch.object(connection,'exchange',side_effect=expire), self.assertRaises(CoreError):
            self.b.connection.apply(self.sid,plan['token'])
        self.assertEqual(self.state(self.b),before)

    def test_host_pending_busy_and_unrelated_space_are_rejected(self):
        self.pair()
        with self.assertRaises(CoreError): self.a.connection.check(self.sid)
        with self.b.flight, self.assertRaises(CoreError): self.b.connection.check(self.sid)
        plan = self.preview()
        with self.assertRaises(CoreError): self.b.connection.apply(uuid.uuid4().hex,plan['token'])
        self.assertEqual(len(self.b.connection.previews),1)

    def test_content_updates_do_not_expand_preview_authority(self):
        self.pair(); plan = self.preview()
        item = self.edit(self.b, text='预览期间的新卡')
        self.b.connection.apply(self.sid,plan['token'])
        self.assertEqual(self.card(self.b,item)[0]['body']['text'],'预览期间的新卡')
        self.assertNotIn(item,self.state(self.a)['items'])

    def test_peer_without_inspect_support_keeps_existing_sync_compatible(self):
        self.pair(); item=self.edit(self.b)
        original=self.a.receive
        def legacy(route,signed):
            if route=='/inspect': p.fail('unsupported')
            return original(route,signed)
        with patch.object(self.a,'receive',side_effect=legacy):
            self.assertFalse(self.b.connection.check(self.sid)['reachable'])
            self.b.sync(self.sid)
        self.assertEqual(self.card(self.a,item),self.card(self.b,item))


if __name__ == '__main__':
    unittest.main()
