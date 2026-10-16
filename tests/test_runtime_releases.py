"""Runtime slot selection is atomic, verified, offline and independent of data."""
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
import zipfile

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'runtime/node-host'))
from jarvis_core.releases import RuntimeSlots, verify_slot
from jarvis_core.policy import CoreError


@unittest.skipUnless(os.name == 'nt', 'Windows runtime slots')
class RuntimeReleaseTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='jarvis-release-slots-')
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.slots = RuntimeSlots(self.base/'runtime')

    def install(self, version):
        path=self.base/(version+'.zip')
        raw=version.encode()
        manifest={'schema_version':1,'version':version,'files':{
            'source/hello.txt':{'sha256':hashlib.sha256(raw).hexdigest(),'size':len(raw)}}}
        with zipfile.ZipFile(path,'w') as archive:
            archive.writestr('source/hello.txt',raw)
            archive.writestr('release.json',json.dumps(manifest))
        return self.slots.install(path)['id']

    def health(self, ident, version):
        fake=subprocess.CompletedProcess([],0,json.dumps({'status':'passed','version':version}),'')
        with patch('jarvis_core.releases.subprocess.run',return_value=fake):
            self.assertEqual(self.slots.health(ident)['state'],'verified')

    def test_install_is_idempotent_and_unchecked_release_cannot_be_selected(self):
        ident=self.install('a')
        self.assertTrue(self.slots.install(self.base/'a.zip')['existing'])
        with self.assertRaises(ValueError):self.slots.select(ident)
        self.assertIsNone(self.slots.status()['active'])
        self.assertEqual(len(self.slots.status()['releases']),1)

    def test_select_and_rollback_keep_previous_and_unrelated_data(self):
        sentinel=self.base/'data';sentinel.mkdir();(sentinel/'keep').write_text('history')
        first=self.install('a');second=self.install('b')
        self.health(first,'a');self.health(second,'b')
        self.slots.select(first);self.slots.select(second)
        state=RuntimeSlots(self.slots.root).select(rollback=True)
        self.assertEqual((state['active'],state['previous'],state['generation']),(first,second,3))
        self.assertEqual((sentinel/'keep').read_text(),'history')

    def test_failed_health_or_tampered_slot_never_replaces_active(self):
        first=self.install('a');second=self.install('b')
        self.health(first,'a');self.slots.select(first)
        with patch('jarvis_core.releases.subprocess.run',side_effect=subprocess.TimeoutExpired('health',60)):
            self.assertEqual(self.slots.health(second)['state'],'failed')
        with self.assertRaises(ValueError):self.slots.select(second)
        self.health(second,'b')
        (self.slots.slots/second/'source/hello.txt').write_text('changed')
        with self.assertRaises(ValueError):self.slots.select(second)
        self.assertEqual(self.slots.status()['active'],first)

    def test_manifest_or_extra_file_blocks_rollback(self):
        first=self.install('a');second=self.install('b')
        self.health(first,'a');self.health(second,'b')
        self.slots.select(first);self.slots.select(second)
        extra=self.slots.slots/first/'unexpected';extra.write_text('x')
        with self.assertRaises(ValueError):self.slots.select(rollback=True)
        self.assertEqual(self.slots.status()['active'],second)
        extra.unlink()
        meta=self.slots.slots/first/'release.json';value=json.loads(meta.read_text())
        value['version']='forged';meta.write_text(json.dumps(value))
        with self.assertRaises(ValueError):self.slots.select(rollback=True)

    def test_selection_transaction_failure_keeps_original_pointer(self):
        first=self.install('a');second=self.install('b')
        self.health(first,'a');self.health(second,'b');self.slots.select(first)
        with self.slots.connection() as db:
            db.execute("CREATE TRIGGER simulated_crash BEFORE INSERT ON history WHEN NEW.operation='select' BEGIN SELECT RAISE(ABORT,'synthetic failure'); END")
        with self.assertRaises(sqlite3.IntegrityError):self.slots.select(second)
        self.assertEqual(self.slots.status()['active'],first)
        self.assertEqual(self.slots.status()['generation'],1)

    def test_running_release_prevents_switch_and_only_fixed_entry_is_used(self):
        first=self.install('a');second=self.install('b')
        self.health(first,'a');self.health(second,'b');self.slots.select(first)
        data=self.base/'data';data.mkdir()
        def running(command,**kwargs):
            with self.assertRaises(CoreError):self.slots.select(second)
            self.assertEqual(command[-2:],['--data-dir',str(data)])
            self.assertIn(str(self.slots.slots/first/'source/apps/cli/main.py'),command)
            return subprocess.CompletedProcess(command,0)
        with patch('jarvis_core.releases.subprocess.run',side_effect=running):
            self.assertEqual(self.slots.run(data_dir=data),0)
        with self.assertRaises(ValueError):self.slots.run(data_dir=data,mode='shell')
        self.assertEqual(self.slots.select(second)['active'],second)


if __name__ == '__main__':unittest.main()
