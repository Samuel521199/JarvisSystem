"""K4 project tool UI: synthetic proposal, real HTTP, LPAC and durable receipts."""
import argparse
import json
from pathlib import Path
import sys
import tempfile
import threading
import time
import uuid

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'runtime/node-host'),str(ROOT/'adapters/computer-use'),str(ROOT/'apps/web')]
from jarvis_core import __version__
from jarvis_core.service import CoreService
from jarvis_computer.browser import DriverJob
from probe_workspace_ui import SyntheticChat
from playwright.sync_api import sync_playwright,expect
import server as web


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--output',required=True,type=Path)
    parser.add_argument('--intent',action='store_true');args=parser.parse_args();args.output.mkdir(parents=True,exist_ok=False)
    report={'version':__version__,'status':'running','paid_model_calls':0,'checks':[]};errors=[];calls=[]
    def save():(args.output/'report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    save()
    with tempfile.TemporaryDirectory(prefix='jarvis-project-tools-ui-') as tmp:
        root=Path(tmp);project=root/'project';project.mkdir();source=project/'calc.py'
        original=b"def transform(data):\n    return 'wrong'\n";source.write_bytes(original)
        core=CoreService(root/'data');core.initialize(project);server=web.create_server(core=core,chat=SyntheticChat(),port=0)
        def generate(*args):
            calls.append(True)
            return {'status':'SUCCEEDED','text':json.dumps({'code':'def transform(data):\n    return str(sum(data))\n','notes':'synthetic fixture'})}
        server.computer.skills.coding_generate=generate
        thread=threading.Thread(target=server.serve_forever,kwargs={'poll_interval':.02},daemon=True);thread.start()
        origin='http://127.0.0.1:'+str(server.server_port)
        try:
            with sync_playwright() as pw:
                owner=DriverJob(pw)
                try:
                    browser=pw.chromium.launch(channel='msedge',headless=True,chromium_sandbox=True)
                    page=browser.new_page(viewport={'width':1480,'height':1040});page.on('pageerror',lambda e:errors.append(str(e)))
                    page.goto(origin);expect(page.locator('#send')).to_be_enabled(timeout=15000)
                    expect(page.locator('.jarvis-cinema')).not_to_be_visible(timeout=15000)
                    page.locator('#open-project-tools').click();expect(page.locator('#toast')).to_have_text('请先选择已保存的项目会话。')
                    page.locator('#open-project').click();page.locator('#folder-path').fill(str(project));page.locator('#project-open').click()
                    expect(page.locator('#context-project')).to_contain_text(str(project))
                    page.locator('#message').fill('你好');page.locator('#composer').evaluate('e=>e.requestSubmit()')
                    expect(page.locator('#messages')).to_contain_text('文件夹就是项目的根目录',timeout=15000)
                    cid=page.evaluate('Workspace.currentConversation().id');pid=page.evaluate('Workspace.currentProject().id')
                    item=server.conversation_tasks.submit(cid,{'mode':'skill','request_id':'web-'+uuid.uuid4().hex,
                        'prompt':'修复求和','project_id':pid,'skill_id':'matt-pocock.code-review','paths':['calc.py'],
                        'coding':True,'model':'vertex::gemini-3.8-flash','build_recipe':'python-zipapp-v1',
                        'cases':[{'input':[1,2],'expected':'3'},{'input':[],'expected':'0'}],
                        'heldout_cases':[{'input':[-2,2],'expected':'0'},{'input':[10,20],'expected':'30'}]})
                    deadline=time.monotonic()+90
                    while time.monotonic()<deadline:
                        detail=server.conversation_tasks.detail(cid,item['task_id'])
                        if detail['task']['status'] not in {'READY','RUNNING'}:break
                        time.sleep(.1)
                    artifact=json.loads(server.conversation_tasks.artifact(cid,item['task_id']))
                    assert artifact['coding']['passed']
                    page.evaluate('v=>SkillWorkbench.codingPreview(v.report,v.task)',{'report':artifact,'task':item['task_id']})
                    page.get_by_role('button',name='纳入项目工具',exact=True).click()
                    pane=page.locator('#project-tools-view');expect(pane).to_be_visible()
                    pane.get_by_label('工具标识（例如 text-summary）',exact=True).fill('sum-tool')
                    pane.get_by_label('显示名称',exact=True).fill('求和工具')
                    pane.get_by_label('什么时候使用',exact=True).fill('整数列表求和')
                    pane.get_by_label('什么时候不使用',exact=True).fill('对象和字符串不适用')
                    pane.get_by_label('我已核对用途、独立验收和本次灰度范围',exact=True).check()
                    pane.get_by_label('准入审阅依据',exact=True).fill('已核对独立求和要求和本轮真实新输入。')
                    pane.get_by_role('button',name='审阅并进入灰度',exact=True).click()
                    status=pane.locator('[role=status]');expect(status).to_have_text('已完成',timeout=60000)
                    card=pane.locator('article');expect(card).to_contain_text('4 条保留案例')
                    expect(card).to_contain_text('灰度观察')
                    expect(card.get_by_role('button',name='运行工具',exact=True)).to_be_disabled()
                    expect(card.get_by_role('button',name='核对后正式启用',exact=True)).to_be_disabled()
                    def trial(value,expected):
                        card.get_by_label('本次输入（JSON）',exact=True).fill(value)
                        card.get_by_label('独立预期结果（可选，按原样文本比较）',exact=True).fill(expected)
                        card.get_by_label('核对独立预期（可验证空字符串）',exact=True).check()
                        card.get_by_label('本次结果有实际用途（明确反馈，不由模型打分）',exact=True).check()
                        card.get_by_label('本次用途与独立预期依据',exact=True).fill('独立加法核算，用于项目统计。')
                        card.get_by_role('button',name='灰度试用候选',exact=True).click()
                        expect(status).to_contain_text('结果与独立预期一致',timeout=60000)
                        expect(pane.get_by_label('工具任务结果',exact=True)).to_have_text(expected)
                    def review():
                        card.get_by_label('本次启用/暂停/退役审阅依据',exact=True).fill('已核对独立结果、用途和本次恢复范围。')
                        card.get_by_label('我已核对本次生命周期操作',exact=True).check()
                    trial('[100,-8,3]','95');trial('[120,-8,3]','115')
                    expect(card.get_by_role('button',name='核对后正式启用',exact=True)).to_be_enabled(timeout=15000)
                    review();card.get_by_role('button',name='核对后正式启用',exact=True).click()
                    expect(card).to_contain_text('已正式启用',timeout=60000)
                    report['checks'].append('reviewed staging keeps inactive; two novel independent LPAC trials and usefulness unlock explicit promotion')
                    card.get_by_label('本次输入（JSON）',exact=True).fill('[100, -8, 3]')
                    card.get_by_label('独立预期结果（可选，按原样文本比较）',exact=True).fill('95')
                    card.get_by_label('核对独立预期（可验证空字符串）',exact=True).check()
                    card.get_by_role('button',name='运行工具',exact=True).click()
                    expect(status).to_contain_text('结果与独立预期一致',timeout=60000)
                    expect(pane.get_by_label('工具任务结果',exact=True)).to_have_text('95')
                    expect(card).to_contain_text('结果独立核验 1 次',timeout=15000)
                    assert pane.evaluate('e=>{const b=e.getBoundingClientRect();return b.top>=0&&b.bottom<=innerHeight}')
                    expect(card.get_by_label('本次输入（JSON）',exact=True)).to_have_value('[100, -8, 3]')
                    page.screenshot(path=str(args.output/'tool-result.png'))
                    report['checks'].append('new input actual LPAC execution with independent result; usage counted once')
                    if args.intent:
                        from jarvis_core.evolution.tool_intent import ToolIntents
                        from jarvis_core.evolution.catalog import ProjectTools
                        intents=ToolIntents(ProjectTools(server.evolution,server.conversation_tasks))
                        def send(value):
                            page.locator('#message').fill(value);page.locator('#composer').evaluate('e=>e.requestSubmit()')
                        assert not page.evaluate('ToolIntents.command("请用简单语言处理这段说明")')
                        assert page.evaluate('ToolIntents.command("请用求和工具处理 [1,2]")')
                        send('请用求和工具处理 [200, -8]')
                        view=page.locator('#tool-intents-view');expect(view).to_be_visible(timeout=15000)
                        expect(view).to_contain_text('192',timeout=60000)
                        expect(page.locator('#messages')).to_contain_text('工具执行完成',timeout=15000)
                        first=intents.listing(cid)[0];assert first['invocation']['result']['text']=='192'
                        assert not first['invocation']['result']['result_verified']
                        page.screenshot(path=str(args.output/'named-request.png'))
                        page.reload();expect(page.locator('#send')).to_be_enabled(timeout=15000)
                        expect(page.locator('.jarvis-cinema')).not_to_be_visible(timeout=15000)
                        page.locator('#messages>[data-growth-ref]').filter(has_text='工具执行完成').get_by_role('button',name='查看改进与结果').click()
                        page.get_by_role('button',name='查看工具选择与实际结果').click()
                        expect(view).to_contain_text('192',timeout=15000)
                        assert intents.listing(cid)[0]['invocation']['id']==first['invocation']['id']
                        send('/工具 整数列表求和');expect(view).to_contain_text('待选择工具',timeout=15000)
                        newest=intents.listing(cid)[0];assert newest['invocation'] is None
                        selection=view.locator('[data-tool-plan="'+newest['id']+'"]')
                        selection.get_by_label('本次 JSON 输入',exact=True).fill('[7,8]')
                        selection.get_by_label('独立预期（可选）',exact=True).fill('15')
                        selection.get_by_label('核对独立预期',exact=True).check()
                        view.get_by_role('button',name='刷新与核对请求',exact=True).click()
                        expect(selection.get_by_label('本次 JSON 输入',exact=True)).to_have_value('[7,8]')
                        expect(selection.get_by_label('独立预期（可选）',exact=True)).to_have_value('15')
                        expect(selection.get_by_label('核对独立预期',exact=True)).to_be_checked()
                        selection.get_by_role('button',name='使用所选工具',exact=True).click()
                        expect(selection).to_contain_text('结果与独立预期一致',timeout=60000)
                        send('/工具 请把温度转为华氏度');expect(view).to_contain_text('目录中未匹配',timeout=15000)
                        gap=intents.listing(cid)[0];gapcard=view.locator('[data-tool-plan="'+gap['id']+'"]')
                        gapcard.get_by_role('button',name='补齐验收并建立编码改进单').click()
                        expect(page.locator('#skill-coding-demand')).to_be_checked()
                        page.locator('#skill-paths').fill('calc.py')
                        page.locator('#skill-coding-cases').fill(json.dumps([{'input':0,'expected':'32'},{'input':100,'expected':'212'}]))
                        page.locator('#skill-coding-heldout').fill(json.dumps([{'input':-40,'expected':'-40'},{'input':10,'expected':'50'}]))
                        page.locator('#model-trigger').click();page.locator('#model-search').fill('离线验证模型')
                        page.locator('#model-options button').filter(has_text='离线验证模型').first.click()
                        page.locator('#composer').evaluate('e=>e.requestSubmit()')
                        expect(page.locator('#growth-dialog')).to_be_visible(timeout=15000)
                        child=intents.view(cid,gap['id'])['coding'];assert child and child['status']=='PROPOSED' and child['task_id'] is None
                        assert len(calls)==1
                        page.screenshot(path=str(args.output/'gap-handoff.png'))
                        page.locator('#growth-close').click();page.locator('#composer-mode').select_option('chat')
                        send('/工具 不要运行求和工具')
                        expect(view).to_contain_text('没有执行指令',timeout=15000)
                        assert intents.listing(cid)[0]['invocation'] is None
                        report['intent_checks']=['exact named natural request dispatched once','result displayed and archived as control receipt','reload opens original receipt without replay','lexical suggestion waits for explicit input and independent expectation','gap binds original coding demand without model dispatch','negation remains non-executable']
                        page.set_viewport_size({'width':390,'height':844})
                        assert page.evaluate('document.documentElement.scrollWidth<=innerWidth')
                        page.screenshot(path=str(args.output/'intent-narrow.png'))
                        page.set_viewport_size({'width':1480,'height':1040})
                    # Missing nonce and foreign origin must not reach this project capability.
                    no_nonce=page.request.get(origin+'/api/project-tools/'+cid);assert no_nonce.status==403
                    nonce=page.evaluate('NONCE')
                    forbidden=page.request.post(origin+'/api/project-tools/'+cid,headers={'Origin':'https://example.invalid','X-Jarvis-Nonce':nonce},data={})
                    assert forbidden.status==403
                    if args.intent:
                        assert page.request.get(origin+'/api/project-tools/'+cid+'/plans').status==403
                        for suffix in ['', '/'+first['id']+'/start','/'+gap['id']+'/coding','/'+gap['id']+'/cancel']:
                            assert page.request.post(origin+'/api/project-tools/'+cid+'/plans'+suffix,headers={'Origin':'https://example.invalid','X-Jarvis-Nonce':nonce},data={}).status==403
                        report['intent_checks']+=['ordinary prose remains chat','selection form survives panel refresh','all plan mutations reject foreign origin; plan reads require nonce']
                    report['checks'].append('missing nonce / foreign origin rejected')
                    page.reload();expect(page.locator('#send')).to_be_enabled(timeout=15000)
                    expect(page.locator('.jarvis-cinema')).not_to_be_visible(timeout=15000)
                    page.locator('#open-project-tools').click();pane=page.locator('#project-tools-view');card=pane.locator('article')
                    expect(card).to_contain_text('结果独立核验 '+('2' if args.intent else '1')+' 次',timeout=15000)
                    card.get_by_role('button',name='停用工具',exact=True).click()
                    expect(card).to_contain_text('尚未启用',timeout=15000);expect(card.get_by_role('button',name='运行工具',exact=True)).to_be_disabled()
                    card.get_by_role('button',name='恢复上一版本',exact=True).click()
                    expect(card).to_contain_text('已启用',timeout=60000)
                    report['checks'].append('reload retains receipts; disable and validated restore update controls')
                    review();card.get_by_role('button',name='退役此能力',exact=True).click()
                    expect(card).to_contain_text('能力已退役',timeout=15000)
                    expect(card.get_by_role('button',name='运行工具',exact=True)).to_be_disabled()
                    review();card.get_by_role('button',name='重新准入退役能力',exact=True).click()
                    expect(card).to_contain_text('灰度观察',timeout=60000)
                    expect(card.get_by_role('button',name='运行工具',exact=True)).to_be_disabled()
                    expect(card.get_by_role('button',name='核对后正式启用',exact=True)).to_be_disabled()
                    trial('[130,-8,3]','125');trial('[140,-8,3]','135')
                    review();card.get_by_role('button',name='核对后正式启用',exact=True).click()
                    expect(card).to_contain_text('已正式启用',timeout=60000)
                    report['checks'].append('retirement disables capability; restore is inactive until a new reviewed canary qualifies')
                    page.set_viewport_size({'width':390,'height':844})
                    assert page.evaluate('document.documentElement.scrollWidth<=innerWidth')
                    page.screenshot(path=str(args.output/'narrow.png'))
                    assert source.read_bytes()==original and len(calls)==1 and not errors
                    from jarvis_core.evolution.catalog import ProjectTools
                    snapshot=ProjectTools(server.evolution).snapshot(cid)
                    actual=next(j['result'] for j in snapshot['jobs'] if j['request']['submission']['operation']=='run')
                    report['execution']=actual
                    report['ledger_bytes']=server.evolution.store.path.stat().st_size
                    report.update(status='passed',synthetic_proposal_calls=len(calls),tool_model_calls=0,page_errors=errors,
                        business_source_unchanged=True,conversation_id=cid)
                    save();browser.close()
                finally:owner.close()
        except Exception as exc:report.update(status='failed',error=str(exc),page_errors=errors);save();raise
        finally:server.shutdown();server.server_close();thread.join(5)
    print(json.dumps({'status':report['status'],'report':str(args.output/'report.json')}))


if __name__=='__main__':main()
