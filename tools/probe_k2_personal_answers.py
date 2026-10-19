"""Frozen K2 life/learning/work queries and retained-history lifecycle, live or fixture.

The comparison disables only relevance selection, not provenance/permissions.
This is a component ablation, not a replay of a historical binary or owner feedback.
"""
import argparse
from contextlib import nullcontext
from datetime import datetime,timezone
import hashlib
import json
from pathlib import Path
import sys
import tempfile
from unittest.mock import patch
import uuid

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'runtime/node-host'),str(ROOT/'tools')]
from jarvis_core import __version__
from jarvis_core.chat import ChatService,gateway
from jarvis_core.memory import MemoryStore
from jarvis_core.persona import PersonaStore
from jarvis_core.service import CoreService


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--live',action='store_true');parser.add_argument('--route',default='vertex::gemini-3.8-flash')
    parser.add_argument('--output',type=Path,required=True);args=parser.parse_args()
    if args.output.exists():parser.error('Evidence exists; use a new path')
    provider,model=args.route.split('::',1)
    corpus=ROOT/'evals/cases/k2-personal-reference-v1.json'
    cases=json.loads(corpus.read_text(encoding='utf-8'))['cases']
    paths=[p for p in (ROOT/'runtime/node-host/jarvis_core').rglob('*.py')]+[Path(__file__),corpus]
    hashes=lambda:{p.relative_to(ROOT).as_posix():hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}
    report={'version':__version__,'captured_at':datetime.now(timezone.utc).isoformat(),'status':'running','live':args.live,
            'route':args.route,'source_sha256':hashes(),'rows':[],
            'limits':['Developer-authored visible cases, not independent holdout or subjective owner acceptance.',
                      'Same current runtime, with relevance selector bypassed in the ablation arm; not historical version score.',
                      'Synthetic explicitly saved facts; no production personal records. Keyword checks are not a general semantic judge.']}
    real=gateway.probe
    args.output.parent.mkdir(parents=True,exist_ok=True)
    def save():args.output.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    try:
        for case in [c for c in cases if c['id'] in {'KM01','KM02','KM03'}]:
            with tempfile.TemporaryDirectory(prefix='k2-personal-answers-') as temporary:
                base=Path(temporary);source=base/'input';source.mkdir();core=CoreService(base/'data');core.initialize(source)
                store=MemoryStore(core);facts=[]
                for entry in case['facts']:
                    title,body=entry.split('：',1)
                    facts.append(store.put(uuid.uuid4().hex,{'revision':0,'document':{'title':title,'content':body,'project_id':None,'providers':[provider]}}))
                PersonaStore(core).change('preferred_name','小林',request_id=uuid.uuid4().hex)
                chat=ChatService(core)
                for arm in ['all_eligible_ablation','relevant','without_memory']:
                    trace=[]
                    def transport(config,selected,message,*a,**kw):
                        trace.append({'message':message,'history':kw.get('history',[]),'instructions':kw.get('instructions',''),'provider':selected})
                        return real(config,selected,message,*a,**kw) if args.live else {'status':'SUCCEEDED','text':'fixture','provider':selected,'model':model}
                    selection=patch('jarvis_core.memory_view.select_facts',side_effect=lambda facts,query,**kw:facts) if arm=='all_eligible_ablation' else nullcontext()
                    with selection,patch('jarvis_core.chat.gateway.probe',side_effect=transport):
                        result=chat.reply(case['query'],provider=provider,model=model,_route_attempt_limit=1,
                            personal_context={'temporary':False},memory_context={'enabled':arm!='without_memory','project_id':None})
                    raw=json.dumps(trace,ensure_ascii=False)
                    target=facts[0]['document']['content'];unrelated=facts[1]['document']['content']
                    checks={'successful':result.get('status')=='SUCCEEDED','one_dispatch':len(trace)==1,
                        'target_context':(target in raw)==(arm!='without_memory'),
                        'unrelated_context':(unrelated in raw)==(arm=='all_eligible_ablation'),
                        'profile_survives':all('小林' in t['instructions'] for t in trace)}
                    if args.live and arm=='relevant':checks['answer_uses_relevant_fact']=target.replace('喜欢','').replace('完成','').replace('采用','') in result.get('text','')
                    report['rows'].append({'case':case['id'],'arm':arm,'checks':checks,'result':result,'transport':trace});save()
                # Real returned history, then correction and deletion; no raw old fact in later requests.
                original=report['rows'][-2]['result'];history=[{'role':'user','content':case['query']},{'role':'assistant','content':original.get('text','')}]
                refs=[[],original.get('history_info',{}).get('memory',{}).get('references',[])]
                row=facts[0];replacement={'KM01':'喜欢清蒸蔬菜','KM02':'完成基础语法','KM03':'采用短期会话票据'}[case['id']]
                current=store.put(row['id'],{'revision':row['revision'],'document':{**row['document'],'content':replacement}})
                for action in ['correct','forget']:
                    if action=='forget':store.delete(current['id'],{'revision':current['revision']})
                    trace=[]
                    with patch('jarvis_core.chat.gateway.probe',side_effect=transport):
                        result=ChatService(CoreService(core.data_dir)).reply(case['query'],provider=provider,model=model,_route_attempt_limit=1,
                            history=history,history_memory=refs,personal_context={'temporary':False},memory_context={'enabled':True,'project_id':None})
                    raw=json.dumps(trace,ensure_ascii=False)
                    checks={'successful':result.get('status')=='SUCCEEDED','old_fact_absent':row['document']['content'] not in raw,
                        'old_derived_history_absent':all(not t['history'] for t in trace),'current_fact_expected':(replacement in raw)==(action=='correct')}
                    report['rows'].append({'case':case['id'],'arm':action,'checks':checks,'result':result,'transport':trace});save()
        report['source_unchanged']=hashes()==report['source_sha256']
        report['status']='passed' if report['source_unchanged'] and all(all(r['checks'].values()) for r in report['rows']) else 'failed'
        report['cost']={'estimated_usd':sum((r['result'].get('billing') or {}).get('amount',0) or 0 for r in report['rows']),
            'dispatches':sum(len(r['transport']) for r in report['rows']) if args.live else 0}
        print(json.dumps({'status':report['status'],'cost':report['cost'],'failed':[{k:r[k] for k in ('case','arm','checks')} for r in report['rows'] if not all(r['checks'].values())]},ensure_ascii=False))
    except Exception as error:report.update(status='failed',error=repr(error));raise
    finally:save()
    return 0 if report['status']=='passed' else 1


if __name__=='__main__':raise SystemExit(main())
