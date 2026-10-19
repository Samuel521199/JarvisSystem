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
    args=parser.parse_args();args.output.mkdir(parents=True,exist_ok=False)
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
                    pane.get_by_role('button',name='验收并启用工具',exact=True).click()
                    status=pane.locator('[role=status]');expect(status).to_have_text('已完成',timeout=60000)
                    card=pane.locator('article');expect(card).to_contain_text('4 条保留案例')
                    report['checks'].append('verified candidate button -> publish with retained heldout contract -> active tool')
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
                    # Missing nonce and foreign origin must not reach this project capability.
                    no_nonce=page.request.get(origin+'/api/project-tools/'+cid);assert no_nonce.status==403
                    nonce=page.evaluate('NONCE')
                    forbidden=page.request.post(origin+'/api/project-tools/'+cid,headers={'Origin':'https://example.invalid','X-Jarvis-Nonce':nonce},data={})
                    assert forbidden.status==403
                    report['checks'].append('missing nonce / foreign origin rejected')
                    page.reload();expect(page.locator('#send')).to_be_enabled(timeout=15000)
                    expect(page.locator('.jarvis-cinema')).not_to_be_visible(timeout=15000)
                    page.locator('#open-project-tools').click();pane=page.locator('#project-tools-view');card=pane.locator('article')
                    expect(card).to_contain_text('结果独立核验 1 次',timeout=15000)
                    card.get_by_role('button',name='停用工具',exact=True).click()
                    expect(card).to_contain_text('已停用',timeout=15000);expect(card.get_by_role('button',name='运行工具',exact=True)).to_be_disabled()
                    card.get_by_role('button',name='恢复上一版本',exact=True).click()
                    expect(card).to_contain_text('已启用',timeout=60000)
                    report['checks'].append('reload retains receipts; disable and validated restore update controls')
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
