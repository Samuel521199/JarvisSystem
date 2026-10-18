"""Bounded mixed-load endurance on this PC, with explicitly simulated pressure."""
import argparse
import hashlib
from contextlib import nullcontext
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import sys
import tempfile
import threading
import time
import uuid
ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'runtime/node-host'),str(ROOT/'adapters/computer-use'),str(ROOT/'tests')]
from jarvis_core import __version__
from jarvis_core.service import CoreService
from jarvis_core.workspace import WorkspaceService
from jarvis_core.conversation_tasks import ConversationTasks
from jarvis_core.dialogue_process import DialogueProcesses
from jarvis_core.resources import ResourceAdmission, MIB, memory_snapshot
from jarvis_computer.web import ComputerWeb
from test_web import FakeChat
from probe_idle_resources import WindowsProcesses

def main():
    p=argparse.ArgumentParser();p.add_argument('--seconds',type=int,default=1200);p.add_argument('--report',type=Path,required=True);a=p.parse_args()
    if not 60<=a.seconds<=3600:p.error('60..3600 seconds')
    if a.report.exists():p.error('Do not overwrite evidence')
    record={'version':__version__,'observed_at':datetime.now(timezone.utc).isoformat(),'status':'running','cycles':[],
        'limits':'This development PC only. Pressure uses injected 8 GiB counters, not real low-memory hardware. Real queue, LPAC workers and supervised foreground processes; model text is a fixture, no paid requests. A bounded 20-minute mixed run is not multi-day reliability.'}
    source_paths=['runtime/node-host/jarvis_core/'+n+'.py' for n in ['coding_workflow','skill_tasks','skill_validation','skills','task_queue','dialogue_process','dialogue_worker','resources','evolution/provider']]
    source_paths+=['adapters/models/provider-native/jarvis_models/'+n+'.py' for n in ['gateway','catalog']]
    hashes=lambda:{n:hashlib.sha256((ROOT/n).read_bytes()).hexdigest() for n in source_paths}
    record['source_sha256']=hashes()
    def save():a.report.write_text(json.dumps(record,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    start=time.monotonic();reader=WindowsProcesses();pool=None;manager=None
    temporary=tempfile.TemporaryDirectory(prefix='jarvis-skill-soak-')
    try:
        with nullcontext(temporary.name) as tmp:
            base=Path(tmp);source=base/'project';source.mkdir();(source/'calc.py').write_text("def transform(data):\n    return 'wrong'\n")
            core=CoreService(base/'data');core.initialize(source);project=WorkspaceService(core).open_project({'path':str(source)})
            cid=uuid.uuid4().hex;config=json.loads((ROOT/'config/model-profiles/providers.json').read_text())
            def open_manager():
                obj=ComputerWeb(core,FakeChat())
                obj.skills.coding_generate=lambda *args:{'status':'SUCCEEDED','text':json.dumps({'code':'def transform(data):\n    return str(sum(data))\n','notes':'soak fixture'})}
                return obj
            manager=open_manager();pool=DialogueProcesses(core);pool._command=[sys._base_executable,'-u',str(ROOT/'tests/dialogue_process_fixture.py'),'hang']
            n=0
            def wait(predicate,seconds=40):
                end=time.monotonic()+seconds
                while time.monotonic()<end:
                    value=predicate()
                    if value:return value
                    time.sleep(.04)
                raise AssertionError('bounded wait expired')
            while time.monotonic()-start<a.seconds:
                n+=1;bridge=ConversationTasks(core,manager);low=[True];clock=[0.0]
                manager.queue.resources=ResourceAdmission(probe=lambda:{'total_bytes':8192*MIB,'available_bytes':(128 if low[0] else 6000)*MIB,'commit_available_bytes':6000*MIB},clock=lambda:clock[0])
                args={'mode':'skill','request_id':'web-'+uuid.uuid4().hex,'prompt':'求和，空表返回0','project_id':project['id'],'skill_id':'matt-pocock.tdd','paths':['calc.py'],'coding':True,'model':'vertex::gemini-3.8-flash','cases':[{'input':[2,4],'expected':'6'},{'input':[],'expected':'0'}]}
                item=bridge.submit(cid,args);manager.queue.set_paused(False)
                wait(lambda:manager.queue.snapshot()['resources']['waiting'])
                assert core.ledger.record(task_id=item['task_id'])['action']['status']=='PREPARED'
                cancel=threading.Event()
                with ThreadPoolExecutor(1) as executor:
                    future=executor.submit(pool.probe,config,'local','synthetic foreground',core.data_dir,core.assert_running,cancel_event=cancel)
                    wait(lambda:pool.snapshot()['active']==1)
                    if n%3==0:
                        bridge.cancel(cid,item['task_id'],{});assert core.ledger.record(task_id=item['task_id'])['action']['status']=='CANCELLED'
                        task_status='CANCELLED'
                    else:
                        low[0]=False;manager.queue.wake.set();wait(lambda:manager.queue.resources.snapshot()['reason']=='resource_recovering')
                        clock[0]=5;manager.queue.wake.set()
                        result=wait(lambda:(r if (r:=bridge.detail(cid,item['task_id']))['task']['status'] not in {'READY','RUNNING','CANCELLING'} else None))
                        assert result['action_status']=='CONFIRMED',result
                        report=json.loads(bridge.artifact(cid,item['task_id']));assert report['coding']['passed'] and report['coding']['validation']['worker']['lpac']
                        task_status='CONFIRMED'
                    assert pool.snapshot()['active']==1
                    cancel.set();reply=future.result(5);assert reply['cancel_requested'] and pool.snapshot()['active']==0
                restarted=False
                if n%5==0:
                    manager.queue.set_paused(True);manager.close();manager=open_manager();assert manager.queue.snapshot()['paused'];restarted=True
                record['cycles'].append({'number':n,'elapsed_seconds':round(time.monotonic()-start,2),'task_status':task_status,'foreground_cancelled':True,'pressure_wait_and_recovery':True,'reopened_paused':restarted,'processes':reader.sample(os.getpid()),'system_memory':memory_snapshot()});save()
                print(json.dumps({'cycle':n,'status':task_status}),flush=True)
                time.sleep(min(20,max(0,a.seconds-(time.monotonic()-start))))
            record['source_unchanged']=record['source_sha256']==hashes()
            record['status']='passed_on_this_machine' if record['source_unchanged'] else 'source_changed_requires_rerun';record['elapsed_seconds']=round(time.monotonic()-start,2)
    except Exception as exc:
        record['status']='failed';record['error']=str(exc);raise
    finally:
        if pool:pool.close()
        if manager:manager.close()
        temporary.cleanup()
        save()
    return 0

if __name__=='__main__':raise SystemExit(main())
