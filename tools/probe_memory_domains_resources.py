"""Compare bounded fact views on synthetic data; never load models or user data."""
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import statistics
import sys
import tempfile
import time
import tracemalloc
import uuid

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'runtime/node-host'))
from jarvis_core.memory import MemoryStore
from jarvis_core.process_memory import process_memory
from jarvis_core.service import CoreService


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--typed', action='store_true')
    args = parser.parse_args()
    with tempfile.TemporaryDirectory(prefix='jarvis-memory-domains-') as tmp:
        base = Path(tmp); folder = base/'sample'; folder.mkdir()
        core = CoreService(base/'data'); core.initialize(folder); store = MemoryStore(core)
        start = time.perf_counter()
        for i in range(1000):
            doc = {'title': f'合成偏好 {i}', 'content': '本条只是合成测试资料，用于观察记忆读取成本。'*12+str(i),
                   'project_id': None, 'providers': []}
            if args.typed:
                doc['classification'] = {'kind': 'preference', 'subject': 'owner', 'subject_label': '',
                    'uses': ['personal_chat'] if i%2 else ['personal_chat', 'work_assist'], 'expires_at': None}
            store.put(uuid.uuid4().hex, {'revision': 0, 'document': doc})
        population = time.perf_counter()-start
        before = process_memory(); timings = {}; last = {}
        for mode in ('personal_chat', 'work_assist', 'disabled'):
            ctx = {'enabled': mode != 'disabled', 'project_id': None}
            if args.typed and mode != 'disabled': ctx['purpose'] = mode
            samples = []
            store.context(ctx, 'local')
            for _ in range(30):
                start = time.perf_counter(); _, report = store.context(ctx, 'local')
                samples.append((time.perf_counter()-start)*1000)
            timings[mode] = {'p50_ms': round(statistics.median(samples),3), 'p95_ms': round(sorted(samples)[28],3),
                             'samples': len(samples), 'available': report['available'], 'context_bytes': report['bytes']}
            last[mode] = report
        tracemalloc.start(); store.context({'enabled': True, 'project_id': None}, 'local')
        _, peak = tracemalloc.get_traced_memory(); tracemalloc.stop()
        result = {'captured_at': datetime.now(timezone.utc).isoformat(), 'typed': args.typed,
            'facts': 1000, 'population_seconds': round(population,3), 'database_bytes': store.path.stat().st_size,
            'timings': timings, 'python_context_peak_bytes': peak, 'process_before_reads': before,
            'process_after_reads': process_memory(), 'added_dependencies': [], 'added_daemons': 0, 'model_calls': 0,
            'limits': ['Single-process warm synthetic reads on this PC, not an 8 GiB system acceptance or long soak.',
                       'Process totals include Python/core imports; tracemalloc is one-call Python allocation, not RSS.',
                       'No embeddings, source archives, worst-case bodies, concurrent UI/speech or federation.']}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(result,ensure_ascii=False))


if __name__ == '__main__': main()
