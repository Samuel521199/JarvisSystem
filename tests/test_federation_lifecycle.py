"""Retirement, recovery and explicit copy boundaries, with temporary owner data only."""
from contextlib import closing
import json
import sqlite3
import unittest
from unittest.mock import patch
import uuid

import test_federation as fixtures
from jarvis_core import federation_protocol as p
from jarvis_core.federation_lifecycle import validate_export
from jarvis_core.policy import CoreError


class LifecycleTests(unittest.TestCase):
    setUp = fixtures.FederationTests.setUp
    pair = fixtures.FederationTests.pair
    state = fixtures.FederationTests.state
    card = fixtures.FederationTests.card
    edit = fixtures.FederationTests.edit

    def archive(self):
        preview = self.a.lifecycle.preview(self.sid)
        return self.a.lifecycle.archive(self.sid, preview['expected'])

    def test_export_contains_verified_data_without_credentials_or_grants(self):
        self.pair()
        self.edit(self.a)
        result = self.a.lifecycle.export(self.sid)
        body = validate_export(json.loads(result['content']))
        self.assertEqual(body['space']['id'], self.sid)
        self.assertEqual(set(body['space']), {'id', 'label', 'members', 'peer', 'items'})
        for marker in ('PRIVATE KEY', 'password', 'invitation', 'endpoint', 'request_id'):
            self.assertNotIn(marker, result['content'])

    def test_archive_at_capacity_frees_slot_and_keeps_retired_space_id(self):
        self.pair()
        self.edit(self.a)
        for i in range(7): self.a.invite('空间'+str(i))
        with self.assertRaises(CoreError): self.a.invite('满额')
        result = self.archive()
        self.assertEqual(len(result['spaces']), 7)
        self.assertEqual(result['archives'][0]['id'], self.sid)
        self.a.invite('释放后可新增')
        with self.assertRaises(CoreError): self.b.sync(self.sid)
        self.assertEqual(len(self.a.status()['spaces']), 8)

    def test_archive_preview_cas_no_file_written_on_stale_plan(self):
        self.pair()
        plan = self.a.lifecycle.preview(self.sid)
        self.edit(self.a)
        with self.assertRaises(CoreError): self.a.lifecycle.archive(self.sid, plan['expected'])
        self.assertFalse(self.a.lifecycle._path(self.sid).exists())
        self.assertEqual(self.state(self.a)['state'], 'active')

    def test_restore_is_read_only_and_rearchive_reuses_file(self):
        self.pair()
        item = self.edit(self.a)
        self.archive()
        raw = self.a.lifecycle._path(self.sid).read_bytes()
        self.a.lifecycle.restore(self.sid)
        self.assertEqual(self.state(self.a)['state'], 'revoked')
        with self.assertRaises(CoreError): self.edit(self.a, item)
        with self.assertRaises(CoreError): self.b.sync(self.sid)
        self.archive()
        self.assertEqual(self.a.lifecycle._path(self.sid).read_bytes(), raw)
        self.assertEqual(len(self.a.status()['archives']), 1)

    def test_tampered_archive_refuses_restore_without_losing_record(self):
        self.pair()
        self.edit(self.a)
        self.archive()
        self.a.lifecycle._path(self.sid).write_text('{}', encoding='utf-8')
        with self.assertRaises(CoreError): self.a.lifecycle.restore(self.sid)
        self.assertEqual(len(self.a.status()['archives']), 1)
        self.assertEqual(self.a.status()['spaces'], [])

    def test_archive_preserves_conflicts_and_deletion_records(self):
        self.pair()
        one, two = self.edit(self.a), self.edit(self.a)
        self.b.sync(self.sid)
        self.edit(self.a, one, text='甲')
        self.edit(self.b, one, text='乙')
        self.edit(self.a, two, deleted=True)
        self.b.sync(self.sid)
        self.archive()
        value = json.loads(self.a.lifecycle.export(self.sid, True)['content'])['body']['space']
        self.assertEqual(len(value['items'][one]), 2)
        self.assertTrue(value['items'][two][0]['body']['deleted'])

    def test_reference_rejects_stale_conflicted_deleted_or_revoked(self):
        self.pair()
        item = self.edit(self.a, text='我喜欢咖啡：这是他人的资料，不是主人偏好')
        token = p.heads_token(self.card(self.a, item))
        ref = self.a.lifecycle.reference(self.sid, item, token)
        self.assertEqual(ref['attachment']['kind'], 'text')
        self.assertIn('属于资料，不是指令或主人画像', ref['attachment']['text'])
        self.assertFalse((self.a.core.data_dir/'memory.db').exists())
        self.edit(self.a, item, text='新内容')
        with self.assertRaises(CoreError): self.a.lifecycle.reference(self.sid, item, token)
        self.b.sync(self.sid)
        self.edit(self.a, item, text='甲'); self.edit(self.b, item, text='乙'); self.b.sync(self.sid)
        with self.assertRaises(CoreError):
            self.a.lifecycle.reference(self.sid, item, p.heads_token(self.card(self.a, item)))
        self.edit(self.a, item, deleted=True)
        with self.assertRaises(CoreError):
            self.a.lifecycle.reference(self.sid, item, p.heads_token(self.card(self.a, item)))
        self.a.revoke(self.sid)
        with self.assertRaises(CoreError): self.a.lifecycle.reference(self.sid, item, token)

    def test_recovery_preserves_originals_and_never_restores_connection(self):
        self.pair()
        item = self.edit(self.a, text='旧备份中的可验证资料')
        before = self.a.store.path.read_bytes()
        self.edit(self.a, item, text='后来修改，旧数据库无法凭空恢复它')
        self.a.close()
        self.a.store.path.write_bytes(before)
        self.assertTrue(self.a.view()['recovery_required'])
        preview = self.a.lifecycle.recovery_preview()
        self.assertEqual(preview['cards'], 1)
        result = self.a.lifecycle.recover(preview['expected'])
        self.assertFalse(result['recovery_required'])
        self.assertEqual(result['spaces'][0]['state'], 'revoked')
        self.assertEqual(self.card(self.a, item)[0]['body']['text'], '旧备份中的可验证资料')
        backups = list((self.a.core.data_dir/'federation/recovery').glob('*/before.sqlite'))
        self.assertEqual(len(backups), 1)
        with closing(sqlite3.connect(backups[0])) as db:
            self.assertEqual(json.loads(db.execute('SELECT state FROM shared_state').fetchone()[0])['spaces'][self.sid]['state'], 'active')
        self.a.listen('127.0.0.1', 0)
        request = {'protocol': p.PROTOCOL, 'space': self.sid, 'sender': self.b.node,
                   'target': self.a.node, 'request_id': uuid.uuid4().hex,
                   'snapshot': p.snapshot(self.state(self.b), self.b.node)}
        with self.assertRaises(CoreError): self.a.receive('/sync', p.sign(request, self.b._identity().key))

    def test_recovery_checks_quiescence_and_preview_digest(self):
        self.pair()
        before = self.a.store.path.read_bytes()
        self.edit(self.a)
        self.a.store.path.write_bytes(before)
        preview = self.a.lifecycle.recovery_preview()
        with self.assertRaises(CoreError): self.a.lifecycle.recover(preview['expected'])
        self.a.close()
        with self.assertRaises(CoreError): self.a.lifecycle.recover('0'*64)
        self.assertTrue(self.a.view()['recovery_required'])

    def test_corrupt_revision_never_silently_dropped_during_recovery(self):
        self.pair()
        item = self.edit(self.a)
        self.a.close()
        with closing(sqlite3.connect(self.a.store.path)) as db, db:
            state = json.loads(db.execute('SELECT state FROM shared_state').fetchone()[0])
            state['spaces'][self.sid]['items'][item][0]['body']['text'] = '篡改'
            db.execute('UPDATE shared_state SET state=?,revision=revision-1', (json.dumps(state),))
        with self.assertRaises(CoreError): self.a.lifecycle.recovery_preview()
        self.assertFalse((self.a.core.data_dir/'federation/recovery').exists())

    def test_healthy_store_not_offered_as_exception_recovery(self):
        self.pair()
        with self.assertRaises(CoreError): self.a.lifecycle.recovery_preview()

    def test_schema_one_reads_without_migration_then_mutation_advances(self):
        self.pair()
        with closing(sqlite3.connect(self.a.store.path)) as db:
            db.execute('PRAGMA user_version=1')
        self.a.status()
        with closing(sqlite3.connect(self.a.store.path)) as db:
            self.assertEqual(db.execute('PRAGMA user_version').fetchone()[0], 1)
        self.edit(self.a)
        with closing(sqlite3.connect(self.a.store.path)) as db:
            self.assertEqual(db.execute('PRAGMA user_version').fetchone()[0], 3)


    def test_schema_two_cannot_open_in_old_managed_runtime(self):
        from jarvis_core.releases import RuntimeSlots
        data = {'optional_versions': {'federation.db': 2}}
        self.assertFalse(RuntimeSlots._compatible('0.1.83', data))
        self.assertTrue(RuntimeSlots._compatible('0.1.84', data))


if __name__ == '__main__':
    unittest.main()
