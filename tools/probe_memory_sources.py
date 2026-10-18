"""Real Edge/HTTP source review and revocation; temporary data, synthetic model."""
import argparse
from datetime import datetime, timezone
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import threading
import traceback
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT/'runtime/node-host'), str(ROOT/'adapters/computer-use')]
from jarvis_core import __version__
from jarvis_core.service import CoreService
from jarvis_core.chat import ChatService
from jarvis_core.conversations import ConversationStore
from jarvis_core.personal_candidates import PersonalCandidates
from jarvis_computer.browser import DriverJob
from playwright.sync_api import sync_playwright, expect


def run(out, report):
    spec = importlib.util.spec_from_file_location('memory_sources_web', ROOT/'apps/web/server.py')
    web = importlib.util.module_from_spec(spec); spec.loader.exec_module(web)
    calls = []
    def model(config, provider, message, *args, **kwargs):
        calls.append(message)
        return {'status':'SUCCEEDED','text':'这是临时测试回复。','provider':provider,'model':config['providers'][provider]['model']}
    with tempfile.TemporaryDirectory(prefix='jarvis-memory-sources-') as folder:
        base=Path(folder);source=base/'sample';source.mkdir()
        core=CoreService(base/'data');core.initialize(source);chat=ChatService(core)
        server=web.create_server(core=core,chat=chat,port=0)
        if server.evolution:server.evolution.close()
        thread=threading.Thread(target=server.serve_forever,kwargs={'poll_interval':.02},daemon=True);thread.start()
        try:
            with patch('jarvis_core.chat.gateway.probe',side_effect=model),sync_playwright() as p:
                driver=DriverJob(p)
                try:
                    browser=p.chromium.launch(channel='msedge',headless=True,chromium_sandbox=True)
                    page=browser.new_page(viewport={'width':1440,'height':1000})
                    page.on('pageerror',lambda e:report['page_errors'].append(str(e)))
                    page.goto('http://127.0.0.1:'+str(server.server_port))
                    expect(page.locator('#send')).to_be_enabled()
                    expect(page.locator('.jarvis-cinema')).not_to_be_visible(timeout=15000)
                    page.locator('#message').fill('我平时喜欢无糖茶。我们下次继续讨论旅行安排。')
                    page.locator('#composer').evaluate('e=>e.requestSubmit()')
                    expect(page.locator('.message.assistant')).to_have_count(1)
                    expect(page.locator('#conversation-status')).to_have_attribute('data-state','saved')
                    cid=page.evaluate('Workspace.currentConversation().id')
                    page.locator('.candidate-entry').first.click()
                    card=page.locator('.candidate-card').first
                    expect(card).to_be_visible();card.get_by_label('名称',exact=True).fill('饮品偏好')
                    card.get_by_role('button',name='确认并保存',exact=True).click()
                    expect(card).to_contain_text('已保存事实记忆')
                    page.locator('#personal-candidates').get_by_role('button',name='关闭',exact=True).click()
                    def open_memory():
                        page.locator('#open-memory').click()
                        expect(page.locator('#memory-status')).not_to_have_text('正在读取…')
                    open_memory();expect(page.locator('.memory-source-state')).to_contain_text('来源已核对')
                    page.locator('.memory-source summary').click()
                    expect(page.locator('.memory-source blockquote')).to_contain_text('旅行安排')
                    page.screenshot(path=str(out/'source-desktop.png'))
                    page.locator('#memory-close').click();page.locator('#clear').click()
                    archives=ConversationStore(core);archive=archives.get(cid)
                    archive['document']['messages'][0]['content']='我现在喜欢咖啡。'
                    archives.put(cid,{'revision':archive['revision'],'document':archive['document']})
                    open_memory();expect(page.locator('.memory-source-state')).to_contain_text('暂停用于回答')
                    assert chat.memory.context({'enabled':True,'project_id':None},'local')[0]==''
                    page.set_viewport_size({'width':390,'height':844})
                    assert page.evaluate('document.documentElement.scrollWidth<=innerWidth')
                    assert page.locator('#memory-dialog').evaluate('e=>e.scrollWidth<=e.clientWidth')
                    page.screenshot(path=str(out/'source-mobile.png'))
                    # The write succeeds once, but the first browser response is lost.
                    ident=chat.memory.list()['facts'][0]['id']
                    def lost(route):route.fetch();route.abort('failed')
                    page.route('**/api/memory/'+ident,lost)
                    page.get_by_role('button',name='确认独立保留',exact=True).click()
                    expect(page.locator('#memory-status')).to_have_attribute('data-error','true')
                    page.unroute('**/api/memory/'+ident,lost)
                    page.get_by_role('button',name='确认独立保留',exact=True).click()
                    expect(page.locator('#memory-status')).to_contain_text('已按你的确认独立保留')
                    assert chat.memory.list()['facts'][0]['revision']==2
                    expect(page.locator('.memory-source-state')).to_contain_text('你已独立确认')
                    page.locator('#memory-close').click();page.set_viewport_size({'width':1440,'height':1000})
                    page.locator('#message').fill('请给出简短答复')
                    page.locator('#composer').evaluate('e=>e.requestSubmit()')
                    expect(page.locator('.message.assistant')).to_have_count(1)
                    expect(page.locator('#conversation-status')).to_have_attribute('data-state','saved')
                    # Default route may be cloud: local-only is never implicitly expanded.
                    assert len(calls)==2 and all('旅行安排' not in m for m in calls[1:])
                    open_memory();page.get_by_role('button',name='忘记',exact=True).click()
                    page.get_by_role('button',name='确认忘记',exact=True).click()
                    expect(page.locator('#memory-status')).to_contain_text('已忘记')
                    expect(page.locator('.memory-card')).to_have_count(0)
                    assert chat.memory.list()['facts']==[]
                    assert not report['page_errors']
                    report['checks']=['Real UI confirms source-bound fact and displays verified original text',
                        'Changed source pauses model use while preserving visible fact',
                        '390px layout and source controls do not overflow',
                        'Independent confirmation survives lost response with exactly one revision',
                        'Default local-only route permissions preserved; source excerpt not added to model context',
                        'Real forget button removes fact; no automatic model calls for source operations']
                    report['fixture_model_calls']=len(calls)
                    browser.close()
                finally:driver.close()
        finally:server.shutdown();server.server_close();thread.join(5)


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args();args.output.mkdir(parents=True,exist_ok=False)
    report={'version':__version__,'captured_at':datetime.now(timezone.utc).isoformat(),'checks':[],'page_errors':[],
            'real_model_calls':0,'user_data_modified':False}
    try:run(args.output,report);report['status']='passed'
    except Exception:report['status']='failed';report['failure']=traceback.format_exc()
    (args.output/'report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(report,ensure_ascii=False));return 0 if report['status']=='passed' else 1


if __name__=='__main__':raise SystemExit(main())
