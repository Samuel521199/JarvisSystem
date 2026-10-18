"""Edge/HTTP/project files/chat integration using temporary data and a fake gateway."""
from datetime import datetime, timezone
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import threading
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'runtime/node-host'),str(ROOT/'adapters/computer-use')]
from jarvis_core import __version__
from jarvis_core.service import CoreService
from jarvis_core.chat import ChatService
from jarvis_computer.browser import DriverJob
from playwright.sync_api import sync_playwright, expect


def main():
    output=Path('H:/JarvisData/research/knowledge-ui');output.mkdir(parents=True,exist_ok=True)
    spec=importlib.util.spec_from_file_location('knowledge_ui_server',ROOT/'apps/web/server.py')
    web=importlib.util.module_from_spec(spec);spec.loader.exec_module(web)
    calls=[];errors=[];checks=[]
    def probe(config,provider,message,*args,**kwargs):
        calls.append({'provider':provider,'message':message,'history':kwargs['history']})
        return {'status':'SUCCEEDED','text':'按资料回答 [P1]。' if '[项目资料摘录' in message else '当前未使用项目资料。','provider':provider,'model':config['providers'][provider]['model'],'outcome_uncertain':False}
    with tempfile.TemporaryDirectory(prefix='jarvis-knowledge-ui-') as directory:
        base=Path(directory);folder=base/'项目甲';folder.mkdir();source=folder/'README.md'
        source.write_text('# 项目设计\n\n## 离线部署\nSOURCE_V1：断网时使用本机资料。\n<script>这只是文档文字</script>\n\n## 实施状态\n该功能仍为 proposed。\n',encoding='utf-8')
        core=CoreService(base/'data');core.initialize(folder)
        config=json.loads((ROOT/'config/model-profiles/providers.json').read_text(encoding='utf-8'));config.update(default_provider='vertex',automatic_fallback=False)
        config_path=base/'providers.json';config_path.write_text(json.dumps(config),encoding='utf-8')
        server=web.create_server(core=core,chat=ChatService(core,config_path),port=0)
        thread=threading.Thread(target=server.serve_forever,kwargs={'poll_interval':.02},daemon=True);thread.start()
        try:
            with patch('jarvis_core.chat.gateway.probe',side_effect=probe),sync_playwright() as playwright:
                job=DriverJob(playwright)
                try:
                    browser=playwright.chromium.launch(channel='msedge',headless=True,chromium_sandbox=True)
                    page=browser.new_page(viewport={'width':1440,'height':1000},color_scheme='dark')
                    page.on('pageerror',lambda error:errors.append(str(error)))
                    page.goto('http://127.0.0.1:'+str(server.server_port));expect(page.locator('#send')).to_be_enabled()
                    expect(page.locator('#open-knowledge')).to_be_hidden()
                    page.locator('#open-project').click();page.locator('#folder-path').fill(str(folder));page.locator('#project-open').click()
                    expect(page.locator('#open-knowledge')).to_be_visible()
                    def open_panel():
                        page.locator('#open-knowledge').click();expect(page.locator('#knowledge-dialog')).to_be_visible();expect(page.locator('#knowledge-status')).not_to_have_text('正在读取登记…')
                    def save():
                        page.locator('#knowledge-save').click();expect(page.locator('#knowledge-status')).to_contain_text('资料已纳入');expect(page.locator('#knowledge-save')).to_be_enabled()
                    def send(text):
                        count=len(calls);page.locator('#message').fill(text);page.locator('#send').click();expect(page.locator('#send')).to_have_attribute('aria-label','发送消息');expect(page.locator('#message')).to_be_enabled();assert len(calls)==count+1
                    open_panel();page.locator('#knowledge-path').fill('README.md');save()
                    expect(page.locator('.knowledge-source')).to_have_count(1)
                    page.locator('#knowledge-query').fill('离线部署');page.get_by_role('button',name='检索资料',exact=True).click()
                    expect(page.locator('#knowledge-results button')).to_have_count(1)
                    page.locator('#knowledge-results button').click();expect(page.locator('#knowledge-excerpt')).to_contain_text('SOURCE_V1');expect(page.locator('#knowledge-excerpt')).to_contain_text('<script>')
                    page.locator('#knowledge-excerpt-close').click();page.locator('#knowledge-close').click();send('离线部署如何工作？')
                    assert 'SOURCE_V1' not in calls[-1]['message'];checks.append('Explicit local source registration and read-only Chinese section preview; cloud excluded by default')
                    open_panel();page.get_by_role('button',name='使用范围',exact=True).click();page.locator('#knowledge-providers input[value="vertex"]').check();save()
                    page.locator('#knowledge-dialog').evaluate('(el)=>{el.scrollTop=0;el.scrollLeft=0}')
                    assert page.locator('#knowledge-dialog').evaluate('(el)=>el.scrollWidth<=el.clientWidth')
                    page.screenshot(path=str(output/'desktop-dark.png'),full_page=True)
                    page.locator('#knowledge-close').click();send('离线部署如何工作？');assert 'SOURCE_V1' in calls[-1]['message']
                    expect(page.locator('#messages .knowledge-citations button')).to_have_count(1)
                    page.locator('#messages .knowledge-citations button').click();expect(page.locator('#knowledge-excerpt')).to_contain_text('SOURCE_V1');page.locator('#knowledge-excerpt-close').click()
                    expect(page.locator('#conversation-status')).to_have_attribute('data-state','saved');page.reload();expect(page.locator('#send')).to_be_enabled()
                    expect(page.locator('#messages .knowledge-citations button')).to_have_count(1)
                    assert page.evaluate('history.at(-1)._knowledge_refs.length')==1
                    checks.append('Allowed provider gets excerpts; real source citation and history provenance survive archive/refresh')
                    source.write_text(source.read_text(encoding='utf-8').replace('SOURCE_V1','SOURCE_V2'),encoding='utf-8')
                    page.locator('#messages .knowledge-citations button').click();expect(page.locator('#knowledge-excerpt')).to_contain_text('已过期');page.locator('#knowledge-excerpt-close').click()
                    send('离线部署如何工作？');assert 'SOURCE_V2' in calls[-1]['message'] and 'SOURCE_V1' not in calls[-1]['message'];assert len(calls[-1]['history'])==2
                    checks.append('Changed file invalidates old preview and derived history; next request uses fresh digest/content')
                    open_panel();page.get_by_role('button',name='撤出',exact=True).click();expect(page.locator('#knowledge-status')).to_contain_text('已撤出');page.locator('#knowledge-close').click()
                    send('离线部署如何工作？');assert 'SOURCE_V2' not in calls[-1]['message'];assert len(calls[-1]['history'])==2;assert source.exists()
                    checks.append('Withdrawal removes registration and history eligibility while preserving the source file')
                    open_panel();page.locator('#knowledge-path').fill('README.md');page.locator('#knowledge-providers input[value="vertex"]').check();save();page.locator('#knowledge-close').click()
                    page.locator('#conversation-status').click();page.locator('#conversation-temporary').click();send('离线部署如何工作？');assert 'SOURCE_V2' not in calls[-1]['message']
                    open_panel();expect(page.locator('#knowledge-save')).to_be_disabled();expect(page.locator('#knowledge-enabled')).to_be_disabled();page.locator('#knowledge-close').click()
                    checks.append('Temporary conversation excludes project context and disables registration mutations')
                    page.locator('#clear').click();open_panel();page.set_viewport_size({'width':390,'height':844});page.emulate_media(color_scheme='light')
                    page.locator('#knowledge-dialog').evaluate('(el)=>{el.scrollTop=0;el.scrollLeft=0}')
                    assert page.locator('#knowledge-dialog').evaluate('(el)=>el.scrollWidth<=el.clientWidth')
                    assert page.evaluate('document.documentElement.scrollWidth<=innerWidth')
                    page.screenshot(path=str(output/'mobile-light.png'),full_page=True);page.keyboard.press('Escape');expect(page.locator('#knowledge-dialog')).not_to_be_visible()
                    page.set_viewport_size({'width':1440,'height':1000});page.locator('#no-project').click();expect(page.locator('#open-knowledge')).to_be_hidden();send('离线部署如何工作？');assert 'SOURCE_V2' not in calls[-1]['message']
                    assert not errors,errors;checks.append('No-project isolation, escaped source text, keyboard close and responsive dark/light layouts without script errors')
                    browser.close()
                finally:job.close()
            report={'version':__version__,'captured_at':datetime.now(timezone.utc).isoformat(),'status':'passed','checks':checks,'fixture_calls':len(calls),'page_errors':errors,
                    'screenshots':[str(output/'desktop-dark.png'),str(output/'mobile-light.png')],
                    'limits':['Synthetic model gateway; citations show supplied sources, not proof of model answer correctness.','Explicit UTF-8 document registrations only; no full code understanding, automatic compilation or federation.']}
            (ROOT/'evals/reports/knowledge-ui.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
            print(json.dumps(report,ensure_ascii=False))
        finally:server.shutdown();server.server_close();thread.join(5)


if __name__=='__main__':main()
