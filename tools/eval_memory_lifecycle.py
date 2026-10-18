"""Replay public synthetic memory lifecycles; no real model or production data."""
import argparse
from contextlib import ExitStack
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import time
import statistics
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tools'))
from memory_lab.lifecycle import Replay, load_cases
from jarvis_core import __version__
from jarvis_core.process_memory import process_memory
from jarvis_core.memory import MAX_RECEIPTS


def revision_cost():
    """Bounded metadata-read microbenchmark, not a whole-PC resource acceptance."""
    with tempfile.TemporaryDirectory(prefix='jarvis-memory-revision-') as directory:
        replay = Replay(directory)
        with replay.memory.connection() as db:
            db.execute('BEGIN IMMEDIATE')
            db.executemany('INSERT INTO receipts VALUES (?,?,?,?,?)',
                (('synthetic-limit', i+1, 'correct', 'owner_explicit', '2026-10-18T00:00:00Z') for i in range(MAX_RECEIPTS)))
            db.commit()
        before = hashlib.sha256(replay.memory.path.read_bytes()).hexdigest()
        elapsed = []
        for _ in range(100):
            start = time.perf_counter()
            assert replay.memory.review_revision() == MAX_RECEIPTS
            elapsed.append((time.perf_counter()-start)*1000)
        after = hashlib.sha256(replay.memory.path.read_bytes()).hexdigest()
        assert before == after
        return {'receipt_rows': MAX_RECEIPTS, 'reads': len(elapsed), 'database_unchanged': before == after,
                'p50_ms': round(statistics.median(elapsed), 4), 'p95_ms': round(sorted(elapsed)[94], 4),
                'max_ms': round(max(elapsed), 4), 'synthetic_database_bytes': replay.memory.path.stat().st_size}


def run(corpus):
    cases = load_cases(corpus)
    paths = [Path(corpus), Path(__file__), ROOT/'tools/memory_lab/lifecycle.py',
             *[ROOT/'runtime/node-host/jarvis_core'/name for name in
               ('memory.py', 'semantic_candidates.py', 'memory_sources.py', 'memory_policy.py', 'personal_candidates.py')]]
    hashes = lambda: {p.relative_to(ROOT).as_posix() if p.is_relative_to(ROOT) else str(p):
                      hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}
    before = hashes()
    report = {'schema': 'memory-lifecycle-report-v1', 'captured_at': datetime.now(timezone.utc).isoformat(),
              'workspace_version': __version__, 'status': 'running', 'evaluation': 'state_lifecycle_not_extraction_quality',
              'real_model_calls': 0, 'user_data_modified': False, 'new_dependencies': 0,
              'independent_holdout': False, 'cases': [], 'limitations': cases['limitations'], 'source_hashes': before}
    start = time.perf_counter()
    with ExitStack() as stack:
        # Temporary directories do not isolate OS credential stores. Block dispatch
        # and socket egress explicitly even if a future refactor introduces a call.
        for target in ('jarvis_core.chat.gateway.probe', 'socket.socket.connect', 'socket.socket.connect_ex', 'socket.socket.sendto', 'socket.create_connection'):
            stack.enter_context(patch(target, side_effect=AssertionError('Offline lifecycle evaluation forbids model/network dispatch')))
        for case in cases['cases']:
            item = {'id': case['id'], 'title': case['title']}
            began = time.perf_counter()
            with tempfile.TemporaryDirectory(prefix='jarvis-memory-lifecycle-') as directory:
                replay = Replay(directory)
                try:
                    for step in case['steps']:
                        replay.step(step)
                    item['status'] = 'passed'
                except Exception as error:
                    item.update(status='failed', error_type=type(error).__name__, error=str(error),
                                step=len(replay.events))
                item.update(events=replay.events, fixture_model_calls=replay.chat.calls,
                            database_bytes=sum(p.stat().st_size for p in (Path(directory)/'data').glob('memory.db*')),
                            duration_ms=round((time.perf_counter()-began)*1000, 3))
            report['cases'].append(item)
        report['revision_read_cost'] = revision_cost()
    report.update(source_unchanged=before == hashes(), duration_ms=round((time.perf_counter()-start)*1000, 3),
                  process_memory=process_memory())
    report['passed'] = sum(c['status'] == 'passed' for c in report['cases'])
    report['total'] = len(report['cases'])
    report['status'] = 'passed' if report['passed'] == report['total'] and report['source_unchanged'] else 'failed'
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--corpus', type=Path, default=ROOT/'evals/cases/memory-lifecycle-pilot.json')
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        parser.error('Output already exists; keep earlier evidence and choose a new path')
    result = run(args.corpus)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open('x', encoding='utf-8') as file:
        file.write(json.dumps(result, ensure_ascii=False, indent=2)+'\n')
    print(json.dumps({k: result[k] for k in ('status', 'passed', 'total', 'real_model_calls', 'duration_ms')}, ensure_ascii=False))
    return 0 if result['status'] == 'passed' else 1


if __name__ == '__main__':
    raise SystemExit(main())
