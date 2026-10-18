"""Real Host/UI arithmetic with inference forbidden and disposable records."""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime,timezone
import http.client
import importlib.util
import json
import os
from pathlib import Path
import sys
import tempfile
import threading
import time
from unittest.mock import patch
import uuid

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'runtime/node-host'),str(ROOT/'runtime/worker-host'),str(ROOT/'adapters/computer-use')]
from jarvis_core import __version__
from jarvis_core.service import CoreService
from jarvis_core.chat import ChatService
from jarvis_computer.browser import DriverJob
from playwright.sync_api import sync_playwright,expect


def main():
    output=Path(os.environ['LOCALAPPDATA'])/'Jarvis/data/diagnostics/calculator';output.mkdir(parents=True,exist_ok=True)
    spec=importlib.util.spec_from_file_location('calculator_ui_server',ROOT/'apps/web/server.py');web=importlib.util.module_from_spec(spec);spec.loader.exec_module(web)
    errors=[];checks=[];responses=[]
    with tempfile.TemporaryDirectory(prefix='jarvis-calculator-ui-') as temp:
        base=Path(temp);source=base/'sample';source.mkdir();core=CoreService(base/'data');core.initialize(source)
        server=web.create_server(core=core,chat=ChatService(core),port=0)
        thread=threading.Thread(target=server.serve_forever,kwargs={'poll_interval':.01},daemon=True);thread.start()
        origin='http://127.0.0.1:'+str(server.server_port)
        def request(message,token=True,origin_header=True):
            connection=http.client.HTTPConnection('127.0.0.1',server.server_port,timeout=3)
            headers={'Content-Type':'application/json','X-Jarvis-Request':uuid.uuid4().hex}
            if token:headers['X-Jarvis-Nonce']=server.nonce
            if origin_header:headers['Origin']=origin
            start=time.perf_counter();connection.request('POST','/api/chat',json.dumps({'message':message,'provider':'local'}),headers)
            response=connection.getresponse();data=json.loads(response.read());connection.close()
            return response.status,data,round((time.perf_counter()-start)*1000,3)
        try:
            with patch('jarvis_core.chat.gateway.probe',side_effect=AssertionError('Inference forbidden in calculator probe')),sync_playwright() as p:
                # Replay the previous 40 failures with the original question.
                samples=[]
                for _ in range(40):
                    code,data,elapsed=request('17 加 25 等于多少？只回答计算结果。')
                    assert code==200 and data['text']=='42' and data['provider']=='builtin' and data['attempts']==[]
                    samples.append(elapsed)
                checks.append('40/40 original arithmetic requests return exact 42 through Host, with zero inference dispatches')
                # Existing two HTTP slots remain independent of pure evaluation.
                with ThreadPoolExecutor(2) as pool:
                    results=list(pool.map(request,['/计算 (1/3)*3','/计算 0.1+0.2']))
                assert all(code==200 and data['provider']=='builtin' for code,data,_ in results)
                assert request('17+25',token=False)[0]==403 and request('17+25',origin_header=False)[0]==403
                job=DriverJob(p)
                try:
                    browser=p.chromium.launch(channel='msedge',headless=True,chromium_sandbox=True)
                    page=browser.new_page(viewport={'width':1440,'height':1050});page.on('pageerror',lambda e:errors.append(str(e)))
                    page.on('response',lambda r:responses.append(r.status) if r.url.endswith('/api/chat') else None)
                    page.goto(origin);expect(page.locator('#send')).to_be_enabled(timeout=15000)
                    expect(page.locator('.jarvis-cinema')).not_to_be_visible(timeout=15000)
                    def send(text,expected):
                        page.locator('#message').fill(text);page.locator('#composer').evaluate('e=>e.requestSubmit()')
                        expect(page.locator('.message.assistant').last.locator('.bubble')).to_have_text(expected)
                        expect(page.locator('#message')).to_be_enabled()
                    send('17 加 25 等于多少？只回答计算结果。','42')
                    expect(page.locator('.message.assistant').last).to_contain_text('本地精确计算')
                    expect(page.locator('#context-report')).to_contain_text('未调用模型')
                    send('0.1+0.2','0.1+0.2 = 0.3')
                    send('/计算 1/3，保留2位小数','1/3 = 0.33')
                    expect(page.locator('#conversation-status')).to_have_attribute('data-state','saved')
                    page.screenshot(path=str(output/'calculator-desktop.png'),full_page=True)
                    page.reload();expect(page.locator('.message.assistant')).to_have_count(3)
                    expect(page.locator('.message.assistant').last).to_contain_text('本地精确计算')
                    checks.append('Real UI formats results and builtin metadata, keeps existing chat history, and restores truthful local-source labels after archive reload')
                    # Simulate a broken/unavailable model catalog in the page;
                    # the actual Host remains ready and calculates normally.
                    page.route('**/api/models',lambda route:route.fulfill(status=503,content_type='application/json',body='{"user_message":"fixture catalog unavailable"}'))
                    page.reload();expect(page.locator('#toast')).to_contain_text('模型目录暂不可用')
                    page.wait_for_function('() => window.Workspace && !window.Workspace.isBusy() && !refreshing')
                    expect(page.locator('#send')).to_be_disabled()
                    page.locator('#message').fill('/计算 17+25');expect(page.locator('#send')).to_be_enabled()
                    page.locator('#composer').evaluate('e=>e.requestSubmit()')
                    expect(page.locator('.message.assistant').last.locator('.bubble')).to_have_text('17+25 = 42')
                    checks.append('Explicit /计算 works when model catalog is unavailable; core remains connected and ordinary non-model-free requests stay disabled')
                    page.set_viewport_size({'width':390,'height':844});assert page.evaluate('document.documentElement.scrollWidth<=innerWidth')
                    page.screenshot(path=str(output/'calculator-mobile.png'),full_page=True)
                    page.goto(origin+'/settings#modules');card=page.locator('[data-module="calculator"]')
                    expect(card).to_contain_text('本地精确计算',timeout=15000);expect(card).to_contain_text('exact-rational-v1')
                    expect(card).to_contain_text('本次启动');expect(card).not_to_contain_text('1,000')
                    expect(page.locator('[data-module="native-skills"]')).to_contain_text('10 项 · 当前目录')
                    card.screenshot(path=str(output/'calculator-module.png'))
                    assert not errors,errors;browser.close()
                finally:job.close()
            assert not (Path(core.data_dir)/'model-probes.db').exists(),'Unexpected model request journal'
            counters=server.metrics.snapshot()['counters'];assert counters['calculation_completed']==46
            report={'version':__version__,'captured_at':datetime.now(timezone.utc).isoformat(),'status':'passed','checks':checks,
                'replayed_failure_case':{'samples':40,'correct':40,'p50_http_ms':sorted(samples)[19],'max_http_ms':max(samples)},
                'completed_calculations':counters['calculation_completed'],'model_calls':0,'paid_calls':0,'page_errors':errors,
                'screenshots':[str(output/name) for name in ('calculator-desktop.png','calculator-mobile.png','calculator-module.png')],
                'limits':['Host arithmetic route success does not improve or certify raw model arithmetic.','Broken model catalog is injected at browser HTTP boundary; independent Python test forbids reading model configuration.','Temporary records only, no source/production changes or model download.']}
            (ROOT/'evals/reports/calculator-ui.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
            print(json.dumps(report,ensure_ascii=False))
        finally:server.shutdown();server.server_close();thread.join(3)


if __name__=='__main__':main()
