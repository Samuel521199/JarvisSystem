"""Real OS lock/profile recovery after a disposable worker Host exits abruptly."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import threading
import unittest

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'runtime/node-host'))
from jarvis_core import worker
from jarvis_core.worker_recovery import StageLease, recover, process_active, locked
from jarvis_core.policy import CoreError


@unittest.skipUnless(os.name=='nt','Windows LPAC recovery')
class RecoveryTests(unittest.TestCase):
    def setUp(self):
        temp=tempfile.TemporaryDirectory(prefix='jarvis-stage-recovery-')
        self.addCleanup(temp.cleanup);self.parent=Path(temp.name)

    def test_live_lease_retained_then_registered_stage_removed(self):
        lease=StageLease(self.parent,{'task_id':'synthetic'})
        (lease.stage/'input.json').write_text('{}')
        result=recover(self.parent)
        self.assertEqual(result['active'],[lease.stage.name]);self.assertTrue(lease.stage.exists())
        lease.close();self.assertFalse(lease.stage.exists())

    def test_shared_sweep_waits_but_owner_lease_stays_nonblocking(self):
        entered = threading.Event(); result = []; failures = []
        def allocate():
            entered.set()
            try: result.append(StageLease(self.parent, {'task_id': 'concurrent'}))
            except Exception as exc: failures.append(exc)
        with locked(self.parent/'.recovery.lock'):
            thread = threading.Thread(target=allocate); thread.start()
            self.assertTrue(entered.wait(1)); time.sleep(.1)
            self.assertTrue(thread.is_alive())
            start = time.monotonic()
            with self.assertRaises(CoreError):
                with locked(self.parent/'.recovery.lock', timeout=.05): pass
            self.assertLess(time.monotonic()-start, .5)
        thread.join(4); self.assertFalse(thread.is_alive()); self.assertFalse(failures)
        lease = result[0]
        try:
            self.assertEqual(recover(self.parent)['active'], [lease.stage.name])
            with self.assertRaises(CoreError):
                with locked(lease.stage/'.lease.lock'): pass
        finally: lease.close()

    def test_unregistered_or_changed_identity_and_extra_content_are_retained(self):
        old=self.parent/'job-old';old.mkdir();(old/'user.txt').write_text('preserve')
        lease=StageLease(self.parent,{})
        lease._lease.__exit__(None,None,None)
        meta=lease.stage/'.lease.json';record=json.loads(meta.read_text())
        record['stage_identity']=[0,0];meta.write_text(json.dumps(record))
        result=recover(self.parent)
        self.assertEqual(len(result['retained']),2)
        self.assertEqual((old/'user.txt').read_text(),'preserve')
        record['stage_identity']=lease.record['stage_identity'];meta.write_text(json.dumps(record))
        (lease.stage/'unowned.txt').write_text('preserve')
        self.assertEqual(len(recover(self.parent)['retained']),2)
        self.assertTrue((lease.stage/'unowned.txt').exists())

    def test_crash_reclaims_registered_profile_and_stage_after_job_death(self):
        runtime,_=worker.verify_bundle()
        script='''import os,sys
from pathlib import Path
sys.path.insert(0,sys.argv[1])
from jarvis_core import worker
from jarvis_core.worker_recovery import StageLease
lease=StageLease(Path(sys.argv[2]),{'task_id':'synthetic-crash'})
(lease.stage/'worker.py').write_text('import time;time.sleep(30)')
def started(pid):
 lease.started(pid)
 os._exit(77)
worker.run(Path(sys.argv[3]),lease.stage,profile_name=lease.profile,on_started=started)
'''
        result=subprocess.run([sys.executable,'-B','-c',script,str(ROOT/'runtime/node-host'),str(self.parent),str(runtime)],capture_output=True,timeout=15)
        self.assertEqual(result.returncode,77,result.stderr)
        stage=next(self.parent.glob('job-*'));record=json.loads((stage/'.lease.json').read_text())
        deadline=time.monotonic()+5
        while process_active(record['pid']) and time.monotonic()<deadline:time.sleep(.02)
        self.assertFalse(process_active(record['pid']))
        result=recover(self.parent)
        self.assertEqual(result['removed'],[stage.name]);self.assertFalse(stage.exists())
        self.assertEqual(recover(self.parent)['removed'],[])


if __name__=='__main__':unittest.main()
