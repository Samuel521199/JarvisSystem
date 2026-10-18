"""Disposable concurrency, UI, crash and optional real local-model evidence."""
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from datetime import datetime, timezone
import argparse
import http.client
import importlib.util
import json
import math
import os
import re
from pathlib import Path
import statistics
import subprocess
import sys
import tempfile
import threading
import time
import uuid

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'runtime/node-host'),str(ROOT/'adapters/computer-use')]
from jarvis_core import __version__
from jarvis_core.service import CoreService
from jarvis_core.chat import ChatService
from jarvis_core.resources import ResourceAdmission,MIB,memory_snapshot
from jarvis_core.process_usage import process_usage
from jarvis_computer.browser import DriverJob
from playwright.sync_api import sync_playwright,expect

spec=importlib.util.spec_from_file_location('parallel_runtime_web',ROOT/'apps/web/server.py')
web=importlib.util.module_from_spec(spec);spec.loader.exec_module(web)
PLAN={'schema_version':1,'kind':'inventory_report','steps':[
    {'skill':'sample_metadata_read','arguments':{'relative_path':'.'}},
    {'skill':'artifact_output','arguments':{'format':'json'}}]}


def wait(predicate,seconds=20):
    end=time.monotonic()+seconds
    while time.monotonic()<end:
        value=predicate()
        if value:return value
        time.sleep(.02)
    raise AssertionError('Condition timed out')


def request(server,path,method='GET',payload=None,ident=None):
    port=server.server_port
    headers={'X-Jarvis-Nonce':server.nonce,'Origin':'http://127.0.0.1:'+str(port),'Content-Type':'application/json'}
    if ident:headers['X-Jarvis-Request']=ident
    conn=http.client.HTTPConnection('127.0.0.1',port,timeout=100)
    start=time.perf_counter()
    try:
        conn.request(method,path,None if payload is None else json.dumps(payload),headers)
        response=conn.getresponse();raw=response.read()
        return response.status,json.loads(raw),(time.perf_counter()-start)*1000
    finally:conn.close()


def serve(server):
    thread=threading.Thread(target=server.serve_forever,kwargs={'poll_interval':.01},daemon=True);thread.start();return thread


def fixture(base):
    source=base/'sample';source.mkdir();(source/'a.txt').write_bytes(b'abc');(source/'b.TXT').write_bytes(b'ab')
    core=CoreService(base/'data');core.initialize(source);return core


class PlanChat:
    def models(self):return {'models':[]}
    def reply(self,*args,**kwargs):return {'status':'SUCCEEDED','text':json.dumps(PLAN),'provider':'fixture','model':'fixture','outcome_uncertain':False}


def task(server):
    return request(server,'/api/tasks','POST',{'mode':'natural','request_id':'web-'+uuid.uuid4().hex,'prompt':'列出样例目录文件，按类型统计并保存结果。','model':'auto'})[1]


def detail(server,item):return server.computer.detail(item['task_id'],all_tasks=True)


