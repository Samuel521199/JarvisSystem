"""Host-owned retrieval acceptance; no labels or heldout input sent to models."""
import hashlib
import json
import statistics
import time
from pathlib import Path

from .knowledge import normalized, terms
from .retrieval_ranking import LexicalV1, lexical_score, rank
from .ranking_program import Program, features

CASES = Path(__file__).resolve().parents[3] / 'evals/cases/k5-ranking-heldout-v1.json'


def binding():
    files = [CASES, Path(__file__), Path(__file__).with_name('ranking_program.py'),
             Path(__file__).with_name('retrieval_ranking.py'), Path(__file__).with_name('knowledge.py'),
             Path(__file__).with_name('ranking_registry.py'), Path(__file__).parent/'evolution/runner.py']
    return hashlib.sha256(b''.join(p.read_bytes() for p in files)).hexdigest()


def prepare(case):
    words = terms(case['query'])
    rows = []
    for doc in case['documents']:
        text, heading = normalized(doc['text']), normalized(doc['title']+' '+doc['path'])
        score = lexical_score(text, heading, words)
        if score:
            rows.append(dict(score=score, path=doc['path'], start_line=1, text=text, heading=heading))
    return rows, words


def evaluate(source, runner, checkpoint):
    program = Program(source)
    cases = json.loads(CASES.read_text(encoding='utf-8'))['cases']
    prepared = [prepare(case) for case in cases]
    outputs, isolation = runner.run(source, [features(*x) for x in prepared], checkpoint)
    checks = []
    for case, (rows, words), output in zip(cases, prepared, outputs):
        checkpoint()
        original = LexicalV1.order(rows, words)
        order, meta = rank(rows, words, program)
        expected = case['expected']
        old = rows[original[0]]['path'] if original else None
        new = rows[order[0]]['path'] if order else None
        checks.append(dict(id=case['id'], baseline=old == expected, candidate=new == expected,
                           equivalent=output == ','.join(map(str, order)) and not meta['fallback']))
    # Max candidate count, varied headings; feature input is synthetic, not owner data.
    rows = [dict(score=i % 9 + 1, path=f'{i:04}.md', start_line=i+1,
                 text=('offline recovery memory control source permission ' * 20),
                 heading='module recovery') for i in range(2048)]
    words = ['offline', 'recovery', 'memory', 'control', 'source', 'permission']
    timings = {}
    for name, adapter in [('baseline', LexicalV1()), ('candidate', program)]:
        elapsed = []
        for _ in range(12):
            checkpoint(); started = time.perf_counter()
            _, metadata = rank(rows, words, adapter)
            elapsed.append(time.perf_counter()-started)
            if metadata['fallback']: raise ValueError('benchmark fallback')
        timings[name] = dict(median_ms=round(statistics.median(elapsed)*1000, 3),
                             maximum_ms=round(max(elapsed)*1000, 3))
    baseline = sum(c['baseline'] for c in checks)
    candidate = sum(c['candidate'] for c in checks)
    passed = (len(outputs) == len(cases) and all(c['equivalent'] for c in checks)
              and not any(c['baseline'] and not c['candidate'] for c in checks)
              and candidate >= baseline + 4 and timings['candidate']['maximum_ms'] <= 50)
    return dict(passed=passed, binding=binding(), cases=checks, baseline=baseline, candidate=candidate,
                total=len(checks), timing=timings, isolation=isolation,
                criteria={'minimum_additional_top1':4, 'baseline_regressions':0, 'max_2048_rows_ms':50},
                limitation='Fixed lexical retrieval judgments, not final-answer quality or general semantic relevance.')
