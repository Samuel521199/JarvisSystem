"""Thirty-round slow-model/CPU/database contention checks, disposable Host only."""
import argparse
from contextlib import closing
import ctypes as C
from datetime import datetime,timezone
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import threading
import time
import uuid

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'runtime/node-host'),str(ROOT/'apps/web'),str(ROOT/'tools')]
from jarvis_core import __version__
from jarvis_core.service import CoreService
from probe_k2_runtime import stats,dynamic_sample
from probe_idle_resources import WindowsProcesses
from probe_parallel_runtime import request,serve,PlanChat,task,detail
from server import create_server


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--output',type=Path,required=True);args=parser.parse_args()
    if args.output.exists():parser.error('Evidence already exists')
    args.output.parent.mkdir(parents=True,exist_ok=True)
    report={'version':__version__,'captured_at':datetime.now(timezone.utc).isoformat(),'status':'running','rounds':30,'cloud_calls':0,'conditions':{},
        'limits':['Four logical CPUs selected for this disposable Host and children; two CPU burners. Not a physical 8 GiB PC.',
                  'Model latency is a controlled 250 ms fixture. HTTP, LPAC Worker, database writer locks and counters are real.',
                  'Control targets use the frozen K2 200 ms p95; CPU comparisons use the same slow answer input.']}
    paths=[p for p in (ROOT/'runtime/node-host/jarvis_core').rglob('*.py')]+list((ROOT/'apps/web').glob('*.py'))
    hashes=lambda:{p.relative_to(ROOT).as_posix():hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}
    report['source_sha256']=hashes();burners=[];server=None
    api=C.WinDLL('kernel32',use_last_error=True)
    api.GetCurrentProcess.restype=C.c_void_p;handle=api.GetCurrentProcess()
    api.GetProcessAffinityMask.argtypes=[C.c_void_p,C.POINTER(C.c_size_t),C.POINTER(C.c_size_t)]
    api.SetProcessAffinityMask.argtypes=[C.c_void_p,C.c_size_t]
    current=C.c_size_t();system=C.c_size_t()
    if not api.GetProcessAffinityMask(handle,C.byref(current),C.byref(system)):raise C.WinError(C.get_last_error())
    cpus=[i for i in range(64) if current.value&(1<<i)][:4];mask=sum(1<<i for i in cpus)
    if not api.SetProcessAffinityMask(handle,mask):raise C.WinError(C.get_last_error())
    report['selected_logical_cpus']=cpus
    class SlowChat:
        def models(self):return {'models':[]}
        def reply(self,*args,cancel_event=None,**kwargs):
            if cancel_event and cancel_event.wait(.25):return {'status':'CANCELLED','outcome_uncertain':False}
            return {'status':'SUCCEEDED','text':'慢模型测试回答','provider':'fixture','model':'latency-fixture'}
    try:
        with tempfile.TemporaryDirectory(prefix='jarvis-k2-contention-') as temporary:
            base=Path(temporary);source=base/'sample';source.mkdir();(source/'a.txt').write_bytes(b'abc')
            core=CoreService(base/'data');core.initialize(source);server=create_server(core=core,chat=SlowChat(),port=0)
            server.computer.sample.chat_factory=lambda *a,**kw:PlanChat();thread=serve(server)
            def conversation():
                cid=uuid.uuid4().hex;rid=uuid.uuid4().hex;tick=time.monotonic()
                code,row,admit=request(server,'/api/dialogue/turns','POST',{'instance_id':server.instance_id,'conversation_id':cid,'request_id':rid,'chat':{'message':'固定慢回答','personal_context':{'temporary':True}}})
                assert code==202,(code,row)
                controls=[]
                while time.monotonic()-tick<5:
                    code,row,latency=request(server,f'/api/dialogue/turns/{rid}?instance_id={server.instance_id}&conversation_id={cid}')
                    assert code==200;(controls.append(latency))
                    if row['finished']:break
                    time.sleep(.01)
                assert row['status']=='SUCCEEDED',row
                return {'admission_ms':admit,'control_ms':controls,'completion_ms':1000*(time.monotonic()-tick)}
            conversation() # warmup excluded
            report['conditions']['slow_model_alone']=[conversation() for _ in range(30)]
            code='import time\ne=time.monotonic()+90\nx=0\nwhile time.monotonic()<e:\n x=(x*1664525+1013904223)&0xffffffff\n'
            for _ in range(2):burners.append(subprocess.Popen([sys.executable,'-I','-c',code],creationflags=subprocess.CREATE_NO_WINDOW))
            overlap=[];verified=[];samples=[];reader=WindowsProcesses()
            for _ in range(30):
                item=task(server);overlap.append(conversation())
                until=time.monotonic()+5
                while time.monotonic()<until:
                    row=detail(server,item)
                    if row['task']['status'] not in {'READY','RUNNING','CANCELLING'}:break
                    time.sleep(.01)
                assert row['task']['status']=='SUCCEEDED' and row['report']['verified'] and row['report']['total_bytes']==3,row
                verified.append(item['task_id']);values,exited=dynamic_sample(reader,os.getpid());samples.append({'processes':values,'exited':exited})
            report['conditions']['cpu_and_task_overlap']=overlap;report['verified_tasks']=verified;report['process_samples']=samples
            for process in burners:process.terminate();process.wait(5)
            burners=[]
            record=core.prepare_inventory(request_id='locked-cancel');ident=record['task']['task_id'];latencies=[]
            with closing(sqlite3.connect(core.ledger.db_path,isolation_level=None)) as writer:
                writer.execute('BEGIN IMMEDIATE')
                for _ in range(30):
                    code,body,latency=request(server,f'/api/tasks/{ident}/cancel','POST',{})
                    assert code==503,(code,body);latencies.append(latency)
                writer.rollback()
            code,body,_=request(server,f'/api/tasks/{ident}/cancel','POST',{})
            assert code==200 and core.ledger.record(task_id=ident)['action']['status']=='CANCELLED',(code,body)
            report['database_busy_cancel']=stats(latencies)
            serial=stats([r['completion_ms'] for r in report['conditions']['slow_model_alone']]);parallel=stats([r['completion_ms'] for r in overlap])
            allrows=report['conditions']['slow_model_alone']+overlap
            report['latency']={'serial':serial,'parallel':parallel,'ratio':parallel['p95_ms']/serial['p95_ms'],
                'admission':stats([r['admission_ms'] for r in allrows]),'control':stats([v for r in allrows for v in r['control_ms']])}
            report['checks']={'source_unchanged':hashes()==report['source_sha256'],'busy_p95':report['database_busy_cancel']['p95_ms']<=200,
                'admission_p95':report['latency']['admission']['p95_ms']<=200,'control_p95':report['latency']['control']['p95_ms']<=200,
                'degradation':report['latency']['ratio']<=1.3,'task_progress':len(verified)==30}
            report['status']='passed_on_this_machine' if all(report['checks'].values()) else 'failed'
            server.shutdown();server.server_close();thread.join(3);server=None
    except Exception as error:report.update(status='failed',error=repr(error));raise
    finally:
        for process in burners:
            if process.poll() is None:process.terminate()
            process.wait(5)
        if server:server.shutdown();server.server_close()
        api.SetProcessAffinityMask(handle,current.value)
        args.output.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
        print(json.dumps({k:report[k] for k in ('status','checks','latency','database_busy_cancel','error') if k in report},ensure_ascii=False))
    return 0 if report['status']=='passed_on_this_machine' else 1


if __name__=='__main__':raise SystemExit(main())
