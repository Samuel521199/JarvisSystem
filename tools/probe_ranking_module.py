"""One real model candidate, LPAC comparison, actual knowledge selection/recovery."""
import argparse
import json
from pathlib import Path
import sys
import time
import uuid

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'runtime/node-host'),str(ROOT/'adapters/computer-use'),str(ROOT/'tests')]
from test_ranking_modules import RankingModuleTests
from jarvis_core import __version__
from jarvis_core.dialogue_process import DialogueProcesses
from jarvis_core.evolution.provider import default_route
from jarvis_core.knowledge import KnowledgeStore
from jarvis_core.ranking_evaluation import binding, CASES
from jarvis_core.ranking_registry import select_row


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',required=True,type=Path)
    args=parser.parse_args();args.output.mkdir(parents=True,exist_ok=False)
    report={'version':__version__,'status':'running','binding':binding(),'maximum_model_calls':1,
            'scope':'one model-generated restricted Python ranking module; temporary personal-assistant core',
            'limitations':['top-1 source relevance is not final-answer quality','short local trial is not longitudinal benefit',
                           'fixed lexical judgments; semantic and paraphrase failures retained']}
    def save():(args.output/'report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    (args.output/'frozen-heldout.json').write_bytes(CASES.read_bytes());save()
    f=RankingModuleTests();f.setUp()
    try:
        model=DialogueProcesses(f.core,capacity=1);f.addCleanup(model.close)
        f.service.model_calls=model
        request={'request_id':uuid.uuid4().hex,'model':default_route()}
        job=f.service.submit(request);start=time.monotonic()
        while f.manager.busy and time.monotonic()-start<160:time.sleep(.2)
        job=f.manager.store.job(job['id']);report['job']=job;save()
        assert job['status']=='SUCCEEDED',job.get('error')
        assert job['result']['eligible'],job['result']['evaluation']
        ident=job['result']['candidate_id']
        version=next(x for x in f.service.snapshot()['versions'] if x['id']==ident)
        (args.output/'candidate.py').write_text(version['source'],encoding='utf-8')
        assert f.service.submit(request)['id']==job['id']
        assert model.snapshot()['completed']==1
        f.put()
        original=f.file.read_bytes()
        f.action('trial',ident)
        measurements=[]
        for query in ('离线','部署','状态'):
            start=time.perf_counter();text,meta=f.view(query=query)
            measurements.append({'query':query,'milliseconds':round((time.perf_counter()-start)*1000,3),
                                 'ranking':meta['ranking'],'citations':len(meta['citations'])})
            assert meta['ranking']['used']==ident and not meta['ranking']['fallback']
        f.action('confirm',ident);f.service.recover()
        reloaded=KnowledgeStore(f.core)
        assert reloaded.context(reloaded.snapshot(f.ctx,'local'),'离线')[1]['ranking']['used']==ident
        f.action('rollback',ident)
        assert f.view()[1]['ranking']['used']=='lexical-v1'
        # Trial interrupted by restart must not stay active or call a model.
        f.action('trial',ident);f.service.recover()
        with f.manager.store.connection() as db:selection=select_row(db)
        assert selection['active'] is None and selection['last_event']=='unconfirmed_trial_restart_rollback'
        assert f.file.read_bytes()==original
        report.update(status='passed',candidate=version,actual_knowledge_queries=measurements,
                      confirmed_restart_preserved=True,manual_rollback=True,trial_restart_rollback=True,
                      original_source_unchanged=True,actual_model_calls=model.snapshot()['completed'])
        save();print(json.dumps({'status':'passed','report':str(args.output/'report.json'),
                                'quality':job['result']['evaluation']['candidate'],
                                'total':job['result']['evaluation']['total']}),flush=True)
    except Exception as exc:
        report.update(status='failed',error=type(exc).__name__+': '+str(exc));save();raise
    finally:f.doCleanups()


if __name__=='__main__':main()
