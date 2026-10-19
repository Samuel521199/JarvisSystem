"""Use the existing growth lane to deliver this K2 audit's actual evidence inventory.

The export recipe has a complete Host oracle. This proves bounded delivery/reuse/
rollback for a real audit need, not autonomous invention of an unknown algorithm.
"""
import argparse
from datetime import datetime,timezone
import hashlib
import json
from pathlib import Path
import shutil
import sys
import time
import uuid

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'runtime/node-host'),str(ROOT/'adapters/computer-use'),str(ROOT/'tools')]
from jarvis_core import __version__
from jarvis_core.chat import ChatService
from jarvis_core.conversations import ConversationStore
from jarvis_core.conversation_tasks import ConversationTasks
from jarvis_core.evolution import EvolutionManager
from jarvis_core.evolution.demand import ConversationGrowth
from jarvis_core.persona import PersonaStore
from jarvis_core.service import CoreService
from jarvis_computer.web import ComputerWeb
from k2_state_fingerprint import fingerprint


def uid():return uuid.uuid4().hex


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--root',type=Path,required=True);args=parser.parse_args()
    args.root.mkdir(parents=True,exist_ok=False);source=args.root/'evidence';source.mkdir()
    names=['k2-regression-r2.json','k2-personal-answers-r1.json','k2-contention-r1.json','k2-task-faults-r1.json','k2-deployment-r1.json']
    for name in names:shutil.copyfile(Path('H:/JarvisData/diagnostics')/name,source/name)
    core=CoreService(args.root/'data');core.initialize(source)
    chat=ChatService(core);tasks=ComputerWeb(core,chat);bridge=ConversationTasks(core,tasks)
    manager=EvolutionManager(core,monitor=False);growth=ConversationGrowth(core,manager,bridge)
    cid=uid();archive=ConversationStore(core)
    command='保存接续：K2验收=已经完成回归与故障核对｜接下来阅读证据清单'
    archive.put(cid,{'revision':0,'document':{'title':'K2验收资料清单','project_id':None,'context_note':'','messages':[
        {'role':'user','content':command,'meta':'','short_meta':'','attachments_omitted':False,'incomplete':False,'personal_control':True}]}})
    personal={'temporary':False,'source':{'conversation_id':cid,'message_index':0}}
    assert chat.reply(command,personal_context=personal,memory_context={'enabled':True,'project_id':None})['status']=='SUCCEEDED'
    assert chat.reply('记住：验收阅读=先看结果再看明细',personal_context={'temporary':False},memory_context={'enabled':True,'project_id':None})['status']=='SUCCEEDED'
    PersonaStore(core).change('profile',{'preferred_name':'测试主人','style':'严谨','relationship':'伙伴'},request_id=uid(),revision=0)
    report={'version':__version__,'captured_at':datetime.now(timezone.utc).isoformat(),'status':'running','demand':'Deliver a TSV index of the actual K2 acceptance evidence for review.',
            'cases_frozen':names,'baseline':'No active export package; a successful JSON directory report alone is not a TSV deliverable.',
            'steps':[],'source_sha256':{p.relative_to(ROOT).as_posix():hashlib.sha256(p.read_bytes()).hexdigest() for p in (ROOT/'runtime/node-host/jarvis_core/evolution').glob('*.py')},
            'limits':['Isolated personal state; actual K2 evidence files are the input. Does not modify production personal stores.',
                      'Known export recipe and independent complete Host oracle; no claim of novel general programming or owner satisfaction.']}
    def save():(args.root/'report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    def wait(job):
        end=time.monotonic()+180
        while manager.busy and time.monotonic()<end:time.sleep(.05)
        if manager.busy:manager.cancel(job['id']);raise RuntimeError('Growth deadline reached')
        row=manager.store.job(job['id']);report['steps'].append(row);save();assert row['status']=='SUCCEEDED',row.get('error')
        return row
    try:
        item=bridge.submit(cid,{'request_id':'web-'+uid(),'prompt':'列出样例目录文件，按类型统计并保存 JSON。','model':'vertex::gemini-3.8-flash'})
        end=time.monotonic()+120
        while time.monotonic()<end:
            row=bridge.detail(cid,item['task_id'])
            if row['task']['status'] not in {'READY','RUNNING','CANCELLING'}:break
            time.sleep(.05)
        assert row['task']['status']=='SUCCEEDED' and row['report']['verified'] and row['report']['total_files']==len(names),row
        report['source_task']=row;report['personal_before']=fingerprint(core.data_dir,include_evolution=False)
        first=growth.propose(cid,{'request_id':uid(),'prompt':'导出 CSV'});assert first['proposal']['decision']=='create'
        wait(growth.start(cid,first['id'],{}))
        second=growth.propose(cid,{'request_id':uid(),'prompt':'把本会话最近的目录报告导出为 TSV'});assert second['proposal']['decision']=='upgrade'
        upgraded=wait(growth.start(cid,second['id'],{}));raw,fmt=growth.artifact(cid,second['id'])
        assert fmt=='tsv' and all(name.encode() in raw for name in names)
        (args.root/'k2-evidence-inventory.tsv').write_bytes(raw)
        third=growth.propose(cid,{'request_id':uid(),'prompt':'导出 TSV'});assert third['proposal']['decision']=='reuse'
        reused=wait(growth.start(cid,third['id'],{}));assert not reused['attempts']
        wait(manager.submit({'action':'rollback','request_id':'k2-rollback-'+uid()}))
        restored=wait(manager.submit({'action':'execute','request_id':'k2-after-rollback-'+uid(),'input':first['request']['input']}))
        report['personal_after']=fingerprint(core.data_dir,include_evolution=False)
        assert report['personal_before']==report['personal_after']
        report.update(status='passed',personal_state_preserved=True,delivered_rows=len(names),repeat_coding_calls=0,
            benefit=upgraded['result']['benefit'],coding_calls=sum(len(step['attempts']) for step in report['steps']),
            deliverable='k2-evidence-inventory.tsv',rollback_preserved_old_capability=True)
        print(json.dumps({k:report[k] for k in ('status','coding_calls','delivered_rows','personal_state_preserved','rollback_preserved_old_capability')},ensure_ascii=False))
    except Exception as error:report.update(status='failed',error=repr(error));raise
    finally:manager.close();tasks.close();save()


if __name__=='__main__':main()
