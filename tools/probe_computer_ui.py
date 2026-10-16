"""Real Edge UI probe with temporary ledger and fixed actions, no cloud requests."""
import importlib.util
import json
import os
from pathlib import Path
import sys
import tempfile
import threading
import time

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'runtime/node-host'),str(ROOT/'adapters/computer-use')]
from jarvis_core.service import CoreService
from jarvis_computer.browser import DriverJob
from playwright.sync_api import sync_playwright, expect


def main():
    spec=importlib.util.spec_from_file_location('web_ui_probe',ROOT/'apps/web/server.py')
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    output=Path(os.environ['LOCALAPPDATA'])/'Jarvis/data/diagnostics/computer-queue'
    output.mkdir(parents=True,exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='jarvis-computer-ui-') as directory:
        base=Path(directory);(base/'input').mkdir()
        core=CoreService(base/'data');core.initialize(base/'input')
        server=module.create_server(core=core,port=0)
        thread=threading.Thread(target=server.serve_forever,kwargs={'poll_interval':.02},daemon=True);thread.start()
        errors=[];started=time.monotonic()
        try:
            with sync_playwright() as playwright:
                job=DriverJob(playwright)
                try:
                    browser=playwright.chromium.launch(channel='msedge',headless=True,chromium_sandbox=True)
                    page=browser.new_page(viewport={'width':1360,'height':950})
                    page.on('pageerror',lambda error:errors.append(str(error)))
                    page.on('console',lambda message:errors.append(message.text) if message.type=='error' else None)
                    page.goto('http://127.0.0.1:'+str(server.server_address[1]))
                    page.locator('#computer-nav').click()
                    page.locator('#task-mode').select_option('scripted')
                    page.locator('#queue-toggle').click()
                    expect(page.locator('#queue-toggle')).to_have_text('继续队列')
                    for count in range(1,4):
                        page.locator('#task-start').click()
                        expect(page.locator('.task-row')).to_have_count(count)
                    # Cancel the middle waiting task; it must never touch a page.
                    page.locator('.task-row').nth(1).click()
                    page.locator('#task-cancel').click()
                    expect(page.locator('#task-detail-title')).to_contain_text('已取消')
                    server.shutdown();server.server_close();thread.join(5)
                    server=module.create_server(core=core,port=0)
                    thread=threading.Thread(target=server.serve_forever,kwargs={'poll_interval':.02},daemon=True);thread.start()
                    page.goto('http://127.0.0.1:'+str(server.server_address[1]))
                    page.locator('#computer-nav').click()
                    expect(page.locator('.task-row')).to_have_count(3)
                    expect(page.locator('#queue-toggle')).to_have_text('继续队列')
                    assert server.computer.queue.snapshot()['waiting']==2
                    page.locator('#queue-toggle').click()
                    page.locator('#task-result').get_by_text('页面已满足任务的成功条件，结果截图已保存。',exact=True).wait_for(timeout=30000)
                    page.locator('#task-image').wait_for(state='visible')
                    assert page.locator('#task-steps li').count()==4
                    page.locator('#current-chat').click()
                    assert page.locator('#chat-panel').is_visible()
                    page.locator('#message').fill('保留在页面中的草稿')
                    page.locator('#computer-nav').click()
                    page.locator('#current-chat').click()
                    assert page.locator('#message').input_value()=='保留在页面中的草稿'
                    page.reload();page.locator('#computer-nav').click()
                    page.locator('#task-image').wait_for(state='visible')
                    assert page.locator('.task-row').count()==3
                    page.screenshot(path=str(output/'desktop.png'),full_page=True)
                    page.set_viewport_size({'width':390,'height':844})
                    assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
                    page.screenshot(path=str(output/'mobile.png'),full_page=True)
                    assert not errors,errors
                    browser.close()
                finally:job.close()
            tasks=server.computer.list_tasks()['tasks']
            detail=server.computer.detail(tasks[0]['task_id'])
            assert [t['status'] for t in tasks]==['SUCCEEDED','CANCELLED','SUCCEEDED'],tasks
            result={'version':'0.1.10','status':'passed','scope':'temporary instance, real Edge UI, two scripted browser tasks; no cloud calls',
                    'elapsed_seconds':round(time.monotonic()-started,3),'checks':['pause and enqueue three from UI','cancel middle waiting task','restart server with two tasks preserved and paused','explicit resume and FIFO execution','four real browser actions per completed task','switch to chat','draft retained across views','history and screenshot after reload','390px width without horizontal overflow','no console errors'],
                    'task_status':detail['task']['status'],'steps':len(detail['steps']),'statuses':[t['status'] for t in tasks], 'screenshots':['desktop.png','mobile.png'],'errors':errors}
            (output/'result.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
            print(json.dumps(result,ensure_ascii=False))
        finally:server.shutdown();server.server_close();thread.join(5)

if __name__=='__main__':
    sys.stdout.reconfigure(encoding='utf-8')
    main()
