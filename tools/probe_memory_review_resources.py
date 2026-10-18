"""Bounded local review measurement on synthetic independent facts (not a soak test)."""
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import statistics
import sys
import time
import uuid

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'tests'),str(ROOT/'runtime/node-host')]
from test_memory_review import ReviewTests
from jarvis_core import __version__
from jarvis_core.memory import MemoryStore, MAX_FACTS
from jarvis_core.process_memory import process_memory


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    if args.output.exists():raise SystemExit('Use a new evidence path')
    case=ReviewTests();case.setUp();samples=[]
    report={'version':__version__,'captured_at':datetime.now(timezone.utc).isoformat(),
            'real_model_calls':0,'user_data_modified':False,'rows':MAX_FACTS,
            'scope':'1000 independent classified facts, 1024 characters each; no archive reads, browser, GPU or overnight run'}
    try:
        payload=case.confirmation(case.preview())
        before=process_memory()
        memory=MemoryStore(case.core)
        policy=payload['classification']
        for i in range(MAX_FACTS):
            content=('主人平时喜欢茶，合成候选比较数据'+str(i)).ljust(1024,'甲')
            memory.put(uuid.uuid4().hex,{'revision':0,'document':{
                'title':'合成偏好'+str(i),'content':content,'project_id':None,'providers':[], 'classification':policy}})
        seeded=process_memory()
        for _ in range(20):
            started=time.perf_counter();result=case.semantic.review(payload)
            samples.append((time.perf_counter()-started)*1000)
            assert len(result['matches'])==5 and result['truncated'] and result['total_matches']==MAX_FACTS
        after=process_memory()
        report.update(status='passed',review_samples=20,latency_ms={'min':min(samples),'median':statistics.median(samples),
            'p95':sorted(samples)[18],'max':max(samples)},process_memory={'before_seed':before,'after_seed':seeded,'after_reviews':after},
            database_bytes=memory.path.stat().st_size,new_worker_processes=0)
    finally:case.doCleanups()
    args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(report,ensure_ascii=False))


if __name__=='__main__':main()
