"""Explicit paid shadow evaluation; never creates tasks or writes personal memory."""
import argparse
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import time
import uuid

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT),str(ROOT/'runtime/node-host')]
from jarvis_core import __version__
from jarvis_core.chat import ChatService
from jarvis_core.dialogue_process import DialogueProcesses
from jarvis_core.service import CoreService
from jarvis_core.turns import invoke_reply
from jarvis_core.report_intents import select_report, RULE


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--live',action='store_true')
    parser.add_argument('--split',choices=['calibration','heldout'],required=True)
    parser.add_argument('--dataset',choices=['report-intent-v1.json','report-intent-v2.json'],default='report-intent-v1.json')
    parser.add_argument('--tag',required=True);args=parser.parse_args()
    if not args.live:parser.error('--live required; incurs configured Google usage')
    if not args.tag.isalnum():parser.error('tag must be alphanumeric')
    dataset=ROOT/'evals/cases'/args.dataset
    cases=[c for c in json.loads(dataset.read_text(encoding='utf-8'))['cases'] if c['split']==args.split]
    output=ROOT/'evals/reports'/f'report-intent-{args.split}-{args.tag}-2026-10-19.json'
    if output.exists():parser.error('report already exists')
    paths=['runtime/node-host/jarvis_core/'+n+'.py' for n in ['assistant_context','intent','chat','turns','dialogue_process','dialogue_worker','report_intents','work_admission']]
    paths+=['evals/cases/'+args.dataset,'tools/evaluate_report_intents.py']
    hashes=lambda:{p:hashlib.sha256((ROOT/p).read_bytes()).hexdigest() for p in paths}
    before=hashes();rows=[];start=time.monotonic()
    def save(status):
        report={'status':status,'source_version':__version__,'rule':RULE,'route':'vertex::gemini-3.8-flash',
            'split':args.split,'dataset':args.dataset,'completed':len(rows),'cases':len(cases),'source_sha256':before,'source_changed':hashes()!=before,
            'false_selections':[r['id'] for r in rows if r['selected'] and not r['expected']],
            'missed_selections':[r['id'] for r in rows if r['expected'] and not r['selected']],
            'wrong_arguments':[r['id'] for r in rows if r['selected'] and r['expected'] and not r['arguments_match']],
            'elapsed_seconds':round(time.monotonic()-start,3),'task_count':0,'results':sorted(rows,key=lambda x:x['id']),
            'limits':'Author-labelled synthetic bounded-report cases, not independent human labels or full V-DLG. Shadow selection only; real execution tested separately.'}
        output.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
        return report
    with tempfile.TemporaryDirectory(prefix='jarvis-report-shadow-') as directory:
        root=Path(directory);sample=root/'sample';sample.mkdir()
        core=CoreService(root/'data');core.initialize(sample)
        chat=ChatService(core);pool=DialogueProcesses(core);chat.dialogue_models=pool
        def run(case):
            if hashes()!=before:raise RuntimeError('evaluation source changed')
            tick=time.monotonic()
            result=invoke_reply(core,chat,{'message':case['text'],'provider':'vertex','model':'gemini-3.8-flash',
                'personal_context':{'temporary':True}},None,uuid.uuid4().hex)
            selected=select_report(case['text'],result.get('intent_decision')) if result.get('status')=='SUCCEEDED' and not result.get('output_incomplete') else None
            expected=case.get('selection')
            return {'id':case['id'],'text':case['text'],'expected':expected,'selected':selected,
                'arguments_match':bool(selected and expected and all(selected.get(k)==v for k,v in expected.items())),
                'decision':result.get('intent_decision'),'reply':result.get('text'),'status':result['status'],
                'usage':result.get('usage'),'billing':result.get('billing'),'attempts':len(result.get('attempts',[])),
                'elapsed_seconds':round(time.monotonic()-tick,3)}
        try:
            with ThreadPoolExecutor(max_workers=2) as executor:
                for result in executor.map(run,cases):
                    rows.append(result);save('RUNNING');print(result['id'],result['status'],bool(result['selected']),flush=True)
        finally:pool.close()
    report=save('SUCCEEDED' if hashes()==before and len(rows)==len(cases) else 'INVALID')
    print(json.dumps({k:v for k,v in report.items() if k not in {'results','source_sha256'}},ensure_ascii=False))
    return report['status']!='SUCCEEDED' or bool(report['false_selections'] or report['missed_selections'] or report['wrong_arguments'])


if __name__=='__main__':sys.exit(main())
