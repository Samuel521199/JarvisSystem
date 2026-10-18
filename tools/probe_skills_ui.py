"""Real Edge UI, LPAC renderer, sandbox preview and scoped settings. Synthetic model."""
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
from probe_workspace_ui import SyntheticChat
from playwright.sync_api import sync_playwright, expect

def main():
    spec=importlib.util.spec_from_file_location('skill_web',ROOT/'apps/web/server.py')
    web=importlib.util.module_from_spec(spec);spec.loader.exec_module(web)
    output=ROOT/'artifacts/skills';output.mkdir(parents=True,exist_ok=True)
    checks=[];errors=[];evidence={};chat=SyntheticChat();chat.text='calc.py:2 建议明确零除数行为。只读分析，未运行测试。'
    with tempfile.TemporaryDirectory(prefix='jarvis-skill-ui-') as tmp:
        root=Path(tmp);project=root/'project';project.mkdir();(project/'calc.py').write_text('def divide(a,b):\n    return a/b\n')
        core=CoreService(root/'data');core.initialize(project)
        server=web.create_server(core=core,chat=chat,port=0);server.computer.skills.chat_factory=lambda *a,**kw:chat
        thread=threading.Thread(target=server.serve_forever,kwargs={'poll_interval':.02},daemon=True);thread.start()
        origin='http://127.0.0.1:'+str(server.server_address[1])
        try:
            with sync_playwright() as p:
                job=DriverJob(p)
                try:
                    browser=p.chromium.launch(channel='msedge',headless=True,chromium_sandbox=True)
                    page=browser.new_page(viewport={'width':1440,'height':1050});page.on('pageerror',lambda e:errors.append(str(e)))
                    page.goto(origin);expect(page.locator('#send')).to_be_enabled(timeout=15000)
                    expect(page.locator('.jarvis-cinema')).not_to_be_visible(timeout=15000)
                    page.locator('#open-project').click();page.locator('#folder-path').fill(str(project));page.locator('#project-open').click()
                    expect(page.locator('#context-project')).to_contain_text(str(project))
                    def send(text):
                        page.locator('#message').fill(text);page.locator('#composer').evaluate('e=>e.requestSubmit()')
                    send('制作齿轮传动交互动画，支持拆解和组装')
                    expect(page.locator('.conversation-task-card')).to_have_count(1,timeout=15000)
                    expect(page.locator('#conversation-task-list')).to_contain_text('数值、页面交互及交付摘要检查通过',timeout=30000)
                    task=page.locator('.conversation-task-card').get_attribute('data-task-id');cid=page.evaluate('Workspace.currentConversation().id')
                    detail=server.conversation_tasks.detail(cid,task);report=detail['report'];evidence['anatomy']=report['checks']
                    (output/'gear-lesson.html').write_text(report['html'],encoding='utf-8')
                    page.get_by_role('button',name='预览交互图',exact=True).click()
                    frame=page.frame_locator('#skill-preview iframe');expect(frame.locator('#pause')).to_be_visible(timeout=15000)
                    # The sandbox must render but cannot read the workbench DOM/nonce.
                    isolated=page.locator('#skill-preview iframe').content_frame.locator('body').evaluate("()=>{try{return parent.document.body?false:false}catch(e){return e.name==='SecurityError'}}")
                    assert isolated
                    frame.locator('#angle').fill('90');frame.locator('#angle').dispatch_event('input');frame.locator('#explode').click()
                    observed=frame.locator('body').evaluate('()=>window.__jarvisLesson');assert observed['apart'] and observed['angle']==90
                    page.screenshot(path=str(output/'skill-preview.png'));page.get_by_role('button',name='关闭预览',exact=True).click()
                    with page.expect_download() as dl:page.get_by_role('button',name='下载产物',exact=True).click()
                    target=root/'download.html';dl.value.save_as(str(target));assert target.read_text(encoding='utf-8')==report['html']
                    assert chat.calls==0
                    checks.append('natural gear intent -> shared FIFO -> real LPAC renderer -> independent kinematics/browser verification -> saved HTML -> sandbox preview -> exact download, no model call')
                    page.locator('#composer-mode').select_option('skill');page.locator('#skill-explicit').select_option('matt-pocock.code-review');page.locator('#skill-paths').fill('calc.py')
                    send('审阅源码并指出边界问题')
                    expect(page.locator('.conversation-task-card')).to_have_count(2,timeout=10000)
                    expect(page.locator('#conversation-task-list')).to_contain_text('只读模型分析已交付',timeout=15000)
                    assert chat.calls==1
                    checks.append('explicit code-review + selected project source -> bounded model guidance -> source recheck -> delivered report; no code execution')
                    settings=browser.new_page(viewport={'width':1440,'height':1050});settings.on('pageerror',lambda e:errors.append(str(e)))
                    settings.goto(origin+'/settings#skill');expect(settings.locator('.skill-card')).to_have_count(11,timeout=15000)
                    expect(page.locator('#skill-explicit option')).to_have_count(12)
                    settings.locator('#skill-search').fill('to-tickets');expect(settings.locator('.skill-card')).to_have_count(1)
                    settings.get_by_role('button',name='管理需求到任务计划',exact=True).click()
                    expect(settings.locator('#skill-detail')).to_contain_text('to-spec · to-tickets')
                    settings.get_by_role('button',name='关闭技能详情').click();settings.locator('#skill-search').fill('')
                    settings.locator('#skill-kind').select_option('combined');expect(settings.locator('.skill-card')).to_have_count(3)
                    settings.locator('#skill-kind').select_option('');settings.get_by_role('button',name='开发与分析',exact=True).click();expect(settings.locator('.skill-card')).to_have_count(6)
                    settings.get_by_role('button',name='全部技能',exact=True).click()
                    settings.screenshot(path=str(output/'skill-management.png'),full_page=True)
                    settings.get_by_role('button',name='管理齿轮交互科普',exact=True).click()
                    settings.locator('#skill-detail select').select_option('disabled');settings.get_by_role('button',name='保存设置',exact=True).click()
                    expect(settings.locator('[data-skill-id="anatomy.explainer"]')).to_contain_text('已停用',timeout=10000)
                    settings.reload();expect(settings.locator('[data-skill-id="anatomy.explainer"]')).to_contain_text('已停用',timeout=15000)
                    settings.set_viewport_size({'width':390,'height':844})
                    assert settings.evaluate('document.documentElement.scrollWidth <= innerWidth+1')
                    settings.screenshot(path=str(output/'skill-management-mobile.png'),full_page=True)
                    settings.set_viewport_size({'width':1440,'height':1050})
                    checks.append('11 complete capabilities, 3 bundles, component search, 6 engineering capabilities; details and scoped mode; mobile layout has no horizontal overflow')
                    page.locator('#composer-mode').select_option('chat');page.locator('#skill-explicit').select_option('');send('制作齿轮传动交互动画')
                    # Disabled native task must not dispatch. Chat can explain boundaries.
                    expect(page.locator('#send')).to_be_enabled(timeout=15000);time.sleep(.5)
                    assert len(server.conversation_tasks.list(cid)['tasks'])==2
                    checks.append('only complete capabilities visible; global disable persists after reload and prevents native dispatch')
                    settings.screenshot(path=str(output/'skill-management.png'))
                    # Nonce + conversation binding + receipt file integrity checks.
                    for path in ('/api/skills','/api/skills/decisions'):
                        assert page.request.get(origin+path).status==403
                    payload={'conversation_id':cid,'task_id':task}
                    headers={'X-Jarvis-Nonce':server.nonce,'Origin':origin}
                    wrong={**payload,'conversation_id':'0'*32};assert page.request.post(origin+'/api/skills/preview',data=wrong,headers=headers).status==404
                    saved=Path(report['output']['path']);saved.write_text('changed',encoding='utf-8')
                    assert page.request.post(origin+'/api/skills/preview',data=payload,headers=headers).status==409
                    checks.append('missing nonce, cross-conversation preview and modified delivered HTML are denied')
                    assert errors==[],errors
                    browser.close()
                finally:job.close()
        finally:server.shutdown();server.server_close();thread.join(5)
    record={'version':__version__,'status':'passed','observed_at':datetime.now(timezone.utc).isoformat(),'checks':checks,'page_errors':errors,'evidence':evidence,'screenshots':['artifacts/skills/skill-preview.png','artifacts/skills/skill-management.png'],'synthetic_model':True}
    (ROOT/'evals/reports/skills-ui.json').write_text(json.dumps(record,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps({'status':'passed','checks':len(checks),'page_errors':errors}))

if __name__=='__main__':main()
