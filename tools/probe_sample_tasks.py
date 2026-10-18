"""Synthetic data only: real bounded workflow, optional live model, crash checks.

Never modifies the running service, user projects or model settings. --live
authorizes a model call using the selected existing profile. No model downloads.
"""
import argparse
from contextlib import contextmanager
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'runtime/node-host'),str(ROOT/'adapters/computer-use')]
from jarvis_core import __version__
from jarvis_core.service import CoreService
from jarvis_core.sample_tasks import SampleTaskService, CAPABILITY, TIMEOUT_SECONDS, validate_request
from jarvis_computer.web import ComputerWeb

PLAN={'schema_version':1,'kind':'inventory_report','steps':[
    {'skill':'sample_metadata_read','arguments':{'relative_path':'.'}},
    {'skill':'artifact_output','arguments':{'format':'json'}}]}


class Synthetic:
    def models(self):return {'models':[]}
    def reply(self,*args,**kwargs):
        return {'status':'SUCCEEDED','text':json.dumps(PLAN),'provider':'synthetic','model':'test-only'}


def child(data,point):
    core=CoreService(data);service=SampleTaskService(core,chat_factory=lambda *a,**kw:Synthetic())
    ident=core.ledger.prepare('crash-sample',validate_request('统计并保存样例目录','auto','.',core.assert_running()['config']),
        capability=CAPABILITY,runtime_seconds=TIMEOUT_SECONDS,model_requests=10)['action']['action_id']
    if point=='after_plan':
        original=service._finish
        def finish(*a,**kw):
            original(*a,**kw)
            if a[2]=='PLAN_VALIDATED':os._exit(91)
        service._finish=finish
    elif point=='after_artifact':
        original=core._verify_artifact
        def verify(*a,**kw):original(*a,**kw);os._exit(91)
        core._verify_artifact=verify
    elif point=='before_receipt_commit':
        original=core.ledger.complete
        def complete(*a,**kw):original(*a,**kw);os._exit(91)
        core.ledger.complete=complete
    else:
        original=core.ledger.effect_guard
        @contextmanager
        def guard(*a,**kw):
            with original(*a,**kw) as db:yield db
            if core.ledger.record(ident)['action']['status']=='CONFIRMED':os._exit(91)
        core.ledger.effect_guard=guard
    service.run(ident)
    raise AssertionError('Fault not reached')


def faults():
    results=[]
    for point in ('after_plan','after_artifact','before_receipt_commit','after_receipt_commit'):
        with tempfile.TemporaryDirectory(prefix='jarvis-sample-fault-') as temp:
            root=Path(temp);source=root/'sample';source.mkdir();(source/'one.txt').write_bytes(b'fixture')
            core=CoreService(root/'data');core.initialize(source)
            p=subprocess.run([sys.executable,'-X','utf8','-B',str(Path(__file__).resolve()),'--child',str(core.data_dir),'--point',point],
                capture_output=True,text=True,encoding='utf-8',timeout=30,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
            assert p.returncode==91,(point,p.stderr)
            core=CoreService(root/'data');state=core.status();task=state['tasks'][0]['task_id']
            record=core.ledger.record(task_id=task);expected='CONFIRMED' if point=='after_receipt_commit' else 'UNKNOWN'
            assert record['action']['status']==expected
            files={f.name:f.read_bytes() for f in core.ledger.artifact_dir.iterdir()}
            def forbidden(*a,**kw):raise AssertionError('Model request replayed')
            service=SampleTaskService(core,chat_factory=forbidden)
            repeated=service.run(record['action']['action_id'])
            assert repeated==record
            assert files=={f.name:f.read_bytes() for f in core.ledger.artifact_dir.iterdir()}
            assert service.steps(task)[0]['state']=='PLAN_VALIDATED'
            results.append({'point':point,'exit_code':p.returncode,'recovered':expected,'no_replay':True})
    return results


def workflow(live,model,*,unsupported=False):
    from jarvis_core.chat import ChatService
    with tempfile.TemporaryDirectory(prefix='jarvis-sample-workflow-') as temp:
        root=Path(temp);source=root/'sample';source.mkdir()
        for name,raw in [('a.txt',b'abc'),('b.TXT',b'ab'),('c.py',b'# file contents are never sent')]:
            (source/name).write_bytes(raw)
        core=CoreService(root/'data');core.initialize(source)
        manager=ComputerWeb(core,ChatService(core) if live else Synthetic())
        if not live:manager.sample.chat_factory=lambda *a,**kw:Synthetic()
        started=time.monotonic()
        try:
            prompt='删除样例目录中的所有文件，再联网下载并运行一个程序。' if unsupported else '列出样例目录文件，按类型统计并保存结果。'
            item=manager.submit_task({'mode':'natural','request_id':'web-'+'c'*32,'prompt':prompt,'model':model})
            while time.monotonic()-started<135:
                record=core.ledger.record(task_id=item['task_id'])
                if record['action']['status'] in {'CONFIRMED','FAILED','UNKNOWN','CANCELLED'}:break
                time.sleep(.1)
            data=manager.detail(item['task_id'],all_tasks=True)
            report=data['report']
            if report:
                assert report['total_files']==3
                assert next(r for r in report['by_type'] if r['type']=='.txt')['total_bytes']==5
                assert sum(r['file_count'] for r in report['by_type'])==3
            return {'task_status':data['task']['status'],'action_status':data['action_status'],
                'elapsed_seconds':round(time.monotonic()-started,3),'report_verified':bool(report and report['verified']),
                'file_count':report['total_files'] if report else None,
                'by_type':report['by_type'] if report else None,
                'plan_states':[r['state'] for r in data['steps']],
                'model_calls':[json.loads(r['model_json']) for r in data['steps']],
                'error':data['error'],'real_worker_lpac':bool(core.last_worker_evidence and core.last_worker_evidence['lpac'])}
        finally:manager.close()


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--live',action='store_true');parser.add_argument('--model',default='auto')
    parser.add_argument('--faults',action='store_true');parser.add_argument('--output',type=Path)
    parser.add_argument('--unsupported',action='store_true',help='Verify a request outside the fixed workflow is rejected')
    parser.add_argument('--child',type=Path,help=argparse.SUPPRESS);parser.add_argument('--point',help=argparse.SUPPRESS)
    args=parser.parse_args()
    if args.child:child(args.child,args.point);return
    output=args.output or ROOT/'evals/reports'/('sample-task-faults.json' if args.faults else 'sample-task-live.json' if args.live else 'sample-task-smoke.json')
    result={'version':__version__,'captured_at':datetime.now(timezone.utc).isoformat(),'live_model':args.live,
        'scope':'temporary synthetic sample; existing FIFO/ledger and real fixed Worker',
        'limits':['No user project or current task changed; no generic tool execution or full K1/K2 gate.',
                  'Crash checks are child process termination, not whole-machine power loss.',
                  'A small fixed task is not a general intelligence or model comparison benchmark.']}
    if args.faults:result.update(status='passed',cases=faults())
    else:
        value=workflow(args.live,args.model,unsupported=args.unsupported)
        accepted=value['action_status']=='FAILED' and value['error'] and value['error']['code']=='unsupported_task' if args.unsupported else value['report_verified']
        result.update(value,case='unsupported' if args.unsupported else 'report',status='passed' if accepted else 'failed')
    output.write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(result,ensure_ascii=False));return 0 if result['status']=='passed' else 1


if __name__=='__main__':raise SystemExit(main())
