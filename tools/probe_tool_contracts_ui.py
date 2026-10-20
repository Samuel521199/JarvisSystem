"""Synthetic model drafts, real browser review -> K3 -> LPAC candidate chain."""
import argparse
import json
from pathlib import Path
import sys
import tempfile
import threading

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/p) for p in ('runtime/node-host','adapters/computer-use','apps/web')]
from jarvis_core import __version__
from jarvis_core.service import CoreService
from jarvis_core.evolution.catalog import ProjectTools
from jarvis_core.evolution.tool_intent import ToolIntents
from jarvis_core.evolution.tool_contract import ToolContracts
from jarvis_computer.browser import DriverJob
from probe_workspace_ui import SyntheticChat
from playwright.sync_api import sync_playwright,expect
import server as web

DRAFT={'input_contract':'整数数组，可为空。','output_contract':'返回总和的十进制整数字符串。',
       'non_goals':['不接受字符串或对象。'],'public_cases':[{'input':[1,2],'expected':'3'},{'input':[],'expected':'0'}],
       'questions':['空数组是否返回零？']}


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--output',required=True,type=Path)
    args=parser.parse_args();args.output.mkdir(parents=True,exist_ok=False)
    report={'version':__version__,'status':'running','paid_model_calls':0};errors=[];draft_calls=[];coding_calls=[]
    def save():(args.output/'report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    save()
    with tempfile.TemporaryDirectory(prefix='jarvis-contract-ui-') as tmp:
        root=Path(tmp);project=root/'project';project.mkdir();source=project/'calc.py'
        original=b"def transform(data):\n    return 'wrong'\n";source.write_bytes(original)
        core=CoreService(root/'data');core.initialize(project);host=web.create_server(core=core,chat=SyntheticChat(),port=0)
        class Provider:
            def contract(self,goal,route,cancel,checkpoint,reasoning=None):
                checkpoint();draft_calls.append(goal);return DRAFT,{'status':'SUCCEEDED','dispatched':False,'fixture':True}
        host.evolution.provider=Provider()
        def generate(*args):
            coding_calls.append(True)
            return {'status':'SUCCEEDED','text':json.dumps({'code':'def transform(data):\n    return str(sum(data))\n','notes':'synthetic fixture'})}
        host.computer.skills.coding_generate=generate
        thread=threading.Thread(target=host.serve_forever,kwargs={'poll_interval':.02},daemon=True);thread.start()
        url='http://127.0.0.1:'+str(host.server_port)
        try:
            with sync_playwright() as pw:
                owner=DriverJob(pw)
                try:
                    browser=pw.chromium.launch(channel='msedge',headless=True,chromium_sandbox=True)
                    page=browser.new_page(viewport={'width':1480,'height':1040});page.on('pageerror',lambda e:errors.append(str(e)))
                    page.goto(url);expect(page.locator('#send')).to_be_enabled(timeout=15000)
                    expect(page.locator('.jarvis-cinema')).not_to_be_visible(timeout=15000)
                    page.locator('#open-project').click();page.locator('#folder-path').fill(str(project));page.locator('#project-open').click()
                    expect(page.locator('#context-project')).to_contain_text(str(project))
                    def send(text):page.locator('#message').fill(text);page.locator('#composer').evaluate('e=>e.requestSubmit()')
                    send('你好');expect(page.locator('#messages')).to_contain_text('文件夹就是项目的根目录',timeout=15000)
                    send('/工具 计算整数数组的总和');intent=page.locator('#tool-intents-view');expect(intent).to_contain_text('目录中未匹配',timeout=15000)
                    intent.get_by_role('button',name='验收草案与审阅',exact=True).click()
                    view=page.locator('#tool-contracts-view');expect(view).to_be_visible()
                    view.get_by_role('button',name='生成验收草案（调用进化模型）').click()
                    expect(view).to_contain_text('草案待审阅',timeout=15000)
                    cid=page.evaluate('Workspace.currentConversation().id')
                    intents=ToolIntents(ProjectTools(host.evolution,host.conversation_tasks));plan=intents.listing(cid)[0]
                    contracts=ToolContracts(intents.tools);draft=contracts.listing(cid,plan['id'])[0]
                    assert len(draft_calls)==1 and not coding_calls and not draft.get('review')
                    view.get_by_role('button',name='使用已核对草案准备编码').click();expect(view.locator('[role=status]')).to_contain_text('请先核对')
                    view.get_by_label('待澄清：空数组是否返回零？',exact=True).fill('是，返回字符串零。')
                    private=[{'input':[3,8],'expected':'11'},{'input':[-4,4],'expected':'0'}]
                    view.get_by_label('独立留出案例 JSON',exact=True).fill(json.dumps(private))
                    view.get_by_label('独立预期依据',exact=True).fill('人工依据整数加法单独核算。')
                    view.get_by_label('我已核对需求、公开案例和留出预期的依据',exact=True).check()
                    view.get_by_role('button',name='刷新与核对草案').click()
                    expect(view.get_by_label('待澄清：空数组是否返回零？',exact=True)).to_have_value('是，返回字符串零。')
                    view.get_by_role('button',name='使用已核对草案准备编码').click()
                    expect(page.locator('#skill-coding-demand')).to_be_checked();expect(page.locator('#skill-coding-recipe')).to_have_value('python-zipapp-v1')
                    page.locator('#skill-paths').fill('calc.py');page.locator('#model-trigger').click();page.locator('#model-search').fill('离线验证模型');page.locator('#model-options button').filter(has_text='离线验证模型').first.click()
                    page.locator('#composer').evaluate('e=>e.requestSubmit()')
                    dialog=page.locator('#growth-dialog');expect(dialog).to_be_visible(timeout=15000)
                    child=intents.view(cid,plan['id'])['coding'];assert child['status']=='PROPOSED' and not coding_calls
                    assert contracts.bound(cid,plan['id'],draft['id'])['review']['oracle_verified_by_system'] is False
                    dialog.get_by_role('button',name='开始编码与独立验收').click()
                    expect(dialog).to_contain_text('候选与产物已通过',timeout=60000)
                    child=intents.view(cid,plan['id'])['coding'];assert child['result']['verified']
                    page.screenshot(path=str(args.output/'reviewed-candidate.png'))
                    page.locator('#growth-close').click();page.reload();expect(page.locator('#send')).to_be_enabled(timeout=15000)
                    expect(page.locator('.jarvis-cinema')).not_to_be_visible(timeout=15000)
                    # Open the persisted parent through its actual chat receipt.
                    page.locator('#messages>[data-growth-ref="'+plan['id']+'"]').get_by_role('button',name='查看改进与结果').click()
                    page.get_by_role('button',name='查看工具选择与实际结果').click()
                    expect(intent).to_be_visible(timeout=15000)
                    expect(intent).to_contain_text('编码改进单：SUCCEEDED',timeout=15000)
                    # Directly reopen saved draft data through the same exposed UI API.
                    page.evaluate('p=>ToolContracts.open(p)',plan);expect(view).to_contain_text('审阅已接受',timeout=15000)
                    expect(view.get_by_label('输入格式',exact=True)).to_be_disabled()
                    view.get_by_role('button',name='核对或继续原编码交接').click()
                    expect(intent).to_be_visible(timeout=15000)
                    expect(intent).to_contain_text('编码改进单：SUCCEEDED',timeout=15000)
                    assert intents.view(cid,plan['id'])['coding']['id']==child['id'] and len(coding_calls)==1
                    prefix=url+'/api/project-tools/'+cid+'/plans/'+plan['id']+'/contracts'
                    assert page.request.get(prefix).status==403
                    for suffix in ['', '/'+draft['id']+'/review','/'+draft['id']+'/cancel']:
                        assert page.request.post(prefix+suffix,headers={'Origin':'https://example.invalid','X-Jarvis-Nonce':page.evaluate('NONCE')},data={}).status==403
                    page.get_by_role('tab',name='验收草案',exact=True).click()
                    expect(view).to_be_visible(timeout=15000)
                    expect(view).to_contain_text('审阅已接受',timeout=15000)
                    page.set_viewport_size({'width':390,'height':844});assert page.evaluate('document.documentElement.scrollWidth<=innerWidth')
                    expect(page.get_by_role('tab',name='验收草案',exact=True)).to_have_attribute('aria-selected','true')
                    expect(view).to_be_visible()
                    page.screenshot(path=str(args.output/'review-narrow.png'))
                    assert not errors and source.read_bytes()==original
                    report.update(status='passed',checks=['gap -> model draft without code execution','review gate and independent examples','draft inputs survive panel refresh','reviewed public requirements passed to K3; actual isolated acceptance','reload freezes accepted review; retry reconciles same coding task','nonce and Origin enforced on all draft mutations','390px layout and zero page errors','original source unchanged'],draft_fixture_calls=len(draft_calls),coding_fixture_calls=len(coding_calls),coding_result=child['result'],page_errors=errors)
                    save();browser.close()
                finally:owner.close()
        except Exception as exc:report.update(status='failed',error=str(exc),page_errors=errors);save();raise
        finally:host.shutdown();host.server_close();thread.join(5)
    print(json.dumps({'status':report['status'],'report':str(args.output/'report.json')}))

if __name__=='__main__':main()
