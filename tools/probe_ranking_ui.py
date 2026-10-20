"""Real Edge/HTTP module controls with deterministic transport, no paid calls."""
import argparse
from contextlib import closing
import json
from pathlib import Path
import sys
import tempfile
import threading
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'runtime/node-host'),str(ROOT/'adapters/computer-use'),str(ROOT/'apps/web')]
from jarvis_core.service import CoreService
from jarvis_core.workspace import WorkspaceService
from jarvis_core.ranking_program import source_for
from jarvis_computer.browser import DriverJob
from probe_workspace_ui import SyntheticChat
from playwright.sync_api import sync_playwright, expect
import server as web


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args();args.output.mkdir(parents=True,exist_ok=False)
    report={'paid_model_calls':0,'status':'running','checks':[]};errors=[]
    class Transport:
        calls=0
        def probe(self,*a,**kw):
            self.calls+=1
            assert 'security_epoch' in a[4]()
            return {'status':'SUCCEEDED','text':json.dumps({'code':source_for(('coverage','score','path','start_line')),'notes':'deterministic UI fixture'})}
    transport=Transport()
    with tempfile.TemporaryDirectory(prefix='jarvis-ranking-ui-') as tmp:
        root=Path(tmp);project=root/'project';project.mkdir()
        (project/'notes.md').write_text('# 离线部署\n离线部署使用本机资料。\n## 状态\n状态可以查询。\n',encoding='utf-8')
        core=CoreService(root/'data');core.initialize(project)
        server=web.create_server(core=core,chat=SyntheticChat(),port=0)
        server.evolution.ranking_modules.model_calls=transport
        pid=WorkspaceService(core).open_project({'path':str(project)})['id']
        server.knowledge.put('a'*32,{'revision':0,'document':{'project_id':pid,'path':'notes.md','providers':[]}})
        origin='http://127.0.0.1:'+str(server.server_address[1])
        thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
        try:
            with patch.object(server.evolution.provider,'configuration',return_value=({},'local')),patch.object(server.evolution.provider,'receipt',return_value={'status':'SUCCEEDED','synthetic':True}),sync_playwright() as pw,closing(DriverJob(pw)):
                browser=pw.chromium.launch(channel='msedge',headless=True,chromium_sandbox=True)
                page=browser.new_page(viewport={'width':1440,'height':1050})
                page.on('pageerror',lambda e:errors.append(str(e)))
                page.goto(origin+'/settings#growth')
                page.get_by_role('tab',name='进化 EVOLVE').click()
                panel=page.locator('#ranking-module-panel');panel.locator('summary').first.click()
                expect(page.locator('#ranking-model')).not_to_be_empty()
                # Simulate loss after server commits; read reconciles the original ID.
                def drop(route):
                    route.fetch();route.abort('failed')
                page.route('**/api/evolution/ranking/generate',drop)
                page.locator('#ranking-generate').click()
                expect(panel).to_contain_text('通过限定准入',timeout=30000)
                page.unroute('**/api/evolution/ranking/generate',drop)
                assert transport.calls==1
                panel.get_by_role('button',name='审阅后试用',exact=True).click()
                expect(page.locator('#ranking-message')).to_contain_text('至少 8 字')
                page.locator('#ranking-review').fill('核对独立案例、词法局限和实际耗时，开始有限试用。')
                expect(page.locator('#evolution-save')).to_be_disabled()
                panel.get_by_role('button',name='审阅后试用',exact=True).click()
                expect(page.locator('#ranking-state')).to_contain_text('试用中')
                expect(page.locator('#ranking-confirm')).to_be_disabled()
                for q in ('离线','部署','状态'):
                    result=server.knowledge.search({'project_id':pid,'query':q})
                    assert result['ranking']['used']!='lexical-v1'
                page.locator('#ranking-refresh').click()
                expect(page.locator('#ranking-confirm')).to_be_enabled()
                page.locator('#ranking-confirm').click()
                expect(page.locator('#ranking-state')).to_contain_text('已审阅保留')
                page.reload();page.get_by_role('tab',name='进化 EVOLVE').click();page.locator('#ranking-module-panel summary').first.click()
                expect(page.locator('#ranking-state')).to_contain_text('已审阅保留')
                page.screenshot(path=str(args.output/'desktop.png'),full_page=True)
                page.set_viewport_size({'width':420,'height':900})
                page.screenshot(path=str(args.output/'narrow.png'),full_page=True)
                page.locator('#ranking-review').fill('已核对原版本与回退范围，恢复内置排序。')
                page.locator('#ranking-baseline').click()
                expect(page.locator('#ranking-state')).to_contain_text('内置 lexical-v1')
                assert transport.calls==1 and not errors
                # Unauthorized write is rejected by the same server boundary.
                response=page.request.post(origin+'/api/evolution/ranking/select',data='{}')
                assert response.status in (400,403)
                report.update(status='passed',checks=['lost-reply reconciliation: one dispatch','review gate','three distinct real queries',
                    'confirmation persists across reload','baseline rollback','nonce guard','desktop and narrow rendering'],
                    synthetic_calls=transport.calls,page_errors=errors)
                browser.close()
        finally:
            server.shutdown();server.server_close();thread.join(timeout=3)
            (args.output/'report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(report,ensure_ascii=False))


if __name__=='__main__':main()
