"""Actual HTTP/Edge policy and durable request UI, no cloud calls."""
import argparse
import json
from pathlib import Path
import sys
import tempfile
import threading
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'runtime/node-host'),str(ROOT/'adapters/computer-use'),str(ROOT/'apps/web')]
from jarvis_core import __version__
from jarvis_core.service import CoreService
from jarvis_core.evolution.growth_cycle import GrowthCycles
from jarvis_computer.browser import DriverJob
from probe_workspace_ui import SyntheticChat
from playwright.sync_api import sync_playwright,expect
import server as web


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--output',type=Path,required=True)
    args=p.parse_args();args.output.mkdir(parents=True,exist_ok=False);errors=[]
    report={'version':__version__,'paid_model_calls':0,'checks':[]}
    with tempfile.TemporaryDirectory(prefix='jarvis-growth-ui-') as tmp:
        root=Path(tmp);project=root/'project';project.mkdir()
        core=CoreService(root/'data');core.initialize(project)
        with patch.object(GrowthCycles,'tick',return_value=None):
            server=web.create_server(core=core,chat=SyntheticChat(),port=0)
            thread=threading.Thread(target=server.serve_forever,kwargs={'poll_interval':.02},daemon=True);thread.start()
            origin='http://127.0.0.1:'+str(server.server_port)
            try:
                with sync_playwright() as pw:
                    owner=DriverJob(pw)
                    try:
                        browser=pw.chromium.launch(channel='msedge',headless=True,chromium_sandbox=True)
                        page=browser.new_page(viewport={'width':1480,'height':1100});page.on('pageerror',lambda e:errors.append(str(e)))
                        page.goto(origin);expect(page.locator('#send')).to_be_enabled(timeout=15000)
                        expect(page.locator('.jarvis-cinema')).not_to_be_visible(timeout=15000)
                        page.locator('#open-project').click();page.locator('#folder-path').fill(str(project));page.locator('#project-open').click()
                        expect(page.locator('#context-project')).to_contain_text(str(project))
                        page.locator('#message').fill('你好');page.locator('#composer').evaluate('e=>e.requestSubmit()')
                        expect(page.locator('#messages')).to_contain_text('文件夹就是项目的根目录',timeout=15000)
                        page.locator('#open-project-tools').click()
                        page.get_by_role('button',name='可持续成长',exact=True).click()
                        pane=page.locator('#growth-cycles-view');expect(pane).to_be_visible()
                        pane.get_by_label('你希望反复处理的需求',exact=True).fill('请帮我反复清理每日购物清单。')
                        pane.get_by_label('明确选择本轮验收契约',exact=True).select_option('clean-lines')
                        pane.get_by_role('button',name='按策略开始本轮成长',exact=True).click()
                        expect(pane.locator('[role=status]')).to_contain_text('尚无适用且有效的成长策略',timeout=15000)
                        pane.locator('summary').filter(has_text='此项目的成长策略与预算').click()
                        pane.get_by_label('允许按此策略自动推进',exact=True).check()
                        pane.get_by_role('button',name='保存成长策略',exact=True).click()
                        expect(pane.locator('[role=status]')).to_contain_text('请先核对范围和调用预算')
                        pane.get_by_label('已核对范围及预算：每轮最多 8 次模型调用、6 份独立对照样本',exact=True).check()
                        pane.get_by_role('button',name='保存成长策略',exact=True).click()
                        expect(pane.locator('[role=status]')).to_have_text('策略已保存。',timeout=15000)
                        pane.get_by_label('你希望反复处理的需求',exact=True).fill('请帮我反复清理每日购物清单。')
                        pane.get_by_label('明确选择本轮验收契约',exact=True).select_option('')
                        pane.get_by_role('button',name='按策略开始本轮成长',exact=True).click()
                        expect(pane.locator('[role=status]')).to_contain_text('请先选择明确契约')
                        pane.get_by_label('明确选择本轮验收契约',exact=True).select_option('clean-lines')
                        # Drop only response after actual commit; GET reconciles same request.
                        def drop(route):
                            if route.request.method=='POST':route.fetch();route.abort('failed')
                            else:route.continue_()
                        page.route('**/growth',drop)
                        pane.get_by_role('button',name='按策略开始本轮成长',exact=True).click()
                        expect(pane.locator('[role=status]')).to_contain_text('请刷新核对',timeout=15000)
                        page.unroute('**/growth',drop)
                        pane.get_by_role('button',name='刷新原记录',exact=True).click()
                        expect(pane.locator('[role=status]')).to_contain_text('已找到原请求',timeout=15000)
                        with server.evolution.store.connection() as db:assert db.execute('SELECT count(*) FROM growth_cycles').fetchone()[0]==1
                        report['checks'].append('explicit contract and policy; rejected request can be corrected; actual committed request with lost reply reconciled once')
                        # Chat remains interactive while the receipt is pending.
                        page.locator('#message').fill('继续聊聊今天的安排');page.locator('#composer').evaluate('e=>e.requestSubmit()')
                        expect(page.locator('#messages .bubble').filter(has_text='文件夹就是项目的根目录。')).to_have_count(2,timeout=15000)
                        expect(page.locator('#send')).to_be_enabled(timeout=15000)
                        pane.get_by_role('button',name='停止此轮成长',exact=True).click()
                        expect(pane).to_contain_text('停止与恢复',timeout=15000)
                        cid=page.evaluate('Workspace.currentConversation().id')
                        c=server.evolution.growth.snapshot(cid)['cycles'][0]
                        server.evolution.growth.cleanup(c)
                        pane.get_by_role('button',name='刷新原记录',exact=True).click()
                        expect(pane).to_contain_text('已取消',timeout=15000)
                        page.screenshot(path=str(args.output/'growth-desktop.png'))
                        page.reload();expect(page.locator('#send')).to_be_enabled(timeout=15000)
                        expect(page.locator('.jarvis-cinema')).not_to_be_visible(timeout=15000)
                        page.locator('#open-project-tools').click();page.get_by_role('button',name='可持续成长',exact=True).click()
                        expect(page.locator('#growth-cycles-view')).to_contain_text('已取消',timeout=15000)
                        page.set_viewport_size({'width':390,'height':844})
                        assert page.evaluate('document.documentElement.scrollWidth<=innerWidth')
                        page.screenshot(path=str(args.output/'growth-narrow.png'))
                        report['checks'].append('parallel synthetic chat, cancellation, refresh receipt recovery and narrow viewport')
                        assert not errors,errors;browser.close()
                    finally:owner.close()
            finally:server.shutdown();server.server_close()
    report.update(status='passed',page_errors=errors)
    (args.output/'report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(report,ensure_ascii=False))


if __name__=='__main__':main()
