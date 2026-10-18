"""Bounded synthetic memory resource observation; no providers or user records."""
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
from jarvis_core import __version__
from jarvis_core.memory import MemoryStore
from jarvis_core.service import CoreService


def main():
    with tempfile.TemporaryDirectory(prefix='jarvis-memory-resource-') as directory:
        base = Path(directory); folder = base/'sample'; folder.mkdir()
        core = CoreService(base/'data'); core.initialize(folder); store = MemoryStore(core)
        body = '这是用于验证本机记忆容量的合成中文资料。'*10
        start = time.perf_counter()
        for index in range(1000):
            store.put(uuid.uuid4().hex, {'revision': 0, 'document': {
                'title': f'合成条目 {index}', 'content': body+str(index),
                'project_id': None, 'providers': []}})
        population_seconds = time.perf_counter()-start
        request = {'enabled': True, 'project_id': None}
        timings = {}
        for name, action in (
            ('literal_search', lambda: store.list(query='合成中文')),
            ('local_context', lambda: store.context(request, 'local')),
            ('cloud_filter', lambda: store.context(request, 'vertex')),
        ):
            samples = []
            for _ in range(30):
                start = time.perf_counter(); action(); samples.append((time.perf_counter()-start)*1000)
            timings[name] = {'samples': len(samples), 'median_ms': round(statistics.median(samples), 3),
                             'p95_ms': round(sorted(samples)[28], 3)}
        tracemalloc.start()
        _, view = store.context(request, 'local')
        _, peak = tracemalloc.get_traced_memory(); tracemalloc.stop()
        assert view['bytes'] <= 6144 and 0 < len(view['references']) <= 20
        assert len(store.list()['facts']) == 1000
        result = {'version': __version__, 'captured_at': datetime.now(timezone.utc).isoformat(),
                  'status': 'observed', 'fixture': {'facts': 1000, 'body_characters': len(body),
                  'scope': 'global', 'providers': [], 'population_seconds': round(population_seconds, 3)},
                  'database_bytes': store.path.stat().st_size, 'timings': timings,
                  'context_python_peak_allocated_bytes': peak, 'selected_facts': len(view['references']),
                  'context_bytes': view['bytes'], 'added_dependencies': [], 'added_daemons': 0,
                  'limits': ['Synthetic single-process warm-cache observation on the current PC; not a hardware-independent SLA.',
                  'tracemalloc measures Python allocations in one context call, not total process RSS or GPU memory.',
                  'No model, embedding, concurrent load, federation or worst-case 2048-character facts tested.']}
    path = ROOT/'evals/reports/memory-resources.json'
    path.write_text(json.dumps(result, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
    print(json.dumps(result, ensure_ascii=False))


if __name__ == '__main__':
    main()
