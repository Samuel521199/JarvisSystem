"""Small synthetic live smoke test, not a memory framework quality benchmark."""
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import sys
import tempfile
import uuid

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'runtime/node-host'),str(ROOT/'tests')]
from jarvis_core import __version__
from jarvis_core.service import CoreService
from jarvis_core.chat import ChatService
from jarvis_core.conversations import ConversationStore
from jarvis_core.workspace import WorkspaceService
from jarvis_core.semantic_candidates import SemanticCandidates
from jarvis_core.personal_candidates import extract
from test_conversations import document
from eval_policy import default_route


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--live',action='store_true');p.add_argument('--route',default=default_route());p.add_argument('--output',type=Path,required=True)
    args=p.parse_args()
    if not args.live:p.error('Pass --live for at most three real model requests on synthetic text.')
    provider,model=args.route.split('::',1)
    report={'version':__version__,'captured_at':datetime.now(timezone.utc).isoformat(),'route':args.route,
            'scope':'3 synthetic smoke cases, not held-out quality evaluation','owner_data_used':False,'facts_committed':0,'cases':[]}
    cases=[('owner_other','长篇答复读着累，给我的结论请尽量简洁。客户老王喜欢咖啡。',False,{'preference','third_party'}),
           ('fiction_project','游戏里的 NPC 阿明是火系法师。这个项目确定使用 Python。',True,{'fiction','project_fact'}),
           ('hypothetical','假设有人说我喜欢咖啡，那只是例子，不代表我的喜好。',False,set())]
    with tempfile.TemporaryDirectory(prefix='jarvis-semantic-live-') as tmp:
        root=Path(tmp);folder=root/'sample';folder.mkdir();core=CoreService(root/'data');core.initialize(folder)
        chat=ChatService(core);service=SemanticCandidates(core,chat);archives=ConversationStore(core)
        raw_results=[];original_reply=chat.reply
        def capture(*a,**kw):
            result=original_reply(*a,**kw)
            raw_results.append({k:result[k] for k in ('text','output_incomplete','completion_reason') if k in result})
            return result
        chat.reply=capture
        project=WorkspaceService(core).open_project({'path':str(folder)})['id']
        for name,text,use_project,expected in cases:
            cid=uuid.uuid4().hex;doc=document();doc['messages'][0]['content']=text;doc['project_id']=project if use_project else None
            archives.put(cid,{'revision':0,'document':doc})
            result=service.suggest({'source':{'conversation_id':cid,'message_index':0},'project_id':doc['project_id'],
                'provider':provider,'model':model,'reasoning':None,'request_id':uuid.uuid4().hex})
            kinds={i['classification']['kind'] for i in result['candidates']}
            row={'case':name,'source':text,'local_rule_candidates':extract(text),'result':result['result'],
                 'candidates':result['candidates'],'synthetic_raw_result':raw_results[-1], 'expected_categories':sorted(expected),
                 'smoke_pass':result['result']['status']=='SUCCEEDED' and kinds==expected}
            report['cases'].append(row)
            print(json.dumps({'case':name,'status':result['result']['status'],'categories':sorted(kinds),'smoke_pass':row['smoke_pass']},ensure_ascii=False),flush=True)
    report['status']='passed' if all(c['smoke_pass'] for c in report['cases']) else 'needs_review'
    args.output.parent.mkdir(parents=True,exist_ok=True);args.output.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    return 0 if report['status']=='passed' else 1


if __name__=='__main__':raise SystemExit(main())
