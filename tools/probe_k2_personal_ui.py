"""K2 personal/reference UI with disposable stores and intercepted transport."""
import argparse
from contextlib import ExitStack
from datetime import datetime, timezone
import hashlib
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import threading
import time
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'runtime/node-host'),str(ROOT/'adapters/computer-use'),str(ROOT/'apps/web')]
from jarvis_core import __version__
from jarvis_core.chat import ChatService
from jarvis_core.service import CoreService
from jarvis_core.persona import PersonaStore
from jarvis_computer.browser import DriverJob
from playwright.sync_api import sync_playwright,expect


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args();args.output.mkdir(parents=True,exist_ok=False)
    spec=importlib.util.spec_from_file_location('k2_ui_server',ROOT/'apps/web/server.py')
    web=importlib.util.module_from_spec(spec);spec.loader.exec_module(web)
    calls=[];checks=[];errors=[];hold=threading.Event();started=threading.Event()
    report={'version':__version__,'captured_at':datetime.now(timezone.utc).isoformat(),'real_model_calls':0,'checks':checks}
    def model(config,provider,message,*args,cancel_event=None,**kwargs):
        calls.append({'message':message,'provider':provider,**kwargs})
        if message=='请慢慢回答这个问题':
            started.set()
            while not hold.wait(.02):
                if cancel_event and cancel_event.is_set():return {'status':'CANCELLED','outcome_uncertain':False}
        return {'status':'SUCCEEDED','text':'这是本地测试回复。','provider':provider,'model':config['providers'][provider]['model']}
    try:
        with tempfile.TemporaryDirectory(prefix='jarvis-k2-ui-') as temp:
            base=Path(temp);folder=base/'sample';folder.mkdir()
            core=CoreService(base/'data');core.initialize(folder);chat=ChatService(core)
            server=web.create_server(core=core,chat=chat,port=0)
            thread=threading.Thread(target=server.serve_forever,kwargs={'poll_interval':.01},daemon=True);thread.start()
            try:
                with ExitStack() as stack,sync_playwright() as pw:
                    stack.enter_context(patch('jarvis_core.chat.gateway.probe',side_effect=model))
                    stack.enter_context(patch.object(chat.dialogue_models,'reply',side_effect=lambda owner,*a,**kw:owner.reply(*a,**kw)))
                    stack.enter_context(patch.object(chat.dialogue_models,'probe',side_effect=model))
                    stack.enter_context(patch('jarvis_core.dialogue_process.ProcessJob',side_effect=AssertionError('fixture forbids real transport')))
                    job=DriverJob(pw)
                    try:
                        browser=pw.chromium.launch(channel='msedge',headless=True,chromium_sandbox=True)
                        page=browser.new_page(viewport={'width':1440,'height':1000});page.on('pageerror',lambda e:errors.append(str(e)))
                        page.goto(f'http://127.0.0.1:{server.server_port}');expect(page.locator('#send')).to_be_enabled()
                        def idle():
                            deadline=time.monotonic()+10
                            while time.monotonic()<deadline:
                                if page.evaluate('!busy && !window.Dialogue?.hasPending()'): return
                                page.wait_for_timeout(50)
                            raise AssertionError('Dialogue did not finish')
                        def send(text,expected):
                            idle()
                            expect(page.locator('.jarvis-cinema')).not_to_be_visible(timeout=10000)
                            count=page.locator('.message.assistant').count();page.locator('#message').fill(text);page.locator('#send').click()
                            expect(page.locator('.message.assistant')).to_have_count(count+1)
                            expect(page.locator('.message.assistant').last).to_contain_text(expected)
                            expect(page.locator('#send')).to_have_attribute('aria-label','发送消息')
                            expect(page.locator('#conversation-status')).to_have_attribute('data-state','saved')
                        send('查询三库：UNKNOWN','R_UNKNOWN');send('查看能力','旧 K0/K1')
                        assert not calls
                        page.reload();expect(page.locator('#send')).to_be_enabled();assert page.evaluate('history.length')==0
                        checks.append('Local cited seed queries survive archive/reload without cloud calls or model-history export')
                        page.locator('#open-memory').click();page.locator('[data-memory-tab=persona]').click()
                        expect(page.locator('#persona-version')).to_contain_text('修订 0')
                        page.locator('#persona-name').fill('小林');page.locator('#persona-style').select_option('温暖');page.locator('#persona-relationship').select_option('伙伴')
                        page.locator('#persona-save').click();expect(page.locator('#persona-status')).to_contain_text('已保存')
                        assert PersonaStore(core).snapshot()['preferred_name']=='小林'
                        # Concurrent change leaves local edited values intact until explicit retry.
                        PersonaStore(core).change('style','简洁',request_id='f'*32)
                        page.locator('#persona-name').fill('小树');page.locator('#persona-save').click()
                        expect(page.locator('#persona-status')).to_contain_text('其他操作修改');expect(page.locator('#persona-name')).to_have_value('小树')
                        page.locator('#persona-reload').click();expect(page.locator('#persona-version')).to_contain_text('修订 2')
                        page.locator('#persona-save').click();expect(page.locator('#persona-version')).to_contain_text('修订 3')
                        page.locator('#persona-undo').click();expect(page.locator('#persona-name')).to_have_value('小林');expect(page.locator('#persona-style')).to_have_value('简洁')
                        page.screenshot(path=str(args.output/'persona-desktop.png'),full_page=True)
                        page.set_viewport_size({'width':390,'height':844})
                        assert page.evaluate('document.documentElement.scrollWidth<=innerWidth')
                        assert page.locator('#memory-dialog').evaluate('(e)=>e.scrollWidth<=e.clientWidth+1')
                        page.screenshot(path=str(args.output/'persona-mobile.png'),full_page=True)
                        page.set_viewport_size({'width':1440,'height':1000});page.locator('#memory-close').click()
                        checks.append('Profile save, concurrent-edit conflict with retained input, refresh, atomic undo, desktop and mobile layout')
                        send('你好','本地测试回复');assert '小林' in calls[-1]['instructions']
                        assert 'R_UNKNOWN' not in str(calls[-1]);checks.append('Next ordinary turn receives current expression; local seed query is not in cloud-bound history')
                        send('保存接续：英语学习=已练习基础音标｜练习英文短句','已保存')
                        send('保存接续：旅行计划=准备去杭州｜比较住宿','已保存')
                        page.locator('#open-memory').click();page.locator('[data-memory-tab=continuity]').click()
                        expect(page.locator('.continuity-card')).to_have_count(2)
                        # Default records are local-only; choose the local model for suggestions.
                        page.evaluate("selectedKey=modelCatalog.find(x=>x.provider==='local') ? modelKey(modelCatalog.find(x=>x.provider==='local')) : 'auto'")
                        page.locator('#continuity-query').fill('英语学习');page.locator('#continuity-suggest').click()
                        expect(page.locator('.continuity-card')).to_have_count(1)
                        expect(page.locator('.continuity-card')).to_contain_text('基础音标')
                        expect(page.locator('.continuity-card a').first).to_have_attribute('href',__import__('re').compile('/#chat='))
                        page.locator('#continuity-list input[data-continuity-select]').check();assert len(page.evaluate('window.Continuity.snapshot()'))==1
                        checks.append('Related continuity is bounded, source-visible and explicitly selected without dispatching a task')
                        page.locator('#memory-close').click();page.evaluate("window.Continuity.clear();selectedKey='auto';syncSelection()")
                        page.locator('#message').fill('请慢慢回答这个问题');page.locator('#send').click()
                        assert started.wait(5)
                        expect(page.locator('#open-memory')).to_be_enabled();page.locator('#open-memory').click()
                        page.locator('[data-memory-tab=persona]').click();expect(page.locator('#persona-name')).to_have_value('小林')
                        page.locator('#persona-name').fill('下一轮');page.locator('#persona-save').click();expect(page.locator('#persona-status')).to_contain_text('已保存')
                        assert PersonaStore(core).snapshot()['preferred_name']=='下一轮',PersonaStore(core).snapshot()
                        assert '下一轮' not in calls[-1]['instructions'];hold.set();page.locator('#memory-close').click()
                        idle()
                        send('新的一轮','本地测试回复');assert '下一轮' in calls[-1]['instructions'],{'profile':PersonaStore(core).snapshot(),'call':calls[-1]}
                        checks.append('Slow ongoing answer does not block profile controls; a saved profile takes effect at the next turn boundary')
                        page.goto(f'http://127.0.0.1:{server.server_port}/settings#modules')
                        expect(page.locator('[data-module=persona]')).to_contain_text('可读取')
                        expect(page.locator('[data-module=continuity]')).to_contain_text('可读取')
                        expect(page.locator('.module-card')).to_have_count(25)
                        expect(page.locator('[data-module=persona]')).not_to_contain_text('下一轮')
                        page.locator('[data-module=persona]').screenshot(path=str(args.output/'persona-module.png'))
                        assert '聊天尚不能调用这些工具' not in page.locator('#seed-notice').text_content()
                        checks.append('Settings show 25 independently observed modules, including profile and continuity; metadata contains no private name')
                        assert not errors,errors
                        browser.close()
                    finally:hold.set();job.close()
            finally:server.shutdown();server.server_close();thread.join(3)
        report['status']='passed'
    except Exception as error:
        report.update(status='failed',error=repr(error));raise
    finally:
        files=['apps/web/server.py','apps/web/index.html','apps/web/persona.js','apps/web/persona_routes.py','apps/web/memory.js','apps/web/continuity.js','apps/web/modules.js','runtime/node-host/jarvis_core/modules.py','runtime/node-host/jarvis_core/persona.py','runtime/node-host/jarvis_core/reference_library.py','runtime/node-host/jarvis_core/relevance.py','runtime/node-host/jarvis_core/chat.py']
        report.update(page_errors=errors,fixture_model_calls=len(calls),source_sha256={p:hashlib.sha256((ROOT/p).read_bytes()).hexdigest() for p in files})
        (args.output/'report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
        print(json.dumps(report,ensure_ascii=False))


if __name__=='__main__':main()
