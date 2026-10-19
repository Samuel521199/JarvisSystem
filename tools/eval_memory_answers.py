"""Paired final-answer pilot using disposable real Jarvis stores and context.

No production memory is opened. --live is required for paid model calls.
The corpus is developer-authored, visible and not an independent holdout.
"""
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import sys
import tempfile
import time
from unittest.mock import patch
import uuid

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'runtime/node-host'),str(ROOT/'tools')]
from jarvis_core import __version__
from jarvis_core.chat import ChatService, gateway
from jarvis_core.conversations import ConversationStore
from jarvis_core.memory import MemoryStore
from jarvis_core.personal_candidates import PersonalCandidates
from jarvis_core.service import CoreService
from jarvis_core.workspace import WorkspaceService
from eval_policy import default_route

CASES=ROOT/'evals/cases/memory-answer-pilot-v1.json'
UNKNOWN=r'不知道|不清楚|不确定|没有.{0,12}(?:记录|信息|记忆|资料)|未.{0,6}(?:记录|提供|找到)|无法.{0,6}(?:确定|确认|得知)|没.{0,8}(?:记录|告诉)'
ACTIONS={'keep','correct','forget','private','delete_source','other_project','work_purpose','edit_source'}


def load_cases(path):
    data=json.loads(path.read_text(encoding='utf-8'));ids=set()
    if data.get('schema_version')!=1 or not data.get('cases'):raise ValueError('Invalid corpus')
    for c in data['cases']:
        if c['id'] in ids or c['action'] not in ACTIONS:raise ValueError('Invalid case')
        ids.add(c['id'])
        for field in ['source','query','evidence']:
            if not isinstance(c[field],str) or not c[field]:raise ValueError('Missing text')
        if c['action']=='correct' and not c.get('replacement'):raise ValueError('Missing correction')
        if c['expected'] is not None and not isinstance(c['expected'],str):raise ValueError('Invalid rubric')
    return data


def prepare(base,case,provider):
    folder=base/'source';folder.mkdir();core=CoreService(base/'data');core.initialize(folder)
    project=None;query_project=None
    if case['action']=='other_project':
        project=WorkspaceService(core).open_project({'path':str(folder)})['id']
        other=base/'other';other.mkdir();query_project=WorkspaceService(core).open_project({'path':str(other)})['id']
    cid=uuid.uuid4().hex
    archive=ConversationStore(core)
    source=archive.put(cid,{'revision':0,'document':{'title':'Synthetic answer evaluation','project_id':project,'context_note':'',
        'messages':[{'role':'user','content':case['source'],'meta':'','short_meta':'','attachments_omitted':False,'incomplete':False}]}})
    candidates=PersonalCandidates(core)
    preview=candidates.suggest({'source':{'conversation_id':cid,'message_index':0},'project_id':project})
    assert len(preview['candidates'])==1
    item=preview['candidates'][0]
    review=candidates.review({k:item[k] for k in ['candidate_id','title','content','classification']}|
        {'scope':'current','preview_token':preview['preview_token']})
    saved=candidates.resolve({'review_token':review['review_token'],'decision':'new','target_id':None})
    memory=MemoryStore(core);row=memory.list(project_id=project)['facts'][0]
    assert row['id']==saved['receipt']['id']
    events=['archive_source','rule_preview','local_review','explicit_synthetic_confirmation']
    if case['action']!='private':
        row=memory.put(row['id'],{'revision':row['revision'],'document':{**row['document'],'providers':[provider]}})
        events.append('permit_selected_provider_for_synthetic_fact')
    action=case['action']
    if action=='correct':
        memory.put(row['id'],{'revision':row['revision'],'document':{**row['document'],'content':case['replacement']}})
    elif action=='forget':memory.delete(row['id'],{'revision':row['revision']})
    elif action=='delete_source':archive.delete(cid,{'revision':source['revision']})
    elif action=='edit_source':
        source=archive.get(cid)
        source['document']['messages'][0]['content']='这条合成来源已经修改。'
        archive.put(cid,{'revision':source['revision'],'document':source['document']})
    events.append(action)
    context={'enabled':True,'project_id':query_project,'purpose':'work_assist' if action=='work_purpose' else 'personal_chat'}
    return core,context,row['id'],events


def rubric(case,arm,result,trace,fact_id):
    expected=case['expected'] if arm=='memory' else None
    text=result.get('text','');outgoing='\n'.join(t['message'] for t in trace)
    refs=result.get('history_info',{}).get('memory',{}).get('references',[])
    expected_evidence=arm=='memory' and expected is not None
    evidence_present=case['evidence'] in outgoing
    forbidden=case.get('forbidden')
    checks={
        'complete_reply':result.get('status')=='SUCCEEDED' and not result.get('output_incomplete',False),
        'one_dispatch':len(trace)==1,
        'new_conversation_no_history':all(t['history']==[] for t in trace),
        'context_evidence_expected':evidence_present==expected_evidence,
        'context_references_expected':(any(r['id']==fact_id for r in refs))==expected_evidence,
        'old_or_excluded_fact_absent':not forbidden or forbidden not in outgoing and forbidden not in text,
        'answer_keyword_or_abstention':expected in text if expected is not None else bool(re.search(UNKNOWN,text)),
        'control_does_not_guess_fact':arm!='control' or case['evidence'] not in text}
    return {'checks':checks,'passed':all(checks.values()),'expected':expected,
            'rubric':'keyword/abstention + actual context/reference checks; not a general semantic judge'}