def ui_and_pressure():
    output=Path(os.environ['LOCALAPPDATA'])/'Jarvis/data/diagnostics/parallel-runtime';output.mkdir(parents=True,exist_ok=True)
    errors=[];checks=[];control_samples=[]
    with tempfile.TemporaryDirectory(prefix='jarvis-parallel-ui-') as temp:
        core=fixture(Path(temp));chat_release=threading.Event();task_release=threading.Event()
        class HeldChat:
            def models(self):return {'models':[]}
            def reply(self,*args,cancel_event=None,**kwargs):
                while not chat_release.wait(.02):
                    if cancel_event and cancel_event.is_set():return {'status':'CANCELLED','outcome_uncertain':False}
                return {'status':'SUCCEEDED','text':'fixture','outcome_uncertain':False}
        class HeldPlan(PlanChat):
            def reply(self,*args,cancel_event=None,**kwargs):
                while not task_release.wait(.02):
                    if cancel_event and cancel_event.is_set():return {'status':'CANCELLED','outcome_uncertain':False}
                return super().reply(*args,**kwargs)
        server=web.create_server(core=core,chat=HeldChat(),port=0);server.computer.sample.chat_factory=lambda *a,**kw:HeldPlan()
        thread=serve(server)
        try:
            with ThreadPoolExecutor(2) as pool,sync_playwright() as p:
                ident=uuid.uuid4().hex;future=pool.submit(request,server,'/api/chat','POST',{'message':'held chat'},ident)
                second_ident=uuid.uuid4().hex;other=pool.submit(request,server,'/api/chat','POST',{'message':'another held chat'},second_ident)
                item=task(server);wait(lambda:server.metrics.snapshot()['lanes']['task']['active']==1)
                wait(lambda:server.metrics.snapshot()['lanes']['chat']['active']==2)
                for _ in range(20):
                    code,data,elapsed=request(server,'/api/resources');assert code==200;control_samples.append(elapsed)
                    assert data['runtime']['lanes']['chat']['active']==2 and data['runtime']['lanes']['task']['active']==1
                job=DriverJob(p)
                try:
                    browser=p.chromium.launch(channel='msedge',headless=True,chromium_sandbox=True)
                    page=browser.new_page(viewport={'width':1440,'height':1050});page.on('pageerror',lambda e:errors.append(str(e)))
                    page.goto('http://127.0.0.1:'+str(server.server_port)+'/settings#modules')
                    panel=page.locator('#modules-view .runtime-panel');expect(panel.locator('[data-runtime="chat-active"]')).to_have_text('2 / 2 进行中')
                    expect(panel.locator('[data-runtime="task-active"]')).to_have_text('1 / 1 进行中')
                    expect(panel.locator('[data-runtime="host"]')).to_contain_text('MiB',timeout=15000)
                    panel.screenshot(path=str(output/'parallel-desktop.png'))
                    page.set_viewport_size({'width':390,'height':844});assert page.evaluate('document.documentElement.scrollWidth<=innerWidth')
                    panel.screenshot(path=str(output/'parallel-mobile.png'))
                    calls=[];page.on('request',lambda req:calls.append(req.url) if '/api/resources' in req.url else None)
                    page.locator('[data-view="appearance"]').click();page.wait_for_timeout(800);count=len(calls);page.wait_for_timeout(3200);assert len(calls)==count
                    checks.append('Actual settings modules UI shows simultaneous chat/task and native Host memory; mobile fits; leaving observed settings view stops resource polling')
                    browser.close()
                finally:job.close()
                code,_,cancel_ms=request(server,'/api/chat/cancel','POST',{'request_id':ident});assert code==200
                assert future.result()[1]['status']=='CANCELLED'
                assert server.metrics.snapshot()['lanes']['task']['active']==1
                assert server.metrics.snapshot()['lanes']['chat']['active']==1
                chat_release.set();assert other.result()[1]['status']=='SUCCEEDED'
                task_release.set();result=wait(lambda:(d if (d:=detail(server,item))['task']['status']=='SUCCEEDED' else None))
                assert result['report']['verified'] and result['report']['total_files']==2 and result['report']['total_bytes']==5
                wait(lambda:server.metrics.snapshot()['lanes']['task']['active']==0)
                checks.append('Canceling one of two chats leaves the other chat and background plan alive; real LPAC Worker completes a verified two-file/five-byte report once')
                # Synthetic pressure tests admission without exhausting RAM.
                pressure=[True];guard=ResourceAdmission(probe=lambda:{'total_bytes':8192*MIB,'available_bytes':(100 if pressure[0] else 4096)*MIB,'commit_available_bytes':4096*MIB})
                server.computer.queue.resources=guard
                second=task(server);wait(lambda:guard.snapshot()['reason']=='memory_pressure')
                assert detail(server,second)['action_status']=='PREPARED'
                chat_release.set();assert request(server,'/api/chat','POST',{'message':'during pressure'})[1]['status']=='SUCCEEDED'
                third=task(server);server.computer.cancel(third['task_id'],all_tasks=True)
                pressure[0]=False;wait(lambda:guard.snapshot()['reason']=='resource_recovering',seconds=6)
                wait(lambda:detail(server,second)['task']['status']=='SUCCEEDED',seconds=12)
                assert detail(server,third)['task']['status']=='CANCELLED'
                assert len(server.computer.sample.steps(second['task_id']))==1 and not server.computer.sample.steps(third['task_id'])
                checks.append('Injected low-memory admission holds PREPARED without planning; chat works; hysteresis resumes once; canceled waiting task never plans')
                assert not errors,errors
                return {'status':'passed','checks':checks,'page_errors':errors,'control_api_ms':{'samples':len(control_samples),'p50':round(statistics.median(control_samples),2),'max':round(max(control_samples),2)},
                    'cancel_chat_http_ms':round(cancel_ms,2),'metrics':server.metrics.snapshot(),'screenshots':[str(output/'parallel-desktop.png'),str(output/'parallel-mobile.png')],
                    'limits':['Planning and chat are controlled fixtures; native Worker and UI/HTTP are real.','Low memory is injected, not an actual OOM test.','Control API short warm sample is not a universal latency SLA.']}
        finally:chat_release.set();task_release.set();server.shutdown();server.server_close();thread.join(3)


