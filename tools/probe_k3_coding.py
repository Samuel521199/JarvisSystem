"""One real external Codex multi-file task, held-out LPAC checks and offline rebuild."""
import argparse
import base64
from datetime import datetime, timezone
import io
import json
from pathlib import Path
import sys
import time
import uuid
import zipfile

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'runtime/node-host'),str(ROOT/'adapters/computer-use')]
from jarvis_core import __version__,policy
from jarvis_core.service import CoreService
from jarvis_core.workspace import WorkspaceService
from jarvis_core.conversation_tasks import ConversationTasks
from jarvis_computer.web import ComputerWeb
from jarvis_core.coding_settings import CodingSettings
from jarvis_core.coding_workflow import apply_result
from jarvis_core.evolution.runner import IsolatedRunner
from jarvis_core.network_policy import NetworkPolicy


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--directory',type=Path,required=True)
    args=parser.parse_args();root=args.directory.resolve()
    if root.exists():parser.error('Use a new evidence directory; uncertain requests are not replayed')
    root.mkdir(parents=True);source=root/'project';source.mkdir()
    originals={'report.py':'from grouping import aggregate\ndef transform(data):\n    return aggregate(data)\n',
               'grouping.py':"def aggregate(data):\n    return 'incorrect'\n"}
    for path,content in originals.items():(source/path).write_text(content,encoding='utf-8')
    header='extension | count | bytes'
    public=[{'input':[],'expected':header},{'input':[{'path':'a.txt','size':5},{'path':'b.txt','size':3}],'expected':header+'\ntxt | 2 | 8'}]
    private=[{'input':[{'path':'A.CSV','size':7},{'path':'sub.dir/noext','size':0},{'path':'b.csv','size':9}], 'expected':header+'\n[none] | 1 | 0\ncsv | 2 | 16'},
             {'input':[{'path':'dir/a.md','size':4},{'path':'dir/b.py','size':6},{'path':'C.MD','size':1}], 'expected':header+'\nmd | 2 | 5\npy | 1 | 6'}]
    result={'version':__version__,'observed_at':datetime.now(timezone.utc).isoformat(),'status':'running','project':str(source),
            'scope':'Real Codex account, two selected Python modules, LPAC host-held cases, explicit apply/rollback; no owner data.'}
    def save():(root/'report.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    save();core=CoreService(root/'data');core.initialize(source);workspace=WorkspaceService(core)
    project=workspace.open_project({'path':str(source)});settings=CodingSettings(core)
    settings.write({**settings.read(),'enabled':True,'reasoning':'medium'})
    manager=ComputerWeb(core,None)
    try:
        bridge=ConversationTasks(core,manager);cid=uuid.uuid4().hex
        item=bridge.submit(cid,{'mode':'skill','request_id':'web-'+uuid.uuid4().hex,'prompt':
            '修复两份文件形成文件清单汇总工具。入口 report.py 的 transform(data) 接收 path 和非负整数 size 组成的列表；grouping.py 的 aggregate(data) 负责分组统计并返回结构化分组，report.py 负责排版。扩展名只取文件名最后一个点之后并转小写，没有点用 [none]；目录名中的点不算扩展名。按扩展名字典顺序排列，每行 extension | count | bytes，首行固定 extension | count | bytes；空列表只返回首行。不要遗漏任何条目，不修改输入。两文件都须完成各自职责。',
            'project_id':project['id'],'skill_id':'matt-pocock.tdd','paths':['report.py','grouping.py'],'entrypoint':'report.py',
            'coding':True,'coding_provider':'codex','model':'auto','cases':public,'heldout_cases':private})
        result['task']=item;save();deadline=time.monotonic()+240
        while time.monotonic()<deadline:
            detail=bridge.detail(cid,item['task_id'])
            if detail['task']['status'] not in {'READY','RUNNING','CANCELLING'}:break
            time.sleep(.2)
        result['task_status']=detail;save()
        if detail['action_status']!='CONFIRMED':raise RuntimeError('Task did not confirm; do not replay automatically')
        report=json.loads(bridge.artifact(cid,item['task_id']));value=report['coding']
        result['coding']=value;save()
        assert value['passed'] and value['validation']['independent_checks'] and value['attempts']
        assert all((source/p).read_text()==s for p,s in originals.items())
        result['apply']=apply_result(core,report,'apply')
        assert all((source/p).read_text()==s for p,s in value['candidates'].items())
        result['rollback']=apply_result(core,report,'rollback')
        assert all((source/p).read_text()==s for p,s in originals.items())
        raw=base64.b64decode(value['build']['base64']);assert policy.digest(raw)==value['build']['sha256']
        (root/value['build']['filename']).write_bytes(raw)
        with zipfile.ZipFile(io.BytesIO(raw)) as archive:
            rebuilt={p:archive.read(p).decode('utf-8') for p in value['candidates']}
        NetworkPolicy(core.data_dir).change(True,0)
        outputs,evidence=IsolatedRunner().run_bundle(rebuilt,value['entrypoint'],[c['input'] for c in private],core.assert_running)
        assert outputs==[c['expected'] for c in private]
        result['offline_rebuild']={'passed':True,'lpac':evidence['lpac'],'cases':len(private),'worker':evidence}
        result['status']='passed';save()
        print(json.dumps({'status':result['status'],'report':str(root/'report.json'),'calls':len(value['attempts']),
                          'usage':[a['model'].get('usage') for a in value['attempts']]},ensure_ascii=False))
    except Exception as exc:
        result['status']='failed';result['error']=type(exc).__name__+': '+str(exc);save();raise
    finally:manager.close()

if __name__=='__main__':main()
