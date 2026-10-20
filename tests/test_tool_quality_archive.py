"""Bounded contract observations and reversible, scope-bound version storage."""
import copy
import json
import unittest
import tracemalloc
from unittest.mock import patch
from test_project_tools import ProjectToolTests
from jarvis_core import policy
from jarvis_core.evolution.quality import inspect_contract,require_consistent
from jarvis_core.evolution.tool_archive import ToolArchive,capacity
from jarvis_core.evolution.lifecycle import ToolLifecycle
from jarvis_core.releases import RuntimeSlots


class QualityTests(unittest.TestCase):
    def test_counts_conflicts_duplicates_overlap_and_never_certifies_semantic_truth(self):
        c=lambda i,e:{'input':i,'expected':e}
        good=inspect_contract([c('', '0'),c('中文','2')],[c('ab','2'),c('hello','5')])
        self.assertTrue(good['structurally_consistent']);self.assertFalse(good['semantic_truth_verified'])
        self.assertIn('unicode',good['observed_features']);self.assertEqual(good['model_calls'],0)
        for pub,hidden in [([c(1,'1'),c(1,'2')],[c(2,'2')]),([c(1,'1')],[c(1,'1')]),([c(1,'1'),c(1,'1')],[c(2,'2')])]:
            with self.assertRaises(policy.CoreError):require_consistent(inspect_contract(pub,hidden))
        weak=inspect_contract([c(0,'0'),c(1,'0')],[c(2,'0'),c(3,'0')])
        self.assertTrue(weak['structurally_consistent']);self.assertGreaterEqual(len(weak['review_questions']),2)


class ArchiveTests(ProjectToolTests):
    def life(self):return ToolLifecycle(self.tools)
    def seed(self,state='RETIRED',name='old'):
        with self.evolution.store.connection() as db:row=db.execute('SELECT document FROM tool_versions LIMIT 1').fetchone()
        if row is None:
            self.completed(self.request(task_id=self.candidate()))
            with self.evolution.store.connection() as db:row=db.execute('SELECT document FROM tool_versions LIMIT 1').fetchone()
        doc=json.loads(row[0]);doc['metadata']['name']=name
        ident=policy.digest(policy.canonical_json(doc).encode())[7:]
        with self.evolution.store.connection() as db:db.execute('INSERT INTO tool_versions VALUES(?,?,?)',(ident,state,policy.canonical_json(doc)))
        return ident,doc

    def test_archive_load_idempotency_and_receipts_keep_stable_and_source(self):
        ident,doc=self.seed();before=capacity(self.evolution.store);source=(self.source/'calc.py').read_bytes()
        payload=self.request('archive-version',version=ident);job=self.completed(payload)
        self.assertEqual(self.tools.submit(self.cid,payload)['id'],job['id'])
        self.assertTrue(job['result']['online_slot_released']);self.assertGreater(job['result']['online_payload_bytes_released'],0)
        self.assertEqual(capacity(self.evolution.store)['online_versions'],before['online_versions']-1)
        with self.assertRaises(policy.CoreError):self.tools.package(ident)
        archive=self.evolution.store.root/'tool-archives'/(ident+'.json');original=archive.read_bytes()
        self.completed(self.request('load-version',version=ident));self.assertEqual(self.tools.package(ident)[1],'RETIRED')
        self.assertEqual(self.tools.package(ident)[0],doc);self.assertEqual(archive.read_bytes(),original)
        self.assertEqual(self.completed(self.request('run',input=[42],expected='42'))['result']['text'],'42')
        self.assertEqual((self.source/'calc.py').read_bytes(),source)
        self.assertFalse(RuntimeSlots._compatible('0.1.75',{'optional_versions':{'evolution/evolution.db':5}}))

    def test_live_recovery_refs_and_unretired_versions_cannot_archive(self):
        ident,_=self.seed(state='VERIFIED')
        self.assertEqual(self.completed(self.request('archive-version',version=ident),False)['status'],'FAILED')
        active=self.tools.selected(self.project['id'],'sum-tool')['active']
        self.assertEqual(self.completed(self.request('archive-version',version=active),False)['status'],'FAILED')
        with self.evolution.store.connection() as db:
            doc=json.loads(db.execute('SELECT document FROM tool_lifecycle').fetchone()[0]);doc['retired_version']=ident
            db.execute('UPDATE tool_lifecycle SET document=?',(policy.canonical_json(doc),))
            db.execute("UPDATE tool_versions SET state='RETIRED' WHERE id=?",(ident,))
        self.assertEqual(self.completed(self.request('archive-version',version=ident),False)['status'],'FAILED')

    def test_corrupt_archive_cannot_load_or_be_overwritten_and_scope_is_strict(self):
        ident,_=self.seed();self.completed(self.request('archive-version',version=ident))
        path=self.evolution.store.root/'tool-archives'/(ident+'.json');path.write_bytes(b'corrupt')
        self.assertEqual(self.completed(self.request('load-version',version=ident),False)['status'],'FAILED')
        with self.evolution.store.connection() as db:self.assertEqual(db.execute('SELECT state FROM tool_versions WHERE id=?',(ident,)).fetchone()[0],'ARCHIVED')
        service=ToolArchive(self.life())
        with self.assertRaises(policy.CoreError):service.record(ident,{'project_id':'foreign','tool_id':'sum-tool'})
        with self.assertRaises(policy.CoreError):service.save(ident,b'valid different archive')
        self.assertEqual(path.read_bytes(),b'corrupt')

    def test_archive_before_db_failure_leaves_original_and_retry_uses_same_bytes(self):
        ident,_=self.seed();service=ToolArchive(self.life())
        with patch.object(ToolLifecycle,'write',side_effect=policy.CoreError('injected','before commit')):
            self.assertEqual(self.completed(self.request('archive-version',version=ident),False)['status'],'FAILED')
        self.assertEqual(self.tools.package(ident)[1],'RETIRED')
        path=self.evolution.store.root/'tool-archives'/(ident+'.json');before=path.read_bytes()
        self.completed(self.request('archive-version',version=ident));self.assertEqual(path.read_bytes(),before)

    def test_online_limit_released_but_restoration_respects_capacity(self):
        ident,_=self.seed();self.completed(self.request('archive-version',version=ident))
        for i in range(63):self.seed(name='filler-'+str(i))
        self.assertEqual(capacity(self.evolution.store)['online_versions'],64)
        self.assertEqual(self.completed(self.request('load-version',version=ident),False)['status'],'FAILED')
        with self.evolution.store.connection() as db:self.assertEqual(db.execute('SELECT state FROM tool_versions WHERE id=?',(ident,)).fetchone()[0],'ARCHIVED')

    def test_capacity_summary_has_bounded_memory_with_large_stored_packages(self):
        # Capacity is an aggregate view; large synthetic payloads must stay in SQLite.
        with self.evolution.store.connection() as db:
            for i in range(48):db.execute('INSERT INTO tool_versions VALUES(?,?,?)',(str(i).zfill(64),'RETIRED','x'*200000))
        tracemalloc.start()
        try:
            summary=capacity(self.evolution.store);peak=tracemalloc.get_traced_memory()[1]
        finally:tracemalloc.stop()
        self.assertEqual(summary['online_versions'],48);self.assertLess(peak,1024*1024)


for name in dir(ProjectToolTests):
    if name.startswith('test_') and name not in ArchiveTests.__dict__:setattr(ArchiveTests,name,None)
del ProjectToolTests
