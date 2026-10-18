"""Work-linked continuity in real browser, or one explicitly requested live model call."""
import argparse
from datetime import datetime,timezone
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import threading
import time
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'tests'),str(ROOT/'tools'),str(ROOT/'runtime/node-host'),str(ROOT/'adapters/computer-use')]
from jarvis_core import __version__
from jarvis_core.chat import ChatService
from jarvis_core.continuity import ContinuityStore
from jarvis_core.service import CoreService
from jarvis_core.evolution.demand import ConversationGrowth
from jarvis_core.work_state import WorkState
from probe_sample_tasks_ui import Planner
from jarvis_computer.browser import DriverJob
from playwright.sync_api import sync_playwright,expect


def live(output):
    import test_work_continuity as fixtures
    fixture=fixtures.WorkContinuityTests()
    try:
        fixture.setUp();job=fixture.fx.preview()
        fixture.link(fixture.task,{'kind':'growth','id':job['id'],'conversation_id':fixture.cid})
        fixture.change('permissions',providers=['vertex'])
        chat=ChatService(fixture.core)
        result=chat.reply('只根据关联执行记录返回 JSON 数组，每项仅含 kind 和 state。忽略主人旧进展中的推断，不要执行工作。',
            provider='vertex',model='gemini-3.1-pro-preview',personal_context={'temporary':False},
            memory_context={'enabled':True,'project_id':None},continuity_context=fixture.ctx,_route_attempt_limit=1)
        (output/'response.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
        text=result.get('text','').strip()
        if text.startswith('```'):text=text.split('\n',1)[1].rsplit('```',1)[0].strip()
        try:answer=json.loads(text)
        except ValueError:answer=None
        passed=result['status']=='SUCCEEDED' and isinstance(answer,list) and len(answer)==2 and {r.get('kind'):r.get('state') for r in answer if isinstance(r,dict)}=={'task':'completed','growth':'pending'}
        return {'status':'passed' if passed else 'failed','live_model':True,'route':'vertex::gemini-3.1-pro-preview',
            'answer':answer,'request_status':result['status'],'error':result.get('error'),'usage':result.get('usage'),
            'history_info':result.get('history_info'),'scope':'Synthetic files/owner note; real completed LPAC task and persistent proposed growth job; real chat model; no growth execution.'}
    finally:fixture.doCleanups()


def browser_probe(output):
    spec=importlib.util.spec_from_file_location('work_continuity_web',ROOT/'apps/web/server.py')
    web=importlib.util.module_from_spec(spec);spec.loader.exec_module(web)
    calls,errors,checks=[],[],[]
    def probe(config,provider,message,*args,**kwargs):
        calls.append({'message':message,'history':kwargs['history']})
        return {'status':'SUCCEEDED','text':'已核对关联执行状态。','provider':provider,'model':config['providers'][provider]['model']}
    with tempfile.TemporaryDirectory(prefix='jarvis-work-continuity-') as temporary:
        base=Path(temporary);source=base/'source';source.mkdir();(source/'a.txt').write_bytes(b'abc')
        core=CoreService(base/'data');core.initialize(source);chat=ChatService(core)
        server=web.create_server(core=core,chat=chat,port=0);server.computer.queue.set_paused(True)
        planner=Planner();server.computer.sample.chat_factory=lambda *a,**kw:planner
        thread=threading.Thread(target=server.serve_forever,kwargs={'poll_interval':.02},daemon=True);thread.start()
        try:
            with patch('jarvis_core.chat.gateway.probe',side_effect=probe),sync_playwright() as p:
                driver=DriverJob(p)
                try:
                    browser=p.chromium.launch(channel='msedge',headless=True,chromium_sandbox=True)
                    page=browser.new_page(viewport={'width':1440,'height':1000});page.on('pageerror',lambda e:errors.append(str(e)))
                    page.goto('http://127.0.0.1:'+str(server.server_port));expect(page.locator('#send')).to_be_enabled();expect(page.locator('.jarvis-cinema')).not_to_be_visible(timeout=15000)
                    cid=page.evaluate('Workspace.currentConversation().id')
                    def send(text,expected=None):
                        before=page.locator('.message.assistant').count();page.locator('#message').fill(text);page.locator('#composer').evaluate('e=>e.requestSubmit()')
                        if expected:
                            expect(page.locator('.message.assistant')).to_have_count(before+1)
                            expect(page.locator('.message.assistant').last).to_contain_text(expected)
                            expect(page.locator('#send')).to_have_attribute('aria-label','发送消息')
                            expect(page.locator('#conversation-status')).to_have_attribute('data-state','saved')
                    def panel():
                        page.locator('#open-memory').click();page.get_by_role('button',name='接续',exact=True).click()
                        expect(page.locator('.continuity-card')).to_have_count(1)
                    send('/任务 列出样例目录文件并保存报告')
                    expect(page.locator('.conversation-task-card')).to_have_count(1)
                    tid=page.locator('.conversation-task-card').get_attribute('data-task-id')
                    send('保存接续：报告=报告仍未完成｜核对结果后决定下一步','已保存接续')
                    panel();page.get_by_role('button',name='关联任务与实际进展',exact=True).click()
                    page.locator('[data-work-id="'+tid+'"]').check();page.get_by_role('button',name='保存任务关联',exact=True).click()
                    expect(page.locator('#continuity-status')).to_contain_text('任务关联已保存')
                    page.locator('.continuity-card input[value="vertex"]').check();page.get_by_role('button',name='保存许可',exact=True).click();expect(page.locator('#continuity-status')).to_contain_text('接续已更新')
                    assert not calls and planner.calls==0
                    page.locator('#memory-close').click();page.locator('#clear').click()
                    send('继续话题：报告','待办');send('现在实际进展如何？','已核对关联执行状态')
                    assert '"state":"pending"' in calls[-1]['message'] and calls[-1]['history']==[]
                    server.computer.queue.set_paused(False)
                    deadline=time.monotonic()+15
                    while core.ledger.record(task_id=tid)['task']['status']!='SUCCEEDED' and time.monotonic()<deadline:time.sleep(.05)
                    assert core.ledger.record(task_id=tid)['task']['status']=='SUCCEEDED'
                    send('再核对一次实际结果','已核对关联执行状态')
                    assert '"state":"completed"' in calls[-1]['message'] and calls[-1]['history']==[]
                    checks.append('Real queued task linked through UI; fresh conversation sees pending then LPAC-completed; old pending answer is filtered without changing owner note')
                    archived_count=page.locator('.message.assistant').count()
                    page.reload();expect(page.locator('.message.assistant')).to_have_count(archived_count)
                    expect(page.locator('#send')).to_be_enabled();expect(page.locator('.jarvis-cinema')).not_to_be_visible(timeout=15000)
                    send('刷新以后继续核对','已核对关联执行状态')
                    assert calls[-1]['history'] and '"state":"completed"' in calls[-1]['message']
                    # Attach an actual persistent proposal from the original conversation.
                    bridge=ConversationGrowth(core,server.evolution,server.conversation_tasks)
                    job=bridge.propose(cid,{'request_id':__import__('uuid').uuid4().hex,'prompt':'导出 TSV'})
                    panel();page.get_by_role('button',name='关联任务与实际进展 · 1',exact=True).click()
                    expect(page.locator('.continuity-work')).to_contain_text('已完成且交付核验通过')
                    page.locator('[data-work-id="'+job['id']+'"]').check();page.get_by_role('button',name='保存任务关联',exact=True).click();expect(page.locator('#continuity-status')).to_contain_text('任务关联已保存')
                    page.get_by_role('button',name='关联任务与实际进展 · 2',exact=True).click()
                    expect(page.locator('.continuity-work')).to_contain_text('待办')
                    page.locator('.continuity-work').scroll_into_view_if_needed()
                    page.screenshot(path=str(output/'desktop.png'))
                    page.set_viewport_size({'width':390,'height':844});page.locator('.continuity-work').scroll_into_view_if_needed();assert page.evaluate('document.documentElement.scrollWidth<=innerWidth');page.screenshot(path=str(output/'mobile.png'))
                    page.locator('#memory-close').click();send('两项关联分别是什么状态？','已核对关联执行状态')
                    assert '"kind":"growth"' in calls[-1]['message'] and '"state":"pending"' in calls[-1]['message'] and calls[-1]['history']==[]
                    bridge.cancel(cid,job['id'],{});send('再次核对两项','已核对关联执行状态')
                    assert '"state":"cancelled"' in calls[-1]['message'] and calls[-1]['history']==[]
                    checks.append('Reload keeps state fingerprints; explicit growth link shows pending then cancelled without execution; changed state invalidates prior derived turns')
                    panel();page.get_by_role('button',name='关联任务与实际进展 · 2',exact=True).click()
                    expect(page.locator('[data-work-id]')).to_have_count(2)
                    for item in page.locator('[data-work-id]').all():item.uncheck()
                    page.get_by_role('button',name='保存任务关联',exact=True).click();expect(page.locator('#continuity-status')).to_contain_text('任务关联已保存')
                    page.locator('#memory-close').click();send('取消关联后聊些别的','已核对关联执行状态')
                    assert '"linked_work":' not in calls[-1]['message'] and calls[-1]['history']==[]
                    assert server.evolution.store.job(job['id'])['status']=='CANCELLED' and not server.evolution.store.job(job['id'])['attempts']
                    assert not errors,errors
                    checks.append('Explicit unlink clears work dependencies, not underlying ledgers; 1440/390px no overflow; no page errors or paid calls')
                    browser.close()
                finally:driver.close()
        finally:server.shutdown();server.server_close();thread.join(3)
    return {'status':'passed','live_model':False,'checks':checks,'page_errors':errors,'synthetic_chat_calls':len(calls),'paid_calls':0,
        'screenshots':[str(output/name) for name in ('desktop.png','mobile.png')]}


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--output',type=Path,required=True);parser.add_argument('--live',action='store_true')
    args=parser.parse_args();args.output.mkdir(parents=True,exist_ok=False)
    report={'version':__version__,'captured_at':datetime.now(timezone.utc).isoformat(),**(live(args.output) if args.live else browser_probe(args.output))}
    (args.output/'report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(report,ensure_ascii=False));return 0 if report['status']=='passed' else 1


if __name__=='__main__':raise SystemExit(main())
