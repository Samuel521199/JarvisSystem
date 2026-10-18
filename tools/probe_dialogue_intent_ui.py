"""Real Edge + supervised reply child + MCP candidate service; synthetic transport."""
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import threading

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT),str(ROOT/'apps/web'),str(ROOT/'runtime/node-host'),str(ROOT/'adapters/computer-use')]
from jarvis_core import __version__
from jarvis_core.chat import ChatService
from jarvis_core.service import CoreService
from jarvis_core.extensions import ExtensionCatalog
from jarvis_core.mcp_client import ENDPOINT
from jarvis_computer.browser import DriverJob
from server import create_server
from playwright.sync_api import sync_playwright,expect

MESSAGE='我有点难过，陪我聊聊，顺便查询 Electron 文档中的 ipcMain.handle 示例。'


def main():
    paths=['runtime/node-host/jarvis_core/'+n+'.py' for n in ['intent','chat','turns','dialogue_worker','mcp_candidates','conversation_tasks']]
    paths+=['apps/web/index.html','apps/web/dialogue.js','apps/web/conversation_tasks.js','apps/web/server.py','tests/dialogue_process_fixture.py','tools/probe_dialogue_intent_ui.py']
    hashes=lambda:{p:hashlib.sha256((ROOT/p).read_bytes()).hexdigest() for p in paths}
    before=hashes();errors=[];checks=[]
    output=Path('H:/JarvisData/diagnostics/dialogue');output.mkdir(parents=True,exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='jarvis-intent-ui-') as tmp:
        base=Path(tmp);sample=base/'sample';sample.mkdir()
        core=CoreService(base/'data');core.initialize(sample)
        config=json.loads((ROOT/'config/model-profiles/providers.json').read_text(encoding='utf-8'))
        config.update(default_provider='local',automatic_fallback=False);config['providers']['local']['enabled']=True
        configpath=base/'providers.json';configpath.write_text(json.dumps(config),encoding='utf-8')
        chat=ChatService(core,configpath);server=create_server(core=core,chat=chat,port=0)
        # A registration is configuration only; the test never invokes MCP.
        ExtensionCatalog(core).put('1'*32,{'revision':0,'document':{'kind':'mcp','name':'Context7','catalog_id':'context7','config':{'transport':'streamable-http','url':ENDPOINT}}})
        def mode(value):chat.dialogue_models._command=[sys._base_executable,'-u',str(ROOT/'tests/dialogue_process_fixture.py'),value]
        thread=threading.Thread(target=server.serve_forever,kwargs={'poll_interval':.02},daemon=True);thread.start()
        try:
            with sync_playwright() as p:
                job=DriverJob(p)
                try:
                    browser=p.chromium.launch(channel='msedge',headless=True,chromium_sandbox=True)
                    page=browser.new_page(viewport={'width':1280,'height':900});page.on('pageerror',lambda e:errors.append(str(e)))
                    origin='http://127.0.0.1:'+str(server.server_port);page.goto(origin)
                    page.wait_for_function('()=>window.Dialogue&&window.Workspace&&!Workspace.isBusy()&&coreReady&&!refreshing')
                    page.wait_for_function('()=>!document.documentElement.hasAttribute("data-brand-cinema")')
                    mode('intent_gateway');page.locator('#message').fill(MESSAGE);page.locator('#send').click()
                    reply=page.locator('.message.assistant:not([data-task-control])').last
                    expect(reply.locator('.bubble')).to_have_text('我在这里陪你。文档查询还没有提交，可以先核对草稿。',timeout=20000)
                    expect(reply.locator('.dialogue-intent summary')).to_contain_text('情感交流 + 任务请求')
                    reply.locator('.dialogue-intent summary').click()
                    expect(reply.locator('.dialogue-intent')).to_contain_text('尚未提交任务')
                    page.wait_for_function('()=>!busy')
                    with core.ledger.connection() as db:assert db.execute('SELECT COUNT(*) FROM tasks').fetchone()[0]==0
                    checks.append('one actual supervised child returns natural text plus two grounded intents; no task created')
                    button=reply.get_by_role('button',name='准备文档查询草稿',exact=True)
                    page.locator('#message').fill('保留这条新输入');button.click()
                    expect(page.locator('#message')).to_have_value('保留这条新输入')
                    page.locator('#message').fill('');button.click()
                    expect(page.locator('#composer-mode')).to_have_value('mcp')
                    expect(page.locator('#mcp-library')).to_have_value('Electron')
                    expect(page.locator('#message')).to_have_value('ipcMain.handle 示例')
                    with core.ledger.connection() as db:assert db.execute('SELECT COUNT(*) FROM tasks').fetchone()[0]==0
                    checks.append('intent button checks actual candidate endpoint; preserves new draft and fills explicit documentation draft without dispatch')
                    page.screenshot(path=str(output/'intent-mixed-draft.png'))
                    page.locator('#message').fill('');page.locator('#composer-mode').select_option('chat')
                    mode('intent_invalid');page.locator('#message').fill('继续聊天');page.locator('#send').click()
                    expect(page.locator('.dialogue-intent summary').last).to_contain_text('暂未识别',timeout=20000)
                    expect(page.locator('.message.assistant .bubble').last).to_contain_text('回复格式未完整确认')
                    assert page.locator('.message.assistant').last.get_attribute('class').find('incomplete')>=0
                    page.wait_for_function('()=>!busy');mode('gateway')
                    page.locator('#message').fill('现在还能聊吗');page.locator('#send').click()
                    expect(page.locator('.message.assistant .bubble').last).to_have_text('isolated gateway reply',timeout=20000)
                    page.wait_for_function('()=>!busy');page.evaluate('Workspace.flushConversation()')
                    page.reload();expect(page.locator('.message.assistant .bubble').last).to_have_text('isolated gateway reply',timeout=10000)
                    expect(page.locator('.message-meta').filter(has_text='意图参考：情感交流 + 任务请求')).to_have_count(1)
                    assert not errors,errors
                    checks.append('invalid structured result is incomplete and cannot auto-save; following plain reply and saved intent summary survive refresh')
                    browser.close()
                finally:job.close()
        finally:server.shutdown();server.server_close();thread.join(3)
    changed=before!=hashes()
    report={'status':'SOURCE_CHANGED' if changed else 'SUCCEEDED','source_version':__version__,'checks':checks,
            'browser_errors':errors,'cloud_calls':0,'mcp_calls':0,'source_sha256':before,'source_changed':changed,
            'screenshot':str(output/'intent-mixed-draft.png'),'limits':'Scripted model output verifies plumbing, not semantic accuracy; full semantic pilot recorded separately.'}
    (ROOT/'evals/reports/dialogue-intent-ui-2026-10-18.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(report,ensure_ascii=False))


if __name__=='__main__':main()
