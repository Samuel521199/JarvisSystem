"""Real local-model and LPAC task overlap on this machine; no cloud transport.

Uses disposable stores and owns its engine. It never takes over port 18180.
Resource samples include this probe/Host and descendants; Worker kernel peaks
are recorded separately because a sample may miss a short-lived process.
"""
import argparse
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime,timezone
import hashlib
import http.client
import json
import math
import os
from pathlib import Path
import statistics
import sys
import tempfile
import threading
import time
import uuid

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'runtime/node-host'),str(ROOT/'apps/web'),str(ROOT/'adapters/computer-use')]
from jarvis_core import __version__
from jarvis_core.chat import ChatService
from jarvis_core.local_model import LocalModel
from jarvis_core.resources import memory_snapshot
from jarvis_core.process_usage import process_usage
from jarvis_core.service import CoreService
from windows_process_snapshot import OwnedProcesses as WindowsProcesses
from server import create_server


def uid():return uuid.uuid4().hex


def stats(values):
    values=sorted(values)
    return {'count':len(values),'p50_ms':values[math.ceil(len(values)*.5)-1],
            'p95_ms':values[math.ceil(len(values)*.95)-1],'max_ms':values[-1]} if values else {'count':0}


def dynamic_sample(reader, root_pid):
    """An exited child is observable churn, not a silently ignored read error."""
    values=[];exited=[]
    for row in reader.tree(root_pid):
        try:
            counters=process_usage(row['pid'])
            if counters['created']!=row['created_ticks']:
                exited.append({**row,'reason':'pid_reused_before_counter_read'});continue
            values.append({**row,**counters,'created_ticks':counters['created'],
                           'working_bytes':counters['working_set_bytes']})
        except OSError as error:
            still_present={p['pid'] for p in reader.tree(root_pid)}
            if row['pid']!=root_pid and error.winerror==87 and row['pid'] not in still_present:
                exited.append(row)
            else:raise RuntimeError(json.dumps({'process':row,'counter_error':repr(error),'still_present':row['pid'] in still_present})) from error
    if not any(p['pid']==root_pid for p in values):raise RuntimeError('Host missing from sample')
    return values,exited


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--rounds',type=int,default=30);parser.add_argument('--seconds',type=int,default=1800)
    parser.add_argument('--output',type=Path,required=True);args=parser.parse_args()
    if args.output.exists():parser.error('Do not overwrite previous evidence')
    if not 1<=args.rounds<=60 or not 0<=args.seconds<=3600:parser.error('Invalid bounded duration/rounds')
    args.output.parent.mkdir(parents=True,exist_ok=True)
    report={'version':__version__,'captured_at':datetime.now(timezone.utc).isoformat(),'status':'running',
            'rounds':args.rounds,'target_seconds':args.seconds,'paid_model_calls':0,'phases':{},'samples':[],
            'environment':{'logical_cpus':os.cpu_count(),'memory':memory_snapshot(),'inference':'Qwen3 0.6B CPU, 4 threads, 2048 context, one inference slot'},
            'limits':['Development machine, not physical 8 GiB acceptance.','The probe and Host share a process; sampler overhead is included. Browser UI is tested separately.',
                      'No system-wide disconnect; configuration contains only the local provider. Periodic process peaks are observations, supplemented by Worker kernel peaks.']}
    paths=[p for p in (ROOT/'runtime/node-host/jarvis_core').rglob('*.py')]+list((ROOT/'apps/web').glob('*.py'))
    paths += [Path(__file__), ROOT/'tools/windows_process_snapshot.py']
    def hashes():return {str(p.relative_to(ROOT)).replace('\\','/'):hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}
    report['source_sha256']=hashes()
    def save():args.output.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    done=threading.Event();sample_errors=[];worker_peaks=[];sampler=None;runtime=None;server=None
    try:
        with tempfile.TemporaryDirectory(prefix='jarvis-k2-runtime-') as temp:
            base=Path(temp);source=base/'sample';source.mkdir()
            (source/'a.txt').write_bytes(b'abc');(source/'b.txt').write_bytes(b'ab')
            core=CoreService(base/'data');core.initialize(source)
            config=json.loads((ROOT/'config/model-profiles/providers.json').read_text(encoding='utf-8'))
            config.update(default_provider='local',automatic_fallback=False,fallback_order=['local'],providers={'local':config['providers']['local']})
            path=base/'providers.json';path.write_text(json.dumps(config),encoding='utf-8')
            runtime=LocalModel(core);tick=time.monotonic();runtime.start();report['engine_ready_seconds']=time.monotonic()-tick
            server=create_server(core=core,chat=ChatService(core,path),port=0)
            thread=threading.Thread(target=server.serve_forever,kwargs={'poll_interval':.01},daemon=True);thread.start()
            origin=f'http://127.0.0.1:{server.server_port}'
            def request(path,method='GET',payload=None):
                start=time.perf_counter();conn=http.client.HTTPConnection('127.0.0.1',server.server_port,timeout=30)
                try:
                    conn.request(method,path,None if payload is None else json.dumps(payload),{'Origin':origin,'X-Jarvis-Nonce':server.nonce,'Content-Type':'application/json'})
                    response=conn.getresponse();body=json.loads(response.read());return response.status,body,(time.perf_counter()-start)*1000
                finally:conn.close()
            reader=WindowsProcesses();started=time.monotonic()
            def sample():
                while not done.is_set():
                    try:
                        processes,exited=dynamic_sample(reader,os.getpid())
                        report['samples'].append({'seconds':time.monotonic()-started,'processes':processes,
                            'exited_between_enumeration_and_read':exited,'memory':memory_snapshot()})
                    except Exception as error:sample_errors.append(repr(error))
                    done.wait(.5)
            sampler=threading.Thread(target=sample,daemon=True);sampler.start()
            def chat():
                conversation=uid();ident=uid();tick=time.monotonic()
                code,row,admission=request('/api/dialogue/turns','POST',{'instance_id':server.instance_id,'conversation_id':conversation,'request_id':ident,
                    'chat':{'message':'请用一句简短的中文问候我。','provider':'local','personal_context':{'temporary':True},'context_note':'性能测试：直接通过模型回复，不调用工具。'}})
                assert code==202,(code,row)
                controls=[]
                while time.monotonic()-tick<60:
                    code,row,latency=request(f'/api/dialogue/turns/{ident}?conversation_id={conversation}&instance_id={server.instance_id}')
                    controls.append(latency);assert code==200,(code,row)
                    if row['finished']:break
                    time.sleep(.025)
                assert row['finished'] and row['result']['status']=='SUCCEEDED',row
                assert row['result'].get('provider')=='local' and row['result'].get('text'),row
                return {'completion_ms':(time.monotonic()-tick)*1000,'admission_ms':admission,'control_ms':controls,'answer':row['result']['text']}
            def task():
                code,row,latency=request('/api/tasks','POST',{'mode':'natural','request_id':'web-'+uid(),'prompt':'列出样例目录文件，按类型统计并保存 JSON。','model':'local::qwen3-0.6b'})
                assert code==202,(code,row)
                return row['task_id'],time.monotonic(),latency
            def finish_task(item):
                ident,tick,admission=item
                while time.monotonic()-tick<90:
                    row=server.computer.detail(ident,all_tasks=True)
                    if row['task']['status'] not in {'READY','RUNNING','CANCELLING'}:break
                    time.sleep(.025)
                assert row['task']['status']=='SUCCEEDED' and row['report']['verified'],row
                assert row['report']['total_files']==2 and row['report']['total_bytes']==5
                if core.last_worker_evidence:worker_peaks.append(core.last_worker_evidence)
                return {'id':ident,'completion_ms':(time.monotonic()-tick)*1000,'admission_ms':admission,'verified':True}
            # Cold start and warm-up are separate from the measured samples.
            report['warmup']=chat()
            report['phases']['single']=[chat() for _ in range(args.rounds)];save()
            parallel=[];completed=[]
            for _ in range(args.rounds):
                item=task();parallel.append(chat());completed.append(finish_task(item))
            report['phases']['parallel']=parallel;report['comparison_tasks']=completed;save()
            soak_start=time.monotonic();cycles=[];report['soak']=cycles
            while time.monotonic()-soak_start<args.seconds:
                item=task();answer=chat();work=finish_task(item)
                metrics=server.metrics.snapshot();queue=server.computer.queue.snapshot()
                cycles.append({'elapsed_seconds':time.monotonic()-soak_start,'chat':answer,'task':work,'queue_wait':metrics['lanes']['task']['queue_wait'],'queue_depth':queue['waiting']})
                save()
                if len(cycles)%6==0:print(json.dumps({'cycles':len(cycles),'seconds':round(time.monotonic()-soak_start),'verified_tasks':len(completed)+len(cycles)}),flush=True)
                done.wait(min(3,max(0,args.seconds-(time.monotonic()-soak_start))))
            report['soak_seconds']=time.monotonic()-soak_start
            single=stats([r['completion_ms'] for r in report['phases']['single']]);parallel_stats=stats([r['completion_ms'] for r in parallel])
            allrows=report['phases']['single']+parallel+[c['chat'] for c in cycles]
            report['latency']={'single_completion':single,'parallel_completion':parallel_stats,
                'parallel_p95_ratio':parallel_stats['p95_ms']/single['p95_ms'],
                'admission':stats([r['admission_ms'] for r in allrows]),'control':stats([v for r in allrows for v in r['control_ms']])}
            report['metrics']=server.metrics.snapshot();report['worker_evidence']=worker_peaks
            report['checks']={'rounds':args.rounds>=30,'soak_duration':report['soak_seconds']>=1800,
                'text_admission_p95':report['latency']['admission']['p95_ms']<=200,
                'text_control_p95':report['latency']['control']['p95_ms']<=200,
                'parallel_degradation':report['latency']['parallel_p95_ratio']<=1.3,
                'background_progress':bool(completed) and bool(cycles),'sample_errors':not sample_errors,'source_unchanged':hashes()==report['source_sha256']}
            report['status']='passed_on_this_machine' if all(report['checks'].values()) else 'acceptance_not_passed'
            done.set();sampler.join(3);server.shutdown();server.server_close();thread.join(3);server=None
            runtime.close();report['engine_reclaimed']=not runtime.port_in_use();runtime=None
            assert report['engine_reclaimed']
    except Exception as error:
        report.update(status='failed',error=repr(error));raise
    finally:
        done.set()
        if sampler:sampler.join(3)
        if server:server.shutdown();server.server_close()
        if runtime:runtime.close()
        report['sample_errors']=sample_errors;save()
        print(json.dumps({k:report[k] for k in ('status','latency','checks','error') if k in report},ensure_ascii=False))
    return 0 if report['status']=='passed_on_this_machine' else 1


if __name__=='__main__':raise SystemExit(main())
