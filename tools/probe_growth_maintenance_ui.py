"""Real local HTTP/SQLite and Edge maintenance flows; synthetic receipts, no model."""
import argparse
import json
from pathlib import Path
import sys
import threading
import uuid

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'runtime/node-host'),str(ROOT/'adapters/computer-use'),str(ROOT/'apps/web'),str(ROOT/'tests')]
from jarvis_core import __version__
from jarvis_core import policy
from jarvis_computer.browser import DriverJob
from playwright.sync_api import sync_playwright,expect
from probe_workspace_ui import SyntheticChat
from test_growth_maintenance import MaintenanceTests
import server as web


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--output',required=True,type=Path);args=parser.parse_args()
    args.output.mkdir(parents=True,exist_ok=False)
    report={'version':__version__,'status':'running','paid_model_calls':0,'checks':[]};errors=[]
    fixture=MaintenanceTests();fixture.setUp()
    original=fixture.seed();blocked=fixture.seed('UNKNOWN');pid,tid,_=fixture.seed_directory()
    chat=SyntheticChat();server=web.create_server(core=fixture.core,chat=chat,port=0)
    # Share this fixture's non-monitoring manager, with no background task creation.
    server.evolution.close();server.evolution=fixture.manager
    thread=threading.Thread(target=server.serve_forever,kwargs={'poll_interval':.02},daemon=True);thread.start()
    origin='http://127.0.0.1:'+str(server.server_port)
    def save():(args.output/'report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    save()
    try:
        with sync_playwright() as pw:
            owner=DriverJob(pw)
            try:
                browser=pw.chromium.launch(channel='msedge',headless=True,chromium_sandbox=True)
                page=browser.new_page(viewport={'width':1460,'height':1100});page.on('pageerror',lambda e:errors.append(str(e)))
                page.goto(origin+'/settings#growth');expect(page.locator('#growth-view')).to_be_visible(timeout=15000)
                pane=page.locator('#evolution-maintenance');pane.locator('summary').first.click()
                pane.get_by_role('button',name='预览引用与容量',exact=True).click()
                expect(pane.locator('#evolution-maintenance-summary')).to_contain_text('在线回执 2 / 1000',timeout=15000)
                expect(pane.locator('input[value="'+blocked['id']+'"]')).to_be_disabled()
                pane.locator('input[value="'+original['id']+'"]').check()
                pane.locator('#evolution-maintenance-note').fill('核对终态与恢复引用；保留原编号及全部完整材料。')
                pane.locator('#evolution-maintenance-reviewed').check()
                pane.get_by_role('button',name='校验并归档所选回执',exact=True).click()
                expect(pane.locator('#evolution-maintenance-summary')).to_contain_text('在线回执 1 / 1000 · 已归档 1',timeout=15000)
                assert fixture.store.job(original['id'])==original
                assert fixture.store.existing_job(original['request']['request_id'])==original
                report['checks'].append('explicit preview, unknown protected; reviewed actual archive frees online slot, original ID/request and result intact')
                pane.locator('#evolution-maintenance-reviewed').check()
                pane.get_by_role('button',name='收存退役目录',exact=True).click()
                expect(pane.get_by_role('button',name='恢复目录（保持退役）',exact=True)).to_be_visible(timeout=15000)
                expect(pane.locator('#evolution-maintenance-summary')).to_contain_text('在线目录 0 / 32')
                pane.locator('#evolution-maintenance-reviewed').check()
                pane.get_by_role('button',name='恢复目录（保持退役）',exact=True).click()
                expect(pane.get_by_role('button',name='收存退役目录',exact=True)).to_be_visible(timeout=15000)
                with fixture.store.connection() as db:
                    life=json.loads(db.execute('SELECT document FROM tool_lifecycle').fetchone()[0])
                    assert life['phase']=='RETIRED'
                    assert db.execute('SELECT active FROM project_tools').fetchone()[0] is None
                report['checks'].append('reviewed directory store releases slot; restore remains retired with original identity and increasing generation')
                # Lose only the reply after a committed operation, then reconcile by preview.
                late=fixture.seed();pane.get_by_role('button',name='预览引用与容量',exact=True).click()
                expect(pane.locator('input[value="'+late['id']+'"]').first).to_be_visible(timeout=15000)
                pane.locator('input[value="'+late['id']+'"]').check();pane.locator('#evolution-maintenance-reviewed').check()
                def drop(route):
                    if route.request.method=='POST':route.fetch();route.abort('failed')
                    else:route.continue_()
                page.route('**/api/evolution/maintenance',drop)
                pane.get_by_role('button',name='校验并归档所选回执',exact=True).click()
                expect(pane.locator('#evolution-maintenance-result')).to_contain_text('原整理已完成',timeout=15000)
                page.unroute('**/api/evolution/maintenance',drop)
                with fixture.store.connection() as db:assert db.execute('SELECT COUNT(*) FROM maintenance_receipts').fetchone()[0]==4
                assert fixture.store.job(late['id'])==late
                report['checks'].append('committed POST reply lost; recent maintenance receipt reconciles same operation with no second admission')
                page.screenshot(path=str(args.output/'maintenance.png'))
                page.reload();expect(page.locator('#growth-view')).to_be_visible(timeout=15000)
                pane=page.locator('#evolution-maintenance');pane.locator('summary').first.click()
                pane.get_by_role('button',name='预览引用与容量',exact=True).click()
                expect(pane.locator('#evolution-maintenance-summary')).to_contain_text('已归档 2',timeout=15000)
                page.set_viewport_size({'width':390,'height':844});assert page.evaluate('document.documentElement.scrollWidth<=innerWidth')
                page.screenshot(path=str(args.output/'narrow.png'))
                assert not errors and chat.calls==0
                report.update(status='passed',page_errors=errors,chat_calls=chat.calls,capacity=fixture.service.preview()['capacity'])
                report['checks'].append('reload retains archives and audit; narrow layout no document overflow; zero browser errors and zero model calls')
                browser.close()
            finally:owner.close()
    except Exception as exc:report.update(status='failed',error=repr(exc),page_errors=errors);raise
    finally:
        save();server.shutdown();server.server_close();thread.join(5);fixture.doCleanups()
    print(json.dumps({'status':report['status'],'report':str(args.output/'report.json')}))


if __name__=='__main__':main()
