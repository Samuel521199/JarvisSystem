"""Real HTTP/Edge/context assembly, synthetic gateway only. No cloud calls."""
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
from jarvis_core.chat import ChatService
from jarvis_core.service import CoreService
from jarvis_computer.browser import DriverJob
from playwright.sync_api import sync_playwright, expect


def main():
    spec=importlib.util.spec_from_file_location('context_ui_web',ROOT/'apps/web/server.py')
    web=importlib.util.module_from_spec(spec);spec.loader.exec_module(web)
    output=Path('H:/JarvisData/research/context-ui');output.mkdir(parents=True,exist_ok=True)
    calls=[];errors=[];checks=[]
    def gateway(config,provider,message,*args,**kwargs):
        calls.append({'provider':provider,'message':message,'history':kwargs['history']})
        return {'status':'SUCCEEDED','text':'合成验收回复：上下文已装配。','provider':provider,
                'model':config['providers'][provider]['model'],'outcome_uncertain':False}
    with tempfile.TemporaryDirectory(prefix='jarvis-context-ui-') as directory:
        core=CoreService(Path(directory)/'data');core.initialize(ROOT/'tests/fixtures/workspace')
        server=web.create_server(core=core,chat=ChatService(core),port=0)
        worker=threading.Thread(target=server.serve_forever,kwargs={'poll_interval':.02},daemon=True);worker.start()
        try:
            with patch('jarvis_core.chat.gateway.probe',side_effect=gateway),sync_playwright() as pw:
                job=DriverJob(pw)
                try:
                    browser=pw.chromium.launch(channel='msedge',headless=True,chromium_sandbox=True)
                    page=browser.new_page(viewport={'width':1440,'height':1000},reduced_motion='reduce')
                    page.on('pageerror',lambda error:errors.append(str(error)))
                    page.goto('http://127.0.0.1:'+str(server.server_address[1]))
                    expect(page.locator('#send')).to_be_enabled(timeout=15000)
                    page.locator('#session-context summary').click()
                    page.locator('#context-note').fill('固定要求：中文回答，适配 Windows。')
                    page.locator('#message').fill('第一轮验收');page.locator('#send').click()
                    expect(page.locator('.message.assistant')).to_have_count(1,timeout=10000)
                    expect(page.locator('#context-report')).to_contain_text('固定要求已携带')
                    assert '固定要求：中文回答' in calls[-1]['message']
                    checks.append('real HTTP and ChatService send the note as user input and report context')
                    page.locator('#clear').click()
                    page.locator('#session-context summary').click()
                    expect(page.locator('#context-note')).to_have_value('')
                    page.locator('#message').fill('第二个会话');page.locator('#send').click()
                    expect(page.locator('.message.assistant')).to_have_count(1)
                    assert '固定要求' not in calls[-1]['message']
                    page.locator('.session-row').filter(has_text='第一轮验收').click()
                    expect(page.locator('#context-note')).to_have_value('固定要求：中文回答，适配 Windows。')
                    checks.append('new session has no old note; switching back restores its own note')
                    page.locator('#context-note').fill('修改后的要求：只列出要点。')
                    page.locator('#message').fill('继续验收');page.locator('#send').click()
                    expect(page.locator('.message.assistant')).to_have_count(2)
                    assert '修改后的要求' in calls[-1]['message'] and '适配 Windows' not in calls[-1]['message']
                    checks.append('edited note replaces the previous note on the next request')
                    page.locator('#model-trigger').click()
                    page.locator('#model-search').fill('qwen3-0.6b')
                    page.locator('#model-options button').first.click()
                    page.locator('#message').fill('切换本地模型验收');page.locator('#send').click()
                    expect(page.locator('.message.assistant')).to_have_count(3)
                    assert calls[-1]['provider']=='local' and '修改后的要求' in calls[-1]['message']
                    page.locator('#context-clear').click()
                    page.locator('#message').fill('清空后验收');page.locator('#send').click()
                    expect(page.locator('.message.assistant')).to_have_count(4)
                    assert calls[-1]['message']=='清空后验收'
                    checks.append('switching to local route retains note; explicit clear stops resending it')
                    page.locator('#context-note').fill('汉'*3000)
                    page.locator('#message').fill('不能发送');before=len(calls);page.locator('#send').click()
                    expect(page.locator('#toast')).to_contain_text('超过 8 KiB')
                    assert len(calls)==before
                    checks.append('UTF-8 note overflow stops before the model gateway')
                    page.locator('#context-note').fill('请使用中文。优先复用独立模块，保持普通 PC 上的低开销。')
                    page.locator('#message').fill('')
                    page.screenshot(path=str(output/'desktop.png'))
                    page.set_viewport_size({'width':390,'height':844})
                    assert page.evaluate('document.documentElement.scrollWidth<=innerWidth')
                    page.screenshot(path=str(output/'mobile.png'))
                    checks.append('desktop and 390px layout inspected; no horizontal overflow')
                    page.reload();expect(page.locator('#send')).to_be_enabled()
                    expect(page.locator('#context-note')).to_have_value('')
                    checks.append('page reload restores last archived note; unsent edits are not guaranteed saved')
                    assert not errors,errors
                    browser.close()
                finally:job.close()
        finally:
            server.shutdown();server.server_close();worker.join(3)
    result={'version':__version__,'captured_at':datetime.now(timezone.utc).isoformat(),'status':'passed',
        'checks':checks,'gateway_calls':len(calls),'page_errors':errors,
        'screenshots':[str(output/'desktop.png'),str(output/'mobile.png')],
        'limits':['Gateway replies are synthetic. No real model obedience/quality or cloud cost was measured.',
                  'No automatic summarization, curated long-term facts, or autonomous tool execution is claimed.']}
    (ROOT/'evals/reports/context-ui.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(result,ensure_ascii=False))


if __name__=='__main__':main()
