"""Pinned dependency closure: actual LPAC, fail-closed builds and legacy compatibility."""
import base64
import io
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
import uuid
import zipfile

sys.path.insert(0, str(Path(__file__).parent))
import test_coding_workflow as fixture
from jarvis_core import policy, coding_dependencies as deps
from jarvis_core.coding_build import build, bytes_from, inspect, DEPENDENCY, ZIPAPP
from jarvis_core.coding_workflow import apply_result
from jarvis_core.evolution.runner import IsolatedRunner
from jarvis_core.network_policy import NetworkPolicy

SOURCE = 'import jmespath\nimport json\ndef transform(data):\n    return json.dumps(jmespath.search(data["query"], data["value"]), ensure_ascii=False, sort_keys=True)\n'
CASES = [{'input': {'query': 'people[*].name', 'value': {'people': [{'name': '小明'}]}}, 'expected': '["小明"]'},
         {'input': {'query': 'length(@)', 'value': []}, 'expected': '0'}]
PRIVATE = [{'input': {'query': 'sort(@)', 'value': [3, -1, 2]}, 'expected': '[-1, 2, 3]'},
           {'input': {'query': 'missing', 'value': {}}, 'expected': 'null'}]
DIGEST = 'sha256:'+'a'*64


class DependencyBuildTests(unittest.TestCase):
    def artifact(self, source=SOURCE):
        return build({'calc.py': source}, 'calc.py', DIGEST, DEPENDENCY)

    def test_pinned_bundle_license_manifest_and_no_host_import(self):
        before = {n for n in sys.modules if n.startswith('jmespath')}
        artifact = self.artifact(); raw = bytes_from(artifact)
        self.assertLess(artifact['size_bytes'], 24000)
        self.assertEqual(artifact['manifest']['dependencies'], [deps.lock()])
        self.assertEqual(inspect(raw)[2], artifact)
        with zipfile.ZipFile(io.BytesIO(raw)) as archive:
            self.assertIn('_vendor/jmespath-1.1.0.dist-info/LICENSE', archive.namelist())
            self.assertFalse(any('scripts/' in n for n in archive.namelist()))
            self.assertFalse(any('case' in n for n in archive.namelist()))
        self.assertEqual(before, {n for n in sys.modules if n.startswith('jmespath')})

    def test_real_lpac_uses_bundled_library_and_unicode(self):
        outputs, evidence = IsolatedRunner().run_build(self.artifact(), [c['input'] for c in CASES+PRIVATE], lambda: None)
        self.assertEqual(outputs, [c['expected'] for c in CASES+PRIVATE]); self.assertTrue(evidence['lpac'])

    def test_missing_or_corrupt_cache_never_falls_back_and_old_recipe_works(self):
        with tempfile.TemporaryDirectory() as temp, patch('socket.create_connection', side_effect=AssertionError('network')):
            path = Path(temp)/deps.WHEEL
            with patch.object(deps, 'ASSET', path):
                with self.assertRaises(policy.CoreError) as error: self.artifact()
                self.assertEqual(error.exception.code, 'missing_offline_dependency')
                old = build({'calc.py': fixture.GOOD}, 'calc.py', DIGEST, ZIPAPP)
                self.assertEqual(inspect(bytes_from(old))[2], old)
                path.write_bytes(b'corrupt')
                with self.assertRaises(policy.CoreError) as error: self.artifact()
                self.assertEqual(error.exception.code, 'coding_dependency_invalid')

    def test_forged_dependency_license_lock_or_extra_script_rejected(self):
        raw = bytes_from(self.artifact())
        for member in ('_vendor/jmespath/__init__.py', '_vendor/jmespath-1.1.0.dist-info/LICENSE', 'jarvis-build.json'):
            out = io.BytesIO()
            with zipfile.ZipFile(io.BytesIO(raw)) as old, zipfile.ZipFile(out, 'w') as new:
                for item in old.infolist():
                    content = old.read(item)
                    if item.filename == member:
                        if member.endswith('.json'):
                            value=json.loads(content);value['dependencies'][0]['version']='99';content=json.dumps(value).encode()
                        else: content += b'\n# tampered'
                    new.writestr(item, content)
            with self.subTest(member=member), self.assertRaises(policy.CoreError): inspect(out.getvalue())

    def test_dependency_imports_do_not_leak_to_legacy_and_facade_has_no_options(self):
        with self.assertRaises(policy.CoreError): build({'calc.py': SOURCE}, 'calc.py', DIGEST, ZIPAPP)
        with self.assertRaises(policy.CoreError): self.artifact('import os\ndef transform(data):\n    return "bad"\n')
        with self.assertRaises(policy.CoreError): build({'jmespath.py': SOURCE}, 'jmespath.py', DIGEST, DEPENDENCY)
        b = self.artifact('import jmespath\ndef transform(data):\n    return str(jmespath.Options())\n')
        with self.assertRaises(policy.CoreError): IsolatedRunner().run_build(b, [0], lambda: None)

    def test_actual_dependency_worker_cancellation(self):
        b = self.artifact('import jmespath\ndef transform(data):\n    while True:\n        jmespath.search("@", data)\n    return "done"\n')
        import time
        started = time.monotonic()
        def stop():
            if time.monotonic()-started > 1.2: raise policy.CoreError('task_cancelled', 'cancel fixture')
        with self.assertRaises(policy.CoreError) as error: IsolatedRunner().run_build(b, [{}], stop)
        self.assertEqual(error.exception.code, 'task_cancelled')
        outputs, _ = IsolatedRunner().run_build(self.artifact(), [CASES[0]['input']], lambda: None)
        self.assertEqual(outputs, [CASES[0]['expected']])

    def test_offline_cli_rebuild_and_private_verification(self):
        b = self.artifact()
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp); (root/'tool.pyz').write_bytes(bytes_from(b))
            (root/'cases.json').write_text(json.dumps(PRIVATE), encoding='utf-8')
            run=subprocess.run([sys.executable,'-X','utf8','-B',str(policy.REPOSITORY_ROOT/'tools/coding_build.py'),
                '--archive',str(root/'tool.pyz'),'--sha256',b['sha256'],'--cases',str(root/'cases.json'),
                '--output',str(root/'rebuilt.pyz')],capture_output=True,timeout=30)
            self.assertEqual(run.returncode,0,run.stderr.decode())
            report=json.loads(run.stdout);self.assertEqual(report['status'],'verified');self.assertEqual(report['model_calls'],0)
            self.assertEqual((root/'rebuilt.pyz').read_bytes(),(root/'tool.pyz').read_bytes())

    def test_release_source_closure_includes_offline_assets(self):
        from jarvis_core.releases import bundle
        selected = bundle.source_files()
        self.assertIn('third_party/coding/'+deps.WHEEL, selected)
        self.assertIn('third_party/coding/NOTICE.txt', selected)
        self.assertIn('tools/coding_build.py', selected)


