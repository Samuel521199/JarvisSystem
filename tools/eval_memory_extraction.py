"""Reproducible public pilot: rule facts vs review-only structured LLM facts.

Default path needs no framework. Optional frameworks run in separate environments.
No user data, automatic confirmation or persistent worker.
Rubric matches are evidence checks, not general semantic accuracy or a blind test.
"""
import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
import re
import sys
import tempfile
import time
import uuid

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'runtime/node-host'))
from jarvis_core import __version__
from jarvis_core.chat import ChatService
from jarvis_core.conversations import ConversationStore
from jarvis_core.memory import MemoryError, MemoryStore
from jarvis_core.memory_policy import SUBJECTS
from jarvis_core.personal_candidates import extract
from jarvis_core.semantic_candidates import SemanticCandidates, segments, INSTRUCTIONS
from jarvis_core.service import CoreService
from jarvis_core.workspace import WorkspaceService
from eval_policy import default_route

CASES = ROOT / 'evals/cases/memory-extraction-pilot.json'


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def sources_match(hashes):
    return all((ROOT/path).is_file() and digest(ROOT/path) == value for path, value in hashes.items())


def load_cases(path):
    data = json.loads(path.read_text(encoding='utf-8'))
    if data['schema_version'] != 1 or not data['cases']:
        raise ValueError('Invalid corpus')
    ids = set()
    for case in data['cases']:
        if case['id'] in ids or type(case['project']) is not bool:
            raise ValueError('Duplicate case or invalid project flag')
        ids.add(case['id'])
        if not isinstance(case['text'], str) or not 1 <= len(case['text']) <= 800:
            raise ValueError('Invalid source')
        indices = set()
        for target in case['expected']:
            index = target['segment']
            if type(index) is not int or not 0 <= index < len(segments(case['text'])) or index in indices:
                raise ValueError('Invalid or duplicate expected source')
            indices.add(index)
            if not target['categories'] or not set(target['categories']) <= SUBJECTS.keys():
                raise ValueError('Invalid expected categories')
            for pattern in target['all_of'] + target['none_of'] + ([target['label']] if 'label' in target else []):
                re.compile(pattern)
        if case.get('preflight') and case['expected']:
            raise ValueError('Blocked cases cannot also expect candidates')
    return data


def rule_candidates(text):
    """Keep production whole-message rejection; do not re-extract each sentence."""
    facts = [item for item in extract(text) if item['kind'] == 'fact']
    rows = []
    for item in facts:
        found = [i for i, part in enumerate(segments(text)) if item['content'] in part]
        rows.append({**item, 'segment': found[0] if len(found) == 1 else None})
    return rows


def matches(item, target, typed):
    if item.get('segment') != target['segment']:
        return False
    content = item.get('content', '')
    if not all(re.search(p, content, re.I) for p in target['all_of']):
        return False
    if any(re.search(p, content, re.I) for p in target['none_of']):
        return False
    if typed:
        policy = item.get('classification', {})
        if policy.get('kind') not in target['categories']:
            return False
        if policy.get('subject') not in target.get('subject_any', [target.get('subject')]):
            return False
        if 'label' in target and not re.search(target['label'], policy.get('subject_label', ''), re.I):
            return False
    return True


def score(case, row, typed=False):
    candidates, expected = row['candidates'], case['expected']
    # Maximum bipartite matching: a duplicate cannot claim the same expected fact twice.
    parts = segments(case['text'])
    def source_valid(item):
        index = item.get('segment')
        return (type(index) is int and 0 <= index < len(parts) and
                (row.get('engine') == 'rules' or item.get('quote') == parts[index]))
    edges = [[j for j, target in enumerate(expected) if source_valid(item) and matches(item, target, typed)]
             for item in candidates]
    owners = {}
    def assign(i, visited):
        for j in edges[i]:
            if j in visited:
                continue
            visited.add(j)
            if j not in owners or assign(owners[j], visited):
                owners[j] = i
                return True
        return False
    for i in range(len(candidates)):
        assign(i, set())
    tp = len(owners)
    success = row['status'] == 'SUCCEEDED' or (row['status'] == 'BLOCKED' and
              row.get('error_category') == case.get('preflight') and bool(case.get('preflight')))
    # A failed negative case is not a successful abstention.
    return {'tp': tp, 'fp': len(candidates)-tp, 'fn': len(expected)-tp,
            'case_pass': success and tp == len(expected) == len(candidates),
            'negative_pass': success and not candidates if not expected else None,
            'missed_segments': [t['segment'] for j, t in enumerate(expected) if j not in owners],
            'unmatched_indices': [i for i in range(len(candidates)) if i not in owners.values()]}


