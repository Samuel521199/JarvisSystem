#!/usr/bin/env python3
"""Verified CPU llama.cpp runtime: foreground serve or bounded local smoke test."""
from pathlib import Path, PurePosixPath
import argparse
import hashlib
import json
import os
import socket
import subprocess
import sys
import time
import zipfile

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "runtime/node-host"), str(ROOT / "adapters/models/provider-native")]


def prepare(base: Path):
    from manage_models import load_manifest, target_path, verify_file
    catalog, files = load_manifest(ROOT / "config/model-profiles/local-candidates.json")
    entries = list(files.values()) if isinstance(files, dict) else files
    model = next(x for x in entries if x["component"] == "qwen3-0.6b" and x["path"].endswith(".gguf"))
    archive = next(x for x in entries if x["id"] == "llamacpp-win-cpu")
    for entry in [model, archive]:
        if not verify_file(target_path(base, entry["path"]), entry):
            raise ValueError("Missing or modified artifact: " + entry["id"])
    destination = target_path(base, "runtimes/llamacpp-" + archive["revision"])
    destination.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(target_path(base, archive["path"])) as source:
        if len(source.infolist()) > 1000 or sum(item.file_size for item in source.infolist()) > 300_000_000:
            raise ValueError("Runtime extraction exceeds limit")
        for item in source.infolist():
            name = PurePosixPath(item.filename.replace("\\", "/"))
            if name.is_absolute() or ".." in name.parts or any(":" in part for part in name.parts):
                raise ValueError("Unsafe archive path")
            if (item.external_attr >> 16) & 0o170000 == 0o120000:
                raise ValueError("Archive links forbidden")
            relative = destination.relative_to(base).as_posix() + "/" + name.as_posix()
            target = target_path(base, relative)
            if item.is_dir():
                target.mkdir(parents=True, exist_ok=True)
                continue
            content = source.read(item)
            if target.exists():
                if hashlib.sha256(target.read_bytes()).digest() != hashlib.sha256(content).digest():
                    raise ValueError("Cached runtime differs from verified archive")
            else:
                target.parent.mkdir(parents=True, exist_ok=True)
                with target.open("xb") as stream:
                    stream.write(content)
    executables = list(destination.rglob("llama-server.exe"))
    if len(executables) != 1:
        raise ValueError("Expected exactly one llama-server")
    return executables[0], target_path(base, model["path"])


def run(args):
    from jarvis_core.service import CoreService
    import httpx
    core = CoreService(args.data_dir)
    core.assert_running()
    executable, model = prepare(args.model_root)
    with socket.socket() as sock:
        if sock.connect_ex(("127.0.0.1", 18180)) == 0:
            raise ValueError("Port 18180 already in use; refusing to probe an unknown service")
    command = [str(executable), "-m", str(model), "--host", "127.0.0.1", "--port", "18180",
               "-c", "2048", "-t", "4", "-ngl", "0", "-np", "1", "--jinja", "-n", "256"]
    if args.action == "serve":
        core.assert_running()
        process = subprocess.Popen(command, creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
        try:
            while process.poll() is None:
                core.assert_running()
                time.sleep(0.25)
            return process.returncode
        finally:
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=5)
    output = args.data_dir / "diagnostics/local-llm"
    output.mkdir(parents=True, exist_ok=True)
    started = time.monotonic()
    with (output / "server.log").open("w", encoding="utf-8") as log:
        process = subprocess.Popen(command, stdout=log, stderr=subprocess.STDOUT,
                                   creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
        try:
            with httpx.Client(timeout=2, trust_env=False) as client:
                for _ in range(120):
                    core.assert_running()
                    if process.poll() is not None:
                        raise ValueError("Local server exited during startup")
                    try:
                        if client.get("http://127.0.0.1:18180/health").status_code == 200:
                            break
                    except httpx.TransportError:
                        pass
                    time.sleep(0.5)
                else:
                    raise ValueError("Local server readiness timeout")
            from jarvis_models.gateway import probe, read_config
            report = probe(read_config(ROOT / "config/model-profiles/providers.json"), "local",
                           "请用一句简短中文说明你可以帮助整理文件。不要调用工具。", args.data_dir,
                           core.assert_running, admission_context=core.effect_guard)
            report["startup_and_probe_seconds"] = round(time.monotonic() - started, 3)
            report["profile"] = {"threads": 4, "context": 2048, "gpu_layers": 0, "parallel": 1}
            (output / "local-smoke.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            print(json.dumps(report, ensure_ascii=False, indent=2))
            return 0 if report["status"] == "SUCCEEDED" else 1
        finally:
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=5)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["serve", "smoke"])
    parser.add_argument("--model-root", type=Path, default=Path("H:/JarvisData/models"))
    parser.add_argument("--data-dir", type=Path, default=Path(os.environ.get("LOCALAPPDATA", ".")) / "Jarvis/data")
    args = parser.parse_args()
    try:
        return run(args)
    except Exception as exc:
        print(json.dumps({"status": "failed", "error_type": type(exc).__name__}))
        return 1


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    raise SystemExit(main())
