#!/usr/bin/env python3
"""Capture local checks and existing diagnostics; never invoke a cloud model."""
from pathlib import Path
from datetime import datetime, timezone
import hashlib
import json
import os
import platform
import sqlite3
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
REPORT = ROOT / "evals/reports/runtime-start-baseline.json"
SKIP = {".git", "node_modules", "__pycache__", ".venv", ".pytest_cache", ".ruff_cache"}


def source_files():
    for directory, children, files in os.walk(ROOT):
        children[:] = [name for name in children if name not in SKIP]
        for name in files:
            path = Path(directory) / name
            if path == REPORT or path.suffix not in {".py", ".json", ".toml", ".lock", ".ps1", ".md", ".mmd", ".txt", ".html", ".css", ".js"}:
                continue
            yield path


def main():
    sys.path.insert(0, str(ROOT / "runtime/node-host"))
    from jarvis_core import __version__
    report = {"schema_version": 1, "version": __version__,
              "captured_at": datetime.now(timezone.utc).isoformat(),
              "environment": {"platform": platform.platform(), "python": platform.python_version()},
              "status": "verification_in_progress", "checks": []}
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    # Provide a real evidence destination for the documentation link checker.
    REPORT.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    commands = [["tools/check_seed.py"], ["-m", "unittest", "discover", "-s", "tests", "-v"], ["tools/control_probe.py"], ["tools/worker_probe.py"],
                ["tools/manage_models.py", "verify", "--profile", "local-small-cpu"],
                ["tools/check_docs.py", "--root", "."], ["tools/probe_workspace_ui.py"],
                ["tools/probe_task_responsiveness.py"], ["tools/probe_resource_admission.py"]]
    for command in commands:
        result = subprocess.run([sys.executable, *command], cwd=ROOT, capture_output=True,
                                text=True, encoding="utf-8", errors="replace", timeout=240,
                                env={**os.environ, "PYTHONUTF8": "1", "PYTHONDONTWRITEBYTECODE": "1"})
        report["checks"].append({"command": ["python", *command], "exit_code": result.returncode,
                                 "stdout": result.stdout, "stderr": result.stderr})
        print(json.dumps({"check": command, "exit_code": result.returncode}))

    files = list(source_files())
    sys.path.insert(0, str(ROOT / "adapters/models/provider-native"))
    from jarvis_models.vault import load, default_path
    if default_path().exists():
        credentials = load()
        needles = [item["api_key"].encode() for item in credentials.values() if item.get("api_key")]
        for item in credentials.values():
            for line in item.get("service_account", {}).get("private_key", "").splitlines():
                if line and not line.startswith("-----"):
                    needles.append(line.encode())
        violations = [path.relative_to(ROOT).as_posix() for path in files
                      if any(needle in path.read_bytes() for needle in needles)]
        report["secret_scan"] = {"status": "failed" if violations else "passed", "files": len(files),
                                 "matched_paths": violations, "scope": "source/document text; exact configured key material"}
        del credentials, needles
    else:
        report["secret_scan"] = {"status": "not_checked", "reason": "local vault absent"}

    data = Path(os.environ["LOCALAPPDATA"]) / "Jarvis/data"
    diagnostics = {}
    for name, relative in {"local_llm": "diagnostics/local-llm/local-smoke.json",
                           "speech": "diagnostics/speech/speech-smoke.json",
                           "chat_connectivity": "diagnostics/chat-connectivity.json",
                           "web_chat": "diagnostics/web-chat-smoke.json",
                           "model_catalog_discovery": "diagnostics/model-catalog-discovery.json",
                           "model_catalog_connectivity": "diagnostics/model-catalog-connectivity.json",
                           "model_catalog_web": "diagnostics/model-catalog-web.json",
                           "web_workspace": "diagnostics/web-workspace.json",
                           "google_models": "diagnostics/google-models.json",
                           "control_upgrade": "diagnostics/control-upgrade.json",
                           "worker_upgrade": "diagnostics/worker-upgrade.json",
                           "computer_use": "diagnostics/computer-use.json",
                           "computer_ui": "diagnostics/computer-ui/result.json",
                           "computer_web_deployment": "diagnostics/computer-ui/deployment.json",
                           "computer_queue_ui": "diagnostics/computer-queue/result.json",
                           "computer_queue_deployment": "diagnostics/computer-queue/deployment.json",
                           "project_workspace_ui": "diagnostics/project-workspace/result.json",
                           "project_workspace_deployment": "diagnostics/project-workspace/deployment.json",
                           "chat_stop_ui": "diagnostics/chat-stop/result.json",
                           "chat_stop_deployment": "diagnostics/chat-stop/deployment.json",
                           "k1_progress_ui": "diagnostics/k1-progress/ui-state.json",
                           "runtime_package": "diagnostics/k1-progress/runtime-package.json",
                           "k1_progress_readiness": "diagnostics/k1-progress/readiness.json",
                           "k1_progress_deployment": "diagnostics/k1-progress/deployment.json",
                           "personal_lifecycle_ui": "diagnostics/personal-lifecycle/result.json",
                           "runtime_slots": "diagnostics/runtime-continuity/releases.json",
                           "runtime_start": "diagnostics/runtime-start/result.json",
                           "task_responsiveness": "diagnostics/runtime-continuity/responsiveness.json",
                           "resource_admission": "diagnostics/resource-admission/result.json"}.items():
        path = data / relative
        if path.exists():
            payload = json.loads(path.read_text(encoding="utf-8"))
            if "synthetic_audio" in payload:
                payload["synthetic_audio"] = "%LOCALAPPDATA%/Jarvis/data/diagnostics/speech/synthetic-speech-test.wav"
            diagnostics[name] = {"source_sha256": hashlib.sha256(path.read_bytes()).hexdigest(), "result": payload}
    db_path = data / "model-probes.db"
    if db_path.exists():
        with sqlite3.connect(db_path.as_uri() + "?mode=ro", uri=True) as db:
            diagnostics["existing_model_probes"] = [{"provider": provider, "model": model, "created_at": created,
                "status": status, "metadata": json.loads(metadata)} for provider, model, created, status, metadata in
                db.execute("SELECT provider,model,created_at,status,metadata FROM probes ORDER BY created_at")]
    report["diagnostics"] = diagnostics
    report["diagnostic_scope"] = "Historical diagnostics retain their original timestamps; project_workspace_ui is rerun by this collector. No paid requests."
    # A readiness report is expected to say blocked until K1's real boundaries
    # exist. Capturing those gaps successfully is not a full K1 acceptance pass.
    from jarvis_core.preflight import collect_report
    report["preflight"] = collect_report(data)
    report["source_sha256"] = {p.relative_to(ROOT).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest() for p in files}
    report["limitations"] = ["Single-chat cancellation closes the local async transport and prevents fallback/output use. Synchronous authentication can take its bounded wait. Remote execution or billing already admitted cannot be guaranteed cancelled. It does not stop the global core, browser tasks, or committed file writes.",
        "Personal use requires no recovery keys or passwords and exposes no daily global stop command. Legacy stopped data can be explicitly migrated locally with epoch/audit preservation. Protected identity and credential-based recovery are deferred by the owner, not personal-use prerequisites. Standby requires the server process to remain alive; no autostart or watchdog was installed.",
        "Project folders and explicit UTF-8 exports only; no file retrieval, binary generation, overwrite, persistent chat, or agent tools. Native picker interaction is not automated; typed paths and injected picker are tested. Same-user filesystem races are outside the prototype boundary.",
        "K1, K2 and K3 gates incomplete; fixed metadata Worker uses LPAC/Job; Host and supervisor remain under caller identity; no autonomous code release.",
        "Fixed inventory and browser tasks share one durable FIFO in the existing ledger and one in-process dispatcher, with 20 waiting tasks. Windows memory admission checks available physical RAM and calling-process commit headroom, uses estimates and a stable recovery margin; it is not an OS reservation, runtime hard limit or CPU/GPU scheduler. Low memory is injected in tests; two bounded real CPU helpers are measured separately. Restart preserves pending tasks paused; UNKNOWN is never replayed.",
        "Computer Use is an optional fixed-scope DOM browser executor, not native desktop control; browser routing/context is not OS Host isolation. HTTP redirects, downloads, popups, service workers and websockets are unsupported. Screenshots stay local; page text is sent to the selected planner.",
        "Browser lifecycle uses a version-pinned private Playwright driver PID bridge and named Windows Job. Registered private profiles/download stages are reclaimed after owner locks and exit checks. Launch interrupted before PID registration, reparse or unregistered legacy data is retained. No user browser profiles or PID-based killing.",
        "Host CPU/wall polling requires a responsive Host. Registered metadata Worker residues are reclaimed only after owner locks and process checks; unregistered legacy or changed paths are retained. Source on exFAT is not ACL protected.",
        "Runtime slots verify installed members, run real LPAC health checks, select/roll back atomically and use existing business data. Explicit start may check one previously verified fallback before any business launch. Once business launch begins there is no retry/fallback. SQLite read-only compatibility checks can create WAL/SHM auxiliary files. No database schema downgrade, OS-level disconnected proof, process-crash watchdog, hot swap or complete K1/W5 acceptance. The usage lock belongs to the launcher, not an independently supervised child.",
        "Windows symlink tests may be skipped when OS privilege is unavailable; inspect unittest output.",
        "Voiceprint owner enrollment and anti-spoof evaluation not performed; speech smoke is not an accuracy benchmark.",
        "Older UNKNOWN outcomes remain in the journal; later successful requests do not resolve their billing status.",
        "Model download bytes are not peak RAM; true network-disconnected install and GPU inference not tested.",
        "Model probes predate this capture; source hashes identify the current checked source, not an assertion of cloud retest."]
    report["status"] = "passed_with_documented_limits" if (all(c["exit_code"] == 0 for c in report["checks"])
        and report["secret_scan"]["status"] == "passed") else "incomplete_or_failed"
    REPORT.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": report["status"], "report": str(REPORT), "secret_scan": report["secret_scan"]}))
    return 0 if report["status"] == "passed_with_documented_limits" else 1


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    raise SystemExit(main())