def evaluate(case,provider,model,live=False,transport=None):
    with tempfile.TemporaryDirectory(prefix='jarvis-memory-answer-') as tmp:
        core,context,fact_id,events=prepare(Path(tmp),case,provider);chat=ChatService(core)
        original=gateway.probe;rows=[]
        for arm in ['memory','control']:
            trace=[]
            def capture(config,selected,message,*args,**kwargs):
                trace.append({'message':message,'history':kwargs.get('history',[]),'provider':selected,
                    'model':config['providers'][selected]['model'],
                    'instructions_sha256':hashlib.sha256(kwargs.get('instructions','').encode()).hexdigest()})
                if transport:return transport(config,selected,message,*args,**kwargs)
                if live:return original(config,selected,message,*args,**kwargs)
                text=case['expected'] if arm=='memory' and case['expected'] else '没有可靠记录，我不知道。'
                return {'status':'SUCCEEDED','text':text,'provider':selected,'model':model,'fixture':True}
            tick=time.perf_counter()
            with patch('jarvis_core.chat.gateway.probe',side_effect=capture):
                result=chat.reply(case['query'],provider=provider,model=model,reasoning=None,history=[],
                    memory_context={**context,'enabled':arm=='memory'},_route_attempt_limit=1)
            row={'case':case['id'],'arm':arm,'events':events,'elapsed_ms':round((time.perf_counter()-tick)*1000,3),
                 'result':result,'transport':trace,'score':rubric(case,arm,result,trace,fact_id)}
            rows.append(row)
        return rows


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--live',action='store_true');parser.add_argument('--route',default=default_route())
    parser.add_argument('--cases',type=Path,default=CASES);parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args();data=load_cases(args.cases)
    if args.output.exists():raise SystemExit('Use a new report path; historical results are immutable.')
    provider,model=args.route.split('::',1)
    paths=['tools/eval_memory_answers.py','runtime/node-host/jarvis_core/assistant_context.py','runtime/node-host/jarvis_core/chat.py','runtime/node-host/jarvis_core/memory_view.py',
           'runtime/node-host/jarvis_core/memory.py','runtime/node-host/jarvis_core/personal_candidates.py','runtime/node-host/jarvis_core/memory_review.py']
    hashes={p:hashlib.sha256((ROOT/p).read_bytes()).hexdigest() for p in paths}
    report={'status':'RUNNING','source_version':__version__,'captured_at':datetime.now(timezone.utc).isoformat(),
        'live':args.live,'route':args.route,'split':data['split'],'corpus_sha256':hashlib.sha256(args.cases.read_bytes()).hexdigest(),
        'source_sha256':hashes,'rows':[],'limits':['Eight author-created development cases, one run per arm; no independent holdout',
        'Rule extraction and explicit synthetic confirmation only; not Mem0/LangMem comparison',
        'Empty new-conversation history; original source chat still contains forgotten words',
        'Memory references are injected-context evidence, not proof every output claim was grounded',
        'Fixture mode cannot score language-model quality; no production memory is opened']}
    def save():
        args.output.parent.mkdir(parents=True,exist_ok=True)
        args.output.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    save()
    try:
        for case in data['cases']:
            rows=evaluate(case,provider,model,args.live);report['rows'].extend(rows);save()
            print(json.dumps({'case':case['id'],'passed':[r['score']['passed'] for r in rows],'status':[r['result']['status'] for r in rows]}),flush=True)
            if any(r['result']['status']!='SUCCEEDED' for r in rows):
                report['status']='STOPPED_TRANSPORT_FAILURE';break
        else:report['status']='COMPLETED'
    except Exception as exc:
        report['status']='FAILED_SETUP';report['error_type']=type(exc).__name__;save();raise
    rows=report['rows'];costs=[r['result'].get('billing',{}) for r in rows]
    report['summary']={arm:{'runs':sum(r['arm']==arm for r in rows),'rubric_passes':sum(r['arm']==arm and r['score']['passed'] for r in rows)} for arm in ['memory','control']}
    receipts=[c for c in costs if c.get('currency')=='USD' and c.get('amount') is not None]
    report['cost']={'currency':'USD','estimated_amount':sum(c['amount'] for c in receipts),'receipts':len(receipts),
        'cloud_dispatches':sum(len(r['transport']) for r in rows) if args.live else 0,'missing_receipts':len(rows)-len(receipts) if args.live else 0}
    report['source_unchanged']=all(hashlib.sha256((ROOT/p).read_bytes()).hexdigest()==h for p,h in hashes.items())
    save();print(json.dumps({k:report[k] for k in ['status','summary','cost','source_unchanged']},ensure_ascii=False))
    return 0 if report['status']=='COMPLETED' and report['source_unchanged'] else 1


if __name__=='__main__':raise SystemExit(main())
