"""One idle reload, then a persistent Google coding demonstration in an owned fixture project."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'runtime/node-host'),str(ROOT/'runtime/worker-host'),str(ROOT/'adapters/computer-use')]
from jarvis_core import __version__
from jarvis_computer.browser import DriverJob
from playwright.sync_api import sync_playwright,expect
from probe_dialogue_deployment import main as reload_idle, get, request, BASE


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--report',type=Path,required=True)
    parser.add_argument('--project',type=Path,required=True)
    parser.add_argument('--deployment-evidence',type=Path,help='Reuse an already verified current instance, without restarting it again')
    args=parser.parse_args()
    if args.report.exists() or args.project.exists():parser.error('Refuse to replay or overwrite an existing demonstration')
    index=json.loads((ROOT/'config/skills/validation.json').read_text(encoding='utf-8'))
    baseline=json.loads((ROOT/'evals/reports/skills-completion-baseline-2026-10-19.json').read_text(encoding='utf-8'))
    assert baseline['engineering_tests']['status']=='passed' and baseline['version']==__version__
    result={'status':'running','version':__version__,'observed_at':datetime.now(timezone.utc).isoformat(),
        'project':str(args.project),'cloud_route':'vertex::gemini-3.8-flash',
        'limits':'One real deployed single-file task with visible frozen examples. Other model coverage is separate; no general repository correctness or independent quality acceptance.'}
    def save():args.report.write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    save();errors=[]
    try:
        if args.deployment_evidence:
            prior=json.loads(args.deployment_evidence.read_text(encoding='utf-8'))
            reload=prior['reload'];current=get('/api/status')
            assert reload['status']=='SUCCEEDED' and current['version']==__version__ and current['instance_id']==reload['current_instance'] and current['core_ready']
            result['reload']=reload;result['reload_reused_from']=str(args.deployment_evidence)
        else:result['reload']=reload_idle(report_name=None)
        save()
        token=re.search(r'<meta name="jarvis-nonce" content="([^"]+)"',request('/settings').decode())[1]
        for asset in ['skills.js','skills_manager.js','conversation_tasks.js','personal_candidates.js']:
            digest=hashlib.sha256(request('/'+asset)).hexdigest()
            assert digest==hashlib.sha256((ROOT/'apps/web'/asset).read_bytes()).hexdigest()
            result['reload']['served_sha256'][asset]=digest
        assert (ROOT/'apps/web/workbench.css').read_bytes() in request('/')
        assert (ROOT/'apps/web/skills.css').read_bytes() in request('/settings')
        entries=[e for e in get('/api/skills',token)['entries'] if e.get('presentation')]
        assert len(entries)==11 and all(e['validation']['state']=='verified_scope' for e in entries)
        assert all(e['validation']['binding']==index['skills'][e['id']]['binding'] for e in entries)
        result['catalog']={'displayed':len(entries),'all_evidence_bindings_current':True};save()
        args.project.mkdir(parents=True,exist_ok=False)
        original=b'\xef\xbb\xbfdef transform(data):\n    return str(sum(data[1:]))\n'
        source=args.project/'calc.py';source.write_bytes(original)
        with sync_playwright() as pw:
            job=DriverJob(pw)
            try:
                browser=pw.chromium.launch(channel='msedge',headless=True,chromium_sandbox=True)
                page=browser.new_page(viewport={'width':1440,'height':1050});page.on('pageerror',lambda e:errors.append(str(e)))
                page.goto(BASE);expect(page.locator('#send')).to_be_enabled(timeout=20000)
                expect(page.locator('.jarvis-cinema')).not_to_be_visible(timeout=15000)
                page.evaluate('Workspace.newSession(null)')
                page.locator('#open-project').click();page.locator('#folder-path').fill(str(args.project));page.locator('#project-open').click()
                expect(page.locator('#context-project')).to_contain_text(str(args.project))
                page.locator('#model-trigger').click();page.locator('#model-search').fill('Gemini 3.8 Flash')
                page.locator('#model-options button').filter(has_text='Gemini 3.8 Flash').first.click()
                page.locator('#composer-mode').select_option('skill');page.locator('#skill-explicit').select_option('matt-pocock.tdd')
                page.locator('#skill-paths').fill('calc.py');page.locator('#skill-coding').check()
                page.locator('#skill-coding-cases').fill(json.dumps([{'input':[2,4],'expected':'6'},{'input':[],'expected':'0'},{'input':[-2,3],'expected':'1'}]))
                page.locator('#message').fill('编程闭环演示：修复求和，所有列表元素都参与计算，空表返回字符串0。')
                page.locator('#composer').evaluate('e=>e.requestSubmit()')
                expect(page.locator('.conversation-task-card')).to_have_count(1,timeout=15000)
                card=page.locator('.conversation-task-card');task=card.get_attribute('data-task-id')
                cid=page.evaluate('Workspace.currentConversation().id')
                result.update(conversation_id=cid,task_id=task,conversation_url=BASE+'/#chat='+cid);save()
                expect(card).to_contain_text('编程副本通过所提供案例',timeout=170000)
                detail=get('/api/conversation-tasks/'+cid+'/'+task,token)
                assert detail['action_status']=='CONFIRMED',detail
                report=detail['report'];result['report']=report;save()
                coding=report['coding'];assert coding['passed'] and coding['validation']['worker']['lpac']
                assert source.read_bytes()==original
                attempts=coding['attempts'];assert 1<=len(attempts)<=2
                assert all(x['model']['model']=='gemini-3.8-flash' for x in attempts)
                assert all(x['model']['billing']['amount'] is not None for x in attempts)
                result['billing']={'basis':'configured_price_estimate','calls':len(attempts),'amount':sum(x['model']['billing']['amount'] for x in attempts),'currency':attempts[0]['model']['billing']['currency']}
                card.get_by_role('button',name='查看差异与验收',exact=True).click();expect(page.locator('#coding-result')).to_be_visible()
                page.get_by_role('button',name='应用到原文件',exact=True).click();expect(page.locator('#coding-result [role=status]')).to_contain_text('候选已应用')
                assert source.read_bytes()!=original
                page.get_by_role('button',name='恢复本次原文件',exact=True).click();expect(page.locator('#coding-result [role=status]')).to_contain_text('原文件已恢复')
                assert source.read_bytes()==original;result['apply_rollback_bom_exact']=True
                page.screenshot(path=str(ROOT/'artifacts/skills/deployed-coding-workflow.png'))
                page.evaluate('Workspace.flushConversation()');page.reload()
                page.locator('[data-task-id="'+task+'"]').get_by_role('button',name='查看详情',exact=True).click()
                expect(page.locator('[data-task-id="'+task+'"]')).to_contain_text('编程副本通过所提供案例',timeout=20000)
                assert get('/api/conversation-tasks/'+cid+'/'+task,token)['report']==report
                result['saved_conversation_reload_same_receipt']=True
                settings=browser.new_page(viewport={'width':1440,'height':1050});settings.goto(BASE+'/settings#skill')
                expect(settings.locator('.skill-card')).to_have_count(11)
                settings.locator('[data-skill-id="matt-pocock.tdd"] .skill-manage').click()
                settings.get_by_role('tab',name='验证',exact=True).click()
                expect(settings.locator('#skill-detail-pane-verification')).to_contain_text(task)
                expect(settings.locator('#skill-detail-pane-verification')).to_contain_text('与当前源码一致')
                settings.screenshot(path=str(ROOT/'artifacts/skills/deployed-validation-status.png'))
                assert errors==[];browser.close()
            finally:job.close()
        result['status']='passed';result['page_errors']=errors;result['final_status']=get('/api/status');save()
    except Exception as exc:
        result['status']='failed';result['error']=str(exc);result['page_errors']=errors;save();raise
    print(json.dumps({'status':result['status'],'conversation_url':result['conversation_url'],'billing':result['billing']},ensure_ascii=False))


if __name__=='__main__':main()
