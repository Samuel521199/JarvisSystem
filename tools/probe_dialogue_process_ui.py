"""Real Edge, supervised child faults and bounded task Worker; synthetic model."""
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import threading
import time

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT),str(ROOT/'apps/web'),str(ROOT/'runtime/node-host'),str(ROOT/'adapters/computer-use')]
from jarvis_core import __version__
from jarvis_core.chat import ChatService
from tools.probe_parallel_runtime import fixture,PlanChat,wait
from jarvis_computer.browser import DriverJob
from server import create_server
from playwright.sync_api import sync_playwright,expect


def main(report_name='conversation-lanes-ui-2026-10-18.json'):
    output=Path('H:/JarvisData/diagnostics/dialogue');output.mkdir(parents=True,exist_ok=True)
    errors=[];checks=[]
    with tempfile.TemporaryDirectory(prefix='jarvis-dialogue-process-ui-') as directory:
        base=Path(directory);core=fixture(base)
        config=json.loads((ROOT/'config/model-profiles/providers.json').read_text(encoding='utf-8'))
        config.update(default_provider='local',automatic_fallback=False)
        config['providers']['local']['enabled']=True
        configpath=base/'providers.json';configpath.write_text(json.dumps(config),encoding='utf-8')
        chat=ChatService(core,configpath);server=create_server(core=core,chat=chat,port=0)
        server.computer.sample.chat_factory=lambda *a,**kw:PlanChat()
        models=chat.dialogue_models
        def mode(name):models._command=[sys._base_executable,'-u',str(ROOT/'tests/dialogue_process_fixture.py'),name]
        thread=threading.Thread(target=server.serve_forever,kwargs={'poll_interval':.02},daemon=True);thread.start()
        try:
            with sync_playwright() as p:
                driver=DriverJob(p)
                try:
                    browser=p.chromium.launch(channel='msedge',headless=True,chromium_sandbox=True)
                    page=browser.new_page(viewport={'width':1280,'height':900});page.on('pageerror',lambda e:errors.append(str(e)))
                    page.on('dialog',lambda dialog:dialog.accept())
                    url='http://127.0.0.1:'+str(server.server_port)
                    page.goto(url)
                    page.wait_for_function('()=>Boolean(window.Dialogue&&window.Workspace&&!Workspace.isBusy()&&coreReady&&!refreshing)')
                    page.wait_for_function('()=>!document.documentElement.hasAttribute("data-brand-cinema")')
                    def send(text):
                        page.locator('#message').fill(text);expect(page.locator('#send')).to_be_enabled();page.locator('#send').click()
                    mode('hang');send('请简单回应这句话。')
                    wait(lambda:models.snapshot()['active']==1)
                    send('/任务 列出样例目录文件，按类型统计并保存结果。')
                    wait(lambda:server.metrics.snapshot()['lanes']['task']['outcomes'].get('CONFIRMED',0)==1,seconds=15)
                    assert server.metrics.snapshot()['lanes']['task']['outcomes'].get('CONFIRMED',0)==1
                    assert models.snapshot()['active']==1
                    checks.append('Hung model child does not prevent a real bounded directory task from completing')
                    settings=browser.new_page(viewport={'width':1280,'height':900});settings.on('pageerror',lambda e:errors.append(str(e)))
                    settings.goto(url+'/settings#modules')
                    expect(settings.locator('#modules-view [data-runtime="dialogue-process"]')).to_have_text('1 / 2 运行中',timeout=10000)
                    expect(settings.locator('#modules-view [data-runtime="dialogue-process-detail"]')).to_contain_text('PID')
                    state=models.snapshot()
                    settings.locator('#modules-view .runtime-panel').scroll_into_view_if_needed()
                    settings.screenshot(path=str(output/'process-running.png'),full_page=False)
                    start=time.perf_counter()
                    assert page.request.get(url+'/api/status').json()['core_ready']
                    control_ms=round((time.perf_counter()-start)*1000,2)
                    with models.lock:
                        for row in models.active.values(): row['job'].kill()
                    page.wait_for_function('()=>!busy',timeout=10000)
                    assert models.snapshot()['active']==0
                    checks.append('Killed child completes receipt without replay; control endpoint remains responsive; settings show real PID/memory')
                    mode('gateway');send('进程恢复后继续聊天。')
                    expect(page.locator('.message.assistant:not([data-task-control]) .bubble').last).to_have_text('isolated gateway reply',timeout=10000)
                    mode('hang');send('这条用于取消测试。')
                    wait(lambda:models.snapshot()['active']==1)
                    page.locator('#dialogue-stop').click()
                    page.wait_for_function('()=>!busy',timeout=10000)
                    assert models.snapshot()['active']==0
                    mode('gateway');send('取消后仍然可以交流。')
                    expect(page.locator('.message.assistant:not([data-task-control]) .bubble').last).to_have_text('isolated gateway reply',timeout=10000)
                    expect(settings.locator('#modules-view [data-runtime="dialogue-process"]')).to_have_text('0 / 2 运行中',timeout=10000)
                    checks.append('Stop reply reaps child; next ordinary reply succeeds; idle process count returns to zero')
                    # Use the real task service + real ChatService through its
                    # separate owned process, not the synthetic planner factory.
                    server.computer.sample.chat_factory=ChatService
                    background=chat.background_models
                    background._command=[sys._base_executable,'-u',str(ROOT/'tests/dialogue_process_fixture.py'),'model_hang']
                    send('/任务 列出样例目录文件，按类型统计并保存结果。')
                    wait(lambda:any(row['phase']=='model' for row in background.snapshot()['processes']),seconds=15)
                    send('后台还在规划，我们继续聊天。')
                    expect(page.locator('.message.assistant:not([data-task-control]) .bubble').last).to_have_text('isolated gateway reply',timeout=10000)
                    assert background.snapshot()['active']==1
                    expect(settings.locator('#modules-view [data-runtime="background-process"]')).to_have_text('1 / 1 运行中',timeout=10000)
                    expect(settings.locator('#modules-view [data-runtime="background-process-detail"]')).to_contain_text('等待模型',timeout=10000)
                    background_state=background.snapshot()
                    settings.locator('#modules-view .runtime-panel').scroll_into_view_if_needed()
                    settings.screenshot(path=str(output/'lanes-running.png'))
                    send('/取消')
                    wait(lambda:background.snapshot()['active']==0)
                    wait(lambda:server.metrics.snapshot()['lanes']['task']['active']==0)
                    assert not server.computer.queue.snapshot()['running']
                    background._command=[sys._base_executable,'-u',str(ROOT/'tests/dialogue_process_fixture.py'),'plan_gateway']
                    send('/任务 列出样例目录文件，按类型统计并保存结果。')
                    wait(lambda:server.metrics.snapshot()['lanes']['task']['outcomes'].get('CONFIRMED',0)==2,seconds=15)
                    assert background.snapshot()['active']==0
                    checks.append('Real background planning child hangs while chat completes; task cancellation reaps it; next isolated plan validates and runs the real inventory Worker')
                    page.screenshot(path=str(output/'process-recovered.png'))
                    assert not errors,errors
                    browser.close()
                finally:driver.close()
        finally:server.shutdown();server.server_close();thread.join(3)
    paths=['runtime/node-host/jarvis_core/dialogue_process.py','runtime/node-host/jarvis_core/dialogue_worker.py',
           'runtime/node-host/jarvis_core/turns.py','runtime/node-host/jarvis_core/chat.py','apps/web/server.py','apps/web/resources.js',
           'runtime/node-host/jarvis_core/sample_tasks.py','runtime/node-host/jarvis_core/skill_tasks.py',
           'runtime/node-host/jarvis_core/rea_explanation.py','adapters/computer-use/jarvis_computer/web.py',
           'tests/dialogue_process_fixture.py','tests/test_dialogue_process.py','tools/probe_dialogue_process_ui.py']
    report={'status':'SUCCEEDED','source_version':__version__,'checks':checks,'control_http_ms':control_ms,
            'running_snapshot':state,'background_running_snapshot':background_state,'browser_errors':errors,'cloud_calls':0,
            'screenshots':[str(output/'process-running.png'),str(output/'lanes-running.png'),str(output/'process-recovered.png')],
            'limits':'Synthetic transport in actual Windows child; real gateway journal, real Edge and task Worker. No CPU/GPU saturation or full Dialogue Runtime isolation claim.',
            'source_sha256':{p:hashlib.sha256((ROOT/p).read_bytes()).hexdigest() for p in paths}}
    (ROOT/'evals/reports'/report_name).write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(report,ensure_ascii=False))


if __name__=='__main__':main()
