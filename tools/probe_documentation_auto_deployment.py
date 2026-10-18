"""One idle reload and one actual Flash -> Host -> Context7 query, no retry."""
import hashlib
import json
from pathlib import Path
import sys
import time

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT),str(ROOT/'adapters/computer-use'),str(ROOT/'runtime/worker-host')]
from tools.probe_dialogue_deployment import main as reload_idle,get,BASE
from jarvis_computer.browser import DriverJob
from playwright.sync_api import sync_playwright,expect


def main():
    paths=['runtime/node-host/jarvis_core/'+n+'.py' for n in ['__init__','intent','chat','turns','documentation_admission','mcp_tasks','mcp_catalog','task_queue']]
    paths+=['apps/web/dialogue.js','apps/web/conversation_tasks.js','apps/web/server.py','config/mcp/automation.json']
    hashes=lambda:{p:hashlib.sha256((ROOT/p).read_bytes()).hexdigest() for p in paths}
    before=hashes();destination=ROOT/'evals/reports/documentation-auto-deployment-2026-10-18.json'
    assert not destination.exists(),'Inspect previous receipt; never replay a paid input blindly'
    report={'status':'RUNNING','source_sha256':before,'reload':reload_idle(None)}
    def save():destination.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    save();errors=[]
    with sync_playwright() as p:
        job=DriverJob(p)
        try:
            browser=p.chromium.launch(channel='msedge',headless=True,chromium_sandbox=True)
            page=browser.new_page(viewport={'width':1280,'height':1000});page.on('pageerror',lambda e:errors.append(str(e)))
            page.goto(BASE);page.wait_for_function('()=>window.Dialogue&&window.Workspace&&!Workspace.isBusy()&&coreReady&&!refreshing')
            page.wait_for_function('()=>!document.documentElement.hasAttribute("data-brand-cinema")')
            page.evaluate('Workspace.newSession(null)')
            cid=page.evaluate('Workspace.currentConversation().id');nonce=page.evaluate('NONCE')
            report.update(test_conversation=cid,conversation_preserved=True);save()
            # Explicit per-session selection; does not alter global routing.
            page.locator('#model-trigger').click();page.locator('#model-search').fill('gemini-3.8-flash')
            expect(page.locator('#model-options [role="option"]')).to_have_count(1)
            page.locator('#model-options [role="option"]').click()
            tick=time.monotonic();page.locator('#message').fill('查询 Electron 文档中的 ipcMain.handle 错误处理示例');page.locator('#send').click()
            page.wait_for_function('()=>!busy&&document.querySelector(".message.assistant .dialogue-intent")',timeout=125000)
            article=page.locator('.message.assistant:not([data-task-control])').last
            rid=article.get_attribute('data-reply-ref');instance=get('/api/status')['instance_id']
            receipt=get('/api/dialogue/turns/'+rid+'?conversation_id='+cid+'&instance_id='+instance,nonce);result=receipt['result']
            report.update(reply_elapsed_seconds=round(time.monotonic()-tick,3),turn_id=rid,result=result,source_version=get('/api/status')['version']);save()
            assert result['status']=='SUCCEEDED' and result['work_admission']['status']=='submitted',result
            task=result['work_admission']['task_id'];report['task_id']=task;save()
            expect(article.locator('.dialogue-intent summary')).to_contain_text('已受理文档任务')
            expect(page.locator('.message[data-task-control][data-task-ref]')).to_have_count(1)
            expect(page.get_by_role('button',name='查看文档结果',exact=True)).to_be_visible(timeout=100000)
            detail=get('/api/conversation-tasks/'+cid+'/'+task,nonce)
            report.update(task_status=detail['action_status'],tool=detail.get('report',{}).get('tool'),
                          mcp_checks=detail.get('report',{}).get('checks'),origin=detail.get('report',{}).get('origin'),
                          artifact=detail.get('artifact'),total_elapsed_seconds=round(time.monotonic()-tick,3));save()
            assert detail['action_status']=='CONFIRMED' and detail['report']['tool']=='query-docs'
            assert detail['report']['origin']['turn_id']==rid
            page.evaluate('Workspace.flushConversation()');page.reload()
            page.wait_for_function('()=>window.Workspace&&!Workspace.isBusy()&&coreReady&&!refreshing')
            expect(page.locator('.message[data-task-control][data-task-ref]')).to_have_count(1)
            assert len(get('/api/conversation-tasks/'+cid,nonce)['tasks'])==1
            page.get_by_role('button',name='查看真实任务',exact=True).click()
            expect(page.get_by_role('button',name='查看文档结果',exact=True)).to_be_visible()
            output=Path('H:/JarvisData/diagnostics/dialogue/documentation-auto-live.png');page.screenshot(path=str(output))
            state=get('/api/status');assert state['active_tasks']==state['active_chat_requests']==0 and state['core_ready'] and not state['stopped']
            assert not errors,errors
            report.update(source_changed=hashes()!=before,instance_id=instance,browser_errors=errors,screenshot=str(output),
                          model_attempts=len(result.get('attempts',[])),task_count=1,mcp_calls=1,refresh_no_replay=True,
                          limits='One synthetic ordinary request through real Flash and real Context7. No general automation, semantic population or latency guarantee.')
            report['status']='SOURCE_CHANGED' if report['source_changed'] else 'SUCCEEDED';save();browser.close()
        finally:job.close()
    print(json.dumps({k:v for k,v in report.items() if k not in {'result','reload','source_sha256'}},ensure_ascii=False))


if __name__=='__main__':main()
