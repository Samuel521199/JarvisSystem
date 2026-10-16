"""Reproduce a small Chinese FTS5 matching probe without network or user data."""
from __future__ import annotations

import argparse
import hashlib
import json
import platform
import sqlite3
from datetime import datetime, timezone
from pathlib import Path


def probe() -> dict:
    sample = "贾维斯需要离线记忆和知识管理"
    queries = ["离线", "离线记忆", "知识管理"]
    results = []
    with sqlite3.connect(":memory:") as db:
        for name, tokenizer, body in (
            ("unicode61", "unicode61", sample),
            ("trigram", "trigram", sample),
            ("manual_token_control", "unicode61", "贾维斯 需要 离线 记忆 和 知识 管理 离线记忆 知识管理"),
        ):
            # Table names and tokenizer values are internal constants only.
            db.execute(f"CREATE VIRTUAL TABLE {name} USING fts5(body, tokenize='{tokenizer}')")
            db.execute(f"INSERT INTO {name}(body) VALUES (?)", (body,))
            results.append({
                "table": name, "tokenizer": tokenizer, "input": body,
                "matches": {
                    query: db.execute(
                        f"SELECT count(*) FROM {name} WHERE {name} MATCH ?", (query,)
                    ).fetchone()[0]
                    for query in queries
                },
            })
    return {
        "schema_version": 1,
        "recorded_at": datetime.now(timezone.utc).isoformat(),
        "python_version": platform.python_version(),
        "sqlite_version": sqlite3.sqlite_version,
        "script_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "scope": "Synthetic single-row MATCH behavior only; not a quality or performance benchmark.",
        "results": results,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    report = json.dumps(probe(), ensure_ascii=False, indent=2) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(report, encoding="utf-8")
    print(report)


if __name__ == "__main__":
    main()
