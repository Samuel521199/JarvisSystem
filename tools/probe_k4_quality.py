"""Frozen K4 contracts vs novel challenges; optional explicitly paid real coder."""
import argparse
import hashlib
import json
from pathlib import Path
import sys
import time
ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT),str(ROOT/'tests'),str(ROOT/'runtime/node-host'),str(ROOT/'adapters/computer-use')]
from test_project_tools import ProjectToolTests
from jarvis_core import __version__
from jarvis_core.evolution.lifecycle import ToolLifecycle
from jarvis_core.evolution.provider import default_route
from jarvis_core.dialogue_process import DialogueProcesses


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--output',type=Path,required=True)
    p.add_argument('--live',action='store_true',help='Use configured cloud coding model (paid) for each candidate')
    args=p.parse_args();args.output.mkdir(parents=True,exist_ok=False)
    raw=(ROOT/'evals/cases/k4-quality-v1.json').read_bytes();spec=json.loads(raw)
    report={'version':__version__,'case_sha256':hashlib.sha256(raw).hexdigest(),'status':'running','tasks':[],
            'actual_model_candidates':args.live,'paid_model_calls':0,'oracle':'explicit preselected expectations in frozen benchmark; no autonomous semantic oracle',
            'baseline':'seeded naive implementations; actual K3/LPAC execution, not general product quality controls'}
    def save():(args.output/'report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    save()
    for task in spec['tasks']:
        fixture=ProjectToolTests();fixture.setUp();row={'id':task['id'],'status':'running'};report['tasks'].append(row);save()
        try:
            original=(fixture.source/'calc.py').read_bytes();fixture.sources=[task['baseline']]
            def code():
                item=fixture.submit(prompt=task['prompt'],cases=task['public'],heldout_cases=task['heldout'],build_recipe='python-zipapp-v1',model=default_route())
                deadline=time.monotonic()+155
                while time.monotonic()<deadline:
                    detail=fixture.bridge.detail(fixture.cid,item['task_id'])
                    if detail['task']['status'] not in {'READY','RUNNING','CANCELLING'}:break
                    time.sleep(.1)
                artifact=json.loads(fixture.bridge.artifact(fixture.cid,item['task_id']))
                row.setdefault('coding',[]).append({'status':detail['task']['status'],'passed':artifact.get('coding',{}).get('passed'),
                    'attempts':[a.get('model') for a in artifact.get('coding',{}).get('attempts',[])]})
                if args.live and len(row['coding'])>1:report['paid_model_calls']+=len(artifact.get('coding',{}).get('attempts',[]))
                save();assert artifact['coding']['passed'],row['coding'][-1]
                return item['task_id']
            def stage(task_id):
                return fixture.completed(fixture.request(task_id=task_id,name=task['name'],when_to_use=task['prompt'][:150],when_not_to_use='契约未包含的输入和任何文件/网络操作'),auto_admit=False)
            def trials(cases):
                return [fixture.completed(fixture.request('trial',input=c['input'],expected=c['expected'],useful=True,benefit_note='冻结任务样本的独立预期，核对实际统计/整理结果。'))['result'] for c in cases]
            old=stage(code());trials(task['baseline_trials']);fixture.completed(fixture.request('promote'))
            row['baseline_version']=old['result']['version'];row['contract_quality']=fixture.tools.snapshot(fixture.cid)['tools'][0]['lifecycle']['contract_quality']
            if args.live:
                processes=DialogueProcesses(fixture.core,capacity=1);fixture.addCleanup(processes.close)
                fixture.manager.skills.model_calls=processes;del fixture.manager.skills.coding_generate
            else:
                # Deterministic offline repaired controls. Live mode never uses these.
                fixes={'binary-units':task['baseline'].replace("'KiB': 1000","'KiB': 1024"),
                       'stable-lines':"def transform(data):\n    out = []\n    for s in data:\n        value = s.strip()\n        if value and value not in out:\n            out.append(value)\n    return '\\n'.join(out)\n",
                       'stable-groups':task['baseline'].replace('in sorted(totals)','in totals')}
                fixture.sources=[fixes[task['id']]]
            new=stage(code());row['candidate_version']=new['result']['version'];row['trials']=trials(task['challenges'])
            row['assessment']=ToolLifecycle(fixture.tools).assessment(fixture.project['id'],'sum-tool')
            assert row['assessment']['paired_quality_improvements']==2
            fixture.completed(fixture.request('promote'))
            c=task['challenges'][0];row['actual_use']=fixture.completed(fixture.request('run',input=c['input'],expected=c['expected']))['result']
            row['source_unchanged']=(fixture.source/'calc.py').read_bytes()==original;assert row['source_unchanged']
            row['status']='passed';save()
        except Exception as exc:row.update(status='failed',error=type(exc).__name__+': '+str(exc));report['status']='failed';save();raise
        finally:fixture.doCleanups()
    report['status']='passed';save();print(json.dumps({'status':'passed','tasks':len(report['tasks']),'paid_model_calls':report['paid_model_calls'],'report':str(args.output/'report.json')}))


if __name__=='__main__':main()
