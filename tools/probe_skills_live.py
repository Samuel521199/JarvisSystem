"""Explicit small billable native skill smoke. One route, no automatic replay."""
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import sys
import tempfile
import time
import uuid

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'runtime/node-host'),str(ROOT/'adapters/computer-use')]
from jarvis_core import __version__
from jarvis_core.service import CoreService
from jarvis_core.chat import ChatService
from jarvis_core.workspace import WorkspaceService
from jarvis_core.conversation_tasks import ConversationTasks
from jarvis_computer.web import ComputerWeb
from eval_policy import default_route, report_path, route_name

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--live',action='store_true');parser.add_argument('--route',default=default_route());args=parser.parse_args()
    if not args.live:parser.error('--live required: configured provider calls can incur charges')
    route,sep,model=args.route.partition('::')
    if not sep:parser.error('use provider::model')
    report={'version':__version__,'observed_at':datetime.now(timezone.utc).isoformat(),'route':args.route,'scope':'small synthetic source; verifies loading and delivery, not coding accuracy or improvement percentage'}
    with tempfile.TemporaryDirectory(prefix='jarvis-skill-live-') as tmp:
        root=Path(tmp);project=root/'project';project.mkdir();(project/'calc.py').write_text('def divide(a,b):\n    return a/b\n')
        core=CoreService(root/'data');core.initialize(project);chat=ChatService(core)
        result=chat.reply('用两句话说明排错时如何区分猜测和已验证原因。',provider=route,model=model,skill_context={'explicit':'matt-pocock.diagnosing-bugs'},_route_attempt_limit=1)
        report['chat']={k:result[k] for k in ('status','text','provider','model','usage','billing','history_info','error_category','user_message','output_incomplete') if k in result}
        if result['status']=='SUCCEEDED':
            manager=ComputerWeb(core,chat)
            try:
                workspace=WorkspaceService(core);p=workspace.open_project({'path':str(project)})
                bridge=ConversationTasks(core,manager);cid=uuid.uuid4().hex
                item=bridge.submit(cid,{'mode':'skill','request_id':'web-'+uuid.uuid4().hex,'prompt':'审阅 calc.py，引用行号指出零除数行为及改进建议。不要声称运行测试。','project_id':p['id'],'skill_id':'matt-pocock.code-review','paths':['calc.py'],'model':args.route})
                until=time.monotonic()+125
                while time.monotonic()<until:
                    detail=bridge.detail(cid,item['task_id'])
                    if detail['task']['status'] not in {'READY','RUNNING','CANCELLING'}:break
                    time.sleep(.1)
                report['task']={k:detail[k] for k in ('task','action_status','report','error')}
                if detail['action_status']=='CONFIRMED':
                    artifact=json.loads(bridge.artifact(cid,item['task_id']));path=Path(artifact['output']['path'])
                    report['delivery_matches']=path.read_text(encoding='utf-8')==artifact['text']
                    (ROOT/'artifacts/skills'/(route_name('source-review',args.route)+'.txt')).write_text(artifact['text'],encoding='utf-8')
            finally:manager.close()
    report['status']='passed' if result['status']=='SUCCEEDED' and not result.get('output_incomplete') and report.get('delivery_matches') else 'failed'
    report_path('skills-live',args.route).write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps({'status':report['status'],'chat':result['status'],'task':report.get('task',{}).get('action_status'),'delivery_matches':report.get('delivery_matches')}))
    return 0 if report['status']=='passed' else 1

if __name__=='__main__':raise SystemExit(main())
