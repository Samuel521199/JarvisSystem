"""Local status and one-time legacy-state migration; no global-stop or auth UI."""
from __future__ import annotations
import argparse
import json
import os
from pathlib import Path
import sys

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "runtime/sovereignty-supervisor"))
from jarvis_safety import SafetyError, SafetyStore


def default_data():
    if os.environ.get("LOCALAPPDATA"):
        return Path(os.environ["LOCALAPPDATA"]) / "Jarvis/data"
    return Path.home() / ".local/share/Jarvis/data"


def main(argv=None):
    parser = argparse.ArgumentParser(description="Jarvis local status; Stop in chat cancels only that reply")
    parser.add_argument("--data-dir", type=Path, default=default_data())
    commands = parser.add_subparsers(dest="command", required=True)
    for name in ("status", "migrate-local"):
        command = commands.add_parser(name)
        command.add_argument("--data-dir", type=Path, default=argparse.SUPPRESS)
    args = parser.parse_args(argv)
    store = SafetyStore(args.data_dir)
    try:
        result = store.status()
        if args.command == "migrate-local" and result["stopped"]:
            result = store.recover(store.prepare_recovery())
            result["restart_required"] = True
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    except (SafetyError, OSError, ValueError, TypeError) as exc:
        print(json.dumps({"ok": False, "error": getattr(exc, "code", "maintenance_failed"),
                          "message": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 2


if __name__ == "__main__":
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")
    raise SystemExit(main())
