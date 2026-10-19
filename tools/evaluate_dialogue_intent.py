"""Explicit paid pilot through the actual isolated reply path, synthetic data only."""
import argparse
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed
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
from jarvis_core.intent import KINDS, ENGINE
from jarvis_core.service import CoreService
from jarvis_core.turns import invoke_reply
from tools.eval_policy import default_route


def source_hashes(dataset='dialogue-intent-pilot.json'):
    names=['runtime/node-host/jarvis_core/'+n+'.py' for n in ['intent','chat','turns','dialogue_process','dialogue_worker','assistant_context']]
    names+=['evals/cases/'+dataset,'tools/evaluate_dialogue_intent.py']
    if dataset=='dialogue-intent-v2.json': names+=['runtime/node-host/jarvis_core/documentation_admission.py']
    return {n:hashlib.sha256((ROOT/n).read_bytes()).hexdigest() for n in names}


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--live',action='store_true')
    parser.add_argument('--split',choices=['calibration','heldout'],required=True)
    parser.add_argument('--dataset',choices=['pilot','v2'],default='pilot')
    parser.add_argument('--route',default=None)
    parser.add_argument('--tag',default='')
    args=parser.parse_args()
    if not args.live:parser.error('--live is required: uses the configured evaluation provider and incurs usage')
    import re
    if not re.fullmatch(r'[a-zA-Z0-9_-]{0,50}',args.tag):parser.error('invalid tag')
    dataset='dialogue-intent-'+args.dataset+'.json'
    cases=[c for c in json.loads((ROOT/'evals/cases'/dataset).read_text(encoding='utf-8'))['cases'] if c['split']==args.split]
    provider,model=(args.route or default_route()).split('::',1)
    hashes=lambda:source_hashes(dataset)
    before=hashes();rows=[];start=time.monotonic()
    suffix=('-'+args.dataset if args.dataset!='pilot' else '')+('-'+args.tag if args.tag else '')
    destination=ROOT/'evals/reports'/('dialogue-intent'+suffix+'-'+args.split+'-'+datetime.now().strftime('%Y-%m-%d')+'.json')
    if destination.exists():parser.error('Report exists; choose a new tag rather than replacing an evaluation')
    def save(status):
        labels={}
        for kind in KINDS:
            tp=sum(kind in r['expected'] and kind in r['predicted'] for r in rows)
            fp=sum(kind not in r['expected'] and kind in r['predicted'] for r in rows)
            fn=sum(kind in r['expected'] and kind not in r['predicted'] for r in rows)
            labels[kind]={'tp':tp,'fp':fp,'fn':fn,'f1':round(2*tp/(2*tp+fp+fn),4) if 2*tp+fp+fn else None}
        scores=[r['f1'] for r in labels.values() if r['f1'] is not None]
        report={'status':status,'source_version':__version__,'engine':ENGINE,'split':args.split,
            'route':provider+'::'+model,'cases':len(cases),'completed':len(rows),'per_class':labels,
            'macro_f1_present_classes':round(sum(scores)/len(scores),4) if scores else None,
            'exact_label_matches':sum(r['expected']==r['predicted'] for r in rows),
            'effect_polarity_matches':sum(r['expected_effect']==r['predicted_effect'] for r in rows if r['predicted_effect'] is not None),
            'effect_polarity_evaluable':sum(r['predicted_effect'] is not None for r in rows),
            'false_requested_effects':[r['id'] for r in rows if not r['expected_effect'] and r['predicted_effect'] is True],
            'missed_requested_effects':[r['id'] for r in rows if r['expected_effect'] and r['predicted_effect'] is False],
            'unrecognized':[r['id'] for r in rows if r['decision'].get('state')!='recognized'],
            'documentation_false_candidates':[r['id'] for r in rows if r.get('expected_documentation') is False and r.get('predicted_documentation')],
            'documentation_missed_candidates':[r['id'] for r in rows if r.get('expected_documentation') is True and not r.get('predicted_documentation')],
            'auto_false_selections':[r['id'] for r in rows if r.get('auto_expected') is False and r.get('auto_selected')],
            'auto_missed_selections':[r['id'] for r in rows if r.get('auto_expected') is True and not r.get('auto_selected')],
            'auto_expected_count':sum(r.get('auto_expected') is True for r in rows),
            'auto_selected_count':sum(r.get('auto_selected') is True for r in rows),
            'task_count':0,'elapsed_seconds':round(time.monotonic()-start,3),
            'dataset':dataset,'source_sha256':before,'source_changed':hashes()!=before,'results':sorted(rows,key=lambda r:r['id']),
            'limits':'Pilot only; classification labels remain reference judgments. 200-case V-DLG and target binding/fairness/voice gates not passed. No execution is wired to candidates; zero tasks is architectural, not evidence of semantic perfection. No retries or fallback.'}
        destination.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    with tempfile.TemporaryDirectory(prefix='jarvis-intent-live-pilot-') as directory:
        base=Path(directory);sample=base/'sample';sample.mkdir()
        core=CoreService(base/'data');core.initialize(sample)
        chat=ChatService(core);pool=DialogueProcesses(core);chat.dialogue_models=pool
        def run(case):
            if hashes()!=before:raise RuntimeError('Evaluation sources changed; do not dispatch another model request')
            tick=time.monotonic()
            result=invoke_reply(core,chat,{'message':case['text'],'provider':provider,'model':model,
                'personal_context':{'temporary':True},'context_note':'Reply briefly, at most 80 words.'},None,uuid.uuid4().hex)
            decision=result.get('intent_decision',{})
            from jarvis_core.documentation_admission import select_documentation
            predicted=sorted({item['kind'] for item in decision.get('intents',[])})
            effect=any(i['kind'] in {'action','control','memory'} and i['disposition']=='requested' and not i['missing_fields'] for i in decision.get('intents',[]))
            if decision.get('state')!='recognized':effect=None
            docs=case.get('documentation');doc_match=None
            if docs:
                doc_match=any(i['capability']=='mcp.documentation' and i['arguments'].get('library')==docs['library'] and docs['query_contains'] in i['arguments'].get('query','') for i in decision.get('intents',[]))
            return {'id':case['id'],'text':case['text'],'expected':sorted(case['labels']),'predicted':predicted,
                'expected_effect':case['requested_effect'],'predicted_effect':effect,'documentation_match':doc_match,
                'expected_documentation':case.get('documentation_requested'),
                'auto_expected':case.get('auto_expected'), 'auto_selected':bool(select_documentation(case['text'],decision)),
                'predicted_documentation':any(i['kind']=='action' and i['disposition']=='requested' and not i['missing_fields'] and i['capability']=='mcp.documentation' for i in decision.get('intents',[])),
                'needs_clarification':case.get('needs_clarification',False),'decision':decision,
                'status':result['status'],'reply':result.get('text'), 'error':result.get('error'),
                'usage':result.get('usage'),'billing':result.get('billing'),'attempts':len(result.get('attempts',[])),
                'elapsed_seconds':round(time.monotonic()-tick,3)}
        try:
            with ThreadPoolExecutor(max_workers=2) as executor:
                pending={executor.submit(run,c):c for c in cases}
                for future in as_completed(pending):
                    row=future.result();rows.append(row);save('RUNNING')
                    print(json.dumps({k:row[k] for k in ('id','status','predicted','elapsed_seconds')},ensure_ascii=False),flush=True)
            with core.ledger.connection() as db:assert db.execute('SELECT COUNT(*) FROM tasks').fetchone()[0]==0
            assert pool.snapshot()['active']==0
        finally:pool.close()
    save('COMPLETED' if all(r['status']=='SUCCEEDED' for r in rows) and hashes()==before else 'REVIEW_REQUIRED')
    print(str(destination))


if __name__=='__main__':main()