def evaluate(case, provider, model, reasoning, engine='semantic', worker_python=None):
    if engine not in {'semantic', 'langmem', 'mem0'} or (engine != 'semantic' and not worker_python):
        raise ValueError('Unknown engine or missing worker interpreter')
    started = time.perf_counter()
    # A private temporary root per case isolates concurrent gateways and all stores.
    with tempfile.TemporaryDirectory(prefix='jarvis-extraction-eval-') as tmp:
        root = Path(tmp); folder = root/'input'; folder.mkdir()
        core = CoreService(root/'data'); core.initialize(folder)
        project = WorkspaceService(core).open_project({'path': str(folder)})['id'] if case['project'] else None
        doc = {'title': 'Synthetic evaluation', 'project_id': project, 'context_note': '', 'messages': [
            {'role': 'user', 'content': case['text'], 'meta': '', 'short_meta': '', 'attachments_omitted': False, 'incomplete': False}]}
        cid = uuid.uuid4().hex
        ConversationStore(core).put(cid, {'revision': 0, 'document': doc})
        if engine == 'langmem':
            from memory_lab.langmem_bridge import LangMemChat
            chat = LangMemChat(core, worker_python)
        elif engine == 'mem0':
            from memory_lab.mem0_bridge import Mem0Chat
            chat = Mem0Chat(core, worker_python)
        else:
            chat = ChatService(core)
        original = chat.reply; trace = []
        def capture(prompt, **kwargs):
            entry = {'prompt_sha256': hashlib.sha256(prompt.encode()).hexdigest()}
            trace.append(entry)
            result = original(prompt, **kwargs)
            entry['raw'] = {k: result[k] for k in ('text', 'output_incomplete', 'completion_reason') if k in result}
            return result
        chat.reply = capture
        try:
            preview = SemanticCandidates(core, chat).suggest({
                'source': {'conversation_id': cid, 'message_index': 0}, 'project_id': project,
                'provider': provider, 'model': model, 'reasoning': reasoning, 'request_id': uuid.uuid4().hex})
            row = {**preview['result'], 'candidates': preview['candidates']}
        except MemoryError as exc:
            row = {'status': 'BLOCKED', 'error_category': exc.code, 'candidates': []}
        # Never persist preview tokens or call confirm. Verify real writes separately.
        row.update(elapsed_ms=round((time.perf_counter()-started)*1000, 3),
                   gateway_invocations=len(trace), trace=trace,
                   facts_committed=len(MemoryStore(core).list()['facts']))
        if engine in {'langmem', 'mem0'}:
            row['framework'] = chat.diagnostics
            row['gateway_invocations'] = len(chat.diagnostics.get('gateway', []))
        if row['facts_committed']:
            raise AssertionError('Evaluation unexpectedly wrote facts')
        return row


