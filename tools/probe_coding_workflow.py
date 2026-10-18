"""Real Edge, task receipts, LPAC and reversible edits; optional explicit paid models."""
import argparse
from datetime import datetime, timezone
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import threading
ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'runtime/node-host'),str(ROOT/'adapters/computer-use'),str(ROOT/'apps/web')]
from jarvis_core import __version__
from jarvis_core.service import CoreService
from jarvis_core.chat import ChatService
from jarvis_computer.browser import DriverJob
from playwright.sync_api import sync_playwright,expect

def main():
    p=argparse.ArgumentParser();p.add_argument('--live',action='store_true');p.add_argument('--report',required=True,type=Path);a=p.parse_args()
    if a.report.exists():p.error('Refuse to replay or overwrite evidence')
    spec=importlib.util.spec_from_file_location('coding_web',ROOT/'apps/web/server.py');web=importlib.util.module_from_spec(spec);spec.loader.exec_module(web)
    record={'version':__version__,'observed_at':datetime.now(timezone.utc).isoformat(),'live_models':a.live,'results':[],'status':'running'}
    def save():a.report.write_text(json.dumps(record,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    save();errors=[]
    try:
        with tempfile.TemporaryDirectory(prefix='jarvis-coding-ui-') as tmp:
            base=Path(tmp);project=base/'project';project.mkdir();original=b'\xef\xbb\xbfdef transform(data):\n    return str(sum(data[1:]))\n';source=project/'calc.py';source.write_bytes(original)
            core=CoreService(base/'data');core.initialize(project);server=web.create_server(core=core,chat=ChatService(core),port=0)
            if not a.live:server.computer.skills.coding_generate=lambda *args:{'status':'SUCCEEDED','text':json.dumps({'code':'def transform(data):\n    return str(sum(data))\n','notes':'fixture, not real model evidence'})}
            thread=threading.Thread(target=server.serve_forever,kwargs={'poll_interval':.02},daemon=True);thread.start();origin='http://127.0.0.1:'+str(server.server_port)
            try:
                with sync_playwright() as pw:
                    job=DriverJob(pw)
                    try:
                        browser=pw.chromium.launch(channel='msedge',headless=True,chromium_sandbox=True);page=browser.new_page(viewport={'width':1440,'height':1050});page.on('pageerror',lambda e:errors.append(str(e)))
                        page.goto(origin);expect(page.locator('#send')).to_be_enabled(timeout=15000);expect(page.locator('.jarvis-cinema')).not_to_be_visible(timeout=15000)
                        page.locator('#open-project').click();page.locator('#folder-path').fill(str(project));page.locator('#project-open').click();expect(page.locator('#context-project')).to_contain_text(str(project))
                        for name in (['Gemini 3.8 Flash','GPT-6.1 Sol'] if a.live else ['Gemini 3.8 Flash']):
                            previous=set(page.locator('.conversation-task-card').evaluate_all('(rows)=>rows.map(n=>n.dataset.taskId)'))
                            page.locator('#model-trigger').click();page.locator('#model-search').fill(name);page.locator('#model-options button').filter(has_text=name).first.click()
                            page.locator('#composer-mode').select_option('skill');page.locator('#skill-explicit').select_option('matt-pocock.tdd');page.locator('#skill-paths').fill('calc.py');page.locator('#skill-coding').check()
                            page.locator('#skill-coding-cases').fill(json.dumps([{'input':[2,4],'expected':'6'},{'input':[],'expected':'0'},{'input':[-2,3],'expected':'1'}]))
                            page.locator('#message').fill('修复求和，所有列表元素都参与计算；空表返回字符串0。');page.locator('#composer').evaluate('e=>e.requestSubmit()')
                            expect(page.locator('.conversation-task-card')).to_have_count(len(previous)+1,timeout=15000)
                            task=next(t for t in page.locator('.conversation-task-card').evaluate_all('(rows)=>rows.map(n=>n.dataset.taskId)') if t not in previous)
                            card=page.locator('[data-task-id="'+task+'"]');expect(card).to_contain_text('编程副本通过所提供案例',timeout=170000)
                            cid=page.evaluate('Workspace.currentConversation().id');detail=server.conversation_tasks.detail(cid,task)
                            assert detail['action_status']=='CONFIRMED',detail
                            report=detail['report'];assert report['coding']['passed'] and report['coding']['validation']['worker']['lpac'];assert source.read_bytes()==original
                            if a.live:assert report['coding']['attempts'][-1]['model']['model']==('gemini-3.8-flash' if name.startswith('Gemini') else 'gpt-6.1-sol')
                            card.get_by_role('button',name='查看差异与验收',exact=True).click();expect(page.locator('#coding-result')).to_be_visible();expect(page.locator('#coding-result .coding-diff')).to_contain_text('calc.py')
                            page.get_by_role('button',name='应用到原文件',exact=True).click();expect(page.locator('#coding-result [role=status]')).to_contain_text('候选已应用');assert source.read_bytes()!=original
                            page.get_by_role('button',name='恢复本次原文件',exact=True).click();expect(page.locator('#coding-result [role=status]')).to_contain_text('原文件已恢复');assert source.read_bytes()==original
                            headers={'X-Jarvis-Nonce':server.nonce,'Origin':origin};payload={'conversation_id':cid,'task_id':task}
                            assert page.request.post(origin+'/api/skills/coding-apply',data=payload).status==403
                            assert page.request.post(origin+'/api/skills/coding-apply',data={**payload,'conversation_id':'0'*32},headers=headers).status==404
                            source.write_bytes(b'externally changed');conflict=page.request.post(origin+'/api/skills/coding-apply',data=payload,headers=headers);assert conflict.status==409,conflict.text();assert source.read_bytes()==b'externally changed';source.write_bytes(original)
                            record['results'].append({'model':name,'task_id':task,'report':report,'apply_rollback_bom_exact':True,'missing_nonce_cross_scope_conflict_denied':True});save()
                            output=ROOT/'artifacts/skills/coding-workflow.png';output.parent.mkdir(exist_ok=True,parents=True);page.screenshot(path=str(output));page.get_by_role('button',name='关闭编程结果',exact=True).click()
                        settings=browser.new_page(viewport={'width':1440,'height':1050});settings.goto(origin+'/settings#skill');expect(settings.locator('.skill-card')).to_have_count(11);expect(settings.locator('.skill-validation')).to_have_count(11)
                        settings.locator('[data-skill-id="matt-pocock.tdd"] .skill-manage').click();settings.get_by_role('tab',name='验证',exact=True).click();expect(settings.locator('#skill-detail-pane-verification')).to_contain_text('编程案例通过');settings.screenshot(path=str(ROOT/'artifacts/skills/validation-status.png'))
                        settings.get_by_role('button',name='关闭技能详情',exact=True).click();settings.set_viewport_size({'width':390,'height':844});assert settings.evaluate('document.documentElement.scrollWidth<=innerWidth');assert errors==[];browser.close()
                    finally:job.close()
            finally:server.shutdown();server.server_close();thread.join(5)
        record['status']='passed';record['page_errors']=errors;save()
    except Exception as exc:
        record['status']='failed';record['error']=str(exc);record['page_errors']=errors;save();raise

if __name__=='__main__':main()
