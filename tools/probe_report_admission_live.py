"""Real configured Flash dialogue/plan plus LPAC report, in disposable business data."""
import argparse
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import threading
import time
import uuid
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT),str(ROOT/'runtime/node-host'),str(ROOT/'apps/web'),str(ROOT/'adapters/computer-use')]
from jarvis_core import __version__
from jarvis_core.chat import ChatService
from jarvis_core.service import CoreService
from jarvis_core.conversations import ConversationStore
from jarvis_core.report_intents import RULE
from server import create_server
from tools.probe_parallel_runtime import request, wait


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--live',action='store_true');parser.add_argument('--tag',required=True);args=parser.parse_args()
    if not args.live or not args.tag.isalnum():parser.error('--live and alphanumeric --tag required; incurs Google usage')
    destination=ROOT/'evals/reports'/f'report-admission-live-{args.tag}-2026-10-19.json'
    if destination.exists():parser.error('report exists; inspect prior outcome, do not replay')
    paths=['runtime/node-host/jarvis_core/'+x+'.py' for x in ['__init__','report_intents','work_admission','task_revisions','turns','ledger','task_queue','conversation_tasks']]
    paths+=['apps/web/server.py','tools/probe_report_admission_live.py']
    hashes=lambda:{p:hashlib.sha256((ROOT/p).read_bytes()).hexdigest() for p in paths}
    before=hashes();report={'status':'RUNNING','source_version':__version__,'source_sha256':before,'route':'vertex::gemini-3.8-flash','turns':[]}
    def save():destination.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    save()
    with tempfile.TemporaryDirectory(prefix='jarvis-report-live-') as temp:
        root=Path(temp);sample=root/'sample';sample.mkdir();(sample/'a.txt').write_bytes(b'abc')
        sub=sample/'sub';sub.mkdir();(sub/'b.txt').write_bytes(b'12345')
        core=CoreService(root/'data');core.initialize(sample)
        config=json.loads((ROOT/'config/model-profiles/providers.json').read_text(encoding='utf-8'));config['automatic_fallback']=False
        configpath=root/'providers.json';configpath.write_text(json.dumps(config),encoding='utf-8')
        cid=uuid.uuid4().hex
        ConversationStore(core).put(cid,{'revision':0,'document':{'title':'公开合成报告验证','project_id':None,'context_note':'',
            'messages':[{'role':'user','content':'公开合成报告验证','meta':'','short_meta':'','attachments_omitted':False,'incomplete':False}]}})
        server=create_server(core=core,chat=ChatService(core,configpath),port=0)
        thread=threading.Thread(target=server.serve_forever,kwargs={'poll_interval':.02},daemon=True);thread.start()
        server.computer.queue.set_paused(True)
        def turn(message):
            if hashes()!=before:raise RuntimeError('source changed')
            rid=uuid.uuid4().hex;tick=time.monotonic()
            payload={'instance_id':server.instance_id,'conversation_id':cid,'request_id':rid,
                'chat':{'message':message,'provider':'vertex','model':'gemini-3.8-flash','personal_context':{'temporary':False}}}
            status,receipt,_=request(server,'/api/dialogue/turns',method='POST',payload=payload);assert status==202,receipt
            path='/api/dialogue/turns/'+rid+'?conversation_id='+cid+'&instance_id='+server.instance_id
            final=wait(lambda:(r if (r:=request(server,path)[1]).get('finished') else None),seconds=125)
            result=final['result'];report['turns'].append({'request_id':rid,'message':message,'result':result,'elapsed_seconds':round(time.monotonic()-tick,3)});save()
            assert result['status']=='SUCCEEDED',result.get('error')
            return result,payload
        try:
            with patch('jarvis_core.work_admission.settings',return_value={'schema_version':1,'enabled':True,'routes':['vertex::gemini-3.8-flash'],'rule':RULE}):
                first,payload=turn('我很难过，陪我聊聊，顺便把样例报告导出。')
                admitted=first['work_admission'];assert admitted['status']=='submitted',admitted
                second,_=turn('把报告 '+admitted['task_id']+' 的目录改为 sub')
                replacement=second['work_admission'];assert replacement['status']=='submitted',replacement
                assert core.ledger.record(task_id=admitted['task_id'])['task']['status']=='CANCELLED'
                server.computer.queue.set_paused(False)
                wait(lambda:core.ledger.record(task_id=replacement['task_id'])['action']['status']!='PREPARED')
                report['task_status_before_followup']=core.ledger.record(task_id=replacement['task_id'])['task']['status']
                third,_=turn('用一句简短的话鼓励一下正在学习的人。')
                final=wait(lambda:(r if (r:=core.ledger.record(task_id=replacement['task_id']))['action']['status'] in {'CONFIRMED','FAILED','UNKNOWN','CANCELLED'} else None),seconds=125)
                assert final['action']['status']=='CONFIRMED',final['action'].get('error')
                artifact=json.loads(server.conversation_tasks.artifact(cid,replacement['task_id']))
                assert artifact['total_files']==1 and artifact['total_bytes']==5,artifact
                report['artifact']={k:artifact[k] for k in ['total_files','total_bytes','by_type','model','plan']}
                report['worker']=core.last_worker_evidence
                replay=request(server,'/api/dialogue/turns',method='POST',payload=payload)[1]
                assert replay['result']==first
                with core.ledger.connection() as db:report['task_count']=db.execute('SELECT count(*) FROM tasks').fetchone()[0]
                assert report['task_count']==2
                report.update(status='SUCCEEDED',duplicate_replayed_without_new_task=True,source_changed=hashes()!=before,
                    limits='One real mixed report, one pending target revision, and one subsequent chat. Separate finite experiment; not independent semantic annotation or prolonged resource fairness.')
                assert not report['source_changed'];save()
        except Exception as exc:
            report.update(status='FAILED',failure_type=type(exc).__name__,failure=str(exc)[:1000]);save();raise
        finally:server.shutdown();server.server_close();thread.join(3)
    print(json.dumps({k:v for k,v in report.items() if k not in {'source_sha256','turns','worker','artifact'}},ensure_ascii=False))


if __name__=='__main__':main()
