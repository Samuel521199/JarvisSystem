"""Matched end-to-end source/answer ablation using a previously generated module."""
import argparse
import json
import re
from pathlib import Path
import sys
import time
import uuid

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'runtime/node-host'),str(ROOT/'adapters/computer-use'),str(ROOT/'tests')]
from test_ranking_modules import RankingModuleTests
from jarvis_core import policy
from jarvis_core.dialogue_process import DialogueProcesses
from jarvis_core.evolution.provider import default_route, ModelCodingProvider
from jarvis_core.knowledge import KnowledgeStore
from jarvis_core.retrieval_ranking import LexicalV1
from jarvis_core.ranking_registry import StoredRanking


def main():
    p=argparse.ArgumentParser();p.add_argument('--candidate-report',type=Path,required=True);p.add_argument('--output',type=Path,required=True)
    args=p.parse_args();args.output.mkdir(parents=True,exist_ok=False)
    candidate=json.loads(args.candidate_report.read_text(encoding='utf-8'))['candidate']
    ident=candidate.pop('id')
    assert policy.digest(policy.canonical_json(candidate).encode())[7:]==ident
    # Frozen AFTER code generation, BEFORE answer calls. The coder never sees these.
    cases=[{'query':q,'answer':a} for q,a in [
        ('battery charging','JRV-BAT-83'),('audio latency','JRV-AUD-89'),
        ('project archive','JRV-ARC-47'),('persona isolation','JRV-PER-62')]]
    (args.output/'frozen-answer-cases.json').write_text(json.dumps(cases,indent=2)+'\n',encoding='utf-8')
    report={'status':'running','candidate_id':ident,'cases':[],'scope':'four synthetic but actual registered project-source queries; no owner data',
            'limitations':['small deliberate lexical coverage failures, not representative traffic','exact source key recovery, not open-ended conversational quality']}
    def save():(args.output/'report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    save();f=RankingModuleTests();f.setUp()
    try:
        with f.manager.store.connection() as db:db.execute('INSERT INTO ranking_versions VALUES(?,?)',(ident,policy.canonical_json(candidate)))
        calls=DialogueProcesses(f.core,capacity=1);f.addCleanup(calls.close)
        coder=ModelCodingProvider(f.core);config,provider=coder.configuration(default_route())
        f.action('trial',ident)
        for number,case in enumerate(cases):
            first,second=case['query'].split()
            ids=[]
            # Six high-frequency single-concept distractors fill the legacy six-excerpt budget.
            for i in range(7):
                path=f'answer-{number}-{i}.md'
                content=(f'# {first}\n{first} {first}. General background, no release identifier.\n' if i<6
                         else f'# Release record\n{first} {second}: the verified release identifier is {case["answer"]}.\n')
                (f.folder/path).write_text(content,encoding='utf-8')
                docid=uuid.uuid4().hex;ids.append(docid);f.put(path=path,ident=docid)
            row={'query':case['query'],'expected':case['answer'],'routes':[]};report['cases'].append(row)
            for label,adapter in [('baseline',LexicalV1()),('candidate',StoredRanking(f.core))]:
                store=KnowledgeStore(f.core,ranking=adapter)
                started=time.perf_counter();text,meta=store.context(store.snapshot(f.ctx,'local'),case['query'])
                retrieval_ms=round((time.perf_counter()-started)*1000,3)
                response=calls.probe(config,provider,
                    'Question: What is the verified release identifier for '+case['query']+'?\n'+text,
                    f.core.data_dir,f.core.assert_running,deadline_seconds=60,
                    instructions='Use only the supplied project excerpts. Return exactly JSON {"answer":"identifier"}; if absent use {"answer":"UNKNOWN"}. Do not invent or use outside knowledge.')
                receipt=coder.receipt(response,config,provider)
                answer=None
                raw=response.get('text','')
                if response.get('status')=='SUCCEEDED' and not response.get('output_incomplete'):
                    fenced=re.fullmatch(r'\s*```(?:json)?\s*\n([\s\S]*?)\n```\s*',raw)
                    try:answer=json.loads(fenced[1] if fenced else raw)['answer']
                    except (ValueError,KeyError,TypeError):pass
                row['routes'].append(dict(route=label,answer=answer,correct=answer==case['answer'],
                    response_text=raw[:4000],target_in_context=case['answer'] in text,retrieval_ms=retrieval_ms,ranking=meta['ranking'],model=receipt))
                save()
                assert response.get('status')=='SUCCEEDED',receipt
            for docid in ids:f.store.delete(docid,{'revision':1})
        baseline=sum(c['routes'][0]['correct'] for c in report['cases'])
        improved=sum(c['routes'][1]['correct'] for c in report['cases'])
        assert improved==4 and baseline==0
        assert all(not c['routes'][0]['target_in_context'] and c['routes'][1]['target_in_context'] for c in report['cases'])
        report.update(status='passed',baseline_correct=baseline,candidate_correct=improved,model_calls=calls.snapshot()['completed'])
        save();print(json.dumps({'status':'passed','baseline':baseline,'candidate':improved,'model_calls':report['model_calls']}))
    except Exception as exc:
        report.update(status='failed',error=type(exc).__name__+': '+str(exc));save();raise
    finally:f.doCleanups()


if __name__=='__main__':main()