def summarize(cases, rows):
    lookup = {c['id']: c for c in cases}
    summary = {}
    for engine in ('rules', 'semantic', 'langmem', 'mem0'):
        selected = [r for r in rows if r['engine'] == engine]
        if not selected:
            continue
        entry = {'runs': len(selected), 'status_counts': {},
                 'gateway_invocations': sum(r.get('gateway_invocations', 0) for r in selected),
                 'facts_committed': sum(r.get('facts_committed', 0) for r in selected)}
        for row in selected:
            entry['status_counts'][row['status']] = entry['status_counts'].get(row['status'], 0)+1
        for typed in (False, True):
            scores = [score(lookup[row['case']], row, typed) for row in selected]
            totals = {k: sum(s[k] for s in scores) for k in ('tp', 'fp', 'fn')}
            tp, fp, fn = (totals[k] for k in ('tp', 'fp', 'fn'))
            totals.update(precision=round(tp/(tp+fp), 4) if tp+fp else None,
                          recall=round(tp/(tp+fn), 4) if tp+fn else None,
                          passed_cases=sum(s['case_pass'] for s in scores),
                          negative_passes=sum(s['negative_pass'] is True for s in scores),
                          negative_runs=sum(s['negative_pass'] is not None for s in scores))
            entry['typed' if typed else 'content_evidence'] = totals
        elapsed = sorted(r['elapsed_ms'] for r in selected)
        entry['latency_ms'] = {'p50': elapsed[math.ceil(len(elapsed)*.5)-1], 'p95': elapsed[math.ceil(len(elapsed)*.95)-1],
                               'scope': 'rule function only' if engine == 'rules' else
                               'whole isolated case including temporary stores; overlapping calls, not idle-PC measurement'}
        costs, tokens = [], []
        for row in selected:
            billing = row.get('billing', {})
            if billing.get('currency') == 'USD' and billing.get('amount') is not None:
                costs.append(billing['amount'])
            if billing.get('tokens', {}).get('total') is not None:
                tokens.append(billing['tokens']['total'])
        entry.update(reported_tokens=sum(tokens), token_receipts=len(tokens), estimated_usd=round(sum(costs), 6),
                     cost_receipts=len(costs))
        entry['per_case'] = {c['id']: [score(c, r, typed=engine != 'rules')['case_pass']
            for r in selected if r['case'] == c['id']] for c in cases}
        summary[engine] = entry
    return summary


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--cases', type=Path, default=CASES)
    parser.add_argument('--live', action='store_true')
    parser.add_argument('--engine', choices=('semantic', 'langmem', 'mem0'), default='semantic')
    parser.add_argument('--worker-python', type=Path, help='Separate interpreter with the selected pinned lab dependencies')
    parser.add_argument('--route', default=default_route())
    parser.add_argument('--reasoning', default='low')
    parser.add_argument('--repeats', type=int, default=3)
    parser.add_argument('--workers', type=int, default=2)
    parser.add_argument('--only', help='Comma-separated public pilot case IDs; never labels this a full run')
    parser.add_argument('--max-attempts', type=int, default=90)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    if not 1 <= args.repeats <= 3 or not 1 <= args.workers <= 2 or not 1 <= args.max_attempts <= 90:
        parser.error('Bounds: repeats 1..3, workers 1..2, max-attempts 1..90')
    if args.output.exists():
        parser.error('Refusing to overwrite an existing report; choose a new output path')
    if args.live and args.engine != 'semantic' and (not args.worker_python or not args.worker_python.is_file()):
        parser.error('A framework requires --worker-python in its separate environment')
    corpus = load_cases(args.cases); cases = corpus['cases']
    if args.only:
        wanted = set(args.only.split(','))
        if not wanted <= {c['id'] for c in cases}:
            parser.error('Unknown case ID')
        cases = [c for c in cases if c['id'] in wanted]
    if args.live and len(cases)*args.repeats > args.max_attempts:
        parser.error('Requested attempts exceed explicit budget; select fewer cases/repeats or increase within hard cap')
    provider, model = args.route.split('::', 1)
    paths = [Path(__file__), args.cases, ROOT/'runtime/node-host/jarvis_core/semantic_candidates.py',
             ROOT/'runtime/node-host/jarvis_core/personal_candidates.py', ROOT/'runtime/node-host/jarvis_core/chat.py']
    if args.engine == 'langmem':
        paths += [ROOT/'tools/memory_lab'/p for p in ('langmem_bridge.py', 'langmem_worker.py', 'requirements-langmem.lock')]
    elif args.engine == 'mem0':
        paths += [ROOT/'tools/memory_lab'/p for p in ('mem0_bridge.py', 'mem0_worker.py', 'requirements-mem0.lock',
                                                    'langmem_bridge.py', 'langmem_worker.py')]
    report = {'schema_version': 1, 'status': 'running', 'version': __version__,
              'captured_at': datetime.now(timezone.utc).isoformat(), 'scope': corpus['scope'],
              'corpus_id': corpus['id'], 'case_ids': [c['id'] for c in cases],
              'route': args.route if args.live else None, 'reasoning': args.reasoning if args.live else None,
              'engine': args.engine, 'worker_python': str(args.worker_python) if args.worker_python else None,
              'transport': {'langmem': 'serialized tool calls over existing text gateway',
                            'mem0': 'public SDK, local protocol bridge, serialized messages over gateway; JSON candidates encoded inside native memory text'
                            }.get(args.engine, 'native text gateway'),
              'repeats': args.repeats if args.live else 0, 'workers': args.workers if args.live else 0,
              'max_attempts': args.max_attempts if args.live else 0, 'owner_data_used': False,
              'instructions_sha256': hashlib.sha256(INSTRUCTIONS.encode()).hexdigest(),
              'source_sha256': {str(p.relative_to(ROOT)): digest(p) for p in paths}, 'rows': []}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    def save():
        report['summary'] = summarize(cases, report['rows'])
        temporary = args.output.with_suffix('.tmp')
        temporary.write_text(json.dumps(report, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
        temporary.replace(args.output)
    for case in cases:
        started = time.perf_counter(); items = rule_candidates(case['text'])
        report['rows'].append({'engine': 'rules', 'case': case['id'], 'repeat': 0, 'status': 'SUCCEEDED',
            'candidates': items, 'elapsed_ms': round((time.perf_counter()-started)*1000, 3)})
    save()
    if args.live:
        # Separate repetition rounds; never automatically retry a failed/uncertain call.
        fatal = False
        for repeat in range(args.repeats):
            if fatal:
                break
            with ThreadPoolExecutor(max_workers=args.workers) as pool:
                pending = {}
                remaining = iter(cases)
                def submit_one():
                    nonlocal fatal
                    if not sources_match(report['source_sha256']):
                        fatal = True
                        report['stop_reason'] = 'source_changed'
                        return
                    case = next(remaining, None)
                    if case:
                        pending[pool.submit(evaluate, case, provider, model, args.reasoning,
                                            args.engine, args.worker_python)] = case
                for _ in range(args.workers): submit_one()
                while pending:
                    future = next(as_completed(pending)); case = pending.pop(future)
                    try:
                        row = future.result()
                    except Exception as exc:
                        row = {'status': 'HARNESS_ERROR', 'error_category': type(exc).__name__,
                               'candidates': [], 'elapsed_ms': 0}
                        fatal = True
                    row.update(engine=args.engine, case=case['id'], repeat=repeat+1)
                    report['rows'].append(row)
                    check = score(case, row, typed=True)
                    print(json.dumps({'case': case['id'], 'repeat': repeat+1, 'status': row['status'],
                                      'rubric_pass': check['case_pass']}, ensure_ascii=False), flush=True)
                    # Stop dispatching on quota/auth/uncertain outcomes; already running calls finish.
                    if row['status'] == 'UNKNOWN' or row.get('outcome_uncertain') or row.get('error_category') in {
                        'quota_exhausted', 'insufficient_quota', 'authentication', 'authentication_failed', 'invalid_api_key'}:
                        fatal = True
                    save()
                    if not fatal: submit_one()
        report['completed_attempts'] = sum(r['engine'] == args.engine for r in report['rows'])
        report['planned_attempts'] = len(cases)*args.repeats
        report['status'] = 'interrupted' if fatal else 'completed_requires_review'
    else:
        report['status'] = 'rules_only'
    report['source_unchanged'] = sources_match(report['source_sha256'])
    save()
    print(json.dumps({'status': report['status'], 'summary': report['summary']}, ensure_ascii=False), flush=True)
    return int(report['status'] == 'interrupted' or not report['source_unchanged'])


if __name__ == '__main__':
    raise SystemExit(main())
