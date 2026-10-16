"""Legacy control compatibility and personal-use entry points; synthetic instances only."""
from __future__ import annotations

from contextlib import closing, redirect_stdout, redirect_stderr
import copy
import importlib.util
import io
import json
import os
from pathlib import Path
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch
from concurrent.futures import ThreadPoolExecutor

from jsonschema import Draft202012Validator, FormatChecker

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "runtime/node-host"))
from jarvis_core.service import CoreError, CoreService
from jarvis_safety import SafetyError, SafetyStore
from jarvis_safety.store import canonical

REPAIR = "sha256:" + "a" * 64
CLI = ROOT / "runtime/recovery-cli/main.py"


class ControlTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="jarvis-control-")
        self.addCleanup(temporary.cleanup)
        self.base = Path(temporary.name)
        self.input = self.base / "input"
        self.input.mkdir()
        (self.input / "hello.txt").write_text("hello", encoding="utf-8")
        self.data = self.base / "data"
        self.core = CoreService(self.data)
        self.core.initialize(self.input)
        self.store = SafetyStore(self.data)

    def legacy_stop_process(self, reason):
        script = "import sys;sys.path.insert(0,sys.argv[1]);from jarvis_safety import SafetyStore;import json;result=SafetyStore(sys.argv[2]).stop(sys.argv[3]);print(json.dumps(result));sys.exit(1 if result.get('pending_stop') else 0)"
        return subprocess.run([sys.executable, '-B', '-c', script, str(ROOT/'runtime/sovereignty-supervisor'), str(self.data), reason], capture_output=True, text=True, encoding='utf-8', timeout=10)

    def migration_request(self):
        return self.store.prepare_recovery("Synthetic local migration")

    def assert_code(self, code, function):
        with self.assertRaises((CoreError, SafetyError)) as caught:
            function()
        self.assertEqual(caught.exception.code, code)

    def cli(self, *args):
        return subprocess.run([sys.executable, "-B", str(CLI), "--data-dir", str(self.data), *args],
                              cwd=ROOT, capture_output=True, text=True, encoding="utf-8", timeout=10)

    def test_independent_process_stops_while_business_db_is_write_locked(self):
        with closing(sqlite3.connect(self.data / "control.db")) as db:
            db.execute("BEGIN IMMEDIATE")
            start = time.monotonic()
            stopped = self.legacy_stop_process("synthetic locked business DB")
            self.assertLess(time.monotonic() - start, 2)
            self.assertEqual(stopped.returncode, 0, stopped.stderr)
            self.assertTrue(json.loads(stopped.stdout)["stopped"])
            self.assert_code("stopped", self.core.assert_running)
            status = self.cli("status")
            self.assertEqual(status.returncode, 0, status.stderr)
            self.assertTrue(json.loads(status.stdout)["stopped"])
            db.rollback()

    def test_business_stop_entry_also_returns_without_waiting_on_writer(self):
        with closing(sqlite3.connect(self.data / "control.db")) as db:
            db.execute("BEGIN IMMEDIATE")
            start = time.monotonic()
            result = self.core.stop("busy")
            self.assertLess(time.monotonic() - start, 2)
            self.assertTrue(result["stopped"])
            self.assertIn("reconciliation_error", result)
            db.rollback()

    def test_safety_db_busy_retains_durable_deny_marker(self):
        with closing(sqlite3.connect(self.store.db_path)) as db:
            db.execute("BEGIN IMMEDIATE")
            result = self.legacy_stop_process("busy safety writer")
            self.assertEqual(result.returncode, 1, result.stderr)
            self.assertTrue(json.loads(result.stdout)["pending_stop"])
            self.assertTrue(list(self.store.pending_dir.iterdir()))
            self.assert_code("stopped", CoreService(self.data).assert_running)
            db.rollback()
        restarted = SafetyStore(self.data)
        restarted.reconcile_pending()
        self.assertTrue(restarted.status()["stopped"])
        self.assertEqual(len(restarted.status()["incidents"]), 1)
        self.assertEqual(list(self.store.pending_dir.iterdir()), [])

    def test_damaged_business_db_does_not_prevent_stop_or_alert(self):
        (self.data / "control.db").write_bytes(b"not sqlite")
        result = self.core.stop("damaged business db")
        self.assertTrue(result["stopped"])
        self.assertTrue(self.store.status()["incidents"])
        self.assert_code("stopped", self.core.assert_running)

    def test_local_migration_preserves_incidents_and_increments_epoch(self):
        before = self.store.status()["security_epoch"]
        self.store.stop("first")
        stopped = self.store.status()
        authorization = self.migration_request()
        result = self.store.recover(authorization)
        self.assertFalse(result["stopped"])
        self.assertGreater(result["security_epoch"], stopped["security_epoch"])
        self.assertGreater(stopped["security_epoch"], before)
        self.assertEqual(result["node_id"], stopped["node_id"])
        with self.store.connection() as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM incidents").fetchone()[0], 1)
            self.assertIsNotNone(db.execute("SELECT resolved_epoch FROM incidents").fetchone()[0])
            self.assertEqual(db.execute("SELECT kind FROM audit ORDER BY sequence DESC LIMIT 1").fetchone()[0], "RECOVER")

    def test_retired_credential_payloads_are_rejected_without_changing_state(self):
        self.store.stop("legacy test")
        before = self.store.status()
        for request in ({'password':'unused'}, {'challenge':{}, 'signature':'unused'}, self.migration_request() | {'force':True}):
            self.assert_code('invalid_recovery', lambda: self.store.recover(request))
        self.assertEqual(self.store.status(), before)

    def test_replay_is_rejected_even_after_another_stop(self):
        self.store.stop("first")
        authorization = self.migration_request()
        self.store.recover(authorization)
        self.store.stop("second")
        self.assert_code("recovery_stale", lambda: self.store.recover(authorization))
        self.assertTrue(self.store.status()["stopped"])

    def test_new_incident_invalidates_migration_snapshot(self):
        self.store.stop("first")
        authorization = self.migration_request()
        self.store.stop("second")
        self.assert_code("recovery_stale", lambda: self.store.recover(authorization))
        self.assertEqual(len(self.store.status()["incidents"]), 2)

    def test_new_pending_marker_invalidates_local_migration_snapshot(self):
        self.store.stop("legacy test")
        request = self.migration_request()
        (self.store.pending_dir / 'pending-partial.json').write_bytes(b'partial')
        self.assert_code('recovery_stale', lambda: self.store.recover(request))
        self.assertTrue(self.store.status()['stopped'])

    def test_wrong_node_epoch_or_event_set_are_rejected(self):
        self.store.stop("legacy test")
        original = self.migration_request()
        for field, value in (("security_epoch", original['security_epoch']+1), ("node_id", "00000000-0000-4000-8000-000000000000"), ('incident_ids',['incident_'+'a'*32])):
            candidate = copy.deepcopy(original); candidate[field] = value
            self.assert_code('recovery_stale', lambda: self.store.recover(candidate))

    def test_local_migration_needs_no_enrollment_and_keeps_audit(self):
        self.store.stop("legacy state without credentials")
        self.core.initialize()
        self.assertTrue(self.store.status()["stopped"])
        result = self.store.recover(self.migration_request())
        self.assertFalse(result['stopped'])
        self.assertEqual(result['recovery_mode'],'local-manual-legacy-only')
        self.assertNotIn('recovery_enrolled',result)
        with self.store.connection() as db:
            self.assertIsNone(db.execute('SELECT public_key FROM state').fetchone()[0])
            self.assertEqual(db.execute('SELECT COUNT(*) FROM incidents').fetchone()[0],1)

    def test_pre_stop_task_and_host_cannot_resume_after_recovery(self):
        old = self.core.prepare_inventory(request_id="old")
        self.store.stop("test")
        self.store.recover(self.migration_request())
        self.assert_code("stale_authorization", self.core.assert_running)
        fresh = CoreService(self.data)
        self.assert_code("stale_authorization", lambda: fresh.run(old["action"]["action_id"]))
        self.assert_code("stale_authorization", lambda: fresh.inventory(request_id="old"))
        new = fresh.prepare_inventory(request_id="explicit-new-task")
        self.assert_code("stale_authorization", lambda: self.core.run(new["action"]["action_id"]))
        self.assertEqual(fresh.status(new["task"]["task_id"])["record"]["action"]["status"], "PREPARED")
        result = fresh.inventory(request_id="explicit-new-task")
        self.assertEqual(result["task"]["status"], "SUCCEEDED")
        self.assertEqual(fresh.status(old["task"]["task_id"])["record"]["action"]["status"], "PREPARED")

    def test_stop_then_recover_during_model_reply_still_discards_old_output(self):
        from jarvis_core.chat import ChatService
        def model(*args, **kwargs):
            self.store.stop("during request")
            self.store.recover(self.migration_request())
            return {"status": "SUCCEEDED", "provider": "local", "text": "MUST_NOT_BE_DELIVERED", "outcome_uncertain": False}
        with patch("jarvis_core.chat.gateway.probe", side_effect=model):
            result = ChatService(self.core).reply("test", provider="local")
        self.assertNotEqual(result["status"], "SUCCEEDED")
        self.assertNotIn("MUST_NOT_BE_DELIVERED", json.dumps(result))

    def test_stop_mid_effect_leaves_unknown_receipt_instead_of_claiming_cancel(self):
        def interrupted(artifact):
            result = self.store.stop("during final write")
            self.assertTrue(result["stopped"])
        with patch.object(self.core, "_verify_artifact", side_effect=interrupted):
            result = self.core.inventory(request_id="racing-final-effect")
        self.assertEqual(result["action"]["status"], "UNKNOWN")
        self.assertEqual(len(list((self.data / "artifacts").iterdir())), 1)
        self.store.reconcile_pending()
        self.assertTrue(self.store.status()["stopped"])

    def test_missing_or_corrupt_safety_store_does_not_auto_reset(self):
        self.store.db_path.write_bytes(b"broken")
        self.assert_code("safety_unavailable", self.core.assert_running)
        self.assert_code("safety_unavailable", self.core.initialize)
        self.assertTrue(self.store.stop("damaged safety database")["stopped"])
        self.assert_code("stopped", self.core.assert_running)

    def test_independent_status_does_not_import_business_or_models(self):
        wrapper = (
            "import runpy,sys\n"
            "def audit(event,args):\n"
            " if event=='import' and (args[0].startswith('jarvis_core') or args[0].startswith('jarvis_models') or args[0] in {'httpx','cryptography','getpass'}):\n"
            "  raise RuntimeError('Forbidden business/model import')\n"
            "sys.addaudithook(audit)\n"
            "sys.argv=[sys.argv[1],'status','--data-dir',sys.argv[2]]\n"
            "runpy.run_path(sys.argv[0],run_name='__main__')\n"
        )
        result = subprocess.run([sys.executable, "-B", "-c", wrapper, str(CLI), str(self.data)],
                                capture_output=True, text=True, encoding="utf-8", timeout=10)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_explicit_migration_preserves_old_stop_and_invalidates_old_work(self):
        prepared = self.core.prepare_inventory(request_id="legacy")
        legacy = self.base / "legacy"
        legacy.mkdir()
        (legacy / "artifacts").mkdir()
        (legacy / "worker.lock").write_bytes(b"0")
        with closing(sqlite3.connect(self.data / "control.db")) as source, closing(sqlite3.connect(legacy / "control.db")) as target:
            source.backup(target)
            target.execute("ALTER TABLE tasks DROP COLUMN security_epoch")
            target.execute("UPDATE control SET stopped=1,stop_reason='legacy stop'")
            target.execute("PRAGMA user_version=1")
            target.commit()
        migrated = CoreService(legacy)
        self.assert_code("control_upgrade_required", migrated.assert_running)
        result = migrated.ledger.upgrade_control()
        self.assertTrue(result["stopped"])
        self.assertEqual(result["stop_reason"], "legacy stop")
        with closing(sqlite3.connect(legacy / "control.db")) as db:
            self.assertEqual(db.execute("PRAGMA user_version").fetchone()[0], 2)
            self.assertEqual(db.execute("SELECT security_epoch FROM tasks").fetchone()[0], 0)
        self.assertEqual(migrated.ledger.record(task_id=prepared["task"]["task_id"])["task"]["task_id"], prepared["task"]["task_id"])
        self.assertTrue(migrated.ledger.upgrade_control()["stopped"])

    def test_local_migration_contract_rejects_unknown_fields_and_versions(self):
        schema=json.loads((ROOT/'contracts/schemas/recovery.schema.json').read_text(encoding='utf-8'))
        validator=Draft202012Validator(schema,format_checker=FormatChecker())
        self.store.stop('legacy test');request=self.migration_request()
        validator.validate(request)
        for malformed in (request|{'force':True},request|{'schema_version':'1.0.0'},request|{'reason':' '}):
            self.assertTrue(list(validator.iter_errors(malformed)))
            self.assert_code('invalid_recovery',lambda:self.store.recover(malformed))

    def test_parallel_stops_preserve_all_incidents(self):
        with ThreadPoolExecutor(max_workers=4) as pool:
            results = list(pool.map(lambda number: SafetyStore(self.data).stop(f"incident {number}"), range(4)))
        self.assertTrue(all(item["stopped"] for item in results))
        self.store.reconcile_pending()
        self.assertEqual(len(self.store.status()["incidents"]), 4)
        self.assertEqual(list(self.store.pending_dir.iterdir()), [])

    def test_crash_after_stop_marker_before_sql_commit_is_recoverable(self):
        script = (
            "import sys,os\n"
            "sys.path.insert(0,sys.argv[1])\n"
            "from jarvis_safety import SafetyStore\n"
            "store=SafetyStore(sys.argv[2])\n"
            "store.reconcile_pending=lambda: os._exit(29)\n"
            "store.stop('synthetic crash after marker')\n"
        )
        result = subprocess.run([sys.executable, "-B", "-c", script,
                                 str(ROOT / "runtime/sovereignty-supervisor"), str(self.data)], timeout=10)
        self.assertEqual(result.returncode, 29)
        self.assert_code("stopped", CoreService(self.data).assert_running)
        self.store.reconcile_pending()
        self.assertEqual(len(self.store.status()["incidents"]), 1)

    def test_cli_has_no_stop_or_credential_flow_and_migration_is_explicit(self):
        before=self.store.status()
        for command in ('stop','keygen','enroll','challenge','sign','recover','password'):
            self.assertNotEqual(self.cli(command).returncode,0)
        primary_stop = subprocess.run([sys.executable, '-B', str(ROOT/'apps/cli/main.py'),
                                       'stop', '--data-dir', str(self.data)],
                                      capture_output=True, text=True, timeout=10)
        self.assertNotEqual(primary_stop.returncode, 0)
        self.assertEqual(before,self.store.status())
        # Running instances require no migration and must keep their generation.
        self.assertEqual(json.loads(self.cli('migrate-local').stdout),before)
        self.store.stop('synthetic legacy state')
        migrated=self.cli('migrate-local')
        self.assertEqual(migrated.returncode,0,migrated.stderr)
        value=json.loads(migrated.stdout)
        self.assertFalse(value['stopped']);self.assertTrue(value['restart_required'])
        self.assertEqual(self.cli('status').returncode,0)
        self.assertFalse(any(p.suffix in {'.pem','.pub'} for p in self.base.rglob('*')))


if __name__ == "__main__":
    unittest.main()
