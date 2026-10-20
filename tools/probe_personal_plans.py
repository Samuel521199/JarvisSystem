"""Disposable real-browser personal plan flow; no production data or cloud calls."""
from contextlib import closing
from datetime import datetime, timezone
import argparse
import json
from pathlib import Path
import sys
import tempfile
import time
import uuid

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'tools'),str(ROOT/'tests'),str(ROOT/'runtime/node-host'),str(ROOT/'adapters/computer-use')]
from probe_parallel_runtime import fixture, web, serve, request
from probe_workspace_ui import SyntheticChat
from test_sample_tasks import SyntheticPlanner
from test_conversations import document
from jarvis_core.conversations import ConversationStore
from jarvis_core import __version__
from jarvis_computer.browser import DriverJob
from playwright.sync_api import sync_playwright, expect


def run(output):
    output.mkdir(parents=True,exist_ok=True)
    checks=[];errors=[]
    with tempfile.TemporaryDirectory(prefix='jarvis-personal-plan-ui-') as directory:
        base=Path(directory);core=fixture(base);chat=SyntheticChat()
        server=web.create_server(core=core,chat=chat,port=0)
        planner=SyntheticPlanner()
        server.computer.sample.chat_factory=lambda *a,**kw:planner
        thread=serve(server)
        cid=uuid.uuid4().hex
        ConversationStore(core).put(cid,{'revision':0,'document':document('先整理目录，再复核资料')})
        try:
            with sync_playwright() as pw,closing(DriverJob(pw)):
                browser=pw.chromium.launch(channel='msedge',headless=True,chromium_sandbox=True)
                page=browser.new_page(viewport={'width':1440,'height':1000})
                page.on('pageerror',lambda e:errors.append(str(e)))
                page.goto(f'http://127.0.0.1:{server.server_port}/#chat={cid}')
                page.get_by_role('button',name='个人计划与主动跟进',exact=True).click()
                panel=page.get_by_role('dialog',name='个人计划与主动跟进')
                expect(panel).to_be_visible()
                panel.get_by_label('这次想完成什么？').fill('整理样例并核对结果')
                panel.get_by_label('行动或未结事项').fill('整理样例目录\n再次核对目录')
                panel.get_by_role('button',name='保存可编辑草案').click()
                expect(panel.locator('.plan-step')).to_have_count(2)
                for card in panel.locator('.plan-step').all():
                    card.get_by_label('执行能力',exact=True).select_option('natural')
                    card.get_by_label('模型',exact=True).select_option('auto')
                    card.get_by_label('发送给执行器的要求').fill('列举样例并统计保存报告')
                panel.get_by_label('主动跟进',exact=True).select_option('true')
                panel.get_by_role('button',name='保存修改与授权').click()
                expect(panel.locator('h2')).to_contain_text('已暂停')
                page.screenshot(path=str(output/'plan-draft.png'),full_page=True)
                panel.get_by_role('button',name='确认计划并继续').click()
                page.locator('#message').focus()
                assert page.evaluate("document.activeElement.id==='message'")
                checks.append('nonmodal_plan_panel_keeps_chat_focusable')
                expect(panel.locator('h2')).to_contain_text('执行中')
                # Keep foreground dialogue available during the existing Worker queue.
                started=time.monotonic()
                code,result,_=request(server,'/api/chat','POST',{'message':'你好','provider':'local','history':[]})
                assert code==200 and result['status']=='SUCCEEDED',(code,result)
                chat_latency=time.monotonic()-started
                until=time.monotonic()+30
                while time.monotonic()<until:
                    server.assistant_plans.tick()
                    if server.assistant_plans.list(cid)['plans'][0]['state']=='COMPLETE':break
                    time.sleep(.1)
                assert server.assistant_plans.list(cid)['plans'][0]['state']=='COMPLETE'
                page.evaluate('PersonalPlans.refresh()')
                expect(panel.locator('h2')).to_contain_text('已交付')
                expect(panel.get_by_label('可纠正的结果笔记')).to_be_visible()
                panel.get_by_label('可纠正的结果笔记').fill('样例目录已核对；实际项目目录仍需另行处理。')
                panel.get_by_role('button',name='保存纠正（旧引用立即失效）').click()
                expect(panel).to_have_attribute('aria-busy','false')
                expect(panel.get_by_label('可纠正的结果笔记')).to_have_value('样例目录已核对；实际项目目录仍需另行处理。')
                panel.get_by_role('button',name='确认纳入',exact=True).click()
                expect(panel.get_by_role('heading',name='结果候选 · 已纳入')).to_be_visible()
                page.screenshot(path=str(output/'plan-complete.png'),full_page=True)
                checks.extend(['editable_two_step_plan_real_worker','foreground_reply_during_plan',
                               'candidate_correction_and_knowledge_admission'])
                panel.get_by_role('button',name='撤回此结果候选').click()
                expect(panel.get_by_role('heading',name='结果候选 · 已撤回')).to_be_visible()
                checks.append('candidate_withdrawal_ui')
                page.set_viewport_size({'width':390,'height':844})
                assert page.evaluate('document.documentElement.scrollWidth<=innerWidth+1')
                assert panel.evaluate('(e)=>e.scrollWidth<=e.clientWidth+2')
                page.screenshot(path=str(output/'plan-mobile.png'),full_page=True)
                checks.append('narrow_layout_and_accessible_controls')
                browser.close()
            assert not errors,errors
            return {'status':'passed','version':__version__,'checks':checks,'page_errors':errors,
                    'foreground_fixture_seconds':round(chat_latency,3),'model_fixture_calls':len(planner.calls),
                    'actual_cloud_calls':0,'production_data_modified':False,'screenshots':str(output),
                    'limitations':['Single-PC synthetic model output; not a real model latency or low-memory PC benchmark.']}
        finally:
            server.shutdown();server.server_close();thread.join(3)


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--output',type=Path,required=True);args=parser.parse_args()
    result=run(args.output);result['captured_at']=datetime.now(timezone.utc).isoformat()
    (args.output/'result.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(result,ensure_ascii=False))
