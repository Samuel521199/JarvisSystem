"""Explicit live Context7 probes through the real task queue; no model calls."""
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import sys
import tempfile
import time
import uuid

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT/'runtime/node-host'),str(ROOT/'adapters/computer-use')]
from jarvis_core import __version__
from jarvis_core.mcp_client import ENDPOINT
from jarvis_core.service import CoreService
from jarvis_core.extensions import ExtensionCatalog
from jarvis_core.conversation_tasks import ConversationTasks
from jarvis_computer.web import ComputerWeb


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--live',action='store_true');args=parser.parse_args()
    if not args.live:parser.error('--live required: sends two public documentation queries')
    records=[]
    class NoModels:
        def models(self):return {'models':[]}
    with tempfile.TemporaryDirectory(prefix='jarvis-mcp-live-') as tmp:
        root=Path(tmp);source=root/'source';source.mkdir();core=CoreService(root/'data');core.initialize(source)
        ExtensionCatalog(core).put(uuid.uuid4().hex,{'revision':0,'document':{'kind':'mcp','name':'Context7 文档助手',
            'catalog_id':'context7','config':{'transport':'streamable-http','url':ENDPOINT}}})
        web=ComputerWeb(core,NoModels());tasks=ConversationTasks(core,web)
        try:
            for library in ('Electron','/electron/electron'):
                cid=uuid.uuid4().hex
                task=tasks.submit(cid,{'mode':'mcp','request_id':'web-'+uuid.uuid4().hex,'library':library,
                    'prompt':'Show ipcMain.handle and ipcRenderer.invoke request response examples.'})
                until=time.monotonic()+100
                while time.monotonic()<until:
                    detail=tasks.detail(cid,task['task_id'])
                    if detail['task']['status'] not in {'READY','RUNNING','CANCELLING'}:break
                    time.sleep(.2)
                records.append({'library':library,'task_id':task['task_id'],'status':detail['action_status'],
                    'error':detail.get('error'),'report':detail.get('report')})
                print(library,detail['action_status'],detail.get('error'),flush=True)
                if detail['action_status']!='CONFIRMED':break
        finally:web.close()
    passed=len(records)==2 and all(r['status']=='CONFIRMED' for r in records)
    if passed:
        passed='/electron/electron' in records[0]['report']['candidates'] and all(x in records[1]['report']['text'] for x in ('ipcMain.handle','ipcRenderer.invoke','https://'))
    report={'version':__version__,'observed_at':datetime.now(timezone.utc).isoformat(),'status':'passed' if passed else 'needs_review',
            'scope':'public Context7 read-only documentation via actual shared queue, handshake/list/call/receipt; availability at observed time only',
            'model_calls':0,'records':records}
    (ROOT/'evals/reports/mcp-runtime-live-2026-10-18.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    return 0 if passed else 1


if __name__=='__main__':raise SystemExit(main())
