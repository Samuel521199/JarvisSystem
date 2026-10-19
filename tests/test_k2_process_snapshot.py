"""Sampling must reject stale parent identities and include real owned children."""
import os
from pathlib import Path
import subprocess
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools'))
from windows_process_snapshot import OwnedProcesses,processes
from jarvis_core.process_usage import process_usage


class ProcessSnapshotTests(unittest.TestCase):
    def test_live_identity_matches_kernel_counter(self):
        rows=processes()
        self.assertEqual(rows[os.getpid()]['created_ticks'],process_usage(os.getpid())['created'])
        process=subprocess.Popen([sys.executable,'-c','import sys;sys.stdin.readline()'],stdin=subprocess.PIPE,
                                 creationflags=subprocess.CREATE_NO_WINDOW)
        try:
            reader=OwnedProcesses();tree=reader.tree(os.getpid())
            self.assertIn(process.pid,{p['pid'] for p in tree})
        finally:process.communicate(b'\n',timeout=10)

    def test_old_child_reused_root_and_orphan(self):
        def row(pid,parent,created):return {'pid':pid,'parent_pid':parent,'name':'fixture','created_ticks':created}
        initial={1:row(1,0,100),2:row(2,1,110),3:row(3,2,120),4:row(4,2,80),5:row(5,4,90)}
        reader=OwnedProcesses()
        with patch('windows_process_snapshot.processes',return_value=initial):
            self.assertEqual({r['pid'] for r in reader.tree(1)},{1,2,3})
        # The observed grandchild remains owned after its parent exits.
        with patch('windows_process_snapshot.processes',return_value={1:initial[1],3:initial[3]}):
            self.assertEqual({r['pid'] for r in reader.tree(1)},{1,3})
        with patch('windows_process_snapshot.processes',return_value={1:row(1,0,200),3:row(3,1,210)}):
            self.assertEqual(reader.tree(1),[])


if __name__=='__main__':unittest.main()
