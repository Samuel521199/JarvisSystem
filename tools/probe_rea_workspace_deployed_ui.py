"""Read the retained confirmed example in the real service without dispatching a task."""
import json
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'adapters/computer-use'),str(ROOT/'runtime/worker-host')]
from playwright.sync_api import sync_playwright,expect
from jarvis_computer.browser import DriverJob


def main():
    path=ROOT/'evals/reports/rea-explanation-deployment-2026-10-18.json'
    record=json.loads(path.read_bytes());errors=[]
    with sync_playwright() as p:
        job=DriverJob(p)
        try:
            browser=p.chromium.launch(channel='msedge',headless=True,chromium_sandbox=True)
            page=browser.new_page(viewport={'width':1440,'height':1000});page.on('pageerror',lambda e:errors.append(str(e)))
            page.goto('http://127.0.0.1:18181/#chat='+record['conversation_id'])
            expect(page.locator('#send')).to_be_enabled(timeout=15000)
            expect(page.locator('.jarvis-cinema')).not_to_be_visible(timeout=15000)
            page.get_by_role('button',name='查看真实任务',exact=True).click()
            expect(page.get_by_role('button',name='查看分析报告',exact=True)).to_be_visible(timeout=15000)
            page.get_by_role('button',name='查看分析报告',exact=True).click();page.get_by_role('tab',name='中文解释',exact=True).click()
            expect(page.locator('#rea-pane-explanation')).to_contain_text('fixture:op1')
            expect(page.locator('#rea-pane-explanation')).to_contain_text('vertex / gemini-3.1-pro-preview')
            page.screenshot(path=str(ROOT/'artifacts/rea-explanation/live-workspace.png'));assert errors==[],errors
            page.goto('http://127.0.0.1:18181/settings#skill')
            expect(page.locator('.skill-card')).to_have_count(11,timeout=15000)
            expect(page.locator('#page-title')).to_have_text('技能与工具')
            page.screenshot(path=str(ROOT/'artifacts/rea-explanation/live-settings.png'),full_page=True)
            assert errors==[],errors;browser.close()
        finally:job.close()
    record['live_ui']={'status':'passed','page_errors':errors,
        'screenshots':['artifacts/rea-explanation/live-workspace.png','artifacts/rea-explanation/live-settings.png'],
        'checks':['retained confirmed task in real service','Chinese explanation and model route visible','11 cards in unified settings']}
    path.write_text(json.dumps(record,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print('Live UI passed; no new model call')


if __name__=='__main__':main()
