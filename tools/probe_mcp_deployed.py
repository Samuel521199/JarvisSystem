"""Use an already running release; add a retained Context7 example, never restart it."""
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import re
import sys
import time
import uuid

import httpx

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'runtime/node-host'),str(ROOT/'adapters/computer-use'),str(ROOT/'runtime/worker-host')]
from jarvis_core import __version__
from jarvis_core.mcp_client import ENDPOINT
from jarvis_computer.browser import DriverJob
from playwright.sync_api import sync_playwright,expect


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--live',action='store_true');parser.add_argument('--verify-existing',action='store_true');args=parser.parse_args()
    if not args.live and not args.verify_existing:parser.error('--live required; saves one connection if absent, one example conversation and one real query')
    origin='http://127.0.0.1:18181'
    path=ROOT/'evals/reports/mcp-runtime-deployment-2026-10-18.json'
    if args.verify_existing:
        record=json.loads(path.read_bytes());cid=record['conversation_id']
    else:
        with httpx.Client(trust_env=False,timeout=20) as client:
            nonce=re.search('nonce="([^"]+)"',client.get(origin).text)[1]
            def api(path,payload=None):
                headers={'X-Jarvis-Nonce':nonce,'Origin':origin}
                response=client.get(origin+path,headers=headers) if payload is None else client.post(origin+path,headers=headers,json=payload)
                response.raise_for_status();return response.json()
            before=api('/api/status');assert before['version']==__version__ and not before['stopped']
            queue=api('/api/resources')['runtime']['queue']
            assert not queue['paused'] and not queue['running'] and not queue['waiting'],'Wait for idle unified deployment'
            item=next(r for r in api('/api/mcp/catalog')['entries'] if r['id']=='context7')
            if not item['registrations']:
                api('/api/extensions/'+uuid.uuid4().hex,{'revision':0,'document':{'kind':'mcp','name':'Context7 文档助手',
                    'catalog_id':'context7','config':{'transport':'streamable-http','url':ENDPOINT}}})
                item=next(r for r in api('/api/mcp/catalog')['entries'] if r['id']=='context7')
            assert item['callable'],'Preserve current policy/configuration; do not silently replace it'
            cid=uuid.uuid4().hex;prompt='Show ipcMain.handle and ipcRenderer.invoke request response examples.'
            def message(role,content,**extra):return dict(role=role,content=content,meta='',short_meta='',attachments_omitted=False,incomplete=False,**extra)
            document={'title':'Context7 文档工具使用示例','project_id':None,'context_note':'','messages':[message('user','查询 Electron 的 IPC 请求与响应示例。')]}
            saved=api('/api/conversations/'+cid,{'revision':0,'document':document})
            task=api('/api/conversation-tasks/'+cid,{'mode':'mcp','request_id':'web-'+uuid.uuid4().hex,'library':'/electron/electron','prompt':prompt})
            until=time.monotonic()+100
            while time.monotonic()<until:
                detail=api('/api/conversation-tasks/'+cid+'/'+task['task_id'])
                if detail['task']['status'] not in {'READY','RUNNING','CANCELLING'}:break
                time.sleep(.3)
            assert detail['action_status']=='CONFIRMED',detail.get('error')
            result=detail['report'];assert result['kind']=='jarvis.mcp-report' and result['checks']['tool_calls']==1 and result['checks']['model_calls']==0
            assert all(x in result['text'] for x in ('ipcMain.handle','ipcRenderer.invoke','https://'))
            document['messages'].append(message('assistant','已从 Context7 取得 Electron 的 IPC 文档和来源链接。点击“查看真实任务”，再点“查看文档结果”阅读。此任务为一次只读工具查询，未调用模型；外部内容仍需核对适用版本。',task_control=True,task_ref=task['task_id']))
            api('/api/conversations/'+cid,{'revision':saved['revision'],'document':document})
            after=api('/api/status');assert after['instance_id']==before['instance_id']
            record={'status':'passed','version':after['version'],'observed_at':datetime.now(timezone.utc).isoformat(),
                'instance_id':after['instance_id'],'conversation_id':cid,'task_id':task['task_id'],'report':result,
                'model_calls':0,'tool_calls':1,'ui_assets':after['ui_assets'],'service_restarted':False}
        record['live_ui']={'status':'pending'}
        path.write_text(json.dumps(record,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    output=ROOT/'artifacts/mcp-runtime';output.mkdir(exist_ok=True,parents=True);errors=[]
    with sync_playwright() as p:
        job=DriverJob(p)
        try:
            browser=p.chromium.launch(channel='msedge',headless=True,chromium_sandbox=True)
            page=browser.new_page(viewport={'width':1440,'height':1000});page.on('pageerror',lambda e:errors.append(str(e)))
            page.goto(origin+'/#chat='+cid)
            expect(page.locator('#send')).to_be_enabled(timeout=15000)
            expect(page.locator('.jarvis-cinema')).not_to_be_visible(timeout=15000)
            page.get_by_role('button',name='查看真实任务',exact=True).click()
            page.get_by_role('button',name='查看文档结果',exact=True).click()
            expect(page.locator('#mcp-result-dialog')).to_contain_text('ipcMain.handle')
            page.screenshot(path=str(output/'live-document-result.png'))
            page.goto(origin+'/settings#mcp')
            expect(page.locator('[data-mcp-id="context7"]')).to_contain_text('可使用 · 按次连接')
            expect(page.locator('#mcp-status')).to_contain_text('1 项可调用')
            page.screenshot(path=str(output/'live-settings.png'),full_page=True)
            assert not errors,errors;browser.close()
        finally:job.close()
    record['live_ui']={'status':'passed','page_errors':errors,'screenshots':['artifacts/mcp-runtime/live-document-result.png','artifacts/mcp-runtime/live-settings.png']}
    (ROOT/'evals/reports/mcp-runtime-deployment-2026-10-18.json').write_text(json.dumps(record,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps({k:v for k,v in record.items() if k not in {'report','ui_assets'}},ensure_ascii=False))


if __name__=='__main__':main()
