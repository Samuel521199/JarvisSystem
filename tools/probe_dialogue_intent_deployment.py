"""One coordinated idle reload, then one real synthetic UI conversation and draft."""
import hashlib
import argparse
import json
import re
from pathlib import Path
import sys
import time

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT),str(ROOT/'adapters/computer-use'),str(ROOT/'runtime/worker-host')]
from tools.probe_dialogue_deployment import main as reload_idle,get,request,BASE
from jarvis_computer.browser import DriverJob
from playwright.sync_api import sync_playwright,expect


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--existing-instance',action='store_true');args=parser.parse_args()
    paths=['runtime/node-host/jarvis_core/'+n+'.py' for n in ['__init__','intent','chat','turns','assistant_context','memory','semantic_candidates','mcp_candidates','mcp_tasks']]
    paths+=['apps/web/index.html','apps/web/dialogue.js','apps/web/conversation_tasks.js','apps/web/personal_candidates.js','apps/web/server.py']
    before={p:hashlib.sha256((ROOT/p).read_bytes()).hexdigest() for p in paths}
    destination=ROOT/'evals/reports/dialogue-intent-deployment-2026-10-18.json'
    if args.existing_instance:
        report=json.loads(destination.read_text(encoding='utf-8'))
        assert report['status']=='RUNNING' and not report.get('test_conversation'), 'Existing live input needs recovery, never replay'
        assert get('/api/status')['instance_id']==report['reload']['current_instance']
        report['probe_recovery']='Browser helper import and then nonce selector failed after successful reload, both before any live input/model call; fixed helper path and read existing page nonce binding, continued same instance without reloading.'
        report['source_sha256']=before
    else:
        report={'status':'RUNNING','source_sha256':before,'reload':reload_idle(None)}
    def save():destination.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    save();errors=[]
    with sync_playwright() as p:
        job=DriverJob(p)
        try:
            browser=p.chromium.launch(channel='msedge',headless=True,chromium_sandbox=True)
            page=browser.new_page(viewport={'width':1280,'height':950});page.on('pageerror',lambda e:errors.append(str(e)))
            page.goto(BASE)
            page.wait_for_function('()=>window.Dialogue&&window.Workspace&&!Workspace.isBusy()&&coreReady&&!refreshing')
            page.wait_for_function('()=>!document.documentElement.hasAttribute("data-brand-cinema")')
            page.evaluate('Workspace.newSession(null)')
            cid=page.evaluate('Workspace.currentConversation().id');nonce=page.evaluate('NONCE')
            report.update(test_conversation=cid,conversation_deleted=False);save()
            message='我有点难过，陪我聊聊，顺便查询 Electron 文档中的 ipcMain.handle 示例。'
            tick=time.monotonic();page.locator('#message').fill(message);page.locator('#send').click()
            page.wait_for_function('()=>!busy&&document.querySelector(".message.assistant .dialogue-intent")',timeout=125000)
            reply=page.locator('.message.assistant').last
            rid=reply.get_attribute('data-reply-ref');instance=get('/api/status')['instance_id']
            receipt=get('/api/dialogue/turns/'+rid+'?conversation_id='+cid+'&instance_id='+instance,nonce)
            result=receipt['result'];decision=result.get('intent_decision',{})
            report.update(source_version=get('/api/status')['version'],reply_elapsed_seconds=round(time.monotonic()-tick,3),
                provider=result.get('provider'),model=result.get('model'),usage=result.get('usage'),billing=result.get('billing'),
                model_attempts=len(result.get('attempts',[])),decision=decision,reply=result.get('text'))
            save()
            assert result['status']=='SUCCEEDED' and decision.get('state')=='recognized'
            assert {i['kind'] for i in decision['intents']} >= {'emotion','action'}
            reply.locator('.dialogue-intent summary').click()
            button=reply.get_by_role('button',name='准备文档查询草稿',exact=True);expect(button).to_be_visible();button.click()
            expect(page.locator('#composer-mode')).to_have_value('mcp')
            expect(page.locator('#mcp-library')).to_have_value('Electron')
            expect(page.locator('#message')).to_have_value(re.compile('.*ipcMain\\.handle.*'))
            tasks=get('/api/conversation-tasks/'+cid,nonce)
            assert tasks['tasks']==[],tasks
            report.update(draft_library=page.locator('#mcp-library').input_value(),draft_query=page.locator('#message').input_value(),
                          task_count=0,mcp_calls=0,automatic_execution=False,browser_errors=errors)
            output=Path('H:/JarvisData/diagnostics/dialogue/intent-live-draft.png')
            reply.screenshot(path=str(output));report['screenshot']=str(output)
            # Only the synthetic conversation created above is removed through
            # its normal revision-checked API. No existing conversation touched.
            page.locator('#message').fill('');page.evaluate('Workspace.flushConversation()')
            conversation=get('/api/conversations/'+cid,nonce)
            request('/api/conversations/'+cid+'/delete',{'revision':conversation['revision']},nonce)
            report['conversation_deleted']=True
            state=get('/api/status');report['instance_id']=state['instance_id']
            assert state['active_tasks']==state['active_chat_requests']==0 and state['core_ready'] and not state['stopped']
            assert not errors,errors
            report['source_changed']=before!={p:hashlib.sha256((ROOT/p).read_bytes()).hexdigest() for p in paths}
            report['status']='SOURCE_CHANGED' if report['source_changed'] else 'SUCCEEDED'
            report['limits']='One actual default-route mixed request; no tool dispatch, no accuracy or latency population claim.'
            save();browser.close()
        finally:job.close()
    print(json.dumps({k:v for k,v in report.items() if k not in {'source_sha256','decision','reply','reload'}},ensure_ascii=False))


if __name__=='__main__':main()
