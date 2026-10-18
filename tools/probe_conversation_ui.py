"""Real Edge/HTTP/SQLite archive and compact composer; synthetic replies only."""
from datetime import datetime, timezone
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import threading

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'runtime/node-host'),str(ROOT/'adapters/computer-use'),str(ROOT/'tools')]
from jarvis_core import __version__
from jarvis_core.service import CoreService
from jarvis_computer.browser import DriverJob
from playwright.sync_api import sync_playwright, expect
from probe_workspace_ui import SyntheticChat


def main():
    output=Path('H:/JarvisData/research/conversation-ui');output.mkdir(parents=True,exist_ok=True)
    spec=importlib.util.spec_from_file_location('conversation_ui_server',ROOT/'apps/web/server.py')
    web=importlib.util.module_from_spec(spec);spec.loader.exec_module(web)
    errors=[];checks=[]
    with tempfile.TemporaryDirectory(prefix='jarvis-archive-ui-') as directory:
        folder=Path(directory)/'project';folder.mkdir();core=CoreService(Path(directory)/'data');core.initialize(folder)
        chat=SyntheticChat();server=web.create_server(core=core,chat=chat,port=0)
        thread=threading.Thread(target=server.serve_forever,kwargs={'poll_interval':.02},daemon=True);thread.start()
        base='http://127.0.0.1:'+str(server.server_port)
        try:
            with sync_playwright() as playwright:
                job=DriverJob(playwright)
                try:
                    browser=playwright.chromium.launch(channel='msedge',headless=True,chromium_sandbox=True)
                    page=browser.new_page(viewport={'width':1440,'height':1000})
                    page.on('pageerror',lambda error:errors.append(str(error)))
                    page.goto(base);expect(page.locator('#send')).to_be_enabled()
                    expect(page.locator('#file-options')).to_be_hidden();assert page.locator('.output-options').count()==0
                    page.locator('#session-context summary').click();page.locator('#context-note').fill('使用中文，保持模块独立。');page.locator('#session-context summary').click()
                    def send(text):
                        page.locator('#message').fill(text);page.locator('#send').click()
                        expect(page.locator('#send')).to_have_attribute('aria-label','发送消息')
                        expect(page.locator('#conversation-status')).to_have_attribute('data-state','saved')
                    send('记录一段测试对话');url=page.url;chat_id=url.split('#chat=')[1]
                    expect(page.get_by_role('button',name='保存回答…',exact=True)).to_have_count(0)
                    expect(page.get_by_role('button',name='导出为文件…',exact=True)).to_have_count(0)
                    assert len(server.conversations.get(chat_id)['document']['messages'])==2
                    page.screenshot(path=str(output/'desktop.png'),full_page=True)
                    page.reload();expect(page.locator('#send')).to_be_enabled();expect(page.locator('.message')).to_have_count(2)
                    expect(page.locator('#context-note')).to_have_value('使用中文，保持模块独立。')
                    assert page.evaluate('history.length')==2
                    checks.append('ordinary text auto-archives; reload restores transcript, note and usable history; no inactive file panel or Save Answer button')

                    second=browser.new_page();second.on('pageerror',lambda error:errors.append(str(error)));second.goto(url);expect(second.locator('#send')).to_be_enabled();expect(second.locator('.message')).to_have_count(2)
                    page.locator('#conversation-status').click();page.locator('#conversation-delete').click()
                    expect(page.locator('.message')).to_have_count(0)
                    assert server.conversations.list()['conversations']==[]
                    second.bring_to_front();second.locator('#message').click();second.locator('#message').fill('旧标签不能复活会话');expect(second.locator('#message')).to_have_value('旧标签不能复活会话');second.locator('#send').click()
                    expect(second.locator('#conversation-status')).to_have_attribute('data-state','failed')
                    assert server.conversations.list()['conversations']==[];second.close()
                    checks.append('delete removes archive; delayed writes from an already-open tab cannot resurrect it')

                    page.locator('#conversation-status').click();page.locator('#conversation-temporary').click()
                    page.locator('#message').fill('不归档的临时问题');page.locator('#send').click();expect(page.locator('#send')).to_have_attribute('aria-label','发送消息')
                    expect(page.locator('#conversation-status')).to_have_attribute('data-state','temporary');assert server.conversations.list()['conversations']==[]
                    page.reload();expect(page.locator('#send')).to_be_enabled();expect(page.locator('.message')).to_have_count(0)
                    checks.append('temporary conversations are never archived and vanish on reload')

                    page.route('**/api/conversations/*',lambda route:route.fulfill(status=503,content_type='application/json',body=json.dumps({'user_message':'模拟磁盘保存失败'})) if route.request.method=='POST' else route.continue_())
                    page.locator('#message').fill('保存失败仍保留回答');page.locator('#send').click();expect(page.locator('#conversation-status')).to_have_attribute('data-state','failed');expect(page.locator('.message.assistant')).to_have_count(1)
                    page.unroute('**/api/conversations/*');page.locator('#conversation-status').click();page.locator('#conversation-retry').click();expect(page.locator('#conversation-status')).to_have_attribute('data-state','saved');page.locator('#conversation-status').click()
                    assert len(server.conversations.list()['conversations'])==1
                    checks.append('archive failure is visible without blocking chat; retry saves exactly one conversation')

                    page.locator('#attachment-input').set_input_files({'name':'sample.txt','mimeType':'text/plain','buffer':b'ATTACHMENT_ONLY_PRIVATE_MARKER'})
                    expect(page.locator('.attachment-card')).to_have_count(1);send('查看附件')
                    stored=server.conversations.get(page.url.split('#chat=')[1])['document']
                    assert 'ATTACHMENT_ONLY_PRIVATE_MARKER' not in json.dumps(stored)
                    assert stored['messages'][-2]['attachments_omitted']
                    page.reload();expect(page.locator('#send')).to_be_enabled();expect(page.locator('.message')).to_have_count(4)
                    expect(page.locator('[data-attachments-omitted="true"]')).to_contain_text('附件未归档')
                    assert page.evaluate('history.length')==2
                    checks.append('attachment contents excluded from archive; restored history excludes incomplete attachment-dependent turns')

                    page.locator('#open-project').click();page.locator('#folder-path').fill(str(folder));page.locator('#project-open').click();expect(page.locator('#context-project')).to_contain_text(str(folder))
                    expect(page.locator('#file-options')).to_be_visible();assert not page.locator('#file-options').evaluate('el=>el.open')
                    page.locator('#file-options-label').click();page.locator('#file-mode').check();page.locator('#output-path').fill('export.md');page.locator('#file-options-label').click();send('导出项目笔记')
                    assert (folder/'export.md').read_text(encoding='utf-8')==chat.text
                    expect(page.locator('.file-receipt').last).to_contain_text('已保存')
                    page.locator('#file-options-label').click();page.locator('#file-mode').uncheck();page.locator('#file-options-label').click();send('普通项目回答')
                    page.locator('.answer-menu summary').last.click();page.get_by_role('button',name='导出为文件…',exact=True).last.click();page.locator('#save-path').fill('manual.md');page.locator('#save-confirm').click();expect(page.locator('#save-dialog')).not_to_be_visible()
                    assert (folder/'manual.md').exists()
                    checks.append('project-only compact file menu retains automatic and explicit exports with real file receipts')
                    page.set_viewport_size({'width':390,'height':844})
                    assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
                    page.screenshot(path=str(output/'mobile.png'),full_page=True)
                    page.locator('#conversation-status').click();assert page.locator('#conversation-menu').is_visible()
                    menu=page.locator('.conversation-menu-body').bounding_box();assert menu['x']>=0 and menu['x']+menu['width']<=390
                    page.keyboard.press('Escape');assert not page.locator('#conversation-menu').evaluate('el=>el.open')
                    checks.append('desktop/mobile layout and keyboard menu closing; no browser script errors')
                    assert not errors,errors
                    browser.close()
                finally:job.close()
            result={'version':__version__,'captured_at':datetime.now(timezone.utc).isoformat(),'status':'passed','checks':checks,'model_fixture_calls':chat.calls,'page_errors':errors,'screenshots':[str(output/'desktop.png'),str(output/'mobile.png')],'limits':['Synthetic model replies; no cloud calls.','Local chat text archive only; no automatic long-term fact extraction or indexing.','Attachments and drafts are excluded. Closing before save acknowledgement may lose latest displayed changes.']}
            (ROOT/'evals/reports/conversation-ui.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
            print(json.dumps(result,ensure_ascii=False))
        finally:server.shutdown();server.server_close();thread.join(5)


if __name__=='__main__':main()
