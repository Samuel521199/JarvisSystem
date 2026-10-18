"""Candidate provenance, revocation, migration, and route/history regressions."""
import copy
from contextlib import closing
import json
import sqlite3
import sys
from pathlib import Path
import unittest
from unittest.mock import patch
import uuid

sys.path[:0] = [str(Path(__file__).resolve().parent), str(Path(__file__).resolve().parents[1]/'runtime/node-host')]
import test_personal_candidates as candidates
from jarvis_core.memory import MemoryStore, MemoryError
from jarvis_core.memory_sources import source_key
from jarvis_core.service import CoreService
from jarvis_core.personal_candidates import PersonalCandidates
from jarvis_core.policy import CoreError


class MemorySourceTests(unittest.TestCase):
    setUp = candidates.CandidateTests.setUp
    payload = candidates.CandidateTests.payload

    def save(self):
        payload = self.payload()
        receipt = self.service.confirm(payload)['receipt']
        return payload, receipt, MemoryStore(self.core)

    def replace_source(self, **changes):
        self.doc['messages'][0].update(changes)
        revision = self.archives.get(self.cid)['revision']
        self.archives.put(self.cid, {'revision':revision, 'document':self.doc})

    def test_source_reference_survives_restart_and_original_is_not_copied_to_model(self):
        payload, receipt, memory = self.save()
        memory = MemoryStore(CoreService(self.core.data_dir))
        row = memory.list()['facts'][0]
        source = row['provenance']['source_ref']
        self.assertEqual(source['conversation_id'], self.cid)
        self.assertEqual(source['sha256'], payload['source_digest'])
        self.assertEqual(source['candidate_id'], payload['candidate']['candidate_id'])
        self.assertEqual(row['provenance']['state'], 'current')
        self.assertIn('旅行安排', row['provenance']['excerpt'])
        text, report = memory.context({'enabled':True,'project_id':None},'local')
        self.assertIn('无糖茶', text)
        self.assertNotIn('旅行安排', text)
        self.assertNotIn(self.cid, text)
        self.assertEqual(report['references'],[{'id':receipt['id'],'revision':1}])

    def test_append_and_title_change_do_not_invalidate_same_message(self):
        _, _, memory = self.save()
        self.doc['title'] = '改名'
        self.doc['messages'].append(copy.deepcopy(self.doc['messages'][0]))
        self.archives.put(self.cid, {'revision':1,'document':self.doc})
        self.assertEqual(memory.list()['facts'][0]['provenance']['state'], 'current')
        self.assertTrue(memory.view_facts({'enabled':True,'project_id':None},'local'))

    def test_source_edit_retracts_context_and_history_but_not_panel_record(self):
        _, receipt, memory = self.save()
        context = {'enabled':True,'project_id':None}
        stale = memory.view_facts(context,'local')
        self.replace_source(content='我更喜欢咖啡')
        self.assertEqual(memory.list()['facts'][0]['provenance']['state'],'source_changed_or_missing')
        self.assertEqual(memory.context(context,'local',facts=stale)[0],'')
        history=[{'role':'user','content':'之前'},{'role':'assistant','content':'旧回答'}]
        refs=[[],[{'id':receipt['id'],'revision':1}]]
        self.assertEqual(memory.filter_history(history,refs,context,'local',facts=stale)[0],[])

    def test_flag_change_and_deleted_archive_stop_candidate_use(self):
        _, _, memory = self.save()
        self.replace_source(task_control=True)
        self.assertEqual(memory.view_facts({'enabled':True,'project_id':None},'local'),[])
        self.archives.delete(self.cid,{'revision':2})
        self.assertEqual(memory.list()['facts'][0]['provenance']['state'],'source_changed_or_missing')

    def test_forget_blocks_renamed_edited_and_rescoped_candidate(self):
        payload, receipt, memory = self.save()
        memory.delete(receipt['id'],{'revision':1})
        for edit in ({'title':'换个名称'},{'content':'换个内容'}):
            other=copy.deepcopy(payload);other['candidate'].update(edit)
            with self.assertRaises(MemoryError) as exc:self.service.confirm(other)
            self.assertEqual(exc.exception.code,'candidate_suppressed')
        other=copy.deepcopy(payload);other['scope']='global'
        with self.assertRaises(MemoryError) as exc:self.service.confirm(other)
        self.assertEqual(exc.exception.code,'candidate_suppressed')
        self.assertTrue(self.service.confirm(payload)['receipt']['replayed'])
        self.assertEqual(memory.list()['facts'],[])
        with memory.connection() as db:
            self.assertIsNone(db.execute('SELECT source_json FROM fact_origins').fetchone()[0])
            self.assertEqual(db.execute('SELECT suppressed FROM candidate_bindings').fetchone()[0],1)
        self.assertNotIn(self.cid.encode(), memory.path.read_bytes())
        # The explicit owner command remains available and does not clear suppression.
        memory.command('remember','新决定','我现在确实喜欢茶',request_id=uuid.uuid4().hex)
        self.assertEqual(len(memory.list()['facts']),1)

    def test_owner_correction_detaches_source_and_old_candidate_cannot_overwrite(self):
        payload, receipt, memory = self.save()
        memory.command('correct',receipt['id'],'现在喜欢咖啡',request_id=uuid.uuid4().hex)
        self.archives.delete(self.cid,{'revision':1})
        text,_=memory.context({'enabled':True,'project_id':None},'local')
        self.assertIn('现在喜欢咖啡',text)
        self.assertEqual(memory.list()['facts'][0]['provenance']['state'],'independent')

    def test_correction_blocks_old_source_even_if_edited_preview_changes_name(self):
        payload, receipt, memory = self.save()
        row=memory.list()['facts'][0]
        memory.put(row['id'],{'revision':1,'document':{**row['document'],'content':'新偏好'}})
        payload['candidate']['title']='旧偏好另存'
        with self.assertRaises(MemoryError) as exc:self.service.confirm(payload)
        self.assertEqual(exc.exception.code,'candidate_suppressed')
        self.assertEqual(len(memory.list()['facts']),1)

    def test_provider_change_does_not_detach_and_cloud_never_gets_source_excerpt(self):
        _, _, memory=self.save();row=memory.list()['facts'][0]
        memory.put(row['id'],{'revision':1,'document':{**row['document'],'providers':['vertex']}})
        self.assertEqual(memory.context({'enabled':True,'project_id':None},'openai')[0],'')
        text,_=memory.context({'enabled':True,'project_id':None},'vertex')
        self.assertNotIn('旅行安排',text)
        self.replace_source(content='我喜欢另一个东西')
        self.assertEqual(memory.context({'enabled':True,'project_id':None},'vertex')[0],'')

    def test_explicit_reaffirm_is_idempotent_and_preserves_provider_permissions(self):
        _, _, memory=self.save();row=memory.list()['facts'][0]
        self.archives.delete(self.cid,{'revision':1})
        payload={'revision':1,'document':row['document'],'reaffirm_source':True}
        self.assertEqual(memory.put(row['id'],payload)['revision'],2)
        self.assertEqual(memory.put(row['id'],payload)['revision'],2)
        self.assertEqual(memory.list()['facts'][0]['provenance']['state'],'independent')
        self.assertTrue(memory.context({'enabled':True,'project_id':None},'local')[0])
        self.assertEqual(memory.context({'enabled':True,'project_id':None},'vertex')[0],'')

    def test_distinct_facts_in_one_message_have_independent_identities(self):
        self.replace_source(content='我喜欢茶。我习惯早睡。')
        first=self.payload(0);first['candidate']['title']='喝茶'
        second=self.payload(1);second['candidate']['title']='作息'
        a=self.service.confirm(first)['receipt'];self.service.confirm(second)
        memory=MemoryStore(self.core);memory.delete(a['id'],{'revision':1})
        self.assertEqual(len(memory.list()['facts']),1)
        self.assertIn('早睡',memory.context({'enabled':True,'project_id':None},'local')[0])

    def test_tampered_identity_and_ambiguous_legacy_edit_rejected(self):
        body=self.payload();body['candidate']['candidate_id']='f'*64
        with self.assertRaises(MemoryError):self.service.confirm(body)
        self.replace_source(content='我喜欢茶。我习惯早睡。')
        body=self.payload();body['candidate'].pop('candidate_id');body['candidate']['content']='改过的内容'
        with self.assertRaises(MemoryError):self.service.confirm(body)

    def test_bounded_source_validation_fails_closed(self):
        _, _, memory=self.save()
        with patch('jarvis_core.memory_sources.MAX_SOURCE_CHATS',0):
            self.assertEqual(memory.list()['facts'][0]['provenance']['state'],'unchecked')
            self.assertEqual(memory.context({'enabled':True,'project_id':None},'local')[0],'')
        with patch('jarvis_core.memory_sources.MAX_SOURCE_BYTES',1):
            self.assertEqual(memory.context({'enabled':True,'project_id':None},'local')[0],'')

    def test_binding_and_fact_commit_or_rollback_together(self):
        memory=MemoryStore(self.core)
        with memory.connection() as db:
            db.execute("CREATE TRIGGER deny_binding BEFORE INSERT ON candidate_bindings BEGIN SELECT RAISE(ABORT,'fixture'); END")
        with self.assertRaises(CoreError):self.service.confirm(self.payload())
        self.assertEqual(memory.list()['facts'],[])
        with memory.connection() as db:
            for table in ('facts','receipts','fact_origins','candidate_bindings','chat_commands'):
                # chat_commands is created in the same transaction and can be absent.
                exists=db.execute('SELECT 1 FROM sqlite_master WHERE name=?',(table,)).fetchone()
                if exists:self.assertEqual(db.execute('SELECT count(*) FROM '+table).fetchone()[0],0)

    def test_existing_independent_fact_is_not_made_dependent_by_matching_candidate(self):
        memory=MemoryStore(self.core);body=self.payload();item=body['candidate']
        original=memory.command('remember',item['title'],item['content'],request_id=uuid.uuid4().hex)
        result=self.service.confirm(body)['receipt'];self.assertEqual(original['id'],result['id'])
        self.archives.delete(self.cid,{'revision':1})
        self.assertTrue(memory.context({'enabled':True,'project_id':None},'local')[0])

    def test_second_source_cannot_silently_rebind_a_paused_fact(self):
        payload, _, memory=self.save()
        self.replace_source(content='我现在喜欢咖啡')
        other=uuid.uuid4().hex
        document=copy.deepcopy(self.doc);document['messages'][0]['content']='我平时喜欢无糖茶。'
        self.archives.put(other,{'revision':0,'document':document})
        query={'source':{'conversation_id':other,'message_index':0},'project_id':None}
        suggestion=self.service.suggest(query)
        payload={**query,'source_digest':suggestion['source_digest'],'candidate':suggestion['candidates'][0],'scope':'current'}
        with self.assertRaises(MemoryError) as exc:self.service.confirm(payload)
        self.assertEqual(exc.exception.code,'memory_conflict')
        self.assertEqual(memory.context({'enabled':True,'project_id':None},'local')[0],'')

    def test_v1_migration_preserves_facts_receipts_and_does_not_invent_provenance(self):
        memory=MemoryStore(self.core)
        ident=memory.command('remember','旧明确记忆','仍然保留',request_id=uuid.uuid4().hex)['id']
        with closing(sqlite3.connect(memory.path)) as db:
            before=[tuple(r) for r in db.execute('SELECT * FROM facts')]
            receipts=[tuple(r) for r in db.execute('SELECT * FROM receipts')]
            db.execute('DROP TABLE fact_origins');db.execute('DROP TABLE candidate_bindings');db.execute('PRAGMA user_version=1')
            db.commit()
        row=MemoryStore(CoreService(self.core.data_dir)).list()['facts'][0]
        self.assertEqual(row['id'],ident);self.assertIsNone(row['provenance']['source_ref'])
        with memory.connection() as db:
            self.assertEqual(db.execute('PRAGMA user_version').fetchone()[0],3)
            self.assertEqual(before,[tuple(r) for r in db.execute('SELECT * FROM facts')])
            self.assertEqual(receipts,[tuple(r) for r in db.execute('SELECT * FROM receipts')])


if __name__=='__main__':unittest.main()
