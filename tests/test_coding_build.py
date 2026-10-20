"""Real archive entry verification, immutable recipes and broken-baseline repair."""
import base64
import io
import json
from pathlib import Path
import sys
import unittest
import warnings
import zipfile
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parent))
import test_coding_workflow as fixture
from jarvis_core import policy
from jarvis_core.coding_build import build, inspect, bytes_from, SOURCE, ZIPAPP
from jarvis_core.coding_bundle import package
from jarvis_core.coding_workflow import apply_result
from jarvis_core.evolution.runner import IsolatedRunner

SOURCES = {'calc.py': fixture.GOOD}
DIGEST = 'sha256:' + '1' * 64
PRIVATE = [{'input': [-10, 3], 'expected': '-7'}, {'input': [11, 1], 'expected': '12'}]


class BuildTests(unittest.TestCase):
    def test_reproducible_and_legacy_recipe(self):
        original = build(SOURCES, 'calc.py', DIGEST, ZIPAPP)
        sources, entry, rebuilt = inspect(bytes_from(original), original['sha256'])
        self.assertEqual((sources, entry, rebuilt), (SOURCES, 'calc.py', original))
        self.assertEqual(build(SOURCES, 'calc.py', DIGEST, SOURCE), package(SOURCES, 'calc.py', DIGEST))

    def test_tampered_digest_launcher_and_duplicate_member(self):
        b = build(SOURCES, 'calc.py', DIGEST, ZIPAPP); raw = bytes_from(b)
        with self.assertRaises(policy.CoreError): inspect(raw, 'sha256:' + '0' * 64)
        for name, replacement in [('__main__.py', b'print("forged")'), ('calc.py', b'def transform(data): return "forged"')]:
            out = io.BytesIO()
            with zipfile.ZipFile(io.BytesIO(raw)) as old, zipfile.ZipFile(out, 'w') as new:
                for item in old.infolist(): new.writestr(item, replacement if item.filename == name else old.read(item))
            with self.subTest(name=name), self.assertRaises(policy.CoreError): inspect(out.getvalue())
        out = io.BytesIO(raw)
        with zipfile.ZipFile(out, 'a') as archive: archive.writestr('../escape.py', 'bad')
        with self.assertRaises(policy.CoreError): inspect(out.getvalue())
        out = io.BytesIO(raw)
        with warnings.catch_warnings():
            warnings.simplefilter('ignore', UserWarning)
            with zipfile.ZipFile(out, 'a') as archive: archive.writestr('calc.py', fixture.GOOD)
        with self.assertRaises(policy.CoreError): inspect(out.getvalue())

    def test_missing_dependency_and_receipt_swap_fail_before_execution(self):
        with self.assertRaises(policy.CoreError): build({'calc.py': 'import requests\ndef transform(data):\n    return str(data)\n'}, 'calc.py', DIGEST, ZIPAPP)
        b = build(SOURCES, 'calc.py', DIGEST, ZIPAPP)
        for field, value in [('filename', 'other.pyz'), ('manifest', {}), ('base64', 'invalid!')]:
            with self.subTest(field=field), self.assertRaises(policy.CoreError): bytes_from({**b, field: value})

    def test_real_archive_lpac_unicode_and_no_implicit_newline(self):
        b = build({'calc.py': 'def transform(data):\n    return "你好：" + str(data)\n'}, 'calc.py', DIGEST, ZIPAPP)
        outputs, evidence = IsolatedRunner().run_build(b, [0, '世界'], lambda: None)
        self.assertEqual(outputs, ['你好：0', '你好：世界']); self.assertTrue(evidence['lpac'])

    def test_actual_archive_entry_cannot_mutate_input(self):
        b = build({'calc.py': 'def transform(data):\n    data.append(5)\n    return "ok"\n'}, 'calc.py', DIGEST, ZIPAPP)
        with self.assertRaises(policy.CoreError) as error: IsolatedRunner().run_build(b, [[]], lambda: None)
        self.assertEqual(error.exception.code, 'candidate_execution_failed')


class BuildWorkflowTests(fixture.CodingTests):
    def test_broken_baseline_can_be_repaired_and_built(self):
        broken = 'def transform(data)\n    return "broken"\n'
        (self.source/'calc.py').write_text(broken, encoding='utf-8')
        report = self.report(self.submit(build_recipe=ZIPAPP, heldout_cases=PRIVATE))
        value = report['coding']; self.assertTrue(value['passed'])
        self.assertFalse(value['baseline']['executed']); self.assertEqual(value['baseline']['diagnostics'][0]['line'], 1)
        self.assertTrue(value['build_validation']['actual_archive_entry'])
        self.assertTrue(value['build_validation']['worker']['lpac'])
        self.assertEqual(value['build_validation']['cases'], 4)
        self.assertEqual(value['build']['filename'], 'candidate-python.pyz')
        self.assertIn('source_build', value)
        apply_result(self.core, report, 'apply'); apply_result(self.core, report, 'rollback')
        self.assertEqual((self.source/'calc.py').read_text(), broken)

    def test_artifact_failure_prevents_delivery_and_application(self):
        with patch.object(IsolatedRunner, 'run_build', return_value=(['wrong']*4, {'lpac': True})):
            report = self.report(self.submit(build_recipe=ZIPAPP, heldout_cases=PRIVATE))
        value = report['coding']; self.assertTrue(value['validation']['passed']); self.assertFalse(value['passed'])
        self.assertNotIn('build', value); self.assertEqual(len(self.calls), 1)
        with self.assertRaises(policy.CoreError): apply_result(self.core, report, 'apply')

    def test_zipapp_requires_independent_cases_and_known_recipe(self):
        for kw in [{'build_recipe': ZIPAPP}, {'build_recipe': 'shell-install'}, {'coding': False, 'build_recipe': SOURCE}]:
            with self.subTest(kw=kw), self.assertRaises(policy.CoreError): self.submit(**kw)
        self.assertFalse(self.calls)

    def test_passing_baseline_builds_offline_without_model(self):
        from jarvis_core.network_policy import NetworkPolicy
        (self.source/'calc.py').write_text(fixture.GOOD, encoding='utf-8')
        network = NetworkPolicy(self.core.data_dir); network.change(True, network.snapshot()['revision'])
        report = self.report(self.submit(build_recipe=ZIPAPP, heldout_cases=PRIVATE))
        self.assertTrue(report['coding']['passed']); self.assertFalse(self.calls)


for name in dir(fixture.CodingTests):
    if name.startswith('test_') and name not in BuildWorkflowTests.__dict__: setattr(BuildWorkflowTests, name, None)

if __name__ == '__main__': unittest.main()
