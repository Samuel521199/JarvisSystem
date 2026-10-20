"""Explicit live probe: one dialogue + a two-role plan, real Context7 research."""
from datetime import datetime, timezone
import argparse
import json
from pathlib import Path
import sys
import tempfile
import time
import uuid

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'tools'),str(ROOT/'tests'),str(ROOT/'runtime/node-host'),
             str(ROOT/'adapters/computer-use'),str(ROOT/'adapters/models/provider-native')]
from probe_parallel_runtime import fixture, web, serve
from jarvis_core import __version__
from jarvis_core.chat import ChatService
from jarvis_core.conversations import ConversationStore
from jarvis_core.extensions import ExtensionCatalog
from jarvis_core.mcp_client import ENDPOINT
from test_conversations import document


def run(output):
    report={'version':__version__,'production_data_modified':False,'synthetic_input':True,
            'automatic_retries':0,'max_expected_cloud_calls':3}
    def save():
        output.parent.mkdir(parents=True,exist_ok=True)
        output.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    with tempfile.TemporaryDirectory(prefix='jarvis-personal-live-') as directory:
        core=fixture(Path(directory));server=web.create_server(core=core,chat=ChatService(core),port=0);thread=serve(server)
        try:
            cid=uuid.uuid4().hex
            message='帮我制定并展示一个可修改的计划：先查询 Python 的 sorted key 文档；然后用协作分析设计按日期和名称稳定排序的方案。先展示计划，我确认后再执行。'
            ConversationStore(core).put(cid,{'revision':0,'document':document(message)})
            ExtensionCatalog(core).put(uuid.uuid4().hex,{'revision':0,'document':{
                'kind':'mcp','name':'Context7','catalog_id':'context7',
                'config':{'transport':'streamable-http','url':ENDPOINT}}})
            route='vertex::gemini-3.1-pro-preview';request_id=uuid.uuid4().hex
            server.dialogue.submit(server.instance_id,cid,request_id,
                {'message':message,'provider':'vertex','model':route.split('::')[1],'history':[],
                 'personal_context':{'temporary':False}})
            end=time.monotonic()+170
            while time.monotonic()<end:
                turn=server.dialogue.view(server.instance_id,cid,request_id)
                if turn['status'] not in {'RUNNING','CANCELLING'}:break
                time.sleep(.2)
            report['dialogue']=turn;save()
            plans=server.assistant_plans.list(cid)['plans']
            if not plans:
                report['status']='no_plan_proposed';save();return report
            row=plans[0]
            report['recognized_steps']=len(row['steps'])
            # Simulate explicit owner review of generated intent and concrete executors.
            ids=[uuid.uuid4().hex for _ in range(2)]
            steps=[
                {'id':ids[0],'title':'查询 Python 稳定排序文档','depends_on':[],'payload':{
                    'mode':'mcp','library':'/python/cpython','prompt':'sorted stability and tuple key for date and name'}},
                {'id':ids[1],'title':'审阅排序方案','depends_on':[ids[0]],'include_results':True,'payload':{
                    'mode':'team','prompt':'根据前序文档，提出按日期和名称稳定排序的简明方案；区分确定语法与未测试假设。',
                    'criteria':['引用前序资料支持的行为','明确尚未测试的边界'],
                    'planner_model':route,'reviewer_model':route,'max_agents':2,'auto_team':False}}]
            row=server.assistant_plans.change(row['id'],{'action':'edit','revision':row['revision'],'steps':steps,
                'policy':{**row['policy'],'max_calls':2,'usd':1,'cny':5,'followup':True}})
            row=server.assistant_plans.change(row['id'],{'action':'start','revision':row['revision']})
            end=time.monotonic()+240
            while time.monotonic()<end:
                server.assistant_plans.tick()
                row=server.assistant_plans.view(row['id'])
                if row['state'] in {'COMPLETE','BLOCKED','PAUSED'}:break
                time.sleep(.25)
            report['plan']=row
            report['status']='passed' if row['state']=='COMPLETE' and row['usage']['calls']==2 else 'not_completed'
            report['captured_at']=datetime.now(timezone.utc).isoformat();save()
            return report
        finally:
            server.shutdown();server.server_close();thread.join(3)


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--live',action='store_true',required=True)
    parser.add_argument('--output',type=Path,required=True);args=parser.parse_args()
    if args.output.exists():parser.error('Preserve earlier evidence; choose a new output filename.')
    value=run(args.output)
    print(json.dumps({k:value[k] for k in ('version','status','recognized_steps') if k in value}))
