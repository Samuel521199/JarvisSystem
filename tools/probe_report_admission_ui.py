"""Real Edge/HTTP/ledger/LPAC report checks, synthetic dialogue and planner only."""
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import threading
import time
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT),str(ROOT/'tests'),str(ROOT/'apps/web'),str(ROOT/'runtime/node-host'),str(ROOT/'adapters/computer-use')]
from jarvis_core import __version__
from jarvis_core.service import CoreService
from tools.probe_workspace_ui import SyntheticChat
from tools.probe_parallel_runtime import wait
from test_sample_tasks import SyntheticPlanner, PLAN
from test_report_admission import reply, TEXT, CONFIG
from jarvis_computer.browser import DriverJob
from server import create_server
from playwright.sync_api import sync_playwright,expect


def main():
    paths=['runtime/node-host/jarvis_core/'+name+'.py' for name in ['report_intents','work_admission','task_revisions','task_queue','ledger','turns']]
    paths+=['apps/web/server.py','apps/web/dialogue.js','apps/web/conversation_tasks.js','tools/probe_report_admission_ui.py']
    hashes=lambda:{name:hashlib.sha256((ROOT/name).read_bytes()).hexdigest() for name in paths}
    before=hashes();checks=[];errors=[];calls=[];latency={}
    output=Path('H:/JarvisData/diagnostics/dialogue');output.mkdir(parents=True,exist_ok=True)
    class Chat(SyntheticChat):
        def reply(self,message,**kwargs):
            calls.append(message)
            if message==TEXT:return reply()
            return reply(message,quote=message,companion=None,kind='control' if 'task_' in message else 'chat')
    planner=SyntheticPlanner();planner.models=lambda:{'models':[{'provider':'vertex','model':'gemini-3.8-flash'}]}
    with tempfile.TemporaryDirectory(prefix='jarvis-report-ui-') as temp, patch('jarvis_core.work_admission.settings',return_value=CONFIG):
        root=Path(temp);sample=root/'sample';sample.mkdir();(sample/'a.txt').write_bytes(b'abc')
        sub=sample/'sub';sub.mkdir();(sub/'b.txt').write_bytes(b'12345')
        core=CoreService(root/'data');core.initialize(sample)
        server=create_server(core=core,chat=Chat(),port=0)
        server.computer.queue.set_paused(True);server.computer.sample.chat_factory=lambda *a,**kw:planner
        thread=threading.Thread(target=server.serve_forever,kwargs={'poll_interval':.02},daemon=True);thread.start()
        try:
            with sync_playwright() as p:
                job=DriverJob(p)
                try:
                    browser=p.chromium.launch(channel='msedge',headless=True,chromium_sandbox=True)
                    page=browser.new_page(viewport={'width':1280,'height':900});page.on('pageerror',lambda e:errors.append(str(e)))
                    page.goto('http://127.0.0.1:'+str(server.server_port))
                    page.wait_for_function('()=>window.Dialogue&&window.Workspace&&!Workspace.isBusy()&&coreReady&&!refreshing')
                    page.wait_for_function('()=>!document.documentElement.hasAttribute("data-brand-cinema")')
                    cid=page.evaluate('Workspace.currentConversation().id')
                    def send(text):
                        page.locator('#message').fill(text);page.locator('#send').click()
                        page.wait_for_function('()=>!busy&&!document.querySelector(".message[data-reply-ref][data-reply-pending=true]")')
                    def rows():return server.conversation_tasks.list(cid)['tasks']
                    def record(task):return core.ledger.record(task_id=task)
                    send(TEXT);wait(lambda:len(rows())==1)
                    first=rows()[0]['task_id']
                    expect(page.locator('.dialogue-intent summary').last).to_contain_text('任务已受理')
                    expect(page.locator('.message.assistant:not([data-task-control]) .bubble').last).to_have_text('我在这里陪你，可以慢慢说。')
                    card=page.locator('[data-task-id="'+first+'"]');expect(card).to_be_visible()
                    page.locator('#message').fill('保留这条草稿');card.get_by_role('button',name='修改目录…').click()
                    expect(page.locator('#message')).to_have_value('保留这条草稿')
                    page.locator('#message').fill('');card.get_by_role('button',name='修改目录…').click()
                    expect(page.locator('#message')).to_have_value('把报告 '+first+' 的目录改为 ')
                    send('把报告 '+first+' 的目录改为 sub');wait(lambda:len(rows())==2)
                    second=next(row['task_id'] for row in rows() if row['task_id']!=first)
                    assert record(first)['task']['status']=='CANCELLED'
                    assert record(second)['action']['arguments']['inventory']['relative_path']=='sub'
                    checks.append('mixed answer plus actual unique report; draft preserved; target-specific pending report atomically replaced')
                    plan=json.loads(json.dumps(PLAN));plan['steps'][0]['arguments']['relative_path']='sub';planner.outputs=[json.dumps(plan)]
                    planner.release.clear();server.computer.queue.set_paused(False);assert planner.entered.wait(5)
                    tick=time.perf_counter();send('我想继续聊聊天');latency['chat_during_held_task_ms']=round((time.perf_counter()-tick)*1000,3)
                    assert record(second)['action']['status']=='DISPATCHING'
                    tick=time.perf_counter();send('取消报告 '+second);latency['cancel_during_held_task_ms']=round((time.perf_counter()-tick)*1000,3)
                    wait(lambda:record(second)['task']['status']=='CANCELLED')
                    expect(page.locator('.dialogue-intent summary').last).to_contain_text('任务控制已受理')
                    planner.release.set();planner.outputs=[json.dumps(PLAN)]
                    checks.append('foreground dialogue completes while background planner held; natural cancellation targets only the selected report')
                    send(TEXT);wait(lambda:len(rows())==3)
                    third=next(row['task_id'] for row in rows() if row['task_id'] not in {first,second})
                    wait(lambda:record(third)['action']['status']=='CONFIRMED')
                    artifact=json.loads(server.conversation_tasks.artifact(cid,third))
                    assert artifact['total_files']==2 and artifact['total_bytes']==8
                    before_calls=len(calls);page.evaluate('Workspace.flushConversation()');page.reload()
                    page.wait_for_function('()=>window.Dialogue&&window.Workspace&&!Workspace.isBusy()&&coreReady&&!refreshing')
                    assert len(rows())==3 and len(calls)==before_calls
                    page.evaluate('ConversationTasks.load(true)')
                    page.screenshot(path=str(output/'report-admission-desktop.png'))
                    page.set_viewport_size({'width':390,'height':844})
                    page.screenshot(path=str(output/'report-admission-mobile.png'))
                    assert page.evaluate('document.documentElement.scrollWidth<=innerWidth+1')
                    checks.append('real LPAC artifact exact counts; refresh restores existing records without re-execution; 390px no horizontal overflow')
                    assert not errors,errors
                    browser.close()
                finally:job.close()
        finally:
            planner.release.set();server.shutdown();server.server_close();thread.join(3)
    report={'status':'SUCCEEDED' if hashes()==before else 'SOURCE_CHANGED','source_version':__version__,
        'source_sha256':before,'source_changed':hashes()!=before,'checks':checks,'browser_errors':errors,'latency':latency,
        'cloud_calls':0,'limits':'Synthetic dialogue/planner timing, real HTTP/browser/ledger/LPAC. Not cloud latency, general semantics or long-load fairness.',
        'screenshots':[str(output/'report-admission-desktop.png'),str(output/'report-admission-mobile.png')]}
    (ROOT/'evals/reports/report-admission-ui-2026-10-19.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps({k:v for k,v in report.items() if k!='source_sha256'},ensure_ascii=False))
    return report['status']!='SUCCEEDED'


if __name__=='__main__':sys.exit(main())
