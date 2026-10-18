"""Bounded, synthetic native Mem0 characterization; no production fact writes."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'runtime/node-host'))
from jarvis_core.service import CoreService
from jarvis_core.memory import MemoryStore
from memory_lab.mem0_bridge import run_worker, model_transport
from eval_policy import default_route


def digest(path): return hashlib.sha256(path.read_bytes()).hexdigest()


def observations(case, result, diagnostics):
    if result['status'] != 'SUCCEEDED': return {'completed': False}
    rows = json.loads(result['text'])['steps']
    prompts = [g['messages'][1]['content'] for g in diagnostics['gateway']]
    facts = lambda n, scope='personal': rows[n]['stores'][scope]['results']
    if case['id'] == 'N01':
        original = rows[0]['result']['results'][0]['id']
        return {'completed': True, 'counts_after_adds': [len(facts(i)) for i in range(4)],
            'original_record_retained_after_changed_preference': any(f['id'] == original for f in facts(3)),
            'manual_update_same_id': any(f['id'] == original and f['memory'] == case['steps'][4]['text'] for f in facts(4))}
    if case['id'] == 'N02':
        return {'completed': True,
                'other_project_canary_in_b_prompt': '紫杉' in prompts[2],
                'other_project_canary_in_later_a_prompt': '白鹭' in prompts[3],
                'personal_nickname_in_project_prompt': '阿辰' in prompts[1],
                'final_scope_counts': {s: len(v['results']) for s, v in rows[-1]['stores'].items()}}
    return {'completed': True, 'facts_after_delete': len(facts(1)),
            'deleted_fact_in_public_history': '蓝鲸七号' in json.dumps(rows[2]['result'], ensure_ascii=False),
            'deleted_source_in_next_model_prompt': '蓝鲸七号' in prompts[-1],
            'facts_after_next_add': len(facts(3))}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--live', action='store_true', required=True)
    parser.add_argument('--worker-python', type=Path, required=True)
    parser.add_argument('--route', default=default_route())
    parser.add_argument('--reasoning', default='low')
    parser.add_argument('--repeats', type=int, default=3)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    if not 1 <= args.repeats <= 3 or args.output.exists() or not args.worker_python.is_file():
        parser.error('Require new output, existing isolated interpreter, repeats 1..3')
    corpus_path = ROOT/'evals/cases/mem0-sequence-pilot.json'
    corpus = json.loads(corpus_path.read_text(encoding='utf-8'))
    paths = [Path(__file__), corpus_path, *[ROOT/'tools/memory_lab'/name for name in
        ('mem0_bridge.py', 'mem0_worker.py', 'requirements-mem0.lock', 'langmem_bridge.py', 'langmem_worker.py')],
        ROOT/'runtime/node-host/jarvis_core/chat.py']
    hashes = {str(p.relative_to(ROOT)): digest(p) for p in paths}
    report = {'schema_version': 1, 'status': 'running', 'captured_at': datetime.now(timezone.utc).isoformat(),
              'scope': corpus['scope'], 'corpus_id': corpus['id'], 'route': args.route, 'reasoning': args.reasoning,
              'source_sha256': hashes, 'worker_python': str(args.worker_python), 'owner_data_used': False,
              'automatic_confirmation': False, 'max_gateway_attempts': args.repeats*10, 'rows': []}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    def unchanged(): return all(digest(ROOT/p) == h for p, h in hashes.items())
    def save():
        trace = [g for row in report['rows'] for g in row['diagnostics']['gateway']]
        billing = [g['result'].get('billing', {}) for g in trace]
        report['summary'] = {'gateway_invocations': len(trace),
            'reported_tokens': sum(b.get('tokens', {}).get('total') or 0 for b in billing),
            'token_receipts': sum(b.get('tokens', {}).get('total') is not None for b in billing),
            'estimated_usd': round(sum(b.get('amount') or 0 for b in billing if b.get('currency') == 'USD'), 6),
            'cost_receipts': sum(b.get('amount') is not None and b.get('currency') == 'USD' for b in billing),
            'facts_committed': sum(row['facts_committed'] for row in report['rows'])}
        target = args.output.with_suffix('.tmp')
        target.write_text(json.dumps(report, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
        target.replace(args.output)
    provider, model = args.route.split('::', 1); save(); stop = False
    for repeat in range(args.repeats):
        if stop: break
        for case in corpus['cases']:
            if not unchanged(): report['stop_reason'] = 'source_changed'; stop = True; break
            with tempfile.TemporaryDirectory(prefix='jarvis-mem0-sequence-host-') as tmp:
                folder = Path(tmp)/'input'; folder.mkdir()
                core = CoreService(Path(tmp)/'data'); core.initialize(folder)
                result, diagnostics = run_worker(args.worker_python, {'mode': 'sequence', 'steps': case['steps']},
                    model_transport(core, provider, model, args.reasoning), timeout=300)
                row = {'case': case['id'], 'repeat': repeat+1, 'result': result, 'diagnostics': diagnostics,
                       'observations': observations(case, result, diagnostics),
                       'facts_committed': len(MemoryStore(core).list()['facts'])}
                report['rows'].append(row); save()
                print(json.dumps({'case': case['id'], 'repeat': repeat+1, 'status': result['status'],
                                  'observations': row['observations']}, ensure_ascii=False), flush=True)
                # Characterization stops on any failure; never rerun a failed scene automatically.
                if result['status'] != 'SUCCEEDED' or row['facts_committed']:
                    stop = True; break
    report.update(status='interrupted' if stop else 'completed_requires_review', source_unchanged=unchanged())
    save()
    return int(stop or not report['source_unchanged'])


if __name__ == '__main__': raise SystemExit(main())
