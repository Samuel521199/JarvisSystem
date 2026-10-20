"""Actual knowledge path delegates only ranking; scope/citation ownership stays."""
import json
from pathlib import Path
import unittest
from test_knowledge import KnowledgeTests
from jarvis_core.knowledge import KnowledgeStore, normalized, terms
from jarvis_core.retrieval_ranking import rank, lexical_score, LexicalV1, CoverageV2


class RankingTests(KnowledgeTests):
    def test_default_compatible_and_candidate_can_be_swapped_without_data_migration(self):
        self.put()
        snapshot=self.store.snapshot(self.ctx,'local')
        old=self.store.context(snapshot,'离线部署')
        other=KnowledgeStore(self.core,ranking=CoverageV2()).context(snapshot,'离线部署')
        self.assertEqual(old[0],other[0]);self.assertEqual(old[1]['citations'],other[1]['citations'])
        self.assertEqual(old[1]['ranking']['used'],'lexical-v1')
        self.assertEqual(other[1]['ranking']['used'],'coverage-v2')
        self.assertEqual(self.store.context(snapshot,'离线部署')[0],old[0])

    def test_bad_order_cannot_inject_or_suppress_sources_and_falls_back(self):
        self.put();snapshot=self.store.snapshot(self.ctx,'local');baseline=self.store.context(snapshot,'离线部署')
        for bad in ([0,0],[-1],[100],[],[True]):
            class Invalid:
                protocol=1;module_id='test-invalid'
                def order(self,rows,words):return bad
            value=KnowledgeStore(self.core,ranking=Invalid()).context(snapshot,'离线部署')
            self.assertEqual(value[0],baseline[0])
            self.assertTrue(value[1]['ranking']['fallback'])
            self.assertEqual(value[1]['ranking']['used'],'lexical-v1')

    def test_immutable_input_and_protocol_mismatch(self):
        rows=[{'score':1,'path':'a','start_line':1,'text':'x','heading':'y'}]
        class Mutates:
            protocol=1;module_id='test-mutate'
            def order(self,items,words):items[0]['text']='tampered'
        self.assertTrue(rank(rows,['x'],Mutates())[1]['fallback'])
        self.assertEqual(rows[0]['text'],'x')
        class Wrong:
            protocol=2;module_id='test-protocol'
            def order(self,*a):raise AssertionError('must not execute incompatible adapter')
        self.assertEqual(rank(rows,['x'],Wrong())[0],[0])
        self.assertTrue(rank(rows,['x'],Wrong())[1]['fallback'])

    def test_restricted_provider_never_passes_content_to_ranker(self):
        self.put(['vertex'])
        class Observe:
            protocol=1;module_id='test-observe'
            def order(self,rows,words):
                if rows:raise AssertionError('unauthorized content')
                return []
        store=KnowledgeStore(self.core,ranking=Observe())
        text,meta=store.context(store.snapshot(self.ctx,'openai'),'离线')
        self.assertEqual(text,'');self.assertFalse(meta['ranking']['fallback'])

    def test_frozen_development_set_reports_both_algorithms(self):
        cases=json.loads((Path(__file__).resolve().parents[1]/'evals/cases/k5-ranking-v1.json').read_text(encoding='utf-8'))['cases']
        scores=[]
        for adapter in (LexicalV1(),CoverageV2()):
            passed=0
            for case in cases:
                words=terms(case['query']);rows=[]
                for d in case['documents']:
                    text=normalized(d['text']);heading=normalized(d['title']+' '+d['path'])
                    score=lexical_score(text,heading,words)
                    if score:rows.append({'score':score,'path':d['path'],'start_line':1,'text':text,'heading':heading})
                order,_=rank(rows,words,adapter)
                actual=rows[order[0]]['path'].split('.')[0] if order else None
                passed+=actual==case['expected']
            scores.append(passed)
        self.assertEqual(scores,[6,12])


for _name in dir(KnowledgeTests):
    if _name.startswith('test_') and _name not in RankingTests.__dict__:setattr(RankingTests,_name,None)
del KnowledgeTests

if __name__=='__main__':unittest.main()
