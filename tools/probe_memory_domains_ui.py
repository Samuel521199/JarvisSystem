"""Real Edge/HTTP fact classification on disposable data; no paid model calls."""
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

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'runtime/node-host'),str(ROOT/'adapters/computer-use')]
from jarvis_core import __version__
from jarvis_core.chat import ChatService
from jarvis_core.service import CoreService
from jarvis_computer.browser import DriverJob
from playwright.sync_api import sync_playwright,expect


def run(out,report):
    spec=importlib.util.spec_from_file_location('domains_web',ROOT/'apps/web/server.py')
    web=importlib.util.module_from_spec(spec);spec.loader.exec_module(web)
    calls=[]
    def model(config,provider,message,*args,**kwargs):
        calls.append({'message':message,'history':kwargs.get('history')})
        return {'status':'SUCCEEDED','text':'合成验证回答。','provider':provider,'model':config['providers'][provider]['model']}
    with tempfile.TemporaryDirectory(prefix='jarvis-memory-domain-ui-') as tmp:
        base=Path(tmp);folder=base/'sample';folder.mkdir()
        core=CoreService(base/'data');core.initialize(folder);chat=ChatService(core)
        server=web.create_server(core=core,chat=chat,port=0)
        if server.evolution:server.evolution.close()
        thread=threading.Thread(target=server.serve_forever,kwargs={'poll_interval':.02},daemon=True);thread.start()
        try:
            with patch('jarvis_core.chat.gateway.probe',side_effect=model),sync_playwright() as p:
                driver=DriverJob(p)
                try:
                    browser=p.chromium.launch(channel='msedge',headless=True,chromium_sandbox=True)
                    page=browser.new_page(viewport={'width':1440,'height':1080})
                    page.on('pageerror',lambda e:report['page_errors'].append(str(e)))
                    page.goto('http://127.0.0.1:'+str(server.server_port))
                    expect(page.locator('#send')).to_be_enabled()
                    expect(page.locator('.jarvis-cinema')).not_to_be_visible(timeout=15000)
                    def open_panel():
                        page.locator('#open-memory').click()
                        expect(page.locator('#memory-save')).to_be_enabled()
                    def add(title,kind='personal_fact',shared=False):
                        page.locator('#memory-new').click();page.locator('#memory-title').fill(title)
                        page.locator('#memory-content').fill(title)
                        page.locator('#memory-kind').select_option(kind)
                        if shared:
                            page.locator('#memory-use-work').check()
                            page.locator('#memory-expires').fill('2030-01-01T12:34:56')
                        for checkbox in page.locator('#memory-providers input').all():checkbox.check()
                        page.locator('#memory-save').click()
                        expect(page.locator('#memory-status')).to_contain_text('已存入本机记忆')
                    open_panel();add('私人健康原因 PRIVATE_REASON')
                    add('回答先给结论 SHARED_STYLE','preference',True)
                    expect(page.locator('.memory-card')).to_have_count(2)
                    page.locator('#memory-purpose').select_option('work_assist')
                    page.locator('#memory-dialog').evaluate('e=>e.scrollTop=0')
                    page.screenshot(path=str(out/'domains-desktop.png'))
                    page.locator('#memory-close').click()
                    page.locator('#message').fill('请帮我安排工作顺序')
                    page.locator('#composer').evaluate('e=>e.requestSubmit()')
                    expect(page.locator('.message.assistant')).to_have_count(1)
                    assert len(calls)==1 and 'PRIVATE_REASON' not in calls[0]['message'] and 'SHARED_STYLE' in calls[0]['message']
                    open_panel();page.locator('#memory-category-filter').select_option('work')
                    expect(page.locator('.memory-card')).to_have_count(0)
                    page.locator('#memory-category-filter').select_option('personal')
                    expect(page.locator('.memory-card')).to_have_count(2)
                    card=page.locator('.memory-card').filter(has_text='SHARED_STYLE')
                    card.get_by_role('button',name='修改',exact=True).click()
                    page.locator('#memory-use-work').uncheck()
                    # Lost response retries must preserve the same fact/revision.
                    ident=next(row['id'] for row in chat.memory.list()['facts'] if 'SHARED_STYLE' in row['document']['title'])
                    expiry_before=next(row['document']['classification']['expires_at'] for row in chat.memory.list()['facts'] if row['id']==ident)
                    def lost(route):route.fetch();route.abort('failed')
                    page.route('**/api/memory/'+ident,lost)
                    page.locator('#memory-save').click()
                    expect(page.locator('#memory-status')).to_have_attribute('data-error','true')
                    page.unroute('**/api/memory/'+ident,lost)
                    page.locator('#memory-save').click()
                    expect(page.locator('#memory-status')).to_contain_text('已存入本机记忆')
                    assert next(r for r in chat.memory.list()['facts'] if r['id']==ident)['revision']==2
                    assert next(r['document']['classification']['expires_at'] for r in chat.memory.list()['facts'] if r['id']==ident)==expiry_before
                    page.set_viewport_size({'width':390,'height':844})
                    assert page.evaluate('document.documentElement.scrollWidth<=innerWidth')
                    assert page.locator('#memory-dialog').evaluate('e=>e.scrollWidth<=e.clientWidth')
                    page.locator('#memory-dialog').evaluate('e=>e.scrollTop=0')
                    page.screenshot(path=str(out/'domains-mobile.png'))
                    page.locator('#memory-close').click()
                    page.locator('#message').fill('继续刚才的工作安排')
                    page.locator('#composer').evaluate('e=>e.requestSubmit()')
                    expect(page.locator('.message.assistant')).to_have_count(2)
                    assert len(calls)==2 and 'SHARED_STYLE' not in calls[1]['message'] and calls[1]['history']==[]
                    # Mixed static assets / old host must not accept classification writes.
                    def old_host(route):
                        response=route.fetch();data=response.json();data.pop('capabilities',None)
                        route.fulfill(response=response,json=data)
                    page.route('**/api/memory',old_host);open_button=page.locator('#open-memory');open_button.click()
                    expect(page.locator('#memory-status')).to_contain_text('宿主仍为旧版')
                    expect(page.locator('#memory-save')).to_be_disabled()
                    page.unroute('**/api/memory',old_host)
                    assert not report['page_errors']
                    report['checks']=['Saved typed personal/shared facts through real UI and HTTP',
                        'Work request sends allowed shared fact, excludes private fact from actual provider input',
                        'Category filters preserve facts; 390px and desktop layout do not overflow',
                        'Lost response retry produces one policy revision and preserves expiry seconds',
                        'Restricted fact and dependent prior turn absent from next work provider input',
                        'Old host capability mismatch blocks new policy writes']
                    report['fixture_model_calls']=len(calls)
                    browser.close()
                finally:driver.close()
        finally:server.shutdown();server.server_close();thread.join(5)


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args();args.output.mkdir(parents=True,exist_ok=False)
    report={'version':__version__,'captured_at':datetime.now(timezone.utc).isoformat(),'checks':[],
            'page_errors':[],'real_model_calls':0,'user_data_modified':False}
    try:run(args.output,report);report['status']='passed'
    except Exception:report['status']='failed';report['failure']=traceback.format_exc()
    (args.output/'report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(report,ensure_ascii=False));return 0 if report['status']=='passed' else 1


if __name__=='__main__':raise SystemExit(main())
