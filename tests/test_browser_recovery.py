"""Browser scratch ownership and conservative recovery; no user data."""
import json
import os
from pathlib import Path
import tempfile
import sys
import subprocess
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'runtime/node-host'))
from jarvis_core.browser_recovery import BrowserLease, recover
from jarvis_core.policy import CoreError


@unittest.skipUnless(os.name == 'nt', 'Windows file leases and browser Jobs')
class BrowserRecoveryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='jarvis-browser-recovery-')
        self.addCleanup(self.temp.cleanup)
        self.parent = Path(self.temp.name)

    def test_live_lease_and_process_are_preserved(self):
        lease = BrowserLease(self.parent)
        self.addCleanup(lease.close)
        lease.started(os.getpid())
        self.assertEqual(recover(self.parent)['active'], [lease.stage.name])
        self.assertEqual(lease.close()['active'], [lease.stage.name])
        self.assertTrue(lease.profile.exists())

    def test_nested_profile_cleanup_and_unknown_directory_preservation(self):
        legacy = self.parent/'browser-legacy'; legacy.mkdir()
        (legacy/'keep.txt').write_text('user sentinel')
        lease = BrowserLease(self.parent)
        nested = lease.profile/'Default'/'Cache'; nested.mkdir(parents=True)
        (nested/'cache.bin').write_bytes(b'cache')
        self.assertEqual(lease.close()['removed'], [lease.stage.name])
        self.assertFalse(lease.stage.exists())
        result = recover(self.parent)
        self.assertEqual(len(result['retained']), 1)
        self.assertEqual((legacy/'keep.txt').read_text(), 'user sentinel')

    def test_unregistered_content_retains_entire_stage(self):
        lease = BrowserLease(self.parent)
        (lease.stage/'keep.txt').write_text('keep')
        (lease.profile/'cache').write_text('cache')
        self.assertEqual(len(lease.close()['retained']), 1)
        self.assertTrue((lease.profile/'cache').exists())
        with self.assertRaises(CoreError):
            recover(self.parent, only='../outside')

    def test_launch_gap_is_retained_and_metadata_change_is_not_trusted(self):
        lease = BrowserLease(self.parent)
        lease.launching()
        lease._lease.__exit__(None, None, None); lease.released = True
        self.assertEqual(recover(self.parent)['retained'][0]['reason'], 'browser_exit_unconfirmed')
        value = json.loads((lease.stage/'.lease.json').read_text())
        value['stage_identity'] = [0, 0]
        (lease.stage/'.lease.json').write_text(json.dumps(value))
        self.assertEqual(len(recover(self.parent)['retained']), 1)
        self.assertTrue(lease.profile.exists())

    def test_job_still_present_prevents_cleanup(self):
        lease = BrowserLease(self.parent)
        with patch('jarvis_core.browser_recovery.job_exists', return_value=True):
            self.assertEqual(lease.close()['active'], [lease.stage.name])
        self.assertEqual(recover(self.parent)['removed'], [lease.stage.name])

    def test_junction_in_profile_is_retained_without_following_target(self):
        lease = BrowserLease(self.parent)
        outside = self.parent/'outside';outside.mkdir()
        sentinel = outside/'keep';sentinel.write_text('preserve')
        link = lease.profile/'redirect'
        result = subprocess.run(['cmd','/c','mklink','/J',str(link),str(outside)],capture_output=True)
        self.assertEqual(result.returncode,0,result.stderr)
        try:
            self.assertEqual(len(lease.close()['retained']),1)
            self.assertEqual(sentinel.read_text(),'preserve')
        finally:
            os.rmdir(link)  # Remove this test junction itself, never recurse.
            recover(self.parent)


if __name__ == '__main__':
    unittest.main()
