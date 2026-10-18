"""Real chat UI, archives, queue and Worker; synthetic models only."""
from datetime import datetime, timezone
import importlib.util
import json
import os
from pathlib import Path
import sys
import tempfile
import threading

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'tools'),str(ROOT/'runtime/node-host'),str(ROOT/'adapters/computer-use')]
from jarvis_core import __version__
from jarvis_core.service import CoreService
from jarvis_computer.browser import DriverJob
from probe_workspace_ui import SyntheticChat
from probe_sample_tasks_ui import Planner
from playwright.sync_api import sync_playwright, expect


class Chat(SyntheticChat):
    def __init__(self):self.requests=[];self.calls=0
    def reply(self,message,**kwargs):
        self.requests.append({'message':message,'history':kwargs.get('history')})
        return super().reply(message,**kwargs)


def main():
    spec=importlib.util.spec_from_file_location('conversation_task_web',ROOT/'apps/web/server.py')
    web=importlib.util.module_from_spec(spec);spec.loader.exec_module(web)
    output=Path(os.environ['LOCALAPPDATA'])/'Jarvis/data/diagnostics/conversation-tasks';output.mkdir(parents=True,exist_ok=True)
    checks=[];errors=[];chat=Chat();planner=Planner()
    with tempfile.TemporaryDirectory(prefix='jarvis-conversation-task-ui-') as temp:
        root=Path(temp);source=root/'sample';source.mkdir()
        (source/'a.txt').write_bytes(b'abc');(source/'b.TXT').write_bytes(b'ab')
        core=CoreService(root/'data');core.initialize(source)
        server=web.create_server(core=core,chat=chat,port=0)
        server.computer.sample.chat_factory=lambda *a,**kw:planner
        thread=threading.Thread(target=server.serve_forever,kwargs={'poll_interval':.02},daemon=True);thread.start()
        origin='http://127.0.0.1:'+str(server.server_address[1])
        try:
            with sync_playwright() as p:
                job=DriverJob(p)
                try:
                    browser=p.chromium.launch(channel='msedge',headless=True,chromium_sandbox=True)
                    page=browser.new_page(viewport={'width':1440,'height':1050})
                    page.on('pageerror',lambda e:errors.append(str(e)))
                    page.goto(origin)
                    expect(page.locator('#send')).to_be_enabled(timeout=15000)
                    expect(page.locator('.jarvis-cinema')).not_to_be_visible(timeout=15000)
                    first=page.evaluate('Workspace.currentConversation().id')
                    def send(text):
                        page.locator('#message').fill(text)
                        expect(page.locator('#message')).to_have_value(text)
                        page.locator('#composer').evaluate('e=>e.requestSubmit()')
                    send('/任务 列出样例目录文件，按类型统计并保存结果')
                    expect(page.locator('.conversation-task-card')).to_have_count(1,timeout=15000)
                    expect(page.locator('#conversation-task-list')).to_contain_text('已核验：2 个文件',timeout=15000)
                    self_task=page.locator('.conversation-task-card').get_attribute('data-task-id')
                    assert chat.calls==0 and planner.calls==1
                    with page.expect_download() as download:
                        page.get_by_role('button',name='下载已核验报告',exact=True).click()
                    saved=root/'download.json';download.value.save_as(str(saved))
                    assert json.loads(saved.read_text(encoding='utf-8'))['total_bytes']==5
                    checks.append('chat /任务 -> one persisted conversation-bound task -> real LPAC statistics -> exact JSON download')
                    expect(page.locator('#archive-tooltip')).to_contain_text('已存本机')
                    page.screenshot(path=str(output/'desktop.png'))
                    page.locator('#clear').click()
                    expect(page.locator('#composer-mode')).to_have_value('chat')
                    expect(page.locator('.conversation-task-card')).to_have_count(0)
                    other=page.evaluate('Workspace.currentConversation().id');assert first!=other
                    send('普通聊天仍可使用')
                    expect(page.locator('.message.assistant')).to_have_count(1)
                    assert chat.calls==1
                    page.locator('[data-session-id="'+first+'"]').click()
                    expect(page.locator('.conversation-task-card')).to_have_count(1)
                    page.reload();expect(page.locator('#send')).to_be_enabled()
                    expect(page.locator('.conversation-task-link')).to_have_count(1)
                    page.locator('.conversation-task-link').click()
                    expect(page.locator('#conversation-task-list')).to_contain_text('已核验：2 个文件',timeout=10000)
                    send('继续普通聊天')
                    expect(page.locator('#messages')).to_contain_text('# 项目笔记')
                    assert chat.requests[-1]['history']==[]
                    calls=chat.calls
                    send('/进度')
                    expect(page.locator('#messages')).to_contain_text('任务状态已从本机账本查询')
                    assert chat.calls==calls
                    checks.append('conversation switch isolates task list; reload restores links; control messages excluded from model history; status query uses no model')
                    planner.release.clear();planner.entered.clear()
                    send('/任务 统计样例目录并保存报告')
                    assert planner.entered.wait(5)
                    expect(page.locator('.conversation-task-card')).to_have_count(2,timeout=10000)
                    send('执行任务时仍然聊天')
                    expect(page.locator('#send')).to_have_attribute('aria-label','发送消息')
                    assert chat.calls==calls+1
                    task=next(t for t in server.computer.list_tasks(all_tasks=True)['tasks'] if t['status']=='RUNNING')
                    send('/取消 '+task['task_id'])
                    expect(page.locator('.conversation-task-card[data-task-id="'+task['task_id']+'"]')).to_contain_text('已取消',timeout=10000)
                    planner.release.set()
                    assert len(list(core.ledger.artifact_dir.glob('*.json')))==1
                    checks.append('blocked planning permits chat; /取消 cancels only the bound task and discards late result')
                    # Accept once, deliberately lose only the browser response.
                    server.computer.queue.set_paused(True)
                    posts=[]
                    def lost(route):
                        if route.request.method=='POST':
                            posts.append(route.request.post_data_json);route.fetch();route.abort('failed')
                        else:route.continue_()
                    page.route('**/api/conversation-tasks/'+first,lost)
                    send('/任务 列出文件并保存统计结果')
                    expect(page.locator('.conversation-task-card')).to_have_count(3,timeout=15000)
                    expect(page.locator('#message')).to_have_value('')
                    assert len(posts)==1
                    page.unroute('**/api/conversation-tasks/'+first,lost)
                    assert len(core.status()['tasks'])==3
                    checks.append('accepted POST with lost response is recovered by original request ID; no duplicate task or restored retry draft')
                    page.set_viewport_size({'width':390,'height':844})
                    assert page.evaluate('document.documentElement.scrollWidth<=innerWidth')
                    page.screenshot(path=str(output/'mobile.png'))
                    # Temporary conversations disclose task persistence and keep chat unarchived.
                    page.locator('#conversation-status').click();page.locator('#conversation-temporary').click()
                    page.locator('#composer-mode').select_option('task')
                    expect(page.locator('#conversation-task-note')).to_contain_text('任务仍写入本机账本')
                    assert not errors,errors
                    checks.append('390px no horizontal overflow; temporary chat clearly distinguishes persistent task audit')
                    browser.close()
                finally:job.close()
        finally:
            planner.release.set();server.shutdown();server.server_close();thread.join(3)
    report={'version':__version__,'captured_at':datetime.now(timezone.utc).isoformat(),'status':'passed',
        'checks':checks,'page_errors':errors,'planner_calls':planner.calls,'chat_calls':chat.calls,'paid_model_calls':0,
        'screenshots':[str(output/'desktop.png'),str(output/'mobile.png')],
        'limits':['Real UI/HTTP/archive/queue/Worker/artifact paths; all model replies synthetic.','Fixed sample reports only; no arbitrary chat-selected tools, MCP runtime or offline model quality claim.']}
    (ROOT/'evals/reports/conversation-task-ui.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(report,ensure_ascii=False))


if __name__=='__main__':main()
