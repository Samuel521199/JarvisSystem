"""Local candidate resolution: atomic revision checks, scope and retry behavior."""
import copy
import json
import sys
import unittest
import uuid
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT/'tests'), str(ROOT/'runtime/node-host')]
import test_semantic_candidates as fixture
from jarvis_core.memory import MemoryStore, MemoryError
from jarvis_core.memory_comparison import compare, correction_only
from jarvis_core.workspace import WorkspaceService


class ReviewTests(unittest.TestCase):
    setUp = fixture.SemanticTests.setUp
    preview = fixture.SemanticTests.preview
    confirmation = staticmethod(fixture.SemanticTests.confirmation)

    def seed(self, content='主人平时喜欢无糖茶', **changes):
        doc = {'title': '原记忆', 'content': content, 'project_id': None, 'providers': ['vertex'],
               'classification': {'kind': 'preference', 'subject': 'owner', 'subject_label': '',
                                  'uses': ['personal_chat', 'work_assist'], 'expires_at': None}}
        doc.update(changes)
        return MemoryStore(self.core).put(uuid.uuid4().hex, {'revision': 0, 'document': doc})

    def review(self):
        return self.semantic.review(self.confirmation(self.preview()))

    def resolve(self, review, decision, target=None):
        return self.semantic.resolve({'review_token': review['review_token'], 'decision': decision,
                                      'target_id': target})

    def error(self, code, operation):
        with self.assertRaises(MemoryError) as exc: operation()
        self.assertEqual(exc.exception.code, code)

    def source(self, text):
        row = self.archives.get(self.cid)
        self.doc['messages'][0]['content'] = text
        self.archives.put(self.cid, {'revision': row['revision'], 'document': self.doc})

    def test_empty_review_has_no_database_or_model_side_effect(self):
        payload = self.confirmation(self.preview())
        with patch.object(self.semantic.chat, 'reply') as model:
            review = self.semantic.review(payload)
            model.assert_not_called()
        self.assertEqual(review['matches'], [])
        self.assertFalse(review['model_used']); self.assertFalse(review['committed'])
        self.assertFalse(MemoryStore(self.core).path.exists())

    def test_duplicate_keep_preserves_revision_permissions_and_binds_source(self):
        old = self.seed('我平时喜欢无糖茶。')
        preview = self.preview(); review = self.semantic.review(self.confirmation(preview))
        self.assertEqual(review['matches'][0]['relation'], 'duplicate')
        receipt = self.resolve(review, 'keep', old['id'])['receipt']
        self.assertEqual(receipt['revision'], old['revision'])
        row = MemoryStore(self.core).list()['facts'][0]
        self.assertEqual(row['document'], old['document'])
        self.assertEqual(row['provenance']['state'], 'independent')
        self.assertTrue(self.resolve(review, 'keep', old['id'])['receipt']['replayed'])
        self.error('memory_conflict', lambda: self.semantic.confirm(self.confirmation(preview)))
        MemoryStore(self.core).delete(old['id'], {'revision': old['revision']})
        self.assertTrue(self.resolve(review, 'keep', old['id'])['receipt']['replayed'])
        self.error('candidate_suppressed', lambda: self.semantic.confirm(self.confirmation(self.preview())))
        self.assertEqual(MemoryStore(self.core).list()['facts'], [])

    def test_replace_preserves_policy_and_name_updates_origin_and_replays(self):
        old = self.seed('主人平时喜欢黑咖啡')
        self.source('以前我喜欢黑咖啡，现在改为无糖茶。')
        review = self.review()
        self.assertEqual(review['matches'][0]['relation'], 'possible_change')
        result = self.resolve(review, 'replace', old['id'])
        row = MemoryStore(self.core).list()['facts'][0]
        self.assertEqual(row['revision'], 2)
        self.assertEqual(row['document'], old['document'] | {'content': '主人平时喜欢无糖茶'})
        self.assertEqual(row['provenance']['state'], 'current')
        self.assertIn('现在改为', row['provenance']['excerpt'])
        self.assertTrue(self.resolve(review, 'replace', old['id'])['receipt']['replayed'])
        self.assertEqual(result['receipt']['id'], old['id'])

    def test_replace_suppresses_former_source_and_replaces_provenance(self):
        first = self.semantic.confirm(self.confirmation(self.preview()))
        self.source('我不再喝无糖茶，现在改为黑咖啡。')
        self.answer['candidates'][0]['content'] = '主人平时喜欢黑咖啡'
        # Old source must remain available: edit created a new version, making
        # the old provenance invalid. An explicit owner correction detaches it.
        memory = MemoryStore(self.core); row = memory.list()['facts'][0]
        memory.command('correct', row['id'], row['document']['content'], request_id=uuid.uuid4().hex)
        review = self.review(); self.resolve(review, 'replace', first['receipt']['id'])
        self.assertEqual(memory.list()['facts'][0]['document']['content'], '主人平时喜欢黑咖啡')
        self.source('我平时喜欢无糖茶。我们下次继续讨论旅行安排。')
        self.error('candidate_suppressed', lambda: self.semantic.confirm(self.confirmation(self.preview())))

    def test_choice_constraints_and_no_automatic_write(self):
        old = self.seed('主人平时喜欢黑咖啡'); review = self.review()
        self.assertEqual(review['matches'][0]['relation'], 'related')
        self.assertEqual(MemoryStore(self.core).list()['facts'][0]['document'], old['document'])
        self.error('invalid_candidate', lambda: self.resolve(review, 'keep', old['id']))
        self.error('invalid_candidate', lambda: self.resolve(review, 'replace', uuid.uuid4().hex))
        self.error('invalid_candidate', lambda: self.resolve(review, 'new', old['id']))
        self.resolve(review, 'new')
        self.assertEqual(len(MemoryStore(self.core).list()['facts']), 2)

    def test_duplicate_new_and_legacy_confirm_blocked(self):
        self.seed(); payload = self.confirmation(self.preview()); review = self.semantic.review(payload)
        self.error('candidate_duplicate', lambda: self.resolve(review, 'new'))
        self.error('candidate_duplicate', lambda: self.semantic.confirm(payload))
        self.error('invalid_candidate', lambda: self.resolve(review, 'replace', review['matches'][0]['id']))

    def test_duplicate_inserted_after_review_blocked_atomically(self):
        review = self.review(); self.seed()
        self.error('candidate_duplicate', lambda: self.resolve(review, 'new'))
        self.assertEqual(len(MemoryStore(self.core).list()['facts']), 1)

    def test_changed_target_rejects_both_existing_review_and_old_preview(self):
        old = self.seed('主人喜欢黑咖啡'); preview = self.preview()
        review = self.semantic.review(self.confirmation(preview))
        MemoryStore(self.core).put(old['id'], {'revision': 1, 'document': old['document'] | {'providers': []}})
        self.error('candidate_review_changed', lambda: self.resolve(review, 'replace', old['id']))
        self.error('candidate_review_changed', lambda: self.semantic.review(self.confirmation(preview)))

    def test_source_edit_and_delete_block_writes(self):
        review = self.review(); self.source('更正原文内容')
        self.error('candidate_source_changed', lambda: self.resolve(review, 'new'))
        self.assertEqual(MemoryStore(self.core).list()['facts'], [])

    def test_deleted_target_cannot_be_revived(self):
        old = self.seed(); review = self.review()
        MemoryStore(self.core).delete(old['id'], {'revision': old['revision']})
        self.error('candidate_review_changed', lambda: self.resolve(review, 'keep', old['id']))
        self.assertEqual(MemoryStore(self.core).list()['facts'], [])

    def test_token_tampering_wrong_purpose_and_expiry(self):
        preview = self.preview(); review = self.semantic.review(self.confirmation(preview))
        self.error('invalid_candidate', lambda: self.resolve({'review_token': preview['preview_token']}, 'new'))
        self.error('candidate_preview_expired', lambda: self.resolve({'review_token': review['review_token']+'x'}, 'new'))
        with patch('jarvis_core.semantic_candidates.time.time', return_value=10**12):
            self.error('candidate_preview_expired', lambda: self.resolve(review, 'new'))
        self.assertEqual(MemoryStore(self.core).list()['facts'], [])

    def test_project_scope_and_subject_boundaries(self):
        old = self.seed(); project = WorkspaceService(self.core).open_project({'path': str(self.base/'source')})['id']
        self.doc['project_id'] = project
        self.archives.put(self.cid, {'revision': 1, 'document': self.doc})
        self.request['project_id'] = project
        preview = self.preview(); payload = self.confirmation(preview)
        self.assertEqual(self.semantic.review(payload)['matches'], [])
        global_review = self.semantic.review(payload | {'scope': 'global'})
        self.assertEqual(global_review['matches'][0]['id'], old['id'])
        policy = copy.deepcopy(payload['classification']); policy.update(kind='fiction', subject='character', subject_label='茶博士', uses=[])
        self.assertEqual(self.semantic.review(payload | {'scope': 'global', 'classification': policy})['matches'], [])

    def test_unclassified_equal_can_keep_but_never_reclassify(self):
        memory = MemoryStore(self.core)
        memory.command('remember', '旧记忆', '主人平时喜欢无糖茶', request_id=uuid.uuid4().hex)
        old = memory.list()['facts'][0]; doc = old['document']
        review = self.review(); self.assertEqual(review['matches'][0]['relation'], 'unclassified')
        self.error('invalid_candidate', lambda: self.resolve(review, 'replace', old['id']))
        self.resolve(review, 'keep', old['id'])
        self.assertEqual(memory.list()['facts'][0]['document'], doc)

    def test_source_invalid_duplicates_do_not_create_impossible_review_loop(self):
        self.semantic.confirm(self.confirmation(self.preview()))
        self.source('我平时喜欢无糖茶，最近也是这样。')
        self.answer['candidates'][0]['title'] = '另一来源的偏好'
        review = self.review(); self.assertEqual(review['matches'], [])
        self.assertEqual(review['source_unusable'], 1)
        self.resolve(review, 'new')
        self.assertEqual(len(MemoryStore(self.core).list()['facts']), 2)

    def test_max_five_hints_report_truncation(self):
        for i in range(7): self.seed('主人喜欢茶' + str(i), title='偏好'+str(i))
        review = self.review()
        self.assertEqual(len(review['matches']), 5); self.assertTrue(review['truncated'])
        self.assertEqual(review['total_matches'], 7)

    def test_correction_only_skips_model_and_never_makes_negative_profile(self):
        self.source('你刚才说我住在北京，那是你猜错了，我没有说过我的住址。')
        preview = self.preview()
        self.assertEqual(self.calls, []); self.assertFalse(preview['model_used'])
        self.assertEqual(preview['candidates'], []); self.assertIn('notice', preview)
        for text in ('我不喜欢甜食。', '你猜错了我实际住在上海。',
                     '你猜我住北京，但我实际住在上海。', '我叫小林，你之前猜错了。'):
            self.assertFalse(correction_only(text), text)

    def test_mixed_source_rejects_model_guess_but_accepts_independent_fact(self):
        self.source('你刚才说我住在北京，那是你猜错了，我没有说过我的住址。我喜欢无糖茶。')
        bad = self.preview()
        self.assertEqual(bad['result']['error_category'], 'candidate_correction_only')
        self.assertNotIn('preview_token', bad)
        self.answer['candidates'][0]['segment'] = 1
        self.assertEqual(len(self.preview()['candidates']), 1)

    def test_replace_keeps_audited_source_chain_and_invalidates_derived_history(self):
        first = self.semantic.confirm(self.confirmation(self.preview()))['receipt']
        original_cid = self.cid
        self.cid = uuid.uuid4().hex
        self.doc['messages'][0]['content'] = '以前我喜欢无糖茶，现在改为黑咖啡。'
        self.archives.put(self.cid, {'revision': 0, 'document': self.doc})
        self.request['source'] = {'conversation_id': self.cid, 'message_index': 0}
        self.answer['candidates'][0]['content'] = '主人平时喜欢黑咖啡'
        review = self.review(); memory = MemoryStore(self.core)
        self.resolve(review, 'replace', first['id'])
        with memory.connection() as db:
            bindings = db.execute('SELECT suppressed FROM candidate_bindings WHERE fact_id=?', (first['id'],)).fetchall()
            self.assertEqual(sorted(r[0] for r in bindings), [0, 1])
            self.assertNotIn('无糖茶', str([tuple(r) for r in db.execute('SELECT * FROM receipts')]))
        text, refs, indexes = memory.filter_history([{'role':'user', 'content':'喜欢什么'}, {'role':'assistant', 'content':'无糖茶'}],
            [[], [{'id':first['id'], 'revision':1}]], {'enabled':True, 'project_id':None}, 'local')
        self.assertEqual(text, []); self.assertEqual(indexes, [])
        self.request['source']['conversation_id'] = original_cid
        self.error('candidate_suppressed', lambda: self.semantic.confirm(self.confirmation(self.preview())))

    def test_old_source_becomes_unusable_after_review(self):
        first = self.semantic.confirm(self.confirmation(self.preview()))['receipt']
        original_cid = self.cid; original = copy.deepcopy(self.doc)
        self.cid = uuid.uuid4().hex; self.doc['messages'][0]['content'] = '我现在改为喜欢黑咖啡。'
        self.archives.put(self.cid, {'revision': 0, 'document': self.doc})
        self.request['source'] = {'conversation_id': self.cid, 'message_index': 0}
        self.answer['candidates'][0]['content'] = '主人平时喜欢黑咖啡'
        review = self.review()
        original['messages'][0]['content'] = '原始消息已被改写'
        self.archives.put(original_cid, {'revision': 1, 'document': original})
        self.error('candidate_target_changed', lambda: self.resolve(review, 'replace', first['id']))

    def test_compare_detects_revision_change_during_read(self):
        old = self.seed(); payload = self.confirmation(self.preview())
        def race(doc, quote, facts):
            MemoryStore(self.core).delete(old['id'], {'revision':old['revision']})
            return compare(doc, quote, facts)
        with patch('jarvis_core.memory_review.compare', side_effect=race):
            self.error('candidate_review_changed', lambda: self.semantic.review(payload))

    def test_editing_candidate_is_signed_not_mutable_at_resolve(self):
        payload = self.confirmation(self.preview()); payload['content'] = '主人喜欢水'
        review = self.semantic.review(payload)
        self.error('invalid_candidate', lambda: self.semantic.resolve({'review_token':review['review_token'],
            'decision':'new', 'target_id':None, 'content':'被替换的正文'}))
        self.resolve(review, 'new')
        self.assertEqual(MemoryStore(self.core).list()['facts'][0]['document']['content'], '主人喜欢水')

    def test_non_model_review_is_bounded_and_never_fuzzy_auto_merges(self):
        old = self.seed('主人平时喜欢无糖茶，并且晚上不喝茶')
        review = self.review(); self.assertEqual(review['matches'][0]['relation'], 'possible_addition')
        self.assertEqual(MemoryStore(self.core).list()['facts'][0]['document'], old['document'])
        self.error('invalid_candidate', lambda: self.resolve(review, 'keep', old['id']))

    def test_same_subject_label_required_for_other_people(self):
        old = self.seed('喜欢咖啡')
        doc = copy.deepcopy(old['document']); doc['classification'].update(kind='third_party',subject='other',subject_label='老王',uses=[])
        other = copy.deepcopy(doc); other['classification']['subject_label'] = '小陈'
        self.assertEqual(compare(other, '小陈喜欢咖啡', [{'id':old['id'],'revision':1,'document':doc}])['matches'], [])


if __name__ == '__main__': unittest.main()
