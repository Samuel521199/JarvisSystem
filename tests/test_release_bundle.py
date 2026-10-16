"""Release candidate integrity, bounded extraction and no overwrite."""
import hashlib
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
import zipfile

ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('release_bundle',ROOT/'tools/release_bundle.py')
bundle=importlib.util.module_from_spec(spec);spec.loader.exec_module(bundle)


class BundleTests(unittest.TestCase):
    def setUp(self):
        temp=tempfile.TemporaryDirectory(prefix='jarvis-release-test-')
        self.addCleanup(temp.cleanup);self.root=Path(temp.name)

    def archive(self,files=None,extras=None):
        files=files or {'source/hello.txt':b'hello'}
        path=self.root/'candidate.zip'
        meta={'schema_version':1,'version':'test','files':{p:{'sha256':hashlib.sha256(raw).hexdigest(),'size':len(raw)} for p,raw in files.items()}}
        with zipfile.ZipFile(path,'w') as archive:
            for p,raw in files.items():archive.writestr(p,raw)
            archive.writestr('release.json',json.dumps(meta))
            for p,raw in (extras or {}).items():archive.writestr(p,raw)
        return path

    def test_verify_extract_and_existing_slot_is_preserved(self):
        path=self.archive();slot=self.root/'slot'
        self.assertFalse(bundle.extract(path,slot)['activated'])
        self.assertEqual((slot/'source/hello.txt').read_text(),'hello')
        with self.assertRaises(FileExistsError):bundle.extract(path,slot)
        self.assertEqual((slot/'source/hello.txt').read_text(),'hello')

    def test_tamper_extra_and_duplicate_members_fail_before_extract(self):
        path=self.archive(extras={'extra.py':b'bad'})
        with self.assertRaises(ValueError):bundle.extract(path,self.root/'slot')
        self.assertFalse((self.root/'slot').exists())
        with zipfile.ZipFile(path,'w') as archive:
            archive.writestr('release.json','{"schema_version":1,"files":{"code.py":{"size":4,"sha256":"wrong"}}}')
            archive.writestr('code.py',b'evil')
        with self.assertRaises(ValueError):bundle.verify(path)

    def test_traversal_windows_devices_case_collisions_and_links_rejected(self):
        for name in ('../escape','/absolute','C:/file','a\\b','a/../b','a/CON','file:stream','a./b'):
            with self.subTest(name=name),self.assertRaises(ValueError):bundle.archive_path(name)
        path=self.archive({'source/A.py':b'a','source/a.py':b'b'})
        with self.assertRaises(ValueError):bundle.verify(path)
        info=zipfile.ZipInfo('link');info.external_attr=0o120777<<16
        with zipfile.ZipFile(path,'w') as archive:archive.writestr(info,'target')
        with self.assertRaises(ValueError):bundle.verify(path)


if __name__=='__main__':unittest.main()
