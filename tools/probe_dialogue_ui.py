"""Real browser and fixed task Worker; held synthetic replies, no cloud calls."""
from pathlib import Path
import hashlib
import json
import sys
import tempfile
import threading
import time

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT),str(ROOT/'apps/web'),str(ROOT/'runtime/node-host'),str(ROOT/'adapters/computer-use')]
from jarvis_core import __version__
from tools.probe_workspace_ui import SyntheticChat
from tools.probe_parallel_runtime import fixture,PlanChat,wait
from jarvis_computer.browser import DriverJob
from server import create_server
from playwright.sync_api import sync_playwright,expect


def main():
    output=Path('H:/JarvisData/diagnostics/dialogue');output.mkdir(parents=True,exist_ok=True)
    release,task_release=threading.Event(),threading.Event()
    entered,task_entered=threading.Event(),threading.Event();calls=[];errors=[];checks=[]
    class HeldChat(SyntheticChat):
        def reply(self,message,**kwargs):
            calls.append({'message':message,'history':kwargs.get('history',[])})
            if message.startswith('等待'):
                entered.set();release.wait(30)  # Intentionally ignores cancel to test late output.
            if message=='等待失败':return dict(status='FAILED',user_message='故障测试：没有可用回复')
            return dict(status='SUCCEEDED',text='回答：'+message,provider='local',model='offline-fixture',usage={},notice=[])
    class HeldPlan(PlanChat):
        def reply(self,*args,cancel_event=None,**kwargs):
            task_entered.set()
            while not task_release.wait(.02):
                if cancel_event and cancel_event.is_set():return dict(status='CANCELLED',outcome_uncertain=False)
            return super().reply(*args,**kwargs)
    with tempfile.TemporaryDirectory(prefix='jarvis-dialogue-ui-') as directory:
        core=fixture(Path(directory));server=create_server(core=core,chat=HeldChat(),port=0)
        server.computer.sample.chat_factory=lambda *a,**kw:HeldPlan()
        thread=threading.Thread(target=server.serve_forever,kwargs={'poll_interval':.02},daemon=True);thread.start()
        try:
            with sync_playwright() as p:
                driver=DriverJob(p)
                try:
                    browser=p.chromium.launch(channel='msedge',headless=True,chromium_sandbox=True)
                    page=browser.new_page(viewport={'width':1280,'height':800});page.on('pageerror',lambda e:errors.append(str(e)))
                    page.goto('http://127.0.0.1:'+str(server.server_port)+'/')
                    page.wait_for_function('()=>Boolean(window.Dialogue&&window.Workspace&&!Workspace.isBusy()&&coreReady&&!refreshing)')
                    page.wait_for_function('()=>!document.documentElement.hasAttribute("data-brand-cinema")',timeout=10000)
                    def send(text):
                        page.locator('#message').fill(text);expect(page.locator('#send')).to_be_enabled();page.locator('#send').click()
                    send('等待第一条');assert entered.wait(2)
                    tick=time.perf_counter();send('第二条接着聊')
                    expect(page.locator('#dialogue-pending')).to_contain_text('尚未发送')
                    queued_ms=(time.perf_counter()-tick)*1000
                    assert len(calls)==1
                    send('/任务 列出样例目录文件，按类型统计并保存结果。')
                    assert task_entered.wait(5)
                    send('/进度');expect(page.locator('#conversation-task-panel')).to_be_visible()
                    page.wait_for_function('()=>document.querySelectorAll("[data-task-control=true]").length>=3')
                    page.locator('#message').fill('还在编辑的草稿')
                    assert page.locator('#messages').bounding_box()['height']>=120, page.evaluate("()=>Object.fromEntries(['#messages','.composer-wrap','#conversation-task-panel','#dialogue-pending'].map(s=>{const e=document.querySelector(s);return [s,{height:e.getBoundingClientRect().height,max:getComputedStyle(e).maxHeight}]}))")
                    page.screenshot(path=str(output/'parallel-desktop.png'))
                    release.set()
                    expect(page.locator('.message.assistant:not([data-task-control]) .bubble').last).to_have_text('回答：第二条接着聊',timeout=10000)
                    expect(page.locator('#message')).to_have_value('还在编辑的草稿')
                    assert calls[1]['history']==[{'role':'user','content':'等待第一条'},{'role':'assistant','content':'回答：等待第一条'}],calls
                    assert server.metrics.snapshot()['lanes']['task']['active']==1
                    checks.append('Queued text uses prior completed reply; draft preserved; explicit task submission/query runs during reply; task control excluded from model history')
                    # Stop the reply while its model deliberately ignores cancellation.
                    release.clear();entered.clear();send('等待取消');assert entered.wait(2)
                    page.locator('#dialogue-stop').click();send('取消后继续')
                    assert server.chat_requests.active==1
                    assert server.metrics.snapshot()['lanes']['task']['active']==1
                    expect(page.locator('#dialogue-pending')).to_contain_text('取消后继续')
                    assert len(calls)==3
                    release.set();expect(page.locator('.message.assistant:not([data-task-control]) .bubble').last).to_have_text('回答：取消后继续',timeout=10000)
                    assert page.locator('.message.assistant .bubble').filter(has_text='回答：等待取消').count()==0
                    assert all('等待取消' not in r['content'] for r in calls[-1]['history'])
                    task_release.set();wait(lambda:server.metrics.snapshot()['lanes']['task']['active']==0,seconds=20)
                    assert server.metrics.snapshot()['lanes']['task']['outcomes'].get('CONFIRMED')==1, server.metrics.snapshot()['lanes']['task']
                    checks.append('Cancel fences late reply and waits for actual worker exit; background directory task completes independently')
                    # Drop the POST response only after the server has admitted it.
                    def lose_receipt(route):route.fetch();route.abort()
                    page.route('**/api/dialogue/turns',lose_receipt,times=1)
                    before=len(calls);send('断线后查询原回执')
                    expect(page.locator('.message.assistant:not([data-task-control]) .bubble').last).to_have_text('回答：断线后查询原回执',timeout=10000)
                    assert len(calls)==before+1
                    checks.append('Lost POST response recovered through receipt GET; model called once')
                    # Bound queue, preserve overflow draft, and keep mobile controls reachable.
                    release.clear();entered.clear();send('等待容量验证');assert entered.wait(2)
                    for i in range(4):send('待发 '+str(i))
                    send('超出容量的草稿');expect(page.locator('#message')).to_have_value('超出容量的草稿')
                    expect(page.locator('#dialogue-pending')).to_contain_text('4/4')
                    expect(page.locator('#clear')).to_be_disabled()
                    page.set_viewport_size({'width':480,'height':950})
                    assert page.evaluate('document.documentElement.scrollWidth<=innerWidth')
                    box=page.locator('#send').bounding_box();assert box['y']+box['height']<=950
                    assert page.locator('#messages').bounding_box()['height']>=120, page.evaluate("()=>Object.fromEntries(['#messages','.composer-wrap','#conversation-task-panel','#dialogue-pending'].map(s=>{const e=document.querySelector(s);return [s,{height:e.getBoundingClientRect().height,max:getComputedStyle(e).maxHeight}]}))")
                    page.screenshot(path=str(output/'parallel-mobile.png'))
                    release.set();page.wait_for_function('()=>!busy&&!Dialogue.hasPending()',timeout=15000)
                    expect(page.locator('#message')).to_have_value('超出容量的草稿')
                    checks.append('Four-message outbox bounded; overflow draft retained; mobile send visible; all queued inputs drained in order')
                    # A failed preceding answer pauses pending text rather than guessing context.
                    release.clear();entered.clear();send('等待失败');assert entered.wait(2)
                    send('失败后待发');release.set()
                    expect(page.locator('#dialogue-pending')).to_contain_text('待发已暂停',timeout=10000)
                    before=len(calls);page.wait_for_timeout(700);assert len(calls)==before
                    page.get_by_role('button',name='继续发送待发消息',exact=True).click()
                    expect(page.locator('.message.assistant:not([data-task-control]) .bubble').last).to_have_text('回答：失败后待发',timeout=10000)
                    checks.append('Failed previous reply pauses outbox; explicit resume sends only the pending input')
                    settings=browser.new_page(viewport={'width':1280,'height':800});settings.on('pageerror',lambda e:errors.append(str(e)))
                    settings.goto('http://127.0.0.1:'+str(server.server_port)+'/settings#modules')
                    expect(settings.locator('#modules-view [data-runtime="dialogue"]')).to_contain_text('回复回执：0 个处理中',timeout=15000)
                    checks.append('Settings module panel displays reply receipt cache and activity without exposing text')
                    settings.close()
                    assert not errors,errors
                    browser.close()
                finally:driver.close()
        finally:release.set();task_release.set();server.shutdown();server.server_close();thread.join(3)
    paths=['runtime/node-host/jarvis_core/turns.py','apps/web/dialogue_routes.py','apps/web/dialogue.js','apps/web/index.html','apps/web/server.py','apps/web/workspace.js','apps/web/workspace.css','apps/web/resources.js','apps/web/conversation_tasks.js','tools/probe_dialogue_ui.py']
    report=dict(status='SUCCEEDED',source_version=__version__,checks=checks,enqueue_ui_ms=round(queued_ms,2),browser_errors=errors,cloud_calls=0,
        screenshots=[str(output/'parallel-desktop.png'),str(output/'parallel-mobile.png')],
        limits='Synthetic held reply/planner; real Edge and bounded directory Worker. No microphone, semantic intent routing, process isolation, durable turn replay or CPU/GPU fairness claim.',
        source_sha256={p:hashlib.sha256((ROOT/p).read_bytes()).hexdigest() for p in paths})
    (ROOT/'evals/reports/dialogue-ui-2026-10-18.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(report,ensure_ascii=False))


if __name__=='__main__':main()
