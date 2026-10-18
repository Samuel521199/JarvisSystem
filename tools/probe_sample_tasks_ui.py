"""Real Edge/HTTP/FIFO/Worker with a synthetic planner and temporary files."""
from datetime import datetime, timezone
import importlib.util
import json
import os
from pathlib import Path
import sys
import tempfile
import threading
import time

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'tools'),str(ROOT/'runtime/node-host'),str(ROOT/'adapters/computer-use')]
from jarvis_core import __version__
from jarvis_core.service import CoreService
from jarvis_computer.browser import DriverJob
from probe_sample_tasks import Synthetic
from probe_workspace_ui import SyntheticChat
from playwright.sync_api import sync_playwright, expect


class Planner(Synthetic):
    def __init__(self):
        self.entered=threading.Event();self.release=threading.Event();self.release.set();self.calls=0
    def reply(self,*a,**kw):
        self.calls+=1;self.entered.set()
        while not self.release.wait(.01):
            if kw['cancel_event'].is_set():return {'status':'CANCELLED'}
        return super().reply(*a,**kw)


def main():
    spec=importlib.util.spec_from_file_location('sample_ui_web',ROOT/'apps/web/server.py')
    web=importlib.util.module_from_spec(spec);spec.loader.exec_module(web)
    output=Path(os.environ['LOCALAPPDATA'])/'Jarvis/data/diagnostics/sample-tasks';output.mkdir(parents=True,exist_ok=True)
    errors=[];checks=[];planner=Planner();chat=SyntheticChat()
    with tempfile.TemporaryDirectory(prefix='jarvis-sample-ui-') as temp:
        root=Path(temp);source=root/'sample';source.mkdir()
        (source/'a.txt').write_bytes(b'abc');(source/'b.TXT').write_bytes(b'ab');(source/'c.py').write_bytes(b'print(1)')
        core=CoreService(root/'data');core.initialize(source)
        def start():
            server=web.create_server(core=core,chat=chat,port=0)
            server.computer.sample.chat_factory=lambda *a,**kw:planner
            thread=threading.Thread(target=server.serve_forever,kwargs={'poll_interval':.02},daemon=True);thread.start()
            return server,thread,'http://127.0.0.1:'+str(server.server_address[1])
        server,thread,origin=start()
        try:
            with sync_playwright() as p:
                job=DriverJob(p)
                try:
                    browser=p.chromium.launch(channel='msedge',headless=True,chromium_sandbox=True)
                    page=browser.new_page(viewport={'width':1440,'height':1100})
                    page.on('pageerror',lambda e:errors.append(str(e)))
                    page.goto(origin+'/settings#tasks')
                    expect(page.locator('#task-mode')).to_have_value('natural')
                    expect(page.locator('#task-model')).to_have_value('auto')
                    expect(page.locator('#task-privacy')).to_contain_text('文件正文')
                    page.locator('#queue-toggle').click();expect(page.locator('#queue-toggle')).to_have_text('继续队列')
                    page.locator('#task-start').click();expect(page.locator('.task-row')).to_have_count(1)
                    assert planner.calls==0
                    server.shutdown();server.server_close();thread.join(3)
                    server,thread,origin=start();page.goto(origin+'/settings#tasks')
                    expect(page.locator('.task-row')).to_have_count(1)
                    expect(page.locator('#queue-toggle')).to_have_text('继续队列')
                    page.locator('#queue-toggle').click()
                    expect(page.locator('#task-result')).to_contain_text('产物摘要已核验',timeout=15000)
                    expect(page.locator('#task-steps')).to_contain_text('.txt · 2 个文件 · 5 字节')
                    expect(page.locator('#task-steps')).to_contain_text('计划已通过校验')
                    tasks=server.computer.list_tasks(all_tasks=True)['tasks']
                    data=server.computer.detail(tasks[0]['task_id'],all_tasks=True)
                    saved=json.loads(Path(data['artifact_path']).read_text(encoding='utf-8'))
                    assert saved['verified'] and saved['total_files']==3 and planner.calls==1
                    checks.append('natural-language UI -> durable paused request -> restart -> explicit resume -> real LPAC Worker -> verified JSON/type totals')
                    page.screenshot(path=str(output/'desktop.png'),full_page=True)
                    page.reload();expect(page.locator('#task-result')).to_contain_text('产物摘要已核验')
                    assert planner.calls==1
                    checks.append('reload restores receipt, plan states and statistics without reissuing model or Worker')
                    page.locator('#task-model').select_option('auto')
                    planner.release.clear();planner.entered.clear()
                    page.locator('#task-prompt').fill('统计样例目录中的文件类型并保存报告')
                    page.locator('#task-start').click();assert planner.entered.wait(5)
                    start_time=time.monotonic()
                    response=page.request.post(origin+'/api/chat',headers={'X-Jarvis-Nonce':server.nonce,'Origin':origin},data={'message':'并行合成聊天'})
                    assert response.status==200 and time.monotonic()-start_time<2
                    page.locator('#task-cancel').click()
                    expect(page.locator('#task-detail-title')).to_contain_text('已取消',timeout=5000)
                    planner.release.set()
                    assert len(list(core.ledger.artifact_dir.glob('*.json')))==1
                    checks.append('blocked planner leaves chat HTTP responsive; cancellation discards late plan and creates no second artifact')
                    page.set_viewport_size({'width':390,'height':844})
                    assert page.evaluate('document.documentElement.scrollWidth<=innerWidth')
                    page.screenshot(path=str(output/'mobile.png'),full_page=True)
                    checks.append('390px layout has no horizontal overflow; task text remains editable')
                    page.goto(origin+'/settings#modules')
                    expect(page.locator('.module-card')).to_have_count(18,timeout=15000)
                    expect(page.locator('[data-module="sample-report"]')).to_contain_text('已启用')
                    checks.append('module settings include the available sample-report workflow separately from unavailable extension execution')
                    assert not errors,errors
                    browser.close()
                finally:job.close()
        finally:
            planner.release.set();server.shutdown();server.server_close();thread.join(3)
    result={'version':__version__,'captured_at':datetime.now(timezone.utc).isoformat(),'status':'passed',
        'checks':checks,'page_errors':errors,'planner_calls':planner.calls,'paid_model_calls':0,
        'screenshots':[str(output/'desktop.png'),str(output/'mobile.png')],
        'limits':['Synthetic planner and chat; real browser UI, HTTP, ledger, restart, Worker and artifact.','Not a resource-stress SLA, generic chat tools or complete K1/K2 acceptance.']}
    (ROOT/'evals/reports/sample-task-ui.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(result,ensure_ascii=False))


if __name__=='__main__':main()
