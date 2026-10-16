"""K1/W1 diagnostic behavior; no production permission or stop changes."""
from __future__ import annotations

from contextlib import closing
import copy
import errno
import hashlib
import json
import os
from pathlib import Path
import shutil
import socket
import sqlite3
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

from jsonschema import Draft202012Validator, FormatChecker

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "runtime/node-host"))
from jarvis_core import preflight
from jarvis_core.service import CoreService


class PreflightTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="jarvis-preflight-")
        self.addCleanup(temporary.cleanup)
        self.base = Path(temporary.name)
        self.data = self.base / "data"
        self.input = self.base / "input"
        self.input.mkdir()
        (self.input / "example.txt").write_text("sample", encoding="utf-8")
        self.schema = json.loads((ROOT / preflight.SCHEMA).read_text(encoding="utf-8"))
        self.validator = Draft202012Validator(self.schema, format_checker=FormatChecker())

    def collect(self, **kwargs):
        return preflight.collect_report(self.data, ports=(), **kwargs)

    def initialize(self):
        self.service = CoreService(self.data)
        self.service.initialize(self.input)
        return self.service

    def snapshot(self):
        return {path.relative_to(self.base).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
                for path in self.base.rglob("*") if path.is_file()}

    @staticmethod
    def indexed(report):
        return {item["id"]: item for item in report["checks"]}

    def test_missing_data_is_reported_without_initializing(self):
        before = self.snapshot()
        report = self.collect()
        self.assertEqual(report["readiness"], "blocked")
        self.assertEqual(self.indexed(report)["path.data"]["evidence"]["error"], "path_missing")
        self.assertFalse(self.data.exists())
        self.assertEqual(before, self.snapshot())
        self.validator.validate(report)

    def test_live_writer_does_not_block_diagnostics_or_recover_orphan(self):
        service = self.initialize()
        prepared = service.prepare_inventory(request_id="orphan")
        service.ledger.begin_dispatch(prepared["action"]["action_id"], "host_test")
        with closing(sqlite3.connect(self.data / "control.db")) as db:
            db.execute("BEGIN IMMEDIATE")
            # Windows locks a WAL shared-memory range against ordinary file
            # reads. Compare file identities/metadata plus SQL contents through
            # the existing transaction instead of opening that locked range.
            def file_state():
                return {p.name: (p.stat().st_ino, p.stat().st_size, p.stat().st_mtime_ns)
                        for p in self.data.iterdir()}
            before = file_state()
            sql_before = list(db.iterdump())
            start = time.monotonic()
            with patch.object(CoreService, "status", side_effect=AssertionError("status mutates orphan state")):
                report = self.collect()
            elapsed = time.monotonic() - start
            self.assertEqual(before, file_state())
            self.assertEqual(sql_before, list(db.iterdump()))
            row = db.execute("SELECT document FROM actions").fetchone()
            self.assertEqual(json.loads(row[0])["status"], "DISPATCHING")
            db.rollback()
        self.assertLess(elapsed, 15, "Diagnostic may be waiting on the live ledger")
        self.assertEqual(self.indexed(report)["control.live_state"]["status"], "unknown")

    def test_stopped_instance_remains_stopped_with_unchanged_files(self):
        service = self.initialize()
        service.stop("synthetic test stop")
        before = self.snapshot()
        report = self.collect()
        self.assertEqual(before, self.snapshot())
        self.assertTrue(service.ledger.control()["stopped"])
        self.assertEqual(report["readiness"], "blocked")

    def test_missing_and_incompatible_dependencies_are_not_green(self):
        def installed(name):
            if name == "httpx":
                raise preflight.metadata.PackageNotFoundError(name)
            return "999.0.0"
        with patch.object(preflight.metadata, "version", side_effect=installed):
            checks = self.indexed(self.collect())
        self.assertEqual(checks["dependency.httpx"]["status"], "fail")
        self.assertIsNone(checks["dependency.httpx"]["evidence"]["installed"])
        self.assertEqual(checks["dependency.jsonschema"]["status"], "fail")

    def test_unsupported_python_version_is_reported(self):
        with patch.object(preflight.sys, "version_info", (3, 14, 0)):
            report = self.collect()
        self.assertEqual(self.indexed(report)["runtime.python"]["status"], "fail")

    def test_mismatched_project_version_and_missing_source_are_reported(self):
        root = self.base / "source"
        root.mkdir()
        source = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
        (root / "pyproject.toml").write_text(source.replace(f'version = "{preflight.__version__}"', 'version = "99.0.0"'), encoding="utf-8")
        shutil.copyfile(ROOT / "uv.lock", root / "uv.lock")
        checks = self.indexed(self.collect(root=root))
        self.assertEqual(checks["runtime.version"]["status"], "fail")
        self.assertEqual(checks["source.fingerprint"]["status"], "fail")

    def test_permission_denied_does_not_look_like_success(self):
        with patch.object(preflight.policy, "safe_path", side_effect=PermissionError("synthetic denial")):
            result = preflight.path_check("path.synthetic", self.input)
        self.assertEqual(result["status"], "fail")
        self.assertEqual(result["evidence"]["error"], "PermissionError")

    @unittest.skipUnless(os.name == "nt", "Windows ACL evidence")
    def test_unreadable_acl_and_missing_identity_are_unknown(self):
        with patch.object(preflight, "system_query", return_value={"error": "TimeoutExpired"}):
            self.assertEqual(preflight.path_check("path.input", self.input)["status"], "unknown")
            self.assertEqual(preflight.identity_check()["status"], "unknown")

    def test_occupied_loopback_port_is_detected_without_connecting(self):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
            if os.name == "nt":
                listener.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
            listener.bind(("127.0.0.1", 0))
            listener.listen(1)
            port = listener.getsockname()[1]
            with patch.object(socket.socket, "connect", side_effect=AssertionError("No network request")), \
                 patch.object(socket.socket, "connect_ex", side_effect=AssertionError("No network request")):
                result = preflight.port_check(port)
            self.assertEqual(result["evidence"]["observation"], "occupied")
            self.assertEqual(result["status"], "warn")
            listener.setblocking(False)
            with self.assertRaises(BlockingIOError):
                listener.accept()
        self.assertEqual(preflight.port_check(port)["status"], "pass")

    def test_bind_permission_failure_is_not_mislabeled_occupied(self):
        with patch.object(socket.socket, "bind", side_effect=PermissionError(errno.EACCES, "denied")):
            result = preflight.port_check(18180)
        self.assertEqual(result["status"], "unknown")
        self.assertEqual(result["evidence"]["observation"], "unavailable")

    def test_unverified_boundaries_are_blocked_even_with_self_claimed_roles(self):
        report = self.collect()
        checks = self.indexed(report)
        for identifier in ("boundary.supervisor", "boundary.worker"):
            self.assertEqual(checks[identifier]["status"], "fail")
        self.assertEqual(checks["boundary.recovery"]["status"], "warn")
        self.assertEqual(checks["boundary.recovery"]["evidence"]["evidence_level"], "deferred_by_owner")
        self.assertEqual(checks["roles.declaration"]["status"], "warn")
        self.assertNotIn("authorization", report)

    def test_schema_rejects_unknown_fields_versions_and_authorization(self):
        for valid in (True, False):
            path = ROOT / f"tests/fixtures/preflight/{'valid' if valid else 'invalid'}.json"
            payload = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(not list(self.validator.iter_errors(payload)), valid)
        report = self.collect()
        self.validator.validate(report)
        for field, value in (("schema_version", "99.0.0"), ("readiness", "authorized"), ("allow_shell", True)):
            candidate = copy.deepcopy(report)
            candidate[field] = value
            self.assertTrue(list(self.validator.iter_errors(candidate)))

    def test_cli_emits_structured_blocked_result_without_loading_chat_or_vault(self):
        wrapper = (
            "import runpy,sys\n"
            "def audit(event,args):\n"
            " if event=='import' and (args[0].startswith('jarvis_models') or args[0] in ('httpx','jarvis_core.chat')):\n"
            "  raise RuntimeError('Forbidden model/credential import')\n"
            "sys.addaudithook(audit)\n"
            "sys.argv=['main.py','preflight','--json','--data-dir',sys.argv[1]]\n"
            "runpy.run_path('apps/cli/main.py',run_name='__main__')\n"
        )
        result = subprocess.run([sys.executable, "-B", "-c", wrapper, str(self.data)], cwd=ROOT,
                                capture_output=True, text=True, encoding="utf-8", timeout=20)
        self.assertEqual(result.returncode, 1, result.stderr)
        payload = json.loads(result.stdout)
        self.validator.validate(payload)
        self.assertFalse(self.data.exists())


if __name__ == "__main__":
    unittest.main()