def child_crash(base,point):
    core=fixture(base)
    class BlockChat:
        def models(self):return {'models':[]}
        def reply(self,*args,**kwargs):threading.Event().wait(60)
    server=web.create_server(core=core,chat=BlockChat(),port=0);server.reply_timeout=.1;serve(server)
    def crash():
        snapshot=server.metrics.snapshot();assert snapshot['lanes']['chat']['active']==1
        (base/'crash.json').write_text(json.dumps({'point':point,'metrics':snapshot}),encoding='utf-8');os._exit(91)
    class CrashPlan(PlanChat):
        def reply(self,*args,**kwargs):
            if point=='planning':crash()
            return super().reply(*args,**kwargs)
    server.computer.sample.chat_factory=lambda *a,**kw:CrashPlan()
    code,_,_=request(server,'/api/chat','POST',{'message':'parallel crash fixture'},uuid.uuid4().hex);assert code==504
    if point=='prepared':server.computer.queue.set_paused(True)
    elif point=='artifact':
        original=core._verify_artifact
        def verify(*a,**kw):original(*a,**kw);crash()
        core._verify_artifact=verify
    elif point=='committed':
        original=core.ledger.effect_guard
        @contextmanager
        def guard(*a,**kw):
            with original(*a,**kw) as db:yield db
            records=core.status()['tasks']
            if records and core.ledger.record(task_id=records[0]['task_id'])['action']['status']=='CONFIRMED':crash()
        core.ledger.effect_guard=guard
    task(server)
    if point=='prepared':crash()
    time.sleep(20);raise AssertionError('Crash boundary not reached')


