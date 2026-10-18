"""Real Edge + HTTP + MemoryStore + ChatService; deterministic gateway fixture.

All data is synthetic and temporary. No real model credentials or user files.
"""
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
    output=Path('H:/JarvisData/research/memory-ui');output.mkdir(parents=True,exist_ok=True)
    spec=importlib.util.spec_from_file_location('memory_ui_server',ROOT/'apps/web/server.py')
    web=importlib.util.module_from_spec(spec);spec.loader.exec_module(web)
    calls=[];errors=[];checks=[]
    def probe(config,provider,message,*args,**kwargs):
        calls.append({'provider':provider,'message':message,'history':kwargs['history']})
        return {'status':'SUCCEEDED','text':'这是测试回复。','provider':provider,'model':config['providers'][provider]['model'],'outcome_uncertain':False}
    with tempfile.TemporaryDirectory(prefix='jarvis-memory-ui-') as directory:
        base=Path(directory);folder=base/'项目甲';folder.mkdir()
        core=CoreService(base/'data');core.initialize(folder)
        config=json.loads((ROOT/'config/model-profiles/providers.json').read_text(encoding='utf-8'))
        config.update(default_provider='vertex',automatic_fallback=False)
        config_path=base/'providers.json';config_path.write_text(json.dumps(config),encoding='utf-8')
        chat=ChatService(core,config_path);server=web.create_server(core=core,chat=chat,port=0)
        thread=threading.Thread(target=server.serve_forever,kwargs={'poll_interval':.02},daemon=True);thread.start()
        try:
            with patch('jarvis_core.chat.gateway.probe',side_effect=probe),sync_playwright() as playwright:
                job=DriverJob(playwright)
                try:
                    browser=playwright.chromium.launch(channel='msedge',headless=True,chromium_sandbox=True)
                    page=browser.new_page(viewport={'width':1440,'height':1000})
                    page.on('pageerror',lambda error:errors.append(str(error)))
                    page.goto('http://127.0.0.1:'+str(server.server_port));expect(page.locator('#send')).to_be_enabled()
                    def open_memory():
                        page.locator('#open-memory').click();expect(page.locator('#memory-dialog')).to_be_visible()
                        expect(page.locator('#memory-status')).not_to_have_text('正在读取…')
                    def save():
                        page.locator('#memory-save').click();expect(page.locator('#memory-status')).to_contain_text('已存入本机')
                    def send(text):
                        before=len(calls);page.locator('#message').fill(text);page.locator('#send').click()
                        expect(page.locator('#send')).to_have_attribute('aria-label','发送消息')
                        expect(page.locator('#message')).to_be_enabled()
                        assert len(calls)==before+1
                    open_memory();page.locator('#memory-title').fill('回复风格');page.locator('#memory-content').fill('MEMORY_PRIVATE_中文偏好');save()
                    expect(page.locator('.memory-card')).to_have_count(1)
                    fact=server.memory.list()['facts'][0]
                    assert fact['document']['providers']==[]
                    page.locator('#memory-close').click();send('第一轮测试')
                    assert 'MEMORY_PRIVATE_' not in calls[-1]['message'];checks.append('Explicit local-only memory is durable and not sent to cloud by default')

                    open_memory();page.get_by_role('button',name='修改',exact=True).click()
                    page.locator('#memory-providers input[value="vertex"]').check();save();page.locator('#memory-close').click()
                    send('第二轮测试');assert 'MEMORY_PRIVATE_中文偏好' in calls[-1]['message']
                    expect(page.locator('#conversation-status')).to_have_attribute('data-state','saved')
                    stored=server.conversations.get(page.url.split('#chat=')[1])['document']
                    assert stored['messages'][-1]['memory_refs'][0]['id']==fact['id']
                    page.reload();expect(page.locator('#send')).to_be_enabled()
                    assert page.evaluate('history.at(-1)._memory_refs.length')==1
                    checks.append('Allowed provider gets memory; reply provenance survives conversation archive and refresh')

                    open_memory();page.get_by_role('button',name='修改',exact=True).click();page.locator('#memory-content').fill('MEMORY_CORRECTED_新的偏好');save();page.locator('#memory-close').click()
                    send('修改后继续');assert 'MEMORY_CORRECTED_' in calls[-1]['message'] and 'MEMORY_PRIVATE_' not in calls[-1]['message']
                    assert len(calls[-1]['history'])==2
                    checks.append('Corrected facts replace old text and invalidate the old memory-dependent history turn')

                    open_memory();page.get_by_role('button',name='修改',exact=True).click();page.locator('#memory-content').fill('冲突后输入保留')
                    latest=server.memory.list()['facts'][0]
                    server.memory.put(latest['id'],{'revision':latest['revision'],'document':dict(latest['document'],content='另一页面更新')})
                    page.locator('#memory-save').click();expect(page.locator('#memory-status')).to_contain_text('其他页面')
                    expect(page.locator('#memory-content')).to_have_value('冲突后输入保留')
                    page.locator('#memory-reload').click();expect(page.locator('#memory-status')).to_contain_text('列表已更新')
                    page.get_by_role('button',name='忘记',exact=True).click();page.get_by_role('button',name='确认忘记',exact=True).click()
                    expect(page.locator('#memory-status')).to_contain_text('已忘记');assert server.memory.list()['facts']==[]
                    page.locator('#memory-close').click();send('忘记后继续');assert '参考记忆' not in calls[-1]['message']
                    assert len(calls[-1]['history'])==2
                    checks.append('Stale edits show conflict without losing input; forget clears facts and fences derived history')

                    page.locator('#open-project').click();page.locator('#folder-path').fill(str(folder));page.locator('#project-open').click();expect(page.locator('#context-project')).to_contain_text(str(folder))
                    open_memory();page.locator('#memory-title').fill('项目甲约定');page.locator('#memory-content').fill('PROJECT_A_ONLY_使用本地部署');page.locator('#memory-scope').select_option(index=1)
                    page.locator('#memory-providers input[value="vertex"]').check();save()
                    page.locator('#memory-dialog').evaluate('(el)=>{el.scrollTop=0;el.scrollLeft=0}')
                    assert page.locator('#memory-enabled').bounding_box()['width']<=20
                    assert page.locator('#memory-dialog').evaluate('(el)=>el.scrollWidth<=el.clientWidth')
                    page.screenshot(path=str(output/'desktop.png'),full_page=True)
                    page.locator('#memory-close').click();send('项目内查询');assert 'PROJECT_A_ONLY_' in calls[-1]['message']
                    page.locator('#no-project').click();send('项目外查询');assert 'PROJECT_A_ONLY_' not in calls[-1]['message']
                    checks.append('Project facts enter only the matching project; leaving the project excludes them')

                    page.locator('#conversation-status').click();page.locator('#conversation-temporary').click();send('临时会话测试')
                    assert '参考记忆' not in calls[-1]['message']
                    open_memory();expect(page.locator('#memory-save')).to_be_disabled();expect(page.locator('#memory-enabled')).to_be_disabled()
                    assert len(server.memory.list(project_id=server.workspace.projects()['projects'][0]['id'])['facts'])==1
                    page.locator('#memory-close').click();checks.append('Temporary chat reads no memory and cannot create facts through the panel')

                    page.locator('#clear').click();open_memory()
                    page.locator('#memory-title').fill('中文显示');page.locator('#memory-content').fill('<script>不会执行</script> 中文界面测试');save()
                    page.set_viewport_size({'width':390,'height':844})
                    assert page.evaluate('document.documentElement.scrollWidth<=innerWidth')
                    box=page.locator('#memory-dialog').bounding_box();assert box['x']>=0 and box['x']+box['width']<=390
                    page.locator('#memory-dialog').evaluate('(el)=>{el.scrollTop=0;el.scrollLeft=0}')
                    assert page.locator('#memory-dialog').evaluate('(el)=>el.scrollWidth<=el.clientWidth')
                    page.screenshot(path=str(output/'mobile.png'),full_page=True)
                    page.keyboard.press('Escape');expect(page.locator('#memory-dialog')).not_to_be_visible()
                    assert not errors,errors;checks.append('Desktop/mobile modal, escaped text and keyboard closing; no script errors')
                    browser.close()
                finally:job.close()
            result={'version':__version__,'captured_at':datetime.now(timezone.utc).isoformat(),'status':'passed','checks':checks,
                    'fixture_calls':len(calls),'page_errors':errors,'screenshots':[str(output/'desktop.png'),str(output/'mobile.png')],
                    'limits':['Synthetic gateway; no real model quality or cloud calls tested.','Explicit owner facts only; no automatic extraction, embeddings or federation.','Forgetting does not erase prior transcript/exports/provider copies; already dispatched calls cannot be recalled.']}
            (ROOT/'evals/reports/memory-ui.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
            print(json.dumps(result,ensure_ascii=False))
        finally:server.shutdown();server.server_close();thread.join(5)


if __name__=='__main__':main()
