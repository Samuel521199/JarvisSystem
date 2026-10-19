"""Real LPAC multi-module checks, hidden-case leakage and resumable application."""
import base64
import io
import json
import sys
import zipfile
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).parent))
from test_coding_workflow import CodingTests, CASES, GOOD
from jarvis_core import policy
from jarvis_core.coding_bundle import validate_bundle, package
from jarvis_core.coding_workflow import apply_result
from jarvis_core.project_files import ProjectFiles

BAD_FILES={'calc.py':'from helper import total\ndef transform(data):\n    return total(data)\n',
           'helper.py':"def total(data):\n    return 'broken'\n"}
GOOD_FILES={'calc.py':'from helper import total\ndef transform(data):\n    return str(total(data))\n',
            'helper.py':'def total(data):\n    return sum(data)\n'}
PRIVATE=[{'input':[-97531,1],'expected':'-97530'},{'input':[7,7,7],'expected':'21'}]


class BundleTests(CodingTests):
    # Keep this class's test cases separate from the inherited legacy matrix.
    def setUp(self):
        super().setUp()
        for p,s in BAD_FILES.items(): (self.source/p).write_text(s,encoding='utf-8')
        self.bundles=[GOOD_FILES]
        def generate(prompt,instructions,guard):
            guard();self.calls.append(json.loads(prompt))
            self.assertNotIn('97531',prompt+instructions);self.assertNotIn('-97530',prompt+instructions)
            return {'status':'SUCCEEDED','text':json.dumps({'files':self.bundles.pop(0) if len(self.bundles)>1 else self.bundles[0],'notes':'test fixture'})}
        self.manager.skills.coding_generate=generate
    def submit(self,**kw):
        return super().submit(**{'paths':['calc.py','helper.py'],'entrypoint':'calc.py','heldout_cases':PRIVATE,**kw})
    def test_multifile_real_build_apply_and_rollback(self):
        r=self.report(self.submit());v=r['coding'];self.assertTrue(v['passed']);self.assertTrue(v['validation']['heldout']['worker']['lpac'])
        self.assertEqual(v['validation']['cases'],4)
        raw=base64.b64decode(v['build']['base64']);self.assertEqual(policy.digest(raw),v['build']['sha256'])
        with zipfile.ZipFile(io.BytesIO(raw)) as archive:
            self.assertEqual(set(archive.namelist()),{'calc.py','helper.py','jarvis-build.json'})
            self.assertEqual(archive.read('helper.py').decode(),GOOD_FILES['helper.py'])
        self.assertEqual(package(GOOD_FILES,'calc.py',v['cases_digest']),v['build'])
        apply_result(self.core,r,'apply')
        for p,s in GOOD_FILES.items():self.assertEqual((self.source/p).read_text(),s)
        apply_result(self.core,r,'rollback')
        for p,s in BAD_FILES.items():self.assertEqual((self.source/p).read_text(),s)
    def test_hidden_overfit_is_rejected_without_leaking_values(self):
        self.bundles=[{**GOOD_FILES,'helper.py':'def total(data):\n    return 6 if data else 0\n'}]
        r=self.report(self.submit());self.assertFalse(r['coding']['passed']);self.assertEqual(len(self.calls),2)
        self.assertTrue(r['coding']['validation']['public']['passed']);self.assertFalse(r['coding']['validation']['heldout']['passed'])
        self.assertNotIn('build',r['coding']);self.assertNotIn('heldout',json.dumps(self.calls))
        with self.assertRaises(policy.CoreError):apply_result(self.core,r,'apply')
    def test_whole_group_conflict_before_any_write(self):
        r=self.report(self.submit());(self.source/'helper.py').write_text('external')
        with self.assertRaises(policy.CoreError):apply_result(self.core,r,'apply')
        self.assertEqual((self.source/'calc.py').read_text(),BAD_FILES['calc.py'])
    def test_partial_receipt_can_resume_or_restore(self):
        for action in ['apply','rollback']:
            r=self.report(self.submit());original_write=ProjectFiles.write
            def interrupted(obj,args):
                result=original_write(obj,args)
                if args['path']=='calc.py':raise OSError('lost receipt after first write')
                return result
            with patch.object(ProjectFiles,'write',interrupted),self.assertRaises(policy.CoreError) as raised:apply_result(self.core,r,'apply')
            self.assertEqual(raised.exception.code,'coding_partial')
            apply_result(self.core,r,action)
            expected=GOOD_FILES if action=='apply' else BAD_FILES
            for p,s in expected.items():self.assertEqual((self.source/p).read_text(),s)
            if action=='apply':apply_result(self.core,r,'rollback')
    def test_partial_external_edit_is_never_overwritten(self):
        r=self.report(self.submit());original_write=ProjectFiles.write
        def interrupted(obj,args):
            original_write(obj,args);raise OSError('lost receipt')
        with patch.object(ProjectFiles,'write',interrupted),self.assertRaises(policy.CoreError):apply_result(self.core,r,'apply')
        (self.source/'helper.py').write_text('external')
        for action in ['apply','rollback']:
            with self.assertRaises(policy.CoreError):apply_result(self.core,r,action)
        self.assertEqual((self.source/'helper.py').read_text(),'external')
    def test_extra_path_and_bad_import_never_delivered(self):
        self.bundles=[{**GOOD_FILES,'extra.py':GOOD_FILES['helper.py']},{**GOOD_FILES,'helper.py':'import os\ndef total(data):\n    return 1\n'}]
        r=self.report(self.submit());self.assertFalse(r['coding']['passed'])
    def test_contract_rejects_public_private_overlap_and_cycles(self):
        with self.assertRaises(policy.CoreError):self.submit(heldout_cases=CASES)
        with self.assertRaises(policy.CoreError):validate_bundle({**BAD_FILES,'helper.py':'import calc\ndef total(data):\n    return 1\n'},'calc.py')


# unittest discovers inherited methods; the original suite already covers them.
for _name in dir(CodingTests):
    if _name.startswith('test_') and _name not in BundleTests.__dict__: setattr(BundleTests,_name,None)
del CodingTests

if __name__=='__main__':
    import unittest
    unittest.main()
