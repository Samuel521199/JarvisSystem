"""Package graph, explicit creation and real LPAC regression cases."""
import json
import unittest
from unittest.mock import patch
from test_coding_workflow import CodingTests
from jarvis_core import policy
from jarvis_core.coding_package import layout
from jarvis_core.coding_build import build, bytes_from, inspect
from jarvis_core.evolution.runner import IsolatedRunner
from jarvis_core.coding_workflow import apply_result
from jarvis_core.project_files import ProjectFiles

FILES={'tool/__init__.py':'','tool/main.py':'from .numbers import total\ndef transform(data):\n    return str(total(data))\n',
       'tool/numbers.py':'def total(data):\n    return sum(data)\n'}
PRIVATE=[{'input':[-3,5],'expected':'2'},{'input':[7,8],'expected':'15'}]


class PackageTests(CodingTests):
    def setUp(self):
        super().setUp()
        def generate(prompt,instructions,guard):
            guard();self.calls.append(json.loads(prompt))
            return {'status':'SUCCEEDED','text':json.dumps({'files':FILES,'notes':'fixture'})}
        self.manager.skills.coding_generate=generate
    def submit(self,**kw):
        return super().submit(**{'paths':list(FILES),'new_paths':list(FILES),'entrypoint':'tool/main.py',
                                'heldout_cases':PRIVATE,'build_recipe':'python-package-v1',**kw})
    def test_new_package_actual_build_create_restore_and_reapply(self):
        r=self.report(self.submit());v=r['coding'];self.assertTrue(v['passed'],v)
        self.assertFalse((self.source/'tool').exists());self.assertTrue(v['build_validation']['worker']['lpac'])
        raw=bytes_from(v['build']);self.assertEqual(inspect(raw)[2],v['build'])
        for action in ('apply','rollback','apply','rollback'):
            apply_result(self.core,r,action)
            for p,s in FILES.items():
                if action=='apply':self.assertEqual((self.source/p).read_text(),s)
                else:self.assertFalse((self.source/p).exists())
    def test_missing_undeclared_and_new_existing_refused(self):
        with self.assertRaises(policy.CoreError):self.submit(new_paths=[])
        (self.source/'tool').mkdir();(self.source/'tool/main.py').write_text('external')
        with self.assertRaises(policy.CoreError):self.submit()
        self.assertFalse(self.calls)
    def test_newfile_partial_restore_preserves_external_change(self):
        r=self.report(self.submit());write=ProjectFiles.write
        def interrupted(obj,args):
            result=write(obj,args)
            if args['path']=='tool/main.py':raise OSError('receipt loss')
            return result
        with patch.object(ProjectFiles,'write',interrupted),self.assertRaises(policy.CoreError):apply_result(self.core,r,'apply')
        (self.source/'tool/main.py').write_text('external')
        with self.assertRaises(policy.CoreError):apply_result(self.core,r,'rollback')
        self.assertEqual((self.source/'tool/main.py').read_text(),'external')
    def test_newfile_partial_can_restore(self):
        r=self.report(self.submit());write=ProjectFiles.write
        def interrupted(obj,args):
            write(obj,args);raise OSError('receipt loss')
        with patch.object(ProjectFiles,'write',interrupted),self.assertRaises(policy.CoreError):apply_result(self.core,r,'apply')
        apply_result(self.core,r,'rollback')
        for p in FILES:self.assertFalse((self.source/p).exists())
    def test_package_query_and_nested_absolute_import(self):
        s={'pkg/__init__.py':'','pkg/query.py':'import jmespath\nimport json\ndef result(data):\n    return json.dumps(jmespath.search("values",data))\n',
           'pkg/sub/__init__.py':'','pkg/sub/run.py':'import pkg.query\ndef transform(data):\n    return pkg.query.result(data)\n'}
        artifact=build(s,'pkg/sub/run.py','sha256:'+'0'*64,'python-package-query-v1')
        result,evidence=IsolatedRunner().run_build(artifact,[{'values':[1,2]}],lambda:None)
        self.assertEqual(result,['[1, 2]']);self.assertTrue(evidence['lpac']);bytes_from(artifact)
    def test_graph_boundaries(self):
        for paths,entry in [(['pkg/run.py'],'pkg/run.py'),(['pkg.py','pkg/__init__.py'],'pkg.py'),(['../x.py'],'../x.py'),(['json.py'],'json.py')]:
            with self.assertRaises(policy.CoreError):layout(paths,entry)
        for source in ('from .. import secret\ndef transform(data):\n    return str(data)\n',
                       'from .unknown import run\ndef transform(data):\n    return run(data)\n'):
            with self.assertRaises(policy.CoreError):build({**FILES,'tool/main.py':source},'tool/main.py','sha256:'+'0'*64,'python-package-v1')

for name in dir(CodingTests):
    if name.startswith('test_') and name not in PackageTests.__dict__:setattr(PackageTests,name,None)
del CodingTests
if __name__=='__main__':unittest.main()
