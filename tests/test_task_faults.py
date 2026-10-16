"""Real crash boundaries must retain receipts and never replay uncertain effects."""
import os
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'tools'))
from probe_task_faults import POINTS, exercise, corrupt_artifact


@unittest.skipUnless(os.name == 'nt', 'The fixed Worker requires Windows')
class DurableFaultTests(unittest.TestCase):
    def test_acceptance_boundaries(self):
        for point in POINTS[:2]:
            with self.subTest(point=point): self.assertEqual(exercise(point)['status'], 'passed')

    def test_uncertain_effects_are_never_replayed(self):
        for point in POINTS[2:-1]:
            with self.subTest(point=point): self.assertEqual(exercise(point)['retry_action'], 'UNKNOWN')

    def test_committed_receipt_survives_lost_response(self):
        self.assertEqual(exercise(POINTS[-1])['retry_action'], 'CONFIRMED')

    def test_missing_or_changed_artifact_is_visible_and_not_rebuilt(self):
        for mode in ('changed', 'missing'):
            with self.subTest(mode=mode): self.assertTrue(corrupt_artifact(mode)['not_rebuilt'])
