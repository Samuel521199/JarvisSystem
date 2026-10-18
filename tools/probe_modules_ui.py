"""Real Edge + loopback + slots; synthetic candidate health/model, no cloud calls."""
from datetime import datetime, timezone
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import uuid
from unittest.mock import patch
import zipfile

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT),str(ROOT/'runtime/node-host'),str(ROOT/'adapters/computer-use')]
from jarvis_core import __version__
from jarvis_core.service import CoreService
from jarvis_computer.browser import DriverJob
from tools.probe_workspace_ui import SyntheticChat
from playwright.sync_api import sync_playwright, expect


def main():
    spec=importlib.util.spec_from_file_location('modules_ui_probe',ROOT/'apps/web/server.py')
    web=importlib.util.module_from_spec(spec);spec.loader.exec_module(web)
    output=Path(os.environ['LOCALAPPDATA'])/'Jarvis/data/diagnostics/runtime-entry';output.mkdir(parents=True,exist_ok=True)
    errors=[];checks=[];requests=[];release=threading.Event()
    with tempfile.TemporaryDirectory(prefix='jarvis-modules-ui-') as directory:
        base=Path(directory);core=CoreService(base/'data');core.initialize(ROOT/'tests/fixtures/workspace')
        server=web.create_server(core=core,chat=SyntheticChat(),port=0)
        server.memory.put(uuid.uuid4().hex,{'revision':0,'document':{'title':'测试偏好',
            'content':'PRIVATE_MEMORY_MUST_NOT_APPEAR_IN_MODULES','project_id':None,'providers':[]}})
        server.modules.releases_root=base/'slots';server.modules.model_root=base/'absent-models'
        archive=base/'trusted-fixture.zip';raw=b'synthetic UI fixture'
        manifest={'schema_version':1,'version':'ui-fixture','files':{'source/hello.txt':{'sha256':hashlib.sha256(raw).hexdigest(),'size':len(raw)}}}
        with zipfile.ZipFile(archive,'w') as z:
            z.writestr('source/hello.txt',raw);z.writestr('release.json',json.dumps(manifest))
        thread=threading.Thread(target=server.serve_forever,kwargs={'poll_interval':.02},daemon=True);thread.start()
        origin='http://127.0.0.1:'+str(server.server_address[1])
        try:
            with sync_playwright() as playwright:
                job=DriverJob(playwright)
                try:
                    browser=playwright.chromium.launch(channel='msedge',headless=True,chromium_sandbox=True)
                    page=browser.new_page(viewport={'width':1440,'height':1000})
                    page.on('pageerror',lambda e:errors.append(str(e)))
                    page.on('request',lambda r:requests.append(r.url) if r.url==origin+'/api/modules' else None)
                    page.goto(origin+'/settings#modules')
                    expect(page.locator('.module-card')).to_have_count(23,timeout=15000)
                    expect(page.locator('[data-module="memory"]')).to_contain_text('明确事实记忆')
                    expect(page.locator('[data-module="memory"]')).to_contain_text('有效事实')
                    expect(page.locator('[data-module="memory"]')).to_contain_text('1 项')
                    expect(page.locator('[data-module="knowledge"]')).to_contain_text('已启用')
                    expect(page.locator('[data-module="mcp-registration"]')).to_contain_text('MCP 登记')
                    expect(page.locator('[data-module="extension-runtime"]')).to_contain_text('尚未实现')
                    expect(page.locator('[data-module="tts"]')).to_contain_text('未接入')
                    expect(page.locator('#module-error')).to_be_hidden()
                    expect(page.locator('#error')).to_be_hidden()
                    page.locator('#module-filter').select_option('planned');expect(page.locator('.module-card')).to_have_count(2)
                    page.locator('#module-filter').select_option('busy');expect(page.locator('[data-module="host"]')).to_be_visible()
                    page.locator('#module-filter').select_option('all')
                    checks.append('18 observations; explicit memory metadata, sample report, registration/execution and filters distinguished')
                    page.locator('#seed-catalog summary').click()
                    expect(page.locator('#seed-status')).to_contain_text('已校验')
                    page.locator('#seed-query').fill('构建')
                    expect(page.locator('#seed-content')).to_contain_text('规划中')
                    expect(page.locator('#seed-content')).not_to_contain_text('project.definition')
                    page.locator('#seed-query').fill('')
                    expect(page.locator('#seed-content')).to_contain_text('project.definition')
                    response=page.request.get(origin+'/api/modules',headers={'X-Jarvis-Nonce':server.nonce})
                    assert response.status==200
                    assert 'PRIVATE_MEMORY_MUST_NOT_APPEAR_IN_MODULES' not in response.text()
                    assert response.json()['catalog']['chat_callable'] is False
                    checks.append('seed version/source and search visible; planned build not executable; no private fact body in snapshot')
                    page.locator('#seed-catalog').screenshot(path=str(output/'catalog-desktop.png'))
                    page.locator('[data-module="memory"]').screenshot(path=str(output/'memory-card.png'))
                    page.locator('#seed-catalog summary').click()
                    page.locator('#module-archive').fill(str(archive));page.locator('#module-refresh').click()
                    expect(page.locator('#module-archive')).to_have_value(str(archive))
                    page.screenshot(path=str(output/'desktop.png'))
                    page.locator('#module-import button').click()
                    expect(page.locator('.module-release')).to_have_count(1,timeout=15000)
                    expect(page.locator('[data-release-action="select"]')).to_be_disabled()
                    checks.append('import actual ZIP through UI; unverified version cannot be selected')
                    entered=threading.Event()
                    def health(*a,**kw):
                        entered.set();release.wait(20)
                        return subprocess.CompletedProcess([],0,json.dumps({'status':'passed','version':'ui-fixture'}),'')
                    with patch('jarvis_core.releases.subprocess.run',side_effect=health):
                        page.locator('[data-release-action="health"]').click()
                        assert entered.wait(5)
                        expect(page.locator('#module-jobs')).to_contain_text('处理中')
                        response=page.request.post(origin+'/api/chat',headers={'Origin':origin,'X-Jarvis-Nonce':server.nonce},data={'message':'synthetic concurrency check'})
                        assert response.status==200 and response.json()['status']=='SUCCEEDED'
                        release.set()
                        expect(page.locator('[data-release-action="select"]')).to_be_enabled(timeout=15000)
                    page.locator('[data-release-action="select"]').click()
                    expect(page.locator('#module-selection')).to_contain_text('release-',timeout=15000)
                    assert server.modules._releases()['active']
                    checks.append('blocked synthetic health job leaves real HTTP chat responsive; verified slot selection persisted')
                    page.locator('[data-view="appearance"]').click();page.wait_for_timeout(1000)
                    count=len(requests);page.wait_for_timeout(9000);assert len(requests)==count
                    page.locator('[data-view="modules"]').click();expect(page.locator('#module-archive')).to_have_value(str(archive))
                    checks.append('navigation stops module polling; archive draft survives navigation and refresh')
                    page.set_viewport_size({'width':390,'height':844});page.evaluate('scrollTo(0,0)')
                    assert page.evaluate('document.documentElement.scrollWidth<=innerWidth')
                    page.screenshot(path=str(output/'mobile.png'))
                    checks.append('390px layout has no horizontal page overflow')
                    assert not errors,errors
                    browser.close()
                finally:job.close()
        finally:
            release.set();server.shutdown();server.server_close();thread.join(3)
    result={'version':__version__,'captured_at':datetime.now(timezone.utc).isoformat(),
            'status':'passed','checks':checks,'page_errors':errors,'screenshots':[str(output/name) for name in ('desktop.png','mobile.png','catalog-desktop.png','memory-card.png')],
            'limits':['Candidate health subprocess and chat model are synthetic; real ZIP/SQLite/HTTP/browser paths exercised.',
                      'No live runtime switch, cloud model call, full load benchmark or OS sandbox claim.']}
    (ROOT/'evals/reports/runtime-entry-ui.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(result,ensure_ascii=False))


if __name__=='__main__':main()
