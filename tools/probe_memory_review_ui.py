"""Exercise local memory decisions in real Edge, with disposable data and model fixtures."""
import argparse
from datetime import datetime, timezone
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import threading
import traceback
from unittest.mock import patch
import uuid

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT/'runtime/node-host'), str(ROOT/'adapters/computer-use')]
from jarvis_core import __version__
from jarvis_core.chat import ChatService
from jarvis_core.memory import MemoryStore
from jarvis_core.service import CoreService
from jarvis_computer.browser import DriverJob
from playwright.sync_api import sync_playwright, expect


def run(out, report, mode='semantic'):
    spec = importlib.util.spec_from_file_location('memory_review_ui_web', ROOT/'apps/web/server.py')
    web = importlib.util.module_from_spec(spec); spec.loader.exec_module(web)
    calls = []
    answer = {'candidates':[{'segment':0, 'title':'新的饮品记录', 'content':'主人平时喜欢无糖茶',
                             'category':'preference', 'subject_label':''}]}
    def model(config, provider, prompt, *args, **kwargs):
        semantic = kwargs.get('instructions','').startswith('Extract review-only')
        calls.append({'semantic':semantic, 'prompt':prompt})
        return {'status':'SUCCEEDED', 'text':json.dumps(answer,ensure_ascii=False) if semantic else '合成验证回答。',
                'provider':provider, 'model':config['providers'][provider]['model']}
    with tempfile.TemporaryDirectory(prefix='jarvis-memory-review-ui-') as tmp:
        base=Path(tmp); folder=base/'sample'; folder.mkdir()
        core=CoreService(base/'data'); core.initialize(folder); chat=ChatService(core); memory=MemoryStore(core)
        subject='我' if mode=='rule' else '主人'
        old=memory.put(uuid.uuid4().hex, {'revision':0, 'document':{
            'title':'旧饮品偏好', 'content':subject+'平时喜欢黑咖啡', 'project_id':None, 'providers':['vertex'],
            'classification':{'kind':'preference','subject':'owner','subject_label':'',
                'uses':['personal_chat','work_assist'], 'expires_at':None}}})
        server=web.create_server(core=core,chat=chat,port=0)
        if server.evolution:server.evolution.close()
        thread=threading.Thread(target=server.serve_forever,kwargs={'poll_interval':.02},daemon=True);thread.start()
        try:
            with patch('jarvis_core.chat.gateway.probe',side_effect=model), \
                 patch.object(chat.dialogue_models,'reply',side_effect=lambda owner,*args,**kwargs:owner.reply(*args,**kwargs)), \
                 patch.object(chat.dialogue_models,'probe',side_effect=model), \
                 patch('jarvis_core.dialogue_process.ProcessJob',side_effect=AssertionError('No real transport in fixture')), \
                 sync_playwright() as p:
                driver=DriverJob(p); browser=p.chromium.launch(channel='msedge',headless=True,chromium_sandbox=True)
                page=browser.new_page(viewport={'width':1440,'height':1080}); page.on('pageerror',lambda e:report['page_errors'].append(str(e)))
                try:
                    page.goto('http://127.0.0.1:'+str(server.server_port))
                    expect(page.locator('#send')).to_be_enabled();expect(page.locator('.jarvis-cinema')).not_to_be_visible(timeout=15000)
                    def extract(text, count):
                        page.locator('#message').fill(text);page.locator('#composer').evaluate('e=>e.requestSubmit()')
                        expect(page.locator('.message.assistant')).to_have_count(count)
                        expect(page.locator('#conversation-status')).to_have_attribute('data-state','saved')
                        page.locator('.candidate-entry').last.click()
                        if mode=='semantic':
                            page.locator('#candidate-model').select_option('vertex/gemini-3.1-pro-preview')
                            page.locator('#candidate-generate').click()
                        expect(page.locator('#candidate-list .candidate-card')).to_have_count(1)
                        return page.locator('#candidate-list .candidate-card').first
                    card=extract('我平时喜欢无糖茶。' if mode=='rule' else '以前我喜欢黑咖啡，现在改为无糖茶。',1)
                    before=len(calls);card.get_by_role('button',name='核对已有记忆',exact=True).click()
                    expect(card.locator('.candidate-existing')).to_contain_text('相关内容 · 待核对' if mode=='rule' else '可能发生变化')
                    assert len(calls)==before and memory.list()['facts'][0]['revision']==1
                    card.get_by_label('名称',exact=True).fill('我编辑的候选名称')
                    expect(card.locator('.candidate-review')).not_to_be_visible()
                    card.get_by_role('button',name='确认并保存',exact=True).click()
                    expect(card.locator('.candidate-existing')).to_contain_text(subject+'平时喜欢黑咖啡')
                    card.get_by_text('查看已有记忆的来源与权限',exact=True).click()
                    expect(card).to_contain_text('工作协助')
                    card.locator('.candidate-review').scroll_into_view_if_needed();page.screenshot(path=str(out/'review-desktop.png'))
                    page.set_viewport_size({'width':390,'height':844})
                    card.locator('.candidate-review').scroll_into_view_if_needed();page.screenshot(path=str(out/'review-mobile.png'))
                    assert page.evaluate('document.documentElement.scrollWidth<=innerWidth')
                    assert page.locator('#personal-candidates').evaluate('e=>e.scrollWidth<=e.clientWidth')
                    page.set_viewport_size({'width':1440,'height':1080})
                    def lost(route):route.fetch();route.abort('failed')
                    page.route('**/api/personal-candidates/'+mode+'-resolve',lost)
                    card.get_by_role('button',name='用上方内容更新这条',exact=True).click()
                    expect(card.get_by_role('button',name='重试同一次保存',exact=True)).to_be_visible()
                    page.unroute('**/api/personal-candidates/'+mode+'-resolve',lost)
                    card.get_by_role('button',name='重试同一次保存',exact=True).click();expect(card).to_contain_text('此确认已处理')
                    updated=memory.list()['facts'][0]
                    assert updated['revision']==2 and updated['document']==old['document']|{'content':subject+'平时喜欢无糖茶'}
                    assert len(calls)==before
                    page.locator('#personal-candidates').get_by_role('button',name='关闭',exact=True).click()
                    card=extract('我平时喜欢无糖茶。',2);before=len(calls)
                    card.get_by_role('button',name='确认并保存',exact=True).click()
                    expect(card.locator('.candidate-existing')).to_contain_text('重复表达')
                    expect(card.get_by_role('button',name='另存一条新记忆',exact=True)).to_have_count(0)
                    card.get_by_role('button',name='沿用已有记忆',exact=True).click();expect(card).to_contain_text('没有新增或改写事实')
                    current=memory.list()['facts'];assert len(current)==1 and current[0]==updated
                    assert len(calls)==before
                    page.locator('#personal-candidates').get_by_role('button',name='关闭',exact=True).click()
                    answer['candidates'][0]['content']='主人不再喝茶'
                    card=extract('我平时喜欢绿茶。' if mode=='rule' else '以前我喜欢茶，现在不再喝茶。',3)
                    card.get_by_role('button',name='核对已有记忆',exact=True).click()
                    expect(card.locator('.candidate-existing')).to_contain_text('相关内容 · 待核对' if mode=='rule' else '可能发生变化')
                    card.get_by_role('button',name='忽略',exact=True).click()
                    assert memory.list()['facts']==current
                    if mode=='rule':
                        page.locator('#candidate-reload-local').click()
                        card=page.locator('#candidate-list .candidate-card').first
                        card.get_by_label('名称',exact=True).fill('仍未保存的编辑')
                        memory.put(updated['id'],{'revision':updated['revision'],
                            'document':{**updated['document'],'content':'我平时喜欢柠檬茶'}})
                        before=len(calls)
                        with page.expect_response(lambda r:r.url.endswith('/rule-review')) as response:
                            card.get_by_role('button',name='确认并保存',exact=True).click()
                        assert response.value.status==409
                        expect(card.get_by_role('button',name='确认并保存',exact=True)).to_be_disabled()
                        expect(card.get_by_label('名称',exact=True)).to_have_value('仍未保存的编辑')
                        page.screenshot(path=str(out/'rule-stale.png'))
                        page.locator('#candidate-reload-local').click()
                        expect(card.get_by_role('button',name='确认并保存',exact=True)).to_be_enabled()
                        card.get_by_role('button',name='核对已有记忆',exact=True).click()
                        expect(card.locator('.candidate-existing')).to_contain_text('我平时喜欢柠檬茶')
                        assert len(calls)==before and len(memory.list()['facts'])==1
                        page.locator('#personal-candidates').get_by_role('button',name='关闭',exact=True).click()
                        card=extract('我们下次继续讨论旅行计划。',4)
                        expect(card).to_contain_text('候选未结事项')
                        card.get_by_role('button',name='确认并保存',exact=True).click()
                        expect(card).to_contain_text('已保存未结事项')
                        assert not any(c['semantic'] for c in calls)
                    assert not report['page_errors'] and chat.dialogue_models.completed==0
                    report.update(status='passed',mode=mode,fixture_model_calls=len(calls),checks=[
                        'Explicit local review has zero model calls and no fact writes',
                        'Edited fields invalidate local review; stale target is never silently reused',
                        'Shows original/new text, relation and old permissions at desktop and 390px',
                        'Replacement response loss retries once: same ID, revision 2, old permissions and title preserved',
                        'Duplicate from a new message keeps original source/document/revision; no second fact',
                        'Ignore changed preference leaves stored fact unchanged'])
                    if mode=='rule':report['checks'] += [
                        'Correction invalidates old preview with 409; edited fields retained and save disabled',
                        'Explicit local reload refreshes watermark without extraction model calls',
                        'Continuity candidate still saves through its original independent path']
                except Exception:
                    page.screenshot(path=str(out/'failure.png'));raise
                finally:browser.close();driver.close()
        finally:server.shutdown();server.server_close();thread.join(5)


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--mode',choices=['semantic','rule'],default='semantic')
    args=parser.parse_args();args.output.mkdir(parents=True,exist_ok=False)
    report={'version':__version__,'captured_at':datetime.now(timezone.utc).isoformat(),
            'page_errors':[],'real_model_calls':0,'user_data_modified':False}
    try:run(args.output,report,args.mode)
    except Exception:report.update(status='failed',failure=traceback.format_exc())
    (args.output/'report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(report,ensure_ascii=False));return 0 if report['status']=='passed' else 1


if __name__=='__main__':raise SystemExit(main())
