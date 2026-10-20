"""Real knowledge-path selection, source rejection, recovery and independent eval."""
import json
import sqlite3
import time
import unittest
import uuid
from unittest.mock import patch

from test_knowledge import KnowledgeTests
from jarvis_core import policy
from jarvis_core.knowledge import KnowledgeStore
from jarvis_core.evolution.manager import EvolutionManager
from jarvis_core.evolution.ranking_module import RankingModules
from jarvis_core.ranking_evaluation import binding, evaluate
from jarvis_core.ranking_program import Program, compile_source, source_for
from jarvis_core.ranking_registry import read_version, select_row
from jarvis_core.retrieval_ranking import rank
from jarvis_core.releases import RuntimeSlots

SOURCE = source_for(('coverage', 'score', 'path', 'start_line'))


class RankingModuleTests(KnowledgeTests):
    def setUp(self):
        super().setUp()
        self.manager = EvolutionManager(self.core, monitor=False)
        self.addCleanup(self.manager.close)
        self.service = RankingModules(self.manager)
        self.manager.ranking_modules = self.service
        self.service.recover()

    def version(self, passed=True):
        value = dict(source=SOURCE, keys=list(compile_source(SOURCE)), binding=binding(),
                     evaluation={'passed':passed}, notes='Lifecycle fixture, not measured quality.', created_at='test')
        ident = policy.digest(policy.canonical_json(value).encode())[7:]
        with self.manager.store.connection() as db:
            db.execute('INSERT OR IGNORE INTO ranking_versions VALUES(?,?)', (ident,policy.canonical_json(value)))
        return ident

    def action(self, action, version, **changes):
        with self.manager.store.connection() as db: selected = select_row(db)
        payload = dict(action=action,version=version,generation=selected['generation'],
                       review='测试夹具：核对排序结果与独立评价范围。',**changes)
        return self.service.transition(payload),payload

    def observe(self, queries=('离线','部署','状态')):
        for query in queries:
            text,meta = self.store.context(self.store.snapshot(self.ctx,'local'),query)
            self.assertTrue(text);self.assertFalse(meta['ranking']['fallback'])

    def test_entire_source_is_verified_not_just_an_extracted_lambda(self):
        for bad in (SOURCE+'\nopen("secret")', SOURCE.replace('return ', 'import os\n    return '),
                    SOURCE.replace('data[i]["score"]','data[i]["score"] + 1'),
                    SOURCE.replace('def transform(data)', 'def transform(data=[])'),
                    SOURCE.replace('","', '"shell:"'),
                    SOURCE.replace('sorted(', 'eval('),
                    SOURCE.replace('-data[i]["coverage"]', 'data[i]["coverage"]')):
            with self.subTest(source=bad),self.assertRaises((ValueError,SyntaxError)):compile_source(bad)

    def test_real_knowledge_trial_confirmation_restart_and_rollback(self):
        self.put();ident=self.version()
        old=self.view()[0]
        selected,payload=self.action('trial',ident)
        self.assertEqual(self.service.transition(payload),selected)
        with self.assertRaises(policy.CoreError):self.action('confirm',ident)
        self.observe()
        confirmed,_=self.action('confirm',ident)
        self.service.recover()
        other=KnowledgeStore(self.core)
        result=other.context(other.snapshot(self.ctx,'local'),'离线部署')
        self.assertEqual(result[1]['ranking']['used'],ident)
        self.assertEqual(old,result[0])
        with self.manager.store.connection() as db:self.assertEqual(select_row(db)['active'],confirmed['active'])
        self.action('rollback',ident)
        self.assertEqual(self.view()[1]['ranking']['used'],'lexical-v1')

    def test_unconfirmed_restart_reverts_and_does_not_regenerate(self):
        ident=self.version();self.action('trial',ident)
        self.service.recover()
        snap=self.service.snapshot()
        self.assertIsNone(snap['selection']['active'])
        self.assertEqual(snap['selection']['last_event'],'unconfirmed_trial_restart_rollback')
        self.assertEqual(snap['jobs'],[])

    def test_duplicate_queries_and_no_match_do_not_satisfy_observation(self):
        self.put();ident=self.version();self.action('trial',ident)
        self.observe(('离线','离线','离线'))
        self.view(query='unmatched')
        self.assertEqual(len(self.service.snapshot()['selection']['samples']),1)
        with self.assertRaises(policy.CoreError):self.action('confirm',ident)

    def test_changed_source_falls_back_preserving_citations_and_rolls_back(self):
        self.put();ident=self.version();self.action('trial',ident)
        expected=self.view()[1]['citations']
        with self.manager.store.connection() as db:
            doc=json.loads(db.execute('SELECT document FROM ranking_versions WHERE id=?',(ident,)).fetchone()[0])
            doc['source']='def transform(data):\n    while True: pass\n'
            db.execute('UPDATE ranking_versions SET document=? WHERE id=?',(json.dumps(doc),ident))
        text,meta=self.view()
        self.assertTrue(meta['ranking']['fallback']);self.assertEqual(meta['citations'],expected)
        self.assertIsNone(self.service.snapshot()['selection']['active'])

    def test_rejected_candidate_stale_selection_and_runtime_binding_are_blocked(self):
        failed=self.version(False)
        with self.assertRaises(policy.CoreError):self.action('trial',failed)
        ident=self.version()
        _,payload=self.action('trial',ident)
        with self.assertRaises(policy.CoreError):self.service.transition(dict(payload,action='baseline'))
        self.action('baseline',ident)
        with patch('jarvis_core.ranking_evaluation.binding',return_value='changed'):
            with self.assertRaises(policy.CoreError):self.action('trial',ident)

    def test_actual_lpac_matches_interpreter_and_independent_holdout_improves(self):
        evidence=evaluate(SOURCE,self.manager.runner,self.manager._checkpoint)
        self.assertTrue(evidence['passed'],evidence)
        self.assertEqual(evidence['candidate']-evidence['baseline'],8)
        self.assertLess(evidence['candidate'],evidence['total'])  # Known semantic failures remain visible.
        self.assertTrue(all(x['equivalent'] for x in evidence['cases']))
        self.assertTrue(evidence['isolation'])

    def test_scope_denial_never_counts_a_trial_sample(self):
        self.put(['vertex']);ident=self.version();self.action('trial',ident)
        result=self.view(provider='openai')
        self.assertEqual(result[0],'')
        self.assertEqual(self.service.snapshot()['selection']['samples'],[])

    def test_old_runtime_cannot_ignore_new_selection_store(self):
        data={'optional_versions':{'evolution/evolution.db':8}}
        self.assertFalse(RuntimeSlots._compatible('0.1.78',data))
        self.assertTrue(RuntimeSlots._compatible('0.1.79',data))

    def test_unknown_generation_is_one_dispatch_and_durable_on_retry(self):
        class Transport:
            calls=0
            def probe(self,*args,**kwargs):
                assert 'security_epoch' in args[4]()
                self.calls+=1
                return {'status':'UNKNOWN','dispatched':True,'outcome_uncertain':True}
        transport=Transport();self.service.model_calls=transport
        payload={'request_id':uuid.uuid4().hex,'model':'vertex::gemini-3.8-flash'}
        with patch.object(self.manager.provider,'configuration',return_value=({},'vertex')),patch.object(self.manager.provider,'receipt',return_value={'status':'UNKNOWN'}):
            job=self.service.submit(payload)
            end=time.monotonic()+10
            while self.manager.busy and time.monotonic()<end:time.sleep(.02)
            again=self.service.submit(payload)
        self.assertEqual(transport.calls,1)
        self.assertEqual(again['id'],job['id']);self.assertEqual(again['status'],'UNKNOWN')
        self.assertEqual(self.service.snapshot()['versions'],[])

    def test_interrupted_generation_restart_does_not_replay(self):
        job,_=self.manager.store.create_job({'action':'ranking-improve','request_id':uuid.uuid4().hex,
                                             'model':'fixture','binding':binding()})
        self.manager.store.update(job,status='RUNNING',model_outcome='UNKNOWN')
        self.manager.store.recover()
        recovered=self.manager.store.job(job['id'])
        self.assertEqual(recovered['status'],'INTERRUPTED')
        self.assertEqual(recovered['model_outcome'],'UNKNOWN')
        self.assertEqual(self.service.snapshot()['versions'],[])

    def test_unknown_store_schema_uses_builtin_without_modification(self):
        self.put();ident=self.version();self.action('trial',ident)
        with self.manager.store.connection() as db:db.execute('PRAGMA user_version=99')
        _,meta=self.view()
        self.assertTrue(meta['ranking']['fallback']);self.assertEqual(meta['ranking']['used'],'lexical-v1')
        with self.manager.store.connection() as db:
            self.assertEqual(db.execute('PRAGMA user_version').fetchone()[0],99)
            self.assertEqual(select_row(db)['active'],ident)

    def test_old_schema_migrates_without_changing_existing_business_records(self):
        with self.manager.store.connection() as db:
            previous=[tuple(x) for x in db.execute('SELECT * FROM selection')]
            db.execute('DROP TABLE ranking_versions');db.execute('DROP TABLE ranking_selection')
            db.execute('PRAGMA user_version=7')
        from jarvis_core.evolution.store import EvolutionStore
        reopened=EvolutionStore(self.core,'vertex::gemini-3.8-flash')
        with reopened.connection() as db:
            self.assertEqual([tuple(x) for x in db.execute('SELECT * FROM selection')],previous)
            self.assertEqual(db.execute('PRAGMA user_version').fetchone()[0],8)
            self.assertIsNone(select_row(db)['active'])

    def test_slow_trial_rolls_back_without_removing_source_or_mutating_memory(self):
        self.put();ident=self.version();self.action('trial',ident)
        selected=self.service.snapshot()['selection']
        with self.assertRaises(ValueError):
            self.store.ranking._observe(selected,'fake-query-digest',.06)
        # Same as the real adapter's enclosing exception path.
        self.store.ranking._reject(selected)
        self.assertIsNone(self.service.snapshot()['selection']['active'])
        self.assertTrue(self.file.exists())
        self.assertFalse((self.core.data_dir/'memory.db').exists())


for name in dir(KnowledgeTests):
    if name.startswith('test_') and name not in RankingModuleTests.__dict__:
        setattr(RankingModuleTests,name,None)
del KnowledgeTests

if __name__=='__main__':unittest.main()
