"""Reload, host takeover and retrieval in real Edge with a synthetic held model."""
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import threading
import time

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT),str(ROOT/'apps/web'),str(ROOT/'runtime/node-host'),str(ROOT/'adapters/computer-use')]
from jarvis_core import __version__
from tools.probe_workspace_ui import SyntheticChat
from tools.probe_parallel_runtime import fixture,wait,request
from jarvis_computer.browser import DriverJob
from server import create_server
from playwright.sync_api import sync_playwright,expect


def main():
    output=Path('H:/JarvisData/diagnostics/dialogue');output.mkdir(parents=True,exist_ok=True)
    release,entered=threading.Event(),threading.Event();calls=[];errors=[];checks=[]
    class HeldChat(SyntheticChat):
        def reply(self,message,**kwargs):
            calls.append(message);entered.set();release.wait(30)
            return dict(status='SUCCEEDED',text='原回复：'+message,provider='local',model='offline-fixture',usage={},notice=[])
    with tempfile.TemporaryDirectory(prefix='jarvis-dialogue-recovery-') as directory:
        core=fixture(Path(directory));server=create_server(core=core,chat=HeldChat(),port=0)
        def serve(server):
            thread=threading.Thread(target=server.serve_forever,kwargs={'poll_interval':.02},daemon=True);thread.start();return thread
        thread=serve(server)
        try:
            with sync_playwright() as p:
                driver=DriverJob(p)
                try:
                    browser=p.chromium.launch(channel='msedge',headless=True,chromium_sandbox=True)
                    page=browser.new_page(viewport={'width':1280,'height':900});page.on('pageerror',lambda e:errors.append(str(e)))
                    page.on('dialog',lambda dialog:dialog.accept())
                    page.goto('http://127.0.0.1:'+str(server.server_port)+'/')
                    def ready():
                        page.wait_for_function('()=>Boolean(window.Dialogue&&window.Workspace&&!Workspace.isBusy()&&coreReady&&!refreshing)')
                        page.wait_for_function('()=>!document.documentElement.hasAttribute("data-brand-cinema")',timeout=10000)
                    ready()
                    def send(text):page.locator('#message').fill(text);page.locator('#send').click()
                    send('刷新后取回这条回复');assert entered.wait(3)
                    conv=page.evaluate('Workspace.currentConversation().id')
                    ident=page.locator('.user[data-reply-ref]').last.get_attribute('data-reply-ref')
                    assert server.dialogue.recover(conv,ident)['durable']
                    page.reload();ready()
                    expect(page.locator('#dialogue-recovery')).to_contain_text('仍在处理',timeout=10000)
                    page.locator('#message').fill('刷新后继续编辑的草稿')
                    release.set();expect(page.get_by_role('button',name='取回回复',exact=True)).to_be_visible(timeout=10000)
                    page.screenshot(path=str(output/'recovery-ready.png'))
                    page.get_by_role('button',name='取回回复',exact=True).click()
                    expect(page.locator('.assistant[data-reply-ref]')).to_have_count(1)
                    expect(page.locator('#message')).to_have_value('刷新后继续编辑的草稿')
                    assert page.evaluate('history.length')==2
                    page.evaluate('Workspace.flushConversation()')
                    page.reload();ready();expect(page.locator('.assistant[data-reply-ref]')).to_have_count(1)
                    assert page.evaluate('history.length')==2
                    assert calls==['刷新后取回这条回复']
                    checks.append('Refresh reconnects to the original in-flight receipt; explicit retrieval preserves draft/context, archives reply_ref and avoids duplicate after another refresh')
                    # Same data directory, a new Host owner, and a deliberately late old reply.
                    release.clear();entered.clear();send('服务中断时不重做');assert entered.wait(3)
                    ident=page.locator('.user[data-reply-ref]').last.get_attribute('data-reply-ref')
                    original=server;port=server.server_port
                    server.shutdown();server.server_close();thread.join(3)
                    server=create_server(core=core,chat=HeldChat(),port=port);thread=serve(server)
                    page.reload();ready()
                    expect(page.locator('#dialogue-recovery')).to_contain_text('结果未确认',timeout=10000)
                    release.set();wait(lambda:original.chat_requests.active==0)
                    assert server.dialogue.recover(conv,ident)['status']=='UNKNOWN'
                    assert calls==['刷新后取回这条回复','服务中断时不重做']
                    assert page.locator('.assistant .bubble').filter(has_text='原回复：服务中断时不重做').count()==0
                    page.screenshot(path=str(output/'recovery-unknown.png'))
                    checks.append('Host takeover marks unfinished reply UNKNOWN; late old worker cannot overwrite it; no automatic model replay')
                    # Scope and nonce are required even though this is a read-only recovery API.
                    import http.client
                    conn=http.client.HTTPConnection('127.0.0.1',port,timeout=3)
                    conn.request('GET','/api/dialogue/recover/'+ident+'?conversation_id='+conv)
                    response=conn.getresponse();assert response.status==403;response.read();conn.close()
                    code,_,_=request(server,'/api/dialogue/recover/'+ident+'?conversation_id='+'f'*32)
                    assert code==404
                    checks.append('Recovery requires nonce and correct conversation scope')
                    # Temporary inputs remain outside the persistent journal and archive.
                    with server.conversations.connection() as db:before=db.execute('SELECT count(*) FROM dialogue_receipts').fetchone()[0]
                    page.locator('#conversation-menu').evaluate('e=>e.open=true');page.locator('#conversation-temporary').click()
                    send('临时内容不留恢复正文')
                    expect(page.locator('.assistant[data-reply-ref]')).to_have_count(1,timeout=10000)
                    with server.conversations.connection() as db:assert db.execute('SELECT count(*) FROM dialogue_receipts').fetchone()[0]==before
                    page.reload();ready();expect(page.locator('#dialogue-recovery')).to_be_hidden()
                    checks.append('Temporary conversation creates no persistent receipt; refresh does not recover its private response')
                    assert not errors,errors;browser.close()
                finally:driver.close()
        finally:release.set();server.shutdown();server.server_close();thread.join(3)
    paths=['runtime/node-host/jarvis_core/'+n for n in ['turns.py','dialogue_journal.py','conversations.py']]
    paths+=['apps/web/'+n for n in ['server.py','dialogue_routes.py','dialogue.js','conversations.js','workspace.js','index.html']]
    report=dict(status='SUCCEEDED',source_version=__version__,checks=checks,browser_errors=errors,cloud_calls=0,
        screenshots=[str(output/'recovery-ready.png'),str(output/'recovery-unknown.png')],
        limits='Synthetic held model; real browser, SQLite and Host owner replacement. Dedicated unit test exits a child process after durable admission. No separate Dialogue process or semantic intent recognition.',
        source_sha256={p:hashlib.sha256((ROOT/p).read_bytes()).hexdigest() for p in paths})
    (ROOT/'evals/reports/dialogue-recovery-ui-2026-10-18.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(report,ensure_ascii=False))


if __name__=='__main__':main()
