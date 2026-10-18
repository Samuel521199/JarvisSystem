"""Stateful synthetic memory replay and revision-barrier races; never use a model."""
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch
import uuid

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'tools'))
from memory_lab.lifecycle import Replay, load_cases
from jarvis_core.memory import MemoryError, MemoryStore

CORPUS = ROOT/'evals/cases/memory-lifecycle-pilot.json'


class LifecycleTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.replay = Replay(temp.name)
        self.cases = load_cases(CORPUS)['cases']
        self.network = patch('socket.socket.connect', side_effect=AssertionError('No network'))
        self.network.start()
        self.addCleanup(self.network.stop)

    def prepare_stale_case(self):
        for step in self.cases[1]['steps'][:5]:
            self.replay.step(step)
        return self.cases[1]['steps']

    def test_all_public_multiturn_lifecycles(self):
        for case in self.cases:
            with self.subTest(case=case['id']), tempfile.TemporaryDirectory() as directory:
                replay = Replay(directory)
                for step in case['steps']:
                    replay.step(step)

    def test_evaluator_rejects_wrong_context_expectations(self):
        self.replay.step({'op': 'remember', 'name': 'fact', 'title': '偏好', 'content': '喜欢茶'})
        with self.assertRaises(AssertionError):
            self.replay.step({'op': 'context', 'facts': []})

    def test_corpus_detects_disabled_revision_barrier(self):
        steps = self.prepare_stale_case()
        self.replay.step(steps[5])  # forget
        with patch.object(MemoryStore, '_review_revision', return_value=0):
            with self.assertRaisesRegex(AssertionError, 'expected rejection'):
                self.replay.step(steps[6])

    def test_revision_read_does_not_create_or_migrate_database(self):
        store = self.replay.memory
        self.assertEqual(store.review_revision(), 0)
        self.assertFalse(store.path.exists())
        self.replay.step({'op': 'remember', 'name': 'fact', 'title': '隐私', 'content': 'SYNTHETIC_PRIVATE'})
        with store.connection() as db:
            db.execute('PRAGMA user_version=1')
        before = store.path.read_bytes()
        self.assertEqual(store.review_revision(), 0)
        self.assertEqual(store.path.read_bytes(), before)

    def test_revision_argument_rejects_missing_source_boolean_and_negative(self):
        for value in (True, -1, '0', 0):
            with self.subTest(value=value), self.assertRaises(MemoryError) as caught:
                self.replay.memory.command('remember', '名称', '内容', request_id=uuid.uuid4().hex,
                                           candidate_review_revision=value)
            self.assertEqual(caught.exception.code, 'invalid_memory')

    def test_rejected_draft_leaves_no_receipt_or_binding(self):
        steps = self.prepare_stale_case()
        self.replay.step(steps[5])
        def counts():
            with self.replay.memory.connection() as db:
                return [db.execute('SELECT count(*) FROM '+table).fetchone()[0]
                        for table in ('facts', 'receipts', 'candidate_bindings', 'fact_origins', 'chat_commands')]
        before = counts()
        self.replay.step(steps[6])
        self.assertEqual(counts(), before)

    def test_forget_immediately_before_write_is_checked_in_transaction(self):
        self.prepare_stale_case()
        original = MemoryStore.command
        row = self.replay.row('tea')
        def forget_then_write(store, *args, **kwargs):
            # Occurs after token/source validation, immediately before writer entry.
            store.delete(row['id'], {'revision': row['revision']})
            return original(store, *args, **kwargs)
        with patch.object(MemoryStore, 'command', forget_then_write):
            self.replay.step({'op': 'confirm', 'preview': 'p2', 'error': 'candidate_review_changed'})
        self.replay.step({'op': 'state', 'facts': 0, 'forgotten_body_cleared': True})

    def test_queued_writer_sees_other_connection_committed_forget(self):
        self.prepare_stale_case()
        row = self.replay.row('tea')
        entered = threading.Event()
        def confirm():
            entered.set()
            self.replay.step({'op': 'confirm', 'preview': 'p2', 'error': 'candidate_review_changed'})
        with ThreadPoolExecutor(max_workers=1) as pool:
            with self.replay.memory.connection() as db:
                db.execute('BEGIN IMMEDIATE')
                self.replay.memory._delete(db, row['id'], row['revision'])
                future = pool.submit(confirm)
                self.assertTrue(entered.wait(1))
                db.commit()
            future.result(timeout=5)
        self.replay.step({'op': 'state', 'facts': 0, 'forgotten_body_cleared': True})

    def test_unrelated_new_fact_does_not_invalidate_pending_preview(self):
        self.prepare_stale_case()
        self.replay.step({'op': 'remember', 'name': 'new', 'title': '语言', 'content': '偏好中文'})
        self.replay.step({'op': 'confirm', 'preview': 'p2', 'name': 'second'})
        self.replay.step({'op': 'state', 'facts': 3, 'review_revision': 0})

    def test_body_is_cleared_but_revision_survives_forget_and_restart(self):
        steps = self.prepare_stale_case()
        self.replay.step(steps[5])
        self.replay.step({'op': 'restart'})
        self.assertEqual(self.replay.memory.review_revision(), 1)
        self.replay.step({'op': 'state', 'facts': 0, 'forgotten_body_cleared': True})

    def test_failed_revision_read_does_not_create_preview_or_lose_call_receipt(self):
        self.replay.step(self.cases[0]['steps'][0])
        step = dict(self.cases[0]['steps'][1], result_error='memory_unavailable')
        with patch.object(MemoryStore, 'review_revision', side_effect=[0, MemoryError('memory_unavailable', '测试故障')]):
            self.replay.step(step)
        self.assertEqual(self.replay.chat.calls, 1)

    def test_corrupt_database_stops_before_model_dispatch(self):
        self.replay.step(self.cases[0]['steps'][0])
        self.replay.memory.path.write_bytes(b'synthetic corrupt database')
        self.replay.step(dict(self.cases[0]['steps'][1], error='memory_unavailable'))
        self.assertEqual(self.replay.chat.calls, 0)


if __name__ == '__main__':
    unittest.main()
