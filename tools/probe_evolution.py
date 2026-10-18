"""Real model generation/upgrade/self-repair in a dedicated, retained evaluation store."""
import argparse
import hashlib
import json
from pathlib import Path
import sys
import time
import uuid

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'runtime/node-host'))
from jarvis_core import __version__
from jarvis_core.service import CoreService
from jarvis_core.evolution import EvolutionManager
from jarvis_core.evolution import recipes
from eval_policy import default_route


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--live', action='store_true')
    parser.add_argument('--root', type=Path, required=True, help='A new dedicated evaluation directory')
    parser.add_argument('--output', type=Path, default=ROOT/'evals/reports/evolution-live.json', help='Evidence destination; use a fresh path to retain previous results')
    args = parser.parse_args()
    if not args.live: parser.error('--live required: configured model calls')
    args.root.mkdir(parents=True, exist_ok=False)
    source = args.root/'source'; source.mkdir()
    core = CoreService(args.root/'data'); core.initialize(source)
    manager = EvolutionManager(core, monitor=False)
    source_hashes = {str(p.relative_to(ROOT)).replace('\\','/'):hashlib.sha256(p.read_bytes()).hexdigest()
                     for p in (ROOT/'runtime/node-host/jarvis_core/evolution').glob('*.py')}
    report = {'version': __version__, 'feature': 'evolution-v1', 'route': default_route(),
              'isolated_evaluation_data': str(args.root), 'steps': [], 'status': 'running'}
    path = args.output
    path.parent.mkdir(parents=True, exist_ok=True)
    def save(): path.write_text(json.dumps(report, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
    def submit(action, **kwargs):
        start = time.monotonic()
        job = manager.submit({'action':action, 'request_id':'probe-'+uuid.uuid4().hex, **kwargs})
        while manager.busy: time.sleep(.1)
        job = manager.store.job(job['id'])
        report['steps'].append({'action':action, 'elapsed_seconds':round(time.monotonic()-start,3), 'job':job})
        save()
        print(json.dumps({'action':action, 'status':job['status'], 'attempts':len(job['attempts']), 'error':job['error']}), flush=True)
        if job['status'] != 'SUCCEEDED': raise RuntimeError('Growth step failed; evidence retained')
        return job
    try:
        first = submit('ensure', target_revision=1)['result']['package']
        submit('execute', input={'format':'csv','entries':[{'path':'读我.md','size':42},{'path':'a,b.txt','size':0}]})
        second = submit('ensure', target_revision=2)['result']['package']
        submit('execute', input={'format':'tsv','entries':[{'path':'带\t制表符','size':12},{'path':'a','size':1}]})
        # Controlled fault only inside this fresh evaluation tree. The live user's packages are untouched.
        package = manager.store.packages/second/'candidate.py'
        original = package.read_bytes()
        package.write_bytes(b'def transform(data):\n    return "broken"\n')
        manager.configure({'enabled':True, 'route':default_route(), 'target_revision':2})
        healed = submit('check')
        assert healed['rollback']['to'] == first, healed
        active = manager.store.selection()['active']
        assert active not in (first,second)
        submit('execute', input=recipes.cases(2, heldout=True)[-1])
        count_before = sum(len(x['job']['attempts']) for x in report['steps'])
        healthy = submit('check')
        assert not healthy['attempts'] and healthy['result']['healthy']
        report.update(status='passed', paid_model_calls=count_before,
                      autonomous_fault_detection=True, automatic_rollback=True, automatic_model_repair=True,
                      published_package=active, previous_package=first,
                      corruption_original_sha256=hashlib.sha256(original).hexdigest(),
                      source_hashes_before=source_hashes,
                      source_sha256={str(p.relative_to(ROOT)).replace('\\','/'):hashlib.sha256(p.read_bytes()).hexdigest()
                                     for p in (ROOT/'runtime/node-host/jarvis_core/evolution').glob('*.py')})
        if report['source_sha256'] != source_hashes:
            raise RuntimeError('Source changed during evaluation; rerun final code')
    except Exception as exc:
        report.update(status='failed', error=type(exc).__name__)
        raise
    finally:
        manager.close(); save()


if __name__ == '__main__': main()
