"""Explicit live opt-in: one Context7 query and at most one coding model call."""
import argparse
import json
from pathlib import Path
import sys
import time
import uuid

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'tests'),str(ROOT/'runtime/node-host'),str(ROOT/'adapters/models/provider-native'),str(ROOT/'adapters/computer-use')]
from test_ranking_modules import RankingModuleTests
from test_conversations import document
from test_web import FakeChat
from jarvis_core.conversations import ConversationStore
from jarvis_core.conversation_tasks import ConversationTasks
from jarvis_core.extensions import ExtensionCatalog
from jarvis_core.mcp_client import ENDPOINT
from jarvis_core.evolution.learning_loop import LearningLoop
from jarvis_core.dialogue_process import DialogueProcesses
from jarvis_core.evolution.provider import default_route
from jarvis_computer.web import ComputerWeb


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--live',action='store_true',required=True)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    if args.output.exists():parser.error('Preserve previous evidence; choose a new output path.')
    report={'version':'0.1.88','max_model_calls':1,'synthetic_goal':True,'production_data_used':False,'automatic_retries':0}
    fixture=RankingModuleTests();fixture.setUp()
    def save():args.output.parent.mkdir(parents=True,exist_ok=True);args.output.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    try:
        core=fixture.core;cid=uuid.uuid4().hex
        ConversationStore(core).put(cid,{'revision':0,'document':document()})
        computer=ComputerWeb(core,FakeChat());fixture.addCleanup(computer.close)
        tasks=ConversationTasks(core,computer)
        ExtensionCatalog(core).put(uuid.uuid4().hex,{'revision':0,'document':{
            'kind':'mcp','name':'Context7','catalog_id':'context7','config':{'transport':'streamable-http','url':ENDPOINT}}})
        loop=LearningLoop(fixture.manager,tasks);lid=uuid.uuid4().hex
        loop.create(dict(id=lid,goal='如何使用 Python sorted 的 key 元组优先按关键词覆盖率降序，再按原分数降序、路径和行号稳定排序？用于改善多词资料检索。',conversation_id=cid))
        loop.research(lid,'/python/cpython')
        end=time.monotonic()+100
        while time.monotonic()<end:
            row=loop.view(lid);receipt=row.get('research_receipt')
            if receipt and receipt['action_status'] in ('CONFIRMED','FAILED','UNKNOWN','CANCELLED'):break
            time.sleep(.1)
        report['research_status']=receipt['action_status'] if receipt else 'MISSING'
        save()
        if report['research_status']!='CONFIRMED':
            report['status']='research_not_confirmed';return
        row=loop.collect(lid)
        report['evidence']={k:row['evidence'][k] for k in ('source','digest','artifact','trust')}
        loop.review(lid,'仅将 Python 排序文档作为语法参考；不改变已有检索独立测试、受限语法与来源权限。')
        models=DialogueProcesses(core,capacity=1);fixture.addCleanup(models.close)
        fixture.service.model_calls=models
        loop.start(lid,dict(target='ranking',model=default_route(),domain='',policy_revision=0))
        end=time.monotonic()+150
        while fixture.manager.busy and time.monotonic()<end:time.sleep(.1)
        row=loop.view(lid);report['outcome']=row.get('outcome');save()
        if row.get('outcome',{}).get('status')!='SUCCEEDED':
            report['status']='candidate_not_confirmed';return
        result=row['outcome']['result']
        if not result['eligible']:report['status']='candidate_rejected';return
        version=result['candidate_id']
        fixture.put();fixture.action('trial',version);fixture.observe();fixture.action('confirm',version)
        fixture.service.recover()
        assert fixture.view()[1]['ranking']['used']==version
        loop.feedback(lid,True,'合成多词查询的独立检查和实际检索试用通过；不代表长期个人体验。')
        loop.withdraw(lid)
        assert fixture.service.snapshot()['selection']['active'] is None
        assert loop.read(lid)['state']=='WITHDRAWN'
        report.update(status='passed',trial_and_confirmation=True,exact_rollback=True,
                      actual_model_calls=models.snapshot()['completed'])
    except Exception as exc:
        report.update(status='failed',error_type=type(exc).__name__,error_code=getattr(exc,'code',None))
        raise
    finally:
        save();fixture.doCleanups()
        print(json.dumps({k:report.get(k) for k in ('status','research_status','actual_model_calls','trial_and_confirmation','exact_rollback')},ensure_ascii=False))


if __name__=='__main__':main()
