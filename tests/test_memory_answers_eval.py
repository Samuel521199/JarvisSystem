"""Check evidence/rubric failures separately from synthetic language success."""
import copy
from pathlib import Path
import sys
import unittest

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'tools'))
import eval_memory_answers as ev


class AnswerEvaluationTests(unittest.TestCase):
    def test_all_lifecycle_contexts_with_fixture_transport(self):
        for case in ev.load_cases(ev.CASES)['cases']:
            with self.subTest(case=case['id']):
                rows=ev.evaluate(case,'vertex','gemini-3.1-pro-preview')
                self.assertEqual(len(rows),2)
                for row in rows:self.assertTrue(row['score']['passed'],row['score'])

    def test_failure_partial_and_wrong_answer_cannot_pass(self):
        case=ev.load_cases(ev.CASES)['cases'][0]
        for result in [{'status':'FAILED'},{'status':'SUCCEEDED','text':'茉莉花茶','output_incomplete':True},
                       {'status':'SUCCEEDED','text':'西湖龙井'}]:
            with self.subTest(result=result):
                rows=ev.evaluate(case,'vertex','gemini-3.1-pro-preview',transport=lambda *a,**k:copy.deepcopy(result))
                self.assertFalse(rows[0]['score']['passed'])

    def test_correct_keyword_without_injected_evidence_does_not_pass(self):
        case=ev.load_cases(ev.CASES)['cases'][0]
        result={'status':'SUCCEEDED','text':case['expected'],'history_info':{'memory':{'references':[]}}}
        score=ev.rubric(case,'memory',result,[{'message':case['query'],'history':[]}],'f'*32)
        self.assertTrue(score['checks']['answer_keyword_or_abstention'])
        self.assertFalse(score['checks']['context_evidence_expected'])
        self.assertFalse(score['passed'])

    def test_abstention_that_repeats_forgotten_fact_fails(self):
        case=ev.load_cases(ev.CASES)['cases'][2]
        result={'status':'SUCCEEDED','text':'我不知道你是不是喜欢金骏眉。'}
        score=ev.rubric(case,'memory',result,[{'message':case['query'],'history':[]}],'f'*32)
        self.assertTrue(score['checks']['answer_keyword_or_abstention'])
        self.assertFalse(score['checks']['old_or_excluded_fact_absent'])
        self.assertFalse(score['passed'])


if __name__=='__main__':unittest.main()
