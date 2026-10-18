"""Verify an already delivered demo after reload, without dispatching another model call."""
import argparse
from datetime import datetime,timezone
import json
from pathlib import Path
import re
import sys
import time
ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'runtime/node-host'),str(ROOT/'runtime/worker-host'),str(ROOT/'adapters/computer-use')]
from jarvis_computer.browser import DriverJob
from playwright.sync_api import sync_playwright,expect
from probe_dialogue_deployment import get,request,BASE
from probe_idle_resources import WindowsProcesses

def main():
    p=argparse.ArgumentParser();p.add_argument('--delivery',type=Path,required=True);p.add_argument('--report',type=Path,required=True)
    p.add_argument('--cycles',type=int,default=2);p.add_argument('--interval',type=float,default=0);a=p.parse_args()
    if not 2<=a.cycles<=30 or not 0<=a.interval<=30:p.error('2..30 read-only cycles; 0..30 second interval')
    if a.report.exists():p.error('Refuse to overwrite evidence')
    prior=json.loads(a.delivery.read_text(encoding='utf-8'));report=prior['report'];cid=prior['conversation_id'];task=prior['task_id']
    assert prior['apply_rollback_bom_exact'] and report['coding']['passed'] and prior['billing']['amount'] is not None
    out={'status':'running','observed_at':datetime.now(timezone.utc).isoformat(),'delivery_evidence':str(a.delivery),'version':prior['version'],'conversation_id':cid,'task_id':task,'conversation_url':prior['conversation_url'],'cloud_calls':0,
         'limits':'Read-only retrieval of the existing paid task. Earlier probe expected lazy-loaded detail before clicking View details; no new task, restart, model request or file change.'}
    def save():a.report.write_text(json.dumps(out,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    save();errors=[];start=time.monotonic();samples=[];reader=WindowsProcesses()
    try:
        token=re.search(r'<meta name="jarvis-nonce" content="([^"]+)"',request('/settings').decode())[1]
        current=get('/api/status');assert current['instance_id']==prior['reload']['current_instance'] and current['version']==prior['version']
        assert get('/api/conversation-tasks/'+cid+'/'+task,token)['report']==report
        with sync_playwright() as pw:
            job=DriverJob(pw)
            try:
                browser=pw.chromium.launch(channel='msedge',headless=True,chromium_sandbox=True)
                page=browser.new_page(viewport={'width':1440,'height':1050});page.on('pageerror',lambda e:errors.append(str(e)))
                page.goto(prior['conversation_url']);expect(page.locator('#send')).to_be_enabled(timeout=20000)
                expect(page.locator('.jarvis-cinema')).not_to_be_visible(timeout=15000)
                for number in range(a.cycles):
                    tick=time.monotonic()
                    page.get_by_role('button',name='查看真实任务',exact=True).click()
                    card=page.locator('[data-task-id="'+task+'"]');expect(card).to_be_visible(timeout=15000)
                    card.get_by_role('button',name='查看详情',exact=True).click();expect(card).to_contain_text('编程副本通过所提供案例')
                    card.get_by_role('button',name='查看差异与验收',exact=True).click();expect(page.locator('#coding-result .coding-diff')).to_contain_text('calc.py')
                    assert get('/api/conversation-tasks/'+cid+'/'+task,token)['report']==report
                    page.screenshot(path=str(ROOT/'artifacts/skills/deployed-saved-coding.png'));page.reload()
                    samples.append({'cycle':number+1,'elapsed_seconds':round(time.monotonic()-start,3),'interaction_seconds':round(time.monotonic()-tick,3),'processes':reader.sample(pw._impl_obj._connection._transport._proc.pid)})
                    out['cycles']=samples;save()
                    if a.interval:time.sleep(a.interval)
                out['two_page_reload_same_receipt']=True
                settings=browser.new_page(viewport={'width':1440,'height':1050});settings.goto(BASE+'/settings#skill')
                expect(settings.locator('.skill-card')).to_have_count(11);settings.locator('[data-skill-id="matt-pocock.tdd"] .skill-manage').click()
                settings.get_by_role('tab',name='验证',exact=True).click();pane=settings.locator('#skill-detail-pane-verification')
                expect(pane).to_contain_text(task);expect(pane).to_contain_text('与当前源码一致')
                settings.screenshot(path=str(ROOT/'artifacts/skills/deployed-validation-status.png'))
                entries=get('/api/skills',token)['entries'];shown=[e for e in entries if e.get('presentation')]
                assert len(shown)==11 and all(e['validation']['state']=='verified_scope' for e in shown)
                out['settings_current_and_latest_success']=True
                out['current_instance']=current['instance_id'];out['page_errors']=errors;assert not errors;browser.close()
            finally:job.close()
        out['status']='passed';out['elapsed_seconds']=round(time.monotonic()-start,3);save()
    except Exception as exc:out['status']='failed';out['error']=str(exc);save();raise
    print(json.dumps({'status':out['status'],'cycles':len(out.get('cycles',[])),'seconds':out['elapsed_seconds'],'conversation_url':out['conversation_url'],'cloud_calls':0},ensure_ascii=False))

if __name__=='__main__':main()
