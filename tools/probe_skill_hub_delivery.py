"""One explicit paid new-workflow delivery in an isolated temporary project."""
import argparse
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
    p=argparse.ArgumentParser();p.add_argument('--live',action='store_true');p.add_argument('--route',default=default_route());a=p.parse_args()
    if not a.live:p.error('--live required: one configured model call')
    with tempfile.TemporaryDirectory(prefix='jarvis-hub-delivery-') as tmp:
        root=Path(tmp);source=root/'project';source.mkdir();core=CoreService(root/'data');core.initialize(source)
        project=WorkspaceService(core).open_project({'path':str(source)});chat=ChatService(core);manager=ComputerWeb(core,chat)
        try:
            bridge=ConversationTasks(core,manager);cid=uuid.uuid4().hex
            item=bridge.submit(cid,{'mode':'skill','request_id':'web-'+uuid.uuid4().hex,'project_id':project['id'],
                'skill_id':'matt-pocock.to-spec','paths':[],'model':a.route,
                'prompt':'把需求整理成规格和任务：一个离线备忘录，能新建、编辑和删除，重启后保留。只有三天，不做账号和同步。输出不超过 500 字。'})
            until=time.monotonic()+125
            while time.monotonic()<until:
                detail=bridge.detail(cid,item['task_id'])
                if detail['task']['status'] not in {'READY','RUNNING','CANCELLING'}:break
                time.sleep(.1)
            if detail['action_status']!='CONFIRMED':
                report_path('skill-hub-delivery',a.route).write_text(json.dumps({'version':__version__,'route':a.route,'status':'failed','isolated_data':True,'detail':detail},ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
                raise RuntimeError('Delivery incomplete; failure evidence saved, no automatic replay')
            report=json.loads(bridge.artifact(cid,item['task_id']))
            assert report['source_references']==[]
            assert Path(report['output']['path']).read_text(encoding='utf-8')==report['text']
            assert not report['checks']['code_executed']
            artifact=ROOT/'artifacts/skills'/(route_name('planning-report',a.route)+'.txt')
            artifact.write_text(report['text'],encoding='utf-8')
            evidence={'version':__version__,'route':a.route,'status':'passed','paid_model_calls':1,'isolated_data':True,'delivery_bytes_match':True,'artifact':str(artifact),'report':report}
            report_path('skill-hub-delivery',a.route).write_text(json.dumps(evidence,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
            print(json.dumps({'status':'passed','action':'CONFIRMED','source_files':0}))
        finally:manager.close()

if __name__=='__main__':main()
