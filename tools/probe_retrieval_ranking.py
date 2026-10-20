"""K5 development comparison of the real ranking boundary; zero model calls."""
import argparse
import hashlib
import json
from pathlib import Path
import statistics
import sys
import time
import tracemalloc

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'runtime/node-host'))
from jarvis_core import __version__
from jarvis_core.knowledge import terms,normalized
from jarvis_core.retrieval_ranking import rank,lexical_score,LexicalV1,CoverageV2


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--output',required=True,type=Path)
    args=p.parse_args();args.output.mkdir(parents=True,exist_ok=False)
    raw=(ROOT/'evals/cases/k5-ranking-v1.json').read_bytes();cases=json.loads(raw)['cases']
    report={'version':__version__,'stage':'K5 entry, not K5 closure','status':'running','model_calls':0,
            'frozen_sha256':hashlib.sha256(raw).hexdigest(),'production_default':'lexical-v1','results':[],
            'limitations':['12 deliberately targeted development cases, no holdout/general ranking conclusion',
                           'candidate is human-authored, not autonomous self-modification',
                           'timing is this machine; peak is incremental Python allocation, not process RSS']}
    for adapter in (LexicalV1(),CoverageV2()):
        row={'module':adapter.module_id,'cases':[]}
        for c in cases:
            words=terms(c['query']);rows=[]
            for d in c['documents']:
                text=normalized(d['text']);heading=normalized(d['title']+' '+d['path'])
                score=lexical_score(text,heading,words)
                if score:rows.append({'score':score,'text':text,'heading':heading,'path':d['path'],'start_line':1})
            order,meta=rank(rows,words,adapter);actual=rows[order[0]]['path'].split('.')[0] if order else None
            row['cases'].append({'id':c['id'],'expected':c['expected'],'actual':actual,'passed':actual==c['expected'],'metadata':meta})
        row['passed']=sum(x['passed'] for x in row['cases'])
        words=terms('offline model recovery')
        pool=[{'score':i%5+1,'text':('offline model recovery '*50 if i%3==0 else 'offline '*100),
               'heading':'offline','path':f'{i:04}.md','start_line':1} for i in range(2048)]
        measurements=[]
        for _ in range(30):
            begin=time.perf_counter();order,meta=rank(pool,words,adapter)
            measurements.append(time.perf_counter()-begin)
            assert sorted(order)==list(range(2048)) and not meta['fallback']
        tracemalloc.start();rank(pool,words,adapter);_,peak=tracemalloc.get_traced_memory();tracemalloc.stop()
        row['resources']={'candidates':2048,'runs':30,'median_seconds':statistics.median(measurements),
                          'maximum_seconds':max(measurements),'incremental_python_peak_bytes':peak}
        report['results'].append(row)
    assert [r['passed'] for r in report['results']]==[6,12]
    report['status']='passed'
    (args.output/'report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps({r['module']:{'passed':r['passed'],'resources':r['resources']} for r in report['results']},ensure_ascii=False))


if __name__=='__main__':main()
