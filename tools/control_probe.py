"""Reproducible offline control demonstration, using only a temporary instance."""
from contextlib import closing
import json
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import time

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "runtime/node-host"))
from jarvis_core import __version__
from jarvis_core.service import CoreService, CoreError
from jarvis_safety import SafetyStore
from jarvis_safety.store import canonical


def main():
    report = {"version": __version__, "scope": "synthetic temporary instance; no network or default-instance stop/recovery"}
    with tempfile.TemporaryDirectory(prefix="jarvis-control-probe-") as directory:
        data = Path(directory) / "data"
        core = CoreService(data)
        core.initialize(ROOT / "tests/fixtures/workspace")
        store = SafetyStore(data)
        old = core.prepare_inventory(request_id="before-stop")
        with closing(sqlite3.connect(data / "control.db")) as db:
            db.execute("BEGIN IMMEDIATE")
            start = time.perf_counter()
            script="import sys,json;sys.path.insert(0,sys.argv[1]);from jarvis_safety import SafetyStore;print(json.dumps(SafetyStore(sys.argv[2]).stop('synthetic legacy state')))"
            result = subprocess.run([sys.executable, "-B", "-c", script, str(ROOT/'runtime/sovereignty-supervisor'), str(data)],
                                    capture_output=True, text=True, encoding="utf-8", timeout=5)
            report["stop_with_business_writer_seconds"] = round(time.perf_counter() - start, 4)
            if result.returncode != 0 or not json.loads(result.stdout)["stopped"]:
                raise RuntimeError("Independent stop failed")
            db.rollback()
        authorization = store.prepare_recovery("Synthetic local migration")
        report["stopped_epoch"] = store.status()["security_epoch"]
        report["recovered_epoch"] = store.recover(authorization)["security_epoch"]
        fresh = CoreService(data)
        try:
            fresh.run(old["action"]["action_id"])
        except CoreError as exc:
            report["old_task_rejection"] = exc.code
        else:
            raise RuntimeError("Old task was incorrectly re-admitted")
        result = fresh.inventory(request_id="explicit-new-request")
        report["new_task_status"] = result["task"]["status"]
        report["artifact_digest"] = result["artifact"]["digest"]
        report["passed"] = (report["stop_with_business_writer_seconds"] < 2
                            and report["old_task_rejection"] == "stale_authorization"
                            and report["new_task_status"] == "SUCCEEDED")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
