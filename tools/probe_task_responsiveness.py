"""Frozen foreground response check during a real browser task awaiting a model.

All pages and model answers are synthetic. Thresholds are acceptance inputs,
not values chosen from the measured sample. CPU numbers cover this Host only.
"""
from datetime import datetime, timezone
import json
import math
import os
from pathlib import Path
import sys
import threading
import time

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'tests'),str(ROOT/'runtime/node-host'),str(ROOT/'adapters/computer-use')]
from test_computer_web import ComputerWebTests
from jarvis_computer.service import ComputerService
from jarvis_computer.planner import ScriptedDemoPlanner

SAMPLES_PER_OPERATION=15
P95_LIMIT_MS=300
MAX_LIMIT_MS=1000
CANCEL_COMPLETION_LIMIT_MS=3000


def main():
    started,release=threading.Event(),threading.Event()
    class WaitingPlanner:
        last_metadata={}
        def __init__(self,*args):pass
        def plan(self,task,observation):
            started.set();release.wait(30)
            return ScriptedDemoPlanner().plan(task,observation)
    fixture=ComputerWebTests();fixture.setUp()
    try:
        fixture.manager.service=ComputerService(fixture.core,planner_factory=WaitingPlanner)
        status,_,raw=fixture.request('POST','/api/tasks',fixture.payload('demo'))
        assert status==202,raw
        task_id=json.loads(raw)['task_id']
        assert started.wait(15),'Browser/model did not start'
        samples={name:[] for name in ('status','tasks','chat')}
        cpu_before=time.process_time();wall_before=time.monotonic()
        for _ in range(SAMPLES_PER_OPERATION):
            for name in samples:
                begin=time.perf_counter()
                if name=='chat': response=fixture.request('POST','/api/chat',{'message':'synthetic foreground response'})
                elif name=='tasks': response=fixture.get('/api/tasks')
                else: response=fixture.request('GET','/api/status')
                samples[name].append((time.perf_counter()-begin)*1000)
                assert response[0]==200,response
                if name=='status':assert json.loads(response[2])['assistant_state']=='working'
        cpu_seconds=time.process_time()-cpu_before;wall_seconds=time.monotonic()-wall_before
        begin=time.perf_counter()
        response=fixture.request('POST','/api/tasks/'+task_id+'/cancel',{})
        assert response[0]==200,response
        cancelled=fixture.wait_done(task_id)
        cancel_ms=(time.perf_counter()-begin)*1000
        assert cancelled['task']['status']=='CANCELLED',cancelled
        release.set()
        summary={name:{'count':len(values),'p95_ms':sorted(values)[math.ceil(.95*len(values))-1],
                       'max_ms':max(values)} for name,values in samples.items()}
        passed=all(v['p95_ms']<=P95_LIMIT_MS and v['max_ms']<=MAX_LIMIT_MS for v in summary.values()) and cancel_ms<=CANCEL_COMPLETION_LIMIT_MS
        report={'captured_at':datetime.now(timezone.utc).isoformat(),'status':'passed' if passed else 'failed',
                'thresholds':{'p95_ms':P95_LIMIT_MS,'max_ms':MAX_LIMIT_MS,'cancel_completion_ms':CANCEL_COMPLETION_LIMIT_MS},
                'samples_ms':samples,'summary':summary,'cancel_completion_ms':cancel_ms,
                'host_cpu_seconds':cpu_seconds,'elapsed_seconds':wall_seconds,
                'scope':'One real Edge task waiting on a synthetic model, 45 foreground HTTP requests; no cloud requests.',
                'limits':'Single local run; no GPU pressure, external-process peak RAM or long-duration capacity claim.'}
        output=Path(os.environ['LOCALAPPDATA'])/'Jarvis/data/diagnostics/runtime-continuity/responsiveness.json'
        output.parent.mkdir(parents=True,exist_ok=True)
        output.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
        print(json.dumps({'status':report['status'],'summary':summary,'cancel_completion_ms':cancel_ms,'report':str(output)}))
        return 0 if passed else 1
    finally:
        release.set();fixture.doCleanups()


if __name__=='__main__':raise SystemExit(main())
