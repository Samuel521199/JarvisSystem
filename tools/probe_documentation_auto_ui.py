"""Actual Edge/HTTP/turn/FIFO/receipts; synthetic model and MCP, no cloud calls."""
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import threading
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'tools'),str(ROOT/'tests'),str(ROOT/'apps/web'),str(ROOT/'runtime/node-host'),str(ROOT/'runtime/worker-host'),str(ROOT/'adapters/computer-use')]
from jarvis_core import __version__
from jarvis_core.service import CoreService
from jarvis_core.extensions import ExtensionCatalog
from jarvis_core.mcp_catalog import McpManager
from jarvis_core.mcp_client import Context7Client, ENDPOINT
from test_mcp_runtime import Protocol
from test_documentation_admission import reply, TEXT, CONFIG
from probe_workspace_ui import SyntheticChat
from server import create_server
from jarvis_computer.browser import DriverJob
import httpx
from playwright.sync_api import sync_playwright, expect


class Chat(SyntheticChat):
    def reply(self,message,**kwargs):
        self.calls+=1
        return {**reply(message),'usage':{},'notice':[],'attempts':[]}


def main():
    paths=['runtime/node-host/jarvis_core/'+n+'.py' for n in ['__init__','intent','chat','turns','documentation_admission','mcp_tasks','task_queue']]
    paths+=['apps/web/dialogue.js','apps/web/conversation_tasks.js','apps/web/server.py','tools/probe_documentation_auto_ui.py']
    hashes=lambda:{p:hashlib.sha256((ROOT/p).read_bytes()).hexdigest() for p in paths}
    before=hashes();checks=[];errors=[]
    output=Path('H:/JarvisData/diagnostics/dialogue/documentation-auto.png');output.parent.mkdir(parents=True,exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='jarvis-doc-auto-ui-') as tmp,patch('jarvis_core.documentation_admission.settings',lambda:dict(CONFIG)):
        base=Path(tmp);sample=base/'sample';sample.mkdir();core=CoreService(base/'data');core.initialize(sample)
        ExtensionCatalog(core).put('1'*32,{'revision':0,'document':{'kind':'mcp','name':'Context7','catalog_id':'context7','config':{'transport':'streamable-http','url':ENDPOINT}}})
        chat=Chat();server=create_server(core=core,chat=chat,port=0);protocol=Protocol(sse=True)
        server.computer.mcp.client_factory=lambda check:Context7Client(check,transport=httpx.MockTransport(protocol))
        thread=threading.Thread(target=server.serve_forever,kwargs={'poll_interval':.02},daemon=True);thread.start()
        try:
            with sync_playwright() as p:
                job=DriverJob(p)
                try:
                    browser=p.chromium.launch(channel='msedge',headless=True,chromium_sandbox=True)
                    page=browser.new_page(viewport={'width':1280,'height':950});page.on('pageerror',lambda e:errors.append(str(e)))
                    page.goto('http://127.0.0.1:'+str(server.server_port))
                    page.wait_for_function('()=>window.Dialogue&&window.Workspace&&!Workspace.isBusy()&&coreReady&&!refreshing')
                    page.wait_for_function('()=>!document.documentElement.hasAttribute("data-brand-cinema")')
                    def send(text):
                        count=page.locator('.message.assistant:not([data-task-control])').count()
                        page.locator('#message').fill(text);page.locator('#send').click()
                        expect(page.locator('.message.assistant:not([data-task-control])')).to_have_count(count+1,timeout=15000)
                        page.wait_for_function('()=>!busy')
                        return page.locator('.message.assistant:not([data-task-control])').last
                    article=send(TEXT)
                    expect(article.locator('.dialogue-intent summary')).to_contain_text('已受理文档任务')
                    expect(article.get_by_role('button',name='准备文档查询草稿')).to_have_count(0)
                    expect(page.locator('.message[data-task-control][data-task-ref]')).to_have_count(1)
                    cid=page.evaluate('Workspace.currentConversation().id')
                    task=page.locator('.message[data-task-control][data-task-ref]').get_attribute('data-task-ref')
                    expect(page.get_by_role('button',name='查看文档结果',exact=True)).to_be_visible(timeout=15000)
                    assert server.conversation_tasks.detail(cid,task)['action_status']=='CONFIRMED'
                    assert page.evaluate('history.filter(x=>x.content.includes("已按当前规则受理只读文档查询")).length')==0
                    checks.append('one ordinary message creates one confirmed query-docs task; independent receipt excluded from model history')
                    page.screenshot(path=str(output));page.evaluate('Workspace.flushConversation()');page.reload()
                    page.wait_for_function('()=>window.Workspace&&!Workspace.isBusy()&&coreReady&&!refreshing')
                    expect(page.locator('.message[data-task-control][data-task-ref]')).to_have_count(1)
                    assert chat.calls==1 and len(server.conversation_tasks.list(cid)['tasks'])==1
                    checks.append('refresh retains original task link without replaying model or MCP')
                    article=send('不要'+TEXT)
                    expect(article.locator('.dialogue-intent summary')).to_contain_text('未自动派发')
                    assert len(server.conversation_tasks.list(cid)['tasks'])==1
                    checks.append('host rejects negated input even when synthetic model incorrectly marks requested')
                    McpManager(core).put_policy({'mcp_id':'context7','scope':'global','mode':'manual','revision':0})
                    article=send(TEXT);article.locator('.dialogue-intent summary').click()
                    expect(article.locator('.dialogue-intent')).to_contain_text('仅允许明确手动使用')
                    article.get_by_role('button',name='准备文档查询草稿',exact=True).click()
                    expect(page.locator('#composer-mode')).to_have_value('mcp');expect(page.locator('#message')).to_have_value('ipcMain.handle 示例')
                    assert len(server.conversation_tasks.list(cid)['tasks'])==1
                    checks.append('manual policy retains editable draft and never submits it')
                    assert not errors,errors
                    calls=sum(x.method=='POST' and json.loads(x.content)['method']=='tools/call' for x in protocol.calls)
                    assert calls==1
                    browser.close()
                finally:job.close()
        finally:server.shutdown();server.server_close();thread.join(3)
    changed=before!=hashes()
    report={'status':'SOURCE_CHANGED' if changed else 'SUCCEEDED','source_version':__version__,'checks':checks,'browser_errors':errors,
            'cloud_calls':0,'mock_model_calls':chat.calls,'mock_mcp_calls':calls,'screenshot':str(output),'source_sha256':before,'source_changed':changed,
            'limits':'Synthetic replies verify host/UI behavior, not semantic accuracy. Separate real Google heldout and live deployment required.'}
    (ROOT/'evals/reports/documentation-auto-ui-2026-10-18.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps({k:v for k,v in report.items() if k!='source_sha256'},ensure_ascii=False))


if __name__=='__main__':main()