class DependencyWorkflowTests(fixture.CodingTests):
    def submit(self, **kw):
        return super().submit(**{'build_recipe': DEPENDENCY, 'cases': CASES, 'heldout_cases': PRIVATE, **kw})

    def test_repair_apply_restore_and_private_cases_not_sent(self):
        self.sources=[SOURCE]; report=self.report(self.submit()); value=report['coding']
        self.assertTrue(value['passed']);self.assertEqual(len(self.calls),1)
        self.assertEqual(self.calls[0]['cases'],CASES); self.assertNotIn('heldout_cases',self.calls[0])
        self.assertNotIn('sort(@)',json.dumps(self.calls[0]))
        self.assertTrue(value['build_validation']['actual_archive_entry'])
        self.assertEqual(value['dependencies'],[deps.lock()]);self.assertNotIn('source_build',value)
        apply_result(self.core,report,'apply');apply_result(self.core,report,'rollback')
        self.assertEqual((self.source/'calc.py').read_bytes(),b'\xef\xbb\xbf'+fixture.BAD.encode())

    def test_missing_cache_rejected_before_queue_or_model_and_legacy_still_works(self):
        with patch.object(deps,'ASSET',self.source/'missing.whl'):
            with self.assertRaises(policy.CoreError) as error:self.submit()
            self.assertEqual(error.exception.code,'missing_offline_dependency')
            self.assertFalse(self.calls)
            report=self.report(super().submit(build_recipe=ZIPAPP, cases=fixture.CASES, heldout_cases=[{'input':[1],'expected':'1'},{'input':[8],'expected':'8'}]))
            self.assertTrue(report['coding']['passed'])

    def test_cache_lost_after_admission_no_delivery_or_model(self):
        from jarvis_core.coding_dependencies import members
        def require_at_build():
            import inspect as inspect_py
            if any(f.function=='build' for f in inspect_py.stack()):
                raise policy.CoreError('missing_offline_dependency','removed fixture')
            return members()
        (self.source/'calc.py').write_text(SOURCE,encoding='utf-8')
        with patch.object(deps,'members',side_effect=require_at_build):
            detail=self.wait(self.submit())
        self.assertEqual(detail['error']['code'],'missing_offline_dependency');self.assertFalse(self.calls)
        self.assertIsNone(detail['artifact'])

    def test_offline_passing_baseline_uses_no_model(self):
        (self.source/'calc.py').write_text(SOURCE,encoding='utf-8')
        network=NetworkPolicy(self.core.data_dir);network.change(True,network.snapshot()['revision'])
        self.assertTrue(self.report(self.submit())['coding']['passed']);self.assertFalse(self.calls)

    def test_multifile_dependency_apply_and_restore_without_cache(self):
        (self.source/'querydata.py').write_text('def select(data):\n    return "wrong"\n',encoding='utf-8')
        candidates = {'calc.py': 'import querydata\nimport json\ndef transform(data):\n    return json.dumps(querydata.select(data), ensure_ascii=False, sort_keys=True)\n',
                      'querydata.py': 'import jmespath\ndef select(data):\n    return jmespath.search(data["query"], data["value"])\n'}
        before={p:(self.source/p).read_bytes() for p in candidates}
        self.manager.skills.coding_generate=lambda *a:{'status':'SUCCEEDED','text':json.dumps({'files':candidates,'notes':'fixture'})}
        report=self.report(self.submit(paths=list(candidates)));self.assertTrue(report['coding']['passed'])
        self.assertEqual(apply_result(self.core,report,'apply')['files'],2)
        with patch.object(deps,'ASSET',self.source/'missing.whl'):
            self.assertEqual(apply_result(self.core,report,'rollback')['files'],2)
        self.assertEqual({p:(self.source/p).read_bytes() for p in candidates},before)


for name in dir(fixture.CodingTests):
    if name.startswith('test_') and name not in DependencyWorkflowTests.__dict__: setattr(DependencyWorkflowTests,name,None)

if __name__=='__main__':unittest.main()
