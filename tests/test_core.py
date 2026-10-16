"""Behavioral tests for the restricted local shell, not production isolation."""
from __future__ import annotations

from contextlib import closing
import importlib.util
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "runtime" / "node-host"))
from jarvis_core import policy
from jarvis_core.service import CoreError, CoreService


class CoreTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="jarvis-core-test-")
        self.base = Path(self.temporary.name)
        self.input = self.base / "input"
        self.input.mkdir()
        (self.input / "hello.txt").write_text("hello", encoding="utf-8")
        (self.input / "中文").mkdir()
        (self.input / "中文" / "说明.txt").write_text("你好", encoding="utf-8")
        self.data = self.base / "data"
        self.service = CoreService(self.data)
        self.service.initialize(self.input)
        self.children = []

    def tearDown(self):
        for child in self.children:
            if child.poll() is None:
                child.kill()
            child.communicate(timeout=5)
        self.temporary.cleanup()

    def child(self, source, *args):
        environment = dict(os.environ)
        environment["PYTHONPATH"] = str(ROOT / "runtime" / "node-host")
        child = subprocess.Popen([sys.executable, "-c", source, str(self.data), *map(str, args)],
                                 stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=environment, text=True, encoding="utf-8")
        self.children.append(child)
        return child

    def wait_for(self, path, child):
        deadline = time.monotonic() + 10
        while not path.exists() and time.monotonic() < deadline:
            if child.poll() is not None:
                self.fail(f"Worker ended before barrier: {child.communicate()}")
            time.sleep(0.025)
        self.assertTrue(path.exists(), "Worker did not reach barrier")

    def assert_error(self, code, callback):
        with self.assertRaises(CoreError) as captured:
            callback()
        self.assertEqual(captured.exception.code, code)

    def test_inventory_real_artifact_and_stable_replay(self):
        result = self.service.inventory(request_id="same-request")
        self.assertEqual(result["task"]["status"], "SUCCEEDED")
        self.assertEqual(result["action"]["status"], "CONFIRMED")
        output = self.data / "artifacts" / result["artifact"]["path"]
        before = output.stat().st_mtime_ns
        payload = json.loads(output.read_text(encoding="utf-8"))
        self.assertEqual([item["path"] for item in payload["files"]], ["hello.txt", "中文/说明.txt"])
        self.assertEqual(payload["total_bytes"], 11)
        self.assertEqual(result["artifact"]["digest"], policy.digest(output.read_bytes()))
        repeated = CoreService(self.data).inventory(request_id="same-request")
        self.assertEqual(repeated["action"], result["action"])
        self.assertEqual(output.stat().st_mtime_ns, before)
        self.assertEqual(len(list((self.data / "artifacts").iterdir())), 1)

    def test_idempotency_parameter_conflict_rejected(self):
        self.service.inventory(request_id="stable")
        self.assert_error("idempotency_conflict", lambda: self.service.inventory(request_id="stable", max_files=1))
        self.assertEqual(len(self.service.status()["tasks"]), 1)

    def test_empty_directory_and_subset_are_supported(self):
        (self.input / "empty").mkdir()
        result = self.service.inventory(relative_path="empty")
        payload = json.loads((self.data / "artifacts" / result["artifact"]["path"]).read_text(encoding="utf-8"))
        self.assertEqual(payload["files"], [])
        self.assertEqual(payload["total_bytes"], 0)

    def test_count_and_byte_limits_fail_without_artifact(self):
        for arguments in ({"max_files": 1}, {"max_bytes": 1}):
            with self.subTest(arguments=arguments):
                result = self.service.inventory(**arguments)
                self.assertEqual(result["action"]["status"], "FAILED")
                self.assertEqual("limit_exceeded", result["action"]["error"]["code"])
        self.assertFalse(list((self.data / "artifacts").iterdir()))
        self.assert_error("limit_exceeded", lambda: self.service.inventory(max_files=1001))

    def test_empty_directory_queue_obeys_total_scan_deadline(self):
        empty_tree = self.input / "empty-tree"
        empty_tree.mkdir()
        (empty_tree / "a").mkdir()
        (empty_tree / "b").mkdir()
        # The clock crosses the deadline after enqueueing empty directories.
        # Checking only file entries would finish successfully and miss this.
        clock_values = iter((0, 0, 0, 0, policy.MAX_SECONDS + 1))
        with patch("jarvis_core.policy.time.monotonic", side_effect=lambda: next(clock_values, policy.MAX_SECONDS + 1)):
            result = self.service.inventory(relative_path="empty-tree")
        self.assertEqual(result["action"]["status"], "FAILED")
        self.assertEqual(result["action"]["error"]["code"], "limit_exceeded")
        self.assertFalse(list((self.data / "artifacts").iterdir()))

    def test_path_escape_and_data_overlap_rejected(self):
        for relative in ("..", "../input", "C:\\Windows", "/etc", "foo/../../bar", "x:stream"):
            with self.subTest(relative=relative):
                self.assert_error("path_denied", lambda: self.service.inventory(relative_path=relative))
        self.assert_error("control_invalid", lambda: CoreService(self.input / "data").initialize(self.input))

    def test_symlink_is_rejected(self):
        outside = self.base / "outside.txt"
        outside.write_text("not input", encoding="utf-8")
        try:
            (self.input / "linked.txt").symlink_to(outside)
        except OSError as exc:
            self.skipTest(f"OS denied test symlink creation: {exc}")
        result = self.service.inventory()
        self.assertEqual(result["action"]["status"], "FAILED")
        self.assertEqual("path_denied", result["action"]["error"]["code"])
        self.assertFalse(list((self.data / "artifacts").iterdir()))

    @unittest.skipUnless(os.name == "nt", "Windows reparse-point behavior")
    def test_windows_junction_is_rejected(self):
        outside = self.base / "outside"
        outside.mkdir()
        link = self.input / "junction"
        # Test setup only: the runtime never invokes a shell or creates junctions.
        completed = subprocess.run(["cmd.exe", "/d", "/c", "mklink", "/J", str(link), str(outside)], capture_output=True)
        if completed.returncode:
            self.skipTest("Windows did not allow junction creation")
        try:
            result = self.service.inventory()
            self.assertEqual(result["action"]["status"], "FAILED")
            self.assertEqual("path_denied", result["action"]["error"]["code"])
        finally:
            os.rmdir(link)
        self.assertTrue(outside.is_dir())

    def test_cancel_prepared_task_persists_without_effect(self):
        prepared = self.service.inventory(request_id="cancel-me", prepare_only=True)
        result = self.service.cancel(prepared["task"]["task_id"])
        self.assertEqual(result["action"]["status"], "CANCELLED")
        repeated = CoreService(self.data).inventory(request_id="cancel-me")
        self.assertEqual(repeated["task"]["status"], "CANCELLED")
        self.assertFalse(list((self.data / "artifacts").iterdir()))

    def test_stop_persists_across_restart_and_init(self):
        prepared = self.service.inventory(prepare_only=True)
        self.assertTrue(self.service.stop("test stop")["stopped"])
        restarted = CoreService(self.data)
        self.assertTrue(restarted.initialize()["stopped"])
        self.assert_error("stopped", restarted.assert_running)
        self.assert_error("stopped", lambda: restarted.inventory(request_id="after-stop"))
        self.assertEqual(restarted.status(prepared["task"]["task_id"])["record"]["action"]["status"], "CANCELLED")
        self.assertFalse(list((self.data / "artifacts").iterdir()))

    def test_missing_or_corrupt_control_fails_closed(self):
        fresh = CoreService(self.base / "absent")
        self.assertFalse(fresh.status()["initialized"])
        self.assert_error("path_missing", fresh.assert_running)
        with closing(sqlite3.connect(self.data / "control.db")) as connection:
            connection.execute("DELETE FROM control")
            connection.commit()
        self.assert_error("control_invalid", self.service.assert_running)
        self.assert_error("control_invalid", lambda: self.service.inventory())
        self.assert_error("control_invalid", self.service.initialize)

    def test_corrupt_task_history_cannot_roll_back_stop(self):
        self.service.inventory(prepare_only=True)
        with closing(sqlite3.connect(self.data / "control.db")) as connection:
            connection.execute("UPDATE tasks SET document='{' ")
            connection.commit()
        result = self.service.stop("stop despite corrupt history")
        self.assertTrue(result["stopped"])
        self.assertIn("reconciliation_error", result)
        self.assert_error("stopped", CoreService(self.data).assert_running)
        self.assert_error("stopped", lambda: CoreService(self.data).inventory())

    def test_init_cannot_widen_root_or_reset_missing_database(self):
        other = self.base / "other"
        other.mkdir()
        self.assert_error("reconfiguration_denied", lambda: self.service.initialize(other))
        (self.data / "control.db").unlink()
        self.assert_error("control_invalid", self.service.initialize)

    def test_permission_failure_is_recorded(self):
        with patch("jarvis_core.policy.collect_inventory", side_effect=PermissionError("test permission denied")):
            result = self.service.inventory()
        self.assertEqual(result["action"]["status"], "FAILED")
        self.assertEqual("filesystem_error", result["action"]["error"]["code"])
        self.assertFalse(list((self.data / "artifacts").iterdir()))

    def test_artifact_collision_becomes_unknown_without_overwrite(self):
        prepared = self.service.inventory(request_id="collision", prepare_only=True)
        destination = self.data / "artifacts" / (prepared["action"]["action_id"] + ".json")
        destination.write_text("existing", encoding="utf-8")
        result = self.service.inventory(request_id="collision")
        self.assertEqual(result["action"]["status"], "UNKNOWN")
        self.assertEqual(destination.read_text(encoding="utf-8"), "existing")
        self.assertEqual(self.service.inventory(request_id="collision")["action"]["status"], "UNKNOWN")

    def test_tampered_confirmed_artifact_is_not_silently_rebuilt(self):
        result = self.service.inventory(request_id="tamper")
        destination = self.data / "artifacts" / result["artifact"]["path"]
        destination.write_text("tampered", encoding="utf-8")
        self.assert_error("artifact_unavailable", lambda: self.service.inventory(request_id="tamper"))
        self.assertEqual(destination.read_text(encoding="utf-8"), "tampered")

    def test_crash_before_or_after_effect_recovers_unknown_and_does_not_replay(self):
        source = '''
import os, sys
from jarvis_core.service import CoreService
service=CoreService(sys.argv[1])
record=service.prepare_inventory(request_id=sys.argv[2])
with service.ledger.worker_lock():
    service.ledger.begin_dispatch(record['action']['action_id'], 'crash-test')
    if sys.argv[3]=='after':
        path=service.ledger.artifact_dir/(record['action']['action_id']+'.json')
        with path.open('xb') as target:
            target.write(b'{"partial":true}')
            target.flush(); os.fsync(target.fileno())
    os._exit(23)
'''
        for point in ("before", "after"):
            child = self.child(source, "crash-" + point, point)
            child.communicate(timeout=10)
            self.assertEqual(child.returncode, 23)
            status = CoreService(self.data).status()
            self.assertTrue(status["recovered_unknown"])
            existing = sorted(path.name for path in (self.data / "artifacts").iterdir())
            result = self.service.inventory(request_id="crash-" + point)
            self.assertEqual(result["action"]["status"], "UNKNOWN")
            self.assertEqual(sorted(path.name for path in (self.data / "artifacts").iterdir()), existing)

    def test_live_owner_is_not_recovered_and_competing_worker_is_rejected(self):
        ready, release = self.base / "ready", self.base / "release"
        source = '''
import sys, time
from pathlib import Path
from jarvis_core.service import CoreService
from jarvis_core import policy
service=CoreService(sys.argv[1])
original=policy.collect_inventory
def blocked(*args):
    result=original(*args)
    Path(sys.argv[2]).write_text('ready')
    while not Path(sys.argv[3]).exists(): time.sleep(.02)
    return result
policy.collect_inventory=blocked
service.inventory(request_id='competing')
'''
        child = self.child(source, ready, release)
        self.wait_for(ready, child)
        status = self.service.status()
        self.assertEqual(status["action_counts"], {"DISPATCHING": 1})
        self.assertEqual(status["recovered_unknown"], [])
        self.assert_error("worker_busy", lambda: self.service.inventory(request_id="competing"))
        release.write_text("release")
        out, err = child.communicate(timeout=10)
        self.assertEqual(child.returncode, 0, (out, err))
        result = self.service.inventory(request_id="competing")
        self.assertEqual(result["action"]["status"], "CONFIRMED")
        self.assertEqual(len(list((self.data / "artifacts").iterdir())), 1)

    def _run_scan_race(self, use_stop):
        source = '''
import sys, time
from pathlib import Path
from jarvis_core.service import CoreService
from jarvis_core import policy
service=CoreService(sys.argv[1])
original=policy.collect_inventory
def blocked(*args):
    result=original(*args)
    Path(sys.argv[2]).write_text('ready')
    while not Path(sys.argv[3]).exists(): time.sleep(.02)
    return result
policy.collect_inventory=blocked
service.inventory(request_id='race')
'''
        ready, release = self.base / "ready", self.base / "release"
        child = self.child(source, ready, release)
        self.wait_for(ready, child)
        task = self.service.status()["tasks"][0]
        if use_stop:
            self.service.stop("racing stop")
        else:
            self.service.cancel(task["task_id"])
        release.write_text("release")
        out, err = child.communicate(timeout=10)
        self.assertEqual(child.returncode, 0, (out, err))
        self.assertFalse(list((self.data / "artifacts").iterdir()))
        self.assertEqual(self.service.status(task["task_id"])["record"]["action"]["status"], "CANCELLED")

    def test_stop_during_scan_prevents_final_effect(self):
        self._run_scan_race(True)

    def test_cancel_during_scan_prevents_final_effect(self):
        self._run_scan_race(False)

    def test_cli_commands_from_repository_root(self):
        command = [sys.executable, str(ROOT / "apps" / "cli" / "main.py")]
        result = subprocess.run([*command, "status", "--data-dir", str(self.data)], cwd=ROOT, capture_output=True, text=True, encoding="utf-8")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(json.loads(result.stdout)["initialized"])
        result = subprocess.run([*command, "--data-dir", str(self.data), "inventory", "--request-id", "cli"], cwd=ROOT, capture_output=True, text=True, encoding="utf-8")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)["action"]["status"], "CONFIRMED")

    def test_actual_capability_outputs_match_declared_schemas(self):
        from jsonschema import Draft202012Validator
        catalog = json.loads((ROOT / "seed" / "skills" / "catalog.json").read_text(encoding="utf-8"))
        capabilities = {item["capability_id"]: item for item in catalog["capabilities"]}
        def validate(capability_id, value):
            errors = list(Draft202012Validator(capabilities[capability_id]["output_schema"]).iter_errors(value))
            self.assertEqual([error.message for error in errors], [], capability_id)
        result = self.service.inventory(request_id="capability-output")
        inventory = json.loads((self.data / "artifacts" / result["artifact"]["path"]).read_text(encoding="utf-8"))
        validate("filesystem.read_sample.v1", inventory)
        validate("system.status.v1", self.service.status())
        validate("system.status.v1", self.service.status(result["task"]["task_id"]))
        validate("system.status.v1", CoreService(self.base / "not-initialized").status())
        validate("system.status.v1", self.service.stop("output schema test"))

    def test_public_contracts_and_seed_policy_match(self):
        checker = ROOT / "tools" / "check_seed.py"
        if not checker.exists():
            self.skipTest("K0 validator has not been created yet")
        spec = importlib.util.spec_from_file_location("jarvis_seed_check", checker)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        prepared = self.service.inventory(request_id="schema-prepared", prepare_only=True)
        cancelled = self.service.cancel(prepared["task"]["task_id"])
        failed = self.service.inventory(request_id="schema-failed", max_files=1)
        pending = self.service.inventory(request_id="schema-unknown", prepare_only=True)
        collision = self.data / "artifacts" / (pending["action"]["action_id"] + ".json")
        collision.write_text("existing", encoding="utf-8")
        unknown = self.service.inventory(request_id="schema-unknown")
        succeeded = self.service.inventory(request_id="schema")
        for result in (prepared, cancelled, failed, unknown, succeeded):
            for name in ("task", "action", "artifact"):
                if result[name] is not None:
                    self.assertEqual(module.validate_contract(name, result[name], ROOT), [], (name, result["action"]["status"]))
        rules = json.loads((ROOT / "seed" / "rules" / "baseline.json").read_text(encoding="utf-8"))["policy"]
        self.assertEqual(rules["max_files"], policy.MAX_FILES)
        self.assertEqual(rules["max_bytes"], policy.MAX_BYTES)
        self.assertEqual(set(rules["allowed_capabilities"]), set(policy.CAPABILITIES))
        for forbidden in ("network_access", "arbitrary_shell", "device_control", "production_write", "unknown_action_replay"):
            self.assertFalse(rules[forbidden])


if __name__ == "__main__":
    unittest.main()
