"""Evaluation integrity, independent of model output; no paid calls."""
import copy
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'tools'))
import eval_memory_extraction as evaluation


class ExtractionEvalTests(unittest.TestCase):
    def setUp(self):
        self.cases = evaluation.load_cases(evaluation.CASES)['cases']
        self.case = self.cases[0]
        self.item = {'segment': 0, 'quote': '我平时喜欢无糖茶', 'content': '我平时喜欢无糖茶',
                     'classification': {'kind': 'preference', 'subject': 'owner', 'subject_label': ''}}
        self.row = {'engine': 'semantic', 'status': 'SUCCEEDED', 'candidates': [self.item], 'elapsed_ms': 1}

    def test_corpus_has_mixed_negatives_and_unique_explicit_rubrics(self):
        self.assertEqual(len(self.cases), 30)
        self.assertEqual(sum(not c['expected'] for c in self.cases), 12)
        self.assertTrue(any(c['project'] for c in self.cases))
        self.assertEqual(evaluation.score(self.case, self.row, True)['tp'], 1)

    def test_duplicate_wrong_polarity_or_quote_cannot_pass(self):
        duplicate = dict(self.row, candidates=[self.item, self.item])
        score = evaluation.score(self.case, duplicate, True)
        self.assertEqual((score['tp'], score['fp']), (1, 1)); self.assertFalse(score['case_pass'])
        for changes in ({'quote': '别人的茶'}, {'segment': True}, {'segment': 99}):
            row = dict(self.row, candidates=[dict(self.item, **changes)])
            self.assertEqual(evaluation.score(self.case, row, True)['tp'], 0)
        negative = next(c for c in self.cases if c['id'] == 'P10')
        item = dict(self.item, quote=negative['text'].rstrip('。'), content='我喜欢喝含糖饮料')
        self.assertEqual(evaluation.score(negative, dict(self.row, candidates=[item]), True)['tp'], 0)

    def test_classification_is_scored_separately(self):
        row = copy.deepcopy(self.row)
        row['candidates'][0]['classification']['subject'] = 'other'
        self.assertTrue(evaluation.score(self.case, row, False)['case_pass'])
        self.assertFalse(evaluation.score(self.case, row, True)['case_pass'])
        row['candidates'][0].pop('classification')
        self.assertEqual(evaluation.score(self.case, row, True)['tp'], 0)

    def test_failed_negative_never_counts_as_correct_abstention(self):
        case = next(c for c in self.cases if c['id'] == 'P21')
        for status in ('FAILED', 'UNKNOWN', 'HARNESS_ERROR', 'BLOCKED'):
            score = evaluation.score(case, dict(self.row, status=status, candidates=[]), True)
            self.assertFalse(score['case_pass']); self.assertFalse(score['negative_pass'])
        protected = next(c for c in self.cases if c['id'] == 'P25')
        blocked = dict(self.row, status='BLOCKED', candidates=[], error_category='candidate_source_excluded')
        self.assertTrue(evaluation.score(protected, blocked, True)['negative_pass'])
        self.assertFalse(evaluation.score(self.case, blocked, True)['case_pass'])

    def test_rules_whole_message_rejection_is_not_optimized_by_harness(self):
        self.assertEqual(evaluation.rule_candidates('我喜欢喝茶。不要记住客户资料。'), [])
        self.assertEqual(evaluation.rule_candidates('明天继续聊天。'), [])
        self.assertEqual(evaluation.rule_candidates(self.case['text'])[0]['segment'], 0)

    def test_missing_cost_and_failure_denominators_remain_visible(self):
        rows = [dict(self.row, case=self.case['id']), dict(self.row, case=self.case['id'],
                  status='FAILED', candidates=[], billing={'amount': None, 'tokens': {}})]
        summary = evaluation.summarize([self.case], rows)['semantic']
        self.assertEqual(summary['runs'], 2)
        self.assertEqual(summary['typed']['recall'], .5)
        self.assertEqual(summary['cost_receipts'], 0)
        self.assertEqual(summary['token_receipts'], 0)
        self.assertEqual(summary['per_case'][self.case['id']], [True, False])

    def test_temporary_runtime_never_confirms_or_loads_owner_archives(self):
        with patch('jarvis_core.chat.gateway.probe', return_value={
            'status': 'SUCCEEDED', 'text': '{"candidates":[]}', 'provider': 'vertex', 'model': 'gemini-3.1-pro-preview'}), \
             patch.object(evaluation.SemanticCandidates, 'confirm', side_effect=AssertionError('No confirmation')):
            row = evaluation.evaluate(self.case, 'vertex', 'gemini-3.1-pro-preview', 'low')
        self.assertEqual(row['status'], 'SUCCEEDED')
        self.assertEqual(row['facts_committed'], 0)
        self.assertEqual(row['gateway_invocations'], 1)

    def test_source_changes_or_removal_are_detected(self):
        with tempfile.TemporaryDirectory() as tmp, patch.object(evaluation, 'ROOT', Path(tmp)):
            path = Path(tmp)/'source.py'; path.write_text('original', encoding='utf-8')
            hashes = {'source.py': evaluation.digest(path)}
            self.assertTrue(evaluation.sources_match(hashes))
            path.write_text('changed', encoding='utf-8')
            self.assertFalse(evaluation.sources_match(hashes))
            path.unlink()
            self.assertFalse(evaluation.sources_match(hashes))


if __name__ == '__main__':
    unittest.main()
