"""Real Edge and HTTP review/confirm/cancel on disposable data and model fixtures."""
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

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'runtime/node-host'),str(ROOT/'adapters/computer-use')]
from jarvis_core import __version__
from jarvis_core.chat import ChatService
from jarvis_core.service import CoreService
from jarvis_core.memory import MemoryStore
from jarvis_computer.browser import DriverJob
from playwright.sync_api import sync_playwright, expect


def run(out, report):
    spec=importlib.util.spec_from_file_location('semantic_ui_web',ROOT/'apps/web/server.py')
    web=importlib.util.module_from_spec(spec);spec.loader.exec_module(web)
    calls=[];held=threading.Event();entered=threading.Event();release=threading.Event();invalid=threading.Event()
    answer={'candidates':[{'segment':0,'title':'回答风格','content':'主人希望先给出简短结论','category':'preference','subject_label':''},
                           {'segment':1,'title':'客户口味','content':'老王喜欢咖啡','category':'third_party','subject_label':'老王'}]}
    def model(config,provider,prompt,*args,**kwargs):
        semantic=kwargs.get('instructions','').startswith('Extract review-only')
        calls.append({'semantic':semantic,'provider':provider,'prompt':prompt,'history':kwargs.get('history')})
        if semantic and held.is_set():entered.set();release.wait(8)
        return {'status':'SUCCEEDED','text':'bad-json' if semantic and invalid.is_set() else json.dumps(answer,ensure_ascii=False) if semantic else '合成验证回答。',
                'provider':provider,'model':config['providers'][provider]['model'],'usage':{'input_tokens':100,'output_tokens':80}}
    with tempfile.TemporaryDirectory(prefix='jarvis-semantic-ui-') as tmp:
        base=Path(tmp);folder=base/'sample';folder.mkdir()
        core=CoreService(base/'data');core.initialize(folder);chat=ChatService(core)
        memory=MemoryStore(core);memory.command('remember','隐私','PRIVATE_SENTINEL',request_id='a'*32)
        server=web.create_server(core=core,chat=chat,port=0)
        if server.evolution:server.evolution.close()
        thread=threading.Thread(target=server.serve_forever,kwargs={'poll_interval':.02},daemon=True);thread.start()
        try:
            # Dialogue now uses a process transport. Install the fixture at both
            # boundaries; a parent-only gateway patch does not reach a child.
            with patch('jarvis_core.chat.gateway.probe',side_effect=model), \
                 patch.object(chat.dialogue_models,'reply',side_effect=lambda owner,*args,**kwargs:owner.reply(*args,**kwargs)), \
                 patch.object(chat.dialogue_models,'probe',side_effect=model), \
                 patch('jarvis_core.dialogue_process.ProcessJob',side_effect=AssertionError('UI fixture must not start real model transport')), \
                 sync_playwright() as p:
                driver=DriverJob(p)
                try:
                    browser=p.chromium.launch(channel='msedge',headless=True,chromium_sandbox=True)
                    page=browser.new_page(viewport={'width':1440,'height':1080});page.on('pageerror',lambda e:report['page_errors'].append(str(e)))
                    page.goto('http://127.0.0.1:'+str(server.server_port))
                    expect(page.locator('#send')).to_be_enabled();expect(page.locator('.jarvis-cinema')).not_to_be_visible(timeout=15000)
                    page.locator('#message').fill('长篇答复读着累，给我的结论请尽量简洁。客户老王喜欢咖啡。')
                    page.locator('#composer').evaluate('e=>e.requestSubmit()')
                    expect(page.locator('.message.assistant')).to_have_count(1)
                    expect(page.locator('#conversation-status')).to_have_attribute('data-state','saved')
                    page.locator('.candidate-entry').first.click()
                    expect(page.locator('#candidate-list .candidate-card')).to_have_count(0)
                    assert len(calls)==1
                    page.locator('#candidate-model').select_option('vertex/gemini-3.1-pro-preview')
                    expect(page.locator('#candidate-disclosure')).to_contain_text('不附带历史')
                    page.locator('#candidate-generate').click()
                    expect(page.locator('#candidate-list .candidate-card')).to_have_count(2)
                    assert len(calls)==2 and calls[-1]['history']==[] and 'PRIVATE_SENTINEL' not in calls[-1]['prompt']
                    assert len(memory.list()['facts'])==1
                    first=page.locator('#candidate-list .candidate-card').first
                    expect(first.locator('blockquote')).to_contain_text('长篇答复')
                    first.get_by_label('名称',exact=True).fill('我喜欢的回答方式')
                    first.get_by_label('用于协助我的工作',exact=True).check()
                    def lost(route):route.fetch();route.abort('failed')
                    page.route('**/api/personal-candidates/semantic-resolve',lost)
                    first.get_by_role('button',name='确认并保存',exact=True).click()
                    expect(first).to_contain_text('重试相同内容使用同一回执')
                    page.unroute('**/api/personal-candidates/semantic-resolve',lost)
                    first.get_by_role('button',name='重试同一次保存',exact=True).click();expect(first).to_contain_text('此确认已处理')
                    saved=next(x for x in memory.list()['facts'] if x['document']['title']=='我喜欢的回答方式')
                    assert saved['revision']==1 and saved['document']['providers']==[]
                    assert saved['document']['classification']['uses']==['personal_chat','work_assist']
                    second=page.locator('#candidate-list .candidate-card').nth(1)
                    expect(second.get_by_label('类型 / 主体',exact=True)).to_have_value('third_party')
                    expect(second.get_by_label('他人或角色名称',exact=True)).to_have_value('老王')
                    expect(second.get_by_label('用于我的日常聊天',exact=True)).not_to_be_checked()
                    second.get_by_label('名称',exact=True).fill('尚未保存的客户资料')
                    private=next(x for x in memory.list()['facts'] if 'PRIVATE_SENTINEL' in x['document']['content'])
                    memory.put(private['id'],{'revision':private['revision'],
                        'document':{**private['document'],'content':'PRIVATE_SENTINEL_CORRECTED'}})
                    calls_before=len(calls)
                    with page.expect_response(lambda r:r.url.endswith('/api/personal-candidates/semantic-review')) as response:
                        second.get_by_role('button',name='确认并保存',exact=True).click()
                    assert response.value.status==409 and response.value.json()['error_category']=='candidate_review_changed'
                    expect(second.get_by_role('button',name='确认并保存',exact=True)).to_be_disabled()
                    expect(second.get_by_label('名称',exact=True)).to_have_value('尚未保存的客户资料')
                    expect(page.locator('#personal-candidates')).to_contain_text('不会自动调用模型')
                    assert len(calls)==calls_before and len(memory.list()['facts'])==2
                    page.screenshot(path=str(out/'semantic-stale.png'))
                    page.locator('#candidate-generate').click()
                    expect(page.locator('#candidate-list .candidate-card')).to_have_count(2)
                    second=page.locator('#candidate-list .candidate-card').nth(1)
                    expect(second.get_by_role('button',name='确认并保存',exact=True)).to_be_enabled()
                    second.get_by_role('button',name='忽略',exact=True).click()
                    page.screenshot(path=str(out/'semantic-desktop.png'))
                    page.set_viewport_size({'width':390,'height':844})
                    assert page.evaluate('document.documentElement.scrollWidth<=innerWidth')
                    assert page.locator('#personal-candidates').evaluate('e=>e.scrollWidth<=e.clientWidth')
                    page.locator('#personal-candidates').evaluate('e=>e.scrollTop=0');page.screenshot(path=str(out/'semantic-mobile.png'))
                    # A fresh paraphrase is still the same sentence after forgetting.
                    memory.delete(saved['id'],{'revision':saved['revision']})
                    answer['candidates'][0]['title']='换一种标题'
                    page.locator('#candidate-generate').click();expect(page.locator('#candidate-list .candidate-card')).to_have_count(2)
                    page.locator('#candidate-list .candidate-card').first.get_by_role('button',name='确认并保存',exact=True).click()
                    expect(page.locator('#candidate-list .candidate-card').first).to_contain_text('已被纠正或忘记')
                    assert len(memory.list()['facts'])==1
                    held.set();page.locator('#candidate-generate').click();assert entered.wait(5)
                    page.locator('#candidate-stop').click();expect(page.locator('#candidate-generate')).to_be_enabled()
                    expect(page.locator('#personal-candidates')).to_contain_text('已停止接收候选')
                    release.set()
                    assert server.slots.acquire(timeout=5) and server.slots.acquire(timeout=5)
                    server.slots.release();server.slots.release()
                    expect(page.locator('#candidate-list .candidate-card')).to_have_count(0)
                    held.clear();invalid.set();page.locator('#candidate-generate').click()
                    expect(page.locator('#personal-candidates')).to_contain_text('模型未返回合格的候选格式')
                    expect(page.locator('#personal-candidates')).to_contain_text('本次用量')
                    assert len(memory.list()['facts'])==1
                    page.locator('#personal-candidates').get_by_role('button',name='关闭',exact=True).click()
                    assert not report['page_errors']
                    report['checks']=['Rule preview has no extra model call; explicit provider and scope disclosure',
                        'Actual extraction transport has only selected source, no history or private fact',
                        'Review edits classification and both uses; lost response creates exactly one revision',
                        'Third-party remains distinct and stored-only by default; ignore does not write',
                        'Memory correction rejects old preview with HTTP 409; edits stay visible, save is disabled, explicit regeneration restores it without automatic model use',
                        'Same sentence cannot resurrect forgotten fact with new model wording',
                        '390px and desktop fit; stop clears pending candidates and shares admission slots',
                        'Malformed model output shows failure and actual returned usage without saving']
                    assert chat.dialogue_models.completed==0
                    report['fixture_model_calls']=len(calls);report['facts_after']=len(memory.list()['facts'])
                    report['dialogue_transport']='Explicit fixture; no model child started. Supervisor has separate tests.'
                    browser.close()
                except Exception:
                    if 'page' in locals():page.screenshot(path=str(out/'failure.png'))
                    raise
                finally:
                    release.set()
                    if 'browser' in locals():browser.close()
                    driver.close()
        finally:server.shutdown();server.server_close();thread.join(5)


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args();args.output.mkdir(parents=True,exist_ok=False)
    report={'version':__version__,'captured_at':datetime.now(timezone.utc).isoformat(),'checks':[],
            'page_errors':[],'real_model_calls':0,'user_data_modified':False}
    try:run(args.output,report);report['status']='passed'
    except Exception:report['status']='failed';report['failure']=traceback.format_exc()
    (args.output/'report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(report,ensure_ascii=False));return 0 if report['status']=='passed' else 1


if __name__=='__main__':raise SystemExit(main())
