#!/usr/bin/env python3
"""Run a bounded text-only model probe; requires an initialized, non-stopped core."""
from pathlib import Path
import argparse
import json
import os
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "adapters/models/provider-native"), str(ROOT / "runtime/node-host")]
from jarvis_models.gateway import probe, read_config, ModelError, ProbeJournal
from jarvis_models.vault import load, VaultError
from jarvis_models.catalog import select_model
from jarvis_models.registry import effective_config


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--provider", default="auto")
    parser.add_argument("--prompt", default="仅回复：JARVIS_OK。不要调用工具。")
    parser.add_argument("--model", help="Registered model ID; requires an explicit provider")
    parser.add_argument("--data-dir", type=Path, default=Path(os.environ.get("LOCALAPPDATA", ".")) / "Jarvis/data")
    parser.add_argument("--config", type=Path, default=ROOT / "config/model-profiles/providers.json")
    parser.add_argument("--status", action="store_true")
    args = parser.parse_args()
    try:
        config = effective_config(args.config, args.data_dir)
        if args.model:
            if args.provider == "auto":
                raise ModelError("explicit_provider_required_for_model")
            config = select_model(config, args.provider, args.model)
        if args.status:
            configured = sorted(load().keys())
            journal_path = args.data_dir / "model-probes.db"
            counts = ProbeJournal(journal_path).counts() if journal_path.exists() else {}
            print(json.dumps({"configured_providers": configured, "default_provider": config["default_provider"],
                              "probe_calls": counts,
                              "balances": "not_queried", "local_call_limit": None,
                              "automatic_fallback": False, "note": "This diagnostic sends one provider request; chat supports routing."}, ensure_ascii=False))
            return 0
        from jarvis_core.service import CoreService
        core = CoreService(args.data_dir)
        result = probe(config, args.provider, args.prompt, args.data_dir, core.assert_running,
                       admission_context=core.effect_guard)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0 if result["status"] == "SUCCEEDED" else 1
    except (ModelError, VaultError) as exc:
        print(json.dumps({"status": "BLOCKED", "error": str(exc)}))
        return 2
    except Exception:
        print(json.dumps({"status": "BLOCKED", "error": "core_or_configuration_unavailable"}))
        return 2


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    raise SystemExit(main())