def crash_recovery():
    results=[]
    for point in ('prepared','planning','artifact','committed'):
        with tempfile.TemporaryDirectory(prefix='jarvis-parallel-crash-') as temp:
            base=Path(temp)
            process=subprocess.run([sys.executable,'-X','utf8','-B',str(Path(__file__).resolve()),'--child',str(base),'--point',point],
                capture_output=True,text=True,encoding='utf-8',timeout=35,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
            assert process.returncode==91,(point,process.returncode,process.stderr)
            marker=json.loads((base/'crash.json').read_text(encoding='utf-8'))
            core=CoreService(base/'data');core._recover();record=core.ledger.record(task_id=core.status()['tasks'][0]['task_id'])
            expected={'prepared':'PREPARED','planning':'UNKNOWN','artifact':'UNKNOWN','committed':'CONFIRMED'}[point]
            assert record['action']['status']==expected,(point,record['action']['status'])
            files={f.name:f.read_bytes() for f in core.ledger.artifact_dir.iterdir()}
            server=web.create_server(core=core,chat=PlanChat(),port=0)
            calls=[]
            class CountPlan(PlanChat):
                def reply(self,*args,**kwargs):calls.append(1);return super().reply(*args,**kwargs)
            server.computer.sample.chat_factory=lambda *a,**kw:CountPlan()
            try:
                assert not server.metrics.snapshot()['counters']
                if point!='committed':assert server.computer.queue.snapshot()['paused']
                assert server.metrics.snapshot()['lanes']['chat']['active']==0
                time.sleep(.1);assert not calls
                if point=='prepared':
                    server.computer.queue.set_paused(False);wait(lambda:core.ledger.record(task_id=record['task']['task_id'])['action']['status']=='CONFIRMED')
                    assert len(calls)==1
                else:
                    assert server.computer.sample.run(record['action']['action_id'])==record
                    assert not calls and files=={f.name:f.read_bytes() for f in core.ledger.artifact_dir.iterdir()}
                results.append({'point':point,'exit_code':91,'recovered_action':expected,'no_automatic_replay':True,'metrics_reset':True,
                    'chat_active_at_crash':marker['metrics']['lanes']['chat']['active'],'task_active_at_crash':marker['metrics']['lanes']['task']['active']})
            finally:server.server_close()
    return results


def live_local(rounds=20):
    observations=[]
    with tempfile.TemporaryDirectory(prefix='jarvis-parallel-live-') as temp:
        base=Path(temp);core=fixture(base)
        config=json.loads((ROOT/'config/model-profiles/providers.json').read_text(encoding='utf-8'))
        config.update(default_provider='local',automatic_fallback=False,fallback_order=['local'],providers={'local':config['providers']['local']})
        cfg=base/'providers.json';cfg.write_text(json.dumps(config),encoding='utf-8')
        server=web.create_server(core=core,chat=ChatService(core,cfg),port=0);thread=serve(server)
        payload={'message':'17 加 25 等于多少？只回答计算结果。','provider':'local',
                 'context_note':'此轮验证原始模型答案，直接通过模型处理。'}
        stopped=threading.Event();sampler=None
        try:
            # Read the shared engine's counters without taking ownership.
            from urllib.request import Request,build_opener,ProxyHandler
            opener=build_opener(ProxyHandler({}));main_origin='http://127.0.0.1:18181'
            with opener.open(main_origin+'/',timeout=3) as response:nonce=re.search(r'let NONCE="([^"]+)"',response.read().decode())[1]
            with opener.open(Request(main_origin+'/api/modules',headers={'X-Jarvis-Nonce':nonce}),timeout=3) as response:modules=json.loads(response.read())
            local=next(m['runtime'] for m in modules['modules'] if m['id']=='local-llm');assert local['owned'] and local['state']=='running'
            pids={'temporary_host':os.getpid(),'external_shared_local_model':local['pid']}
            first={name:process_usage(pid) for name,pid in pids.items()};peaks={name:{'working_set_bytes':0,'private_bytes':0} for name in pids}
            resource_samples=[];sample_errors=[];control_samples=[]
            def sample():
                while not stopped.is_set():
                    try:
                        rows={name:process_usage(pid) for name,pid in pids.items()}
                        for name,row in rows.items():
                            assert row['created']==first[name]['created'],'Process identity changed'
                            for key in peaks[name]:peaks[name][key]=max(peaks[name][key],row[key])
                        resource_samples.append(memory_snapshot()['available_bytes'])
                    except Exception as error:sample_errors.append(type(error).__name__);return
                    stopped.wait(.1)
            sampler=threading.Thread(target=sample,daemon=True);sample_start=time.monotonic();sampler.start()
            serial=[];parallel=[];answers=[]
            for _ in range(rounds):
                code,data,ms=request(server,'/api/chat','POST',payload,uuid.uuid4().hex)
                assert code==200 and data['status']=='SUCCEEDED' and data.get('provider')!='builtin';serial.append(ms)
                answers.append({'mode':'serial','text':data['text'],'correct':data['text'].strip().rstrip('。.!')=='42'})
            for _ in range(rounds):
                item=task(server);wait(lambda:server.metrics.snapshot()['lanes']['task']['active']==1)
                with ThreadPoolExecutor(1) as pool:
                    pending=pool.submit(request,server,'/api/chat','POST',payload,uuid.uuid4().hex)
                    while not pending.done():
                        status,_,elapsed=request(server,'/api/resources');assert status==200;control_samples.append(elapsed);time.sleep(.02)
                    code,data,ms=pending.result()
                assert code==200 and data['status']=='SUCCEEDED' and data.get('provider')!='builtin';parallel.append(ms)
                answers.append({'mode':'parallel','text':data['text'],'correct':data['text'].strip().rstrip('。.!')=='42'})
                result=wait(lambda:(d if (d:=detail(server,item))['task']['status']=='SUCCEEDED' else None),seconds=90)
                assert result['report']['verified'] and result['report']['total_files']==2
                observations.append({'chat_ms':round(ms,2),'report_verified':True,'file_count':2,'plan_attempts':len(result['steps'])})
            # Development measurements remain distinct from a target-PC SLA.
            wait(lambda:server.metrics.snapshot()['lanes']['task']['active']==0)
            correct=all(a['correct'] for a in answers)
            stopped.set();sampler.join(2);elapsed=time.monotonic()-sample_start
            assert resource_samples and not sample_errors,sample_errors
            for name,pid in pids.items():
                last=process_usage(pid);assert last['created']==first[name]['created']
                peaks[name]['average_cpu_one_core_percent']=round((last['cpu_seconds']-first[name]['cpu_seconds'])/elapsed*100,2)
            resources={'samples':len(resource_samples),'elapsed_seconds':round(elapsed,3),'process_peaks':peaks,
                'minimum_machine_available_bytes':min(resource_samples),'control_api_during_model_calls':{'samples':len(control_samples),'p50_ms':round(statistics.median(control_samples),2),'max_ms':round(max(control_samples),2)}}
            def latency(values):
                values=sorted(values)
                return {'samples':len(values),'p50_ms':round(values[math.ceil(len(values)*.5)-1],2),'p95_ms':round(values[math.ceil(len(values)*.95)-1],2),'max_ms':round(values[-1],2)}
            return {'status':'passed' if correct else 'partial','latency_and_execution_passed':True,'answer_correctness_passed':correct,
                'answers':answers,'provider':'local','model':config['providers']['local']['model'],'serial_chat_ms':[round(v,2) for v in serial],
                'parallel_chat_ms':[round(v,2) for v in parallel],'median_ratio':round(statistics.median(parallel)/statistics.median(serial),3),
                'rounds_per_mode':rounds,'environment':{'logical_cpus':os.cpu_count(),'physical_memory_bytes':memory_snapshot()['total_bytes'],'inference_threads':4,'context_tokens':2048,'inference_slots':1,'cache':'repeated prompt and warm engine'},
                'latency_comparison':{'serial':latency(serial),'parallel':latency(parallel)},
                'observations':observations,'metrics':server.metrics.snapshot(),'local_model_calls':2*rounds+sum(o['plan_attempts'] for o in observations),'paid_model_calls':0,
                'resources':resources,
                'limits':[f'{rounds} baseline and {rounds} overlap rounds on the development PC, not target hardware certification.','Uses already-running shared single-slot CPU model; no service ownership change.','Task planning may queue behind chat at inference server; no new priority scheduler added.',
                    'Resource samples cover temporary Host and shared engine, excluding transient Worker/browser children; CPU here is one-core units, unlike normalized UI.']}
        finally:
            stopped.set()
            if sampler:sampler.join(2)
            server.shutdown();server.server_close();thread.join(3)


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--live',action='store_true');parser.add_argument('--child',type=Path);parser.add_argument('--point');args=parser.parse_args()
    if args.child:child_crash(args.child,args.point);return
    path=ROOT/'evals/reports/parallel-runtime-probe.json'
    report={'version':__version__,'captured_at':datetime.now(timezone.utc).isoformat(),'status':'incomplete','ui_and_pressure':ui_and_pressure(),'crash_recovery':crash_recovery()}
    path.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    if args.live:report['live_local']=live_local()
    report['status']='partial' if report.get('live_local',{}).get('status')=='partial' else 'passed'
    path.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8');print(json.dumps(report,ensure_ascii=False))


if __name__=='__main__':main()
