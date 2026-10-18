"""Real settings start/stop, chat and report with the pinned CPU model only."""
from datetime import datetime,timezone
import importlib.util
import json
import os
import re
from pathlib import Path
import sys
import tempfile
import threading

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'runtime/node-host'),str(ROOT/'adapters/computer-use')]
from jarvis_core import __version__
from jarvis_core.service import CoreService
from jarvis_core.chat import ChatService
from jarvis_computer.browser import DriverJob
from playwright.sync_api import sync_playwright,expect


def main():
    spec=importlib.util.spec_from_file_location('local_model_ui_web',ROOT/'apps/web/server.py')
    web=importlib.util.module_from_spec(spec);spec.loader.exec_module(web)
    output=Path(os.environ['LOCALAPPDATA'])/'Jarvis/data/diagnostics/local-model';output.mkdir(parents=True,exist_ok=True)
    errors=[];checks=[];observations={}
    with tempfile.TemporaryDirectory(prefix='jarvis-local-model-ui-') as temp:
        root=Path(temp);source=root/'sample';source.mkdir();(source/'a.txt').write_bytes(b'abc');(source/'b.TXT').write_bytes(b'ab')
        core=CoreService(root/'data');core.initialize(source)
        config=json.loads((ROOT/'config/model-profiles/providers.json').read_text(encoding='utf-8'))
        config.update(default_provider='local',automatic_fallback=False,fallback_order=['local'],providers={'local':config['providers']['local']})
        cfg=root/'providers.json';cfg.write_text(json.dumps(config),encoding='utf-8')
        server=web.create_server(core=core,chat=ChatService(core,config_path=cfg),port=0)
        thread=threading.Thread(target=server.serve_forever,kwargs={'poll_interval':.02},daemon=True);thread.start()
        origin='http://127.0.0.1:'+str(server.server_address[1])
        try:
            with sync_playwright() as p:
                job=DriverJob(p)
                try:
                    browser=p.chromium.launch(channel='msedge',headless=True,chromium_sandbox=True)
                    page=browser.new_page(viewport={'width':1440,'height':1050})
                    page.on('pageerror',lambda e:errors.append(str(e)));page.goto(origin+'/settings#modules')
                    expect(page.locator('.module-card')).to_have_count(18,timeout=15000)
                    card=page.locator('[data-module="local-llm"]')
                    expect(card.get_by_role('button',name='启动本地模型',exact=True)).to_be_enabled()
                    assert not server.modules.local_model.snapshot()['owned']
                    card.get_by_role('button',name='启动本地模型',exact=True).click()
                    expect(card).to_contain_text('本实例管理',timeout=120000)
                    expect(card.get_by_role('button',name='停止本地模型',exact=True)).to_be_enabled()
                    expect(page.locator('#module-jobs')).to_contain_text('本地 Qwen3 0.6B 已启动')
                    card.screenshot(path=str(output/'runtime-card.png'))
                    checks.append('opening settings does not load weights; explicit start hashes pinned files and creates owned CPU service')
                    page.goto(origin+'/');expect(page.locator('#send')).to_be_enabled(timeout=15000)
                    expect(page.locator('.jarvis-cinema')).not_to_be_visible(timeout=15000)
                    page.locator('#message').fill('/任务 列出样例目录文件，按类型统计并保存结果')
                    page.locator('#composer').evaluate('e=>e.requestSubmit()')
                    expect(page.locator('#conversation-task-list')).to_contain_text('已核验：2 个文件',timeout=30000)
                    assert server.computer.list_tasks(all_tasks=True)['tasks'][0]['status']=='SUCCEEDED'
                    page.screenshot(path=str(output/'offline-report.png'))
                    checks.append('ordinary chat task command -> real local plan -> real LPAC Worker -> verified two-file/five-byte report')
                    page.locator('#message').fill('2加3等于几？只回答数字。');page.locator('#composer').evaluate('e=>e.requestSubmit()')
                    # Chat transport/UI gate: arithmetic correctness. Formatting
                    # compliance is recorded separately, never claimed as passed.
                    expect(page.locator('.message.assistant').last.locator('.bubble')).to_have_text(re.compile(r'^(?:5|2\s*\+\s*3\s*=\s*5)[。.!]?$'),timeout=20000)
                    answer=page.locator('.message.assistant').last.locator('.bubble').inner_text()
                    observations={'arithmetic_response':answer,'requested_number_only_followed':answer.strip()=='5'}
                    expect(page.locator('#send')).to_have_attribute('aria-label','发送消息')
                    page.goto(origin+'/settings#modules');expect(page.locator('.module-card')).to_have_count(18,timeout=15000)
                    card=page.locator('[data-module="local-llm"]');card.get_by_role('button',name='停止本地模型',exact=True).click()
                    expect(page.locator('#module-jobs')).to_contain_text('已停止本实例启动的本地模型',timeout=15000)
                    expect(card.get_by_role('button',name='启动本地模型',exact=True)).to_be_enabled()
                    assert not server.modules.local_model.snapshot()['owned'];assert core.status()['stopped'] is False
                    checks.append('real local chat works; explicit stop reclaims owned model while core and web remain available')
                    page.set_viewport_size({'width':390,'height':844})
                    assert page.evaluate('document.documentElement.scrollWidth<=innerWidth')
                    card.screenshot(path=str(output/'runtime-mobile.png'))
                    assert not errors,errors;browser.close()
                finally:job.close()
        finally:server.shutdown();server.server_close();thread.join(3)
    report={'version':__version__,'captured_at':datetime.now(timezone.utc).isoformat(),'status':'passed','checks':checks,
        'page_errors':errors,'model_observations':observations,'paid_model_calls':0,'screenshots':[str(output/x) for x in ['runtime-card.png','offline-report.png','runtime-mobile.png']],
        'limits':['Loopback local-only profile; no whole-machine network disconnection or OS inference sandbox.','Fixed two-file report and one arithmetic chat do not establish broad local-model quality.']}
    (ROOT/'evals/reports/local-model-ui.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(report,ensure_ascii=False))


if __name__=='__main__':main()
