"""Inject one bad result in the isolated live-evaluation store, then verify real repair/restart."""
import argparse
import hashlib
import json
from pathlib import Path
import sys
import time
import uuid

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'runtime/node-host'))
from jarvis_core.service import CoreService
from jarvis_core.evolution import EvolutionManager


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--live',action='store_true')
    parser.add_argument('--evaluation-root',type=Path,required=True)
    args=parser.parse_args()
    if not args.live:parser.error('--live required')
    # Only reuse the dedicated probe's root, never accept the live user's data directory.
    prior=json.loads((ROOT/'evals/reports/evolution-live.json').read_text(encoding='utf-8'))
    if args.evaluation_root.resolve()!=Path(prior['isolated_evaluation_data']).resolve():
        parser.error('Root must match the isolated evolution evaluation record')
    paths=list((ROOT/'runtime/node-host/jarvis_core/evolution').glob('*.py'))
    hashes={p.relative_to(ROOT).as_posix():hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}
    manager=EvolutionManager(CoreService(args.evaluation_root/'data'),monitor=False)
    report={'feature':'evolution-v1','version':'0.1.37','date':'2026-10-17','status':'running',
            'fault':'replace one actually executed pure-tool result with wrong text in the test harness',
            'user_runtime_modified':False,'source_hashes':hashes}
    real=manager.runner.run
    fault=[True]
    def run(source,inputs,checkpoint):
        values,evidence=real(source,inputs,checkpoint)
        if len(inputs)==1 and fault[0]:
            fault[0]=False;values=['INJECTED BAD RESULT']
        return values,evidence
    manager.runner.run=run
    try:
        job=manager.submit({'action':'execute','request_id':'fault-'+uuid.uuid4().hex,
                            'input':{'format':'csv','entries':[{'path':'fixture.txt','size':3}]}})
        while manager.busy:time.sleep(.1)
        job=manager.store.job(job['id']);report['job']=job
        assert job['status']=='FAILED' and job['error']=='evolution_execution_recovered',job
        assert job['activation_confirmed'] and len(job['attempts'])>=1
        active=manager.store.selection()['active'];assert active==job['published']
        manager.close()
        manager=EvolutionManager(CoreService(args.evaluation_root/'data'),monitor=False)
        assert manager.store.selection()['active']==active
        follow=manager.submit({'action':'execute','request_id':'recovered-'+uuid.uuid4().hex,
                               'input':{'format':'tsv','entries':[{'path':'fixture.txt','size':3}]}})
        while manager.busy:time.sleep(.1)
        follow=manager.store.job(follow['id'])
        assert follow['status']=='SUCCEEDED' and follow['result']['text']=='path\tsize\nfixture.txt\t3\n',follow
        assert hashes=={p.relative_to(ROOT).as_posix():hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}
        report.update(status='passed',restart_preserved_verified_repair=True,
                      original_failed_result_withheld=True,followup=follow,paid_model_calls=len(job['attempts']))
    except Exception as exc:
        report.update(status='failed',error=type(exc).__name__);raise
    finally:
        manager.close()
        (ROOT/'evals/reports/evolution-runtime-repair.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps({'status':report['status'],'paid_model_calls':report['paid_model_calls'],'restart_preserved':True}))


if __name__=='__main__':main()
