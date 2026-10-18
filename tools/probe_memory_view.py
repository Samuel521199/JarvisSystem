"""Disposable union-view UI, resource observation and optional real-model probe."""
import argparse
from datetime import datetime, timezone
import importlib.util
import json
import os
from pathlib import Path
import statistics
import sys
import tempfile
import threading
import time
import tracemalloc
from unittest.mock import patch
import uuid

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT/'runtime/node-host'), str(ROOT/'adapters/computer-use')]
from jarvis_core import __version__
from jarvis_core.service import CoreService
from jarvis_core.workspace import WorkspaceService
from jarvis_core.memory_view import MemoryView
from jarvis_core.chat import ChatService
from jarvis_computer.browser import DriverJob
from playwright.sync_api import sync_playwright, expect


def main():
    parser = argparse.ArgumentParser(); parser.add_argument('--live', action='store_true'); args = parser.parse_args()
    output = Path(os.environ['LOCALAPPDATA'])/'Jarvis/data/diagnostics/memory-view'; output.mkdir(parents=True,exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='jarvis-memory-view-') as temp:
        base = Path(temp); sample = base/'sample'; sample.mkdir()
        core = CoreService(base/'data'); core.initialize(sample); view = MemoryView(core)
        projects = []; files = []
        for name, token in [('项目甲','AlphaGate'),('项目乙','BlueDoor'),('未选项目','DO_NOT_INCLUDE')]:
            folder = base/name; folder.mkdir(); file = folder/'design.md'
            file.write_text('# 登录设计\n登录方案代号：'+token+'。\n',encoding='utf-8'); files.append(file)
            project = WorkspaceService(core).open_project({'path':str(folder)}); projects.append(project)
            view.knowledge.put(uuid.uuid4().hex,{'revision':0,'document':{'project_id':project['id'],'path':'design.md','providers':['vertex']}})
        view.memory.put(uuid.uuid4().hex,{'revision':0,'document':{'project_id':None,'title':'汇报偏好','content':'回答使用简洁中文。','providers':['vertex']}})
        view.memory.put(uuid.uuid4().hex,{'revision':0,'document':{'project_id':projects[1]['id'],'title':'乙项目负责人','content':'登录项目负责人是小林。','providers':['vertex']}})
        context = {'enabled':True,'project_id':projects[0]['id'],'project_ids':[p['id'] for p in projects[:2]]}
        config = json.loads((ROOT/'config/model-profiles/providers.json').read_text(encoding='utf-8'))
        config.update(default_provider='vertex',automatic_fallback=False)
        cfg = base/'providers.json'; cfg.write_text(json.dumps(config),encoding='utf-8'); chat = ChatService(core,cfg)
        payload = {'project_id':context['project_id'],'project_ids':context['project_ids'],'query':'登录设计','memory_enabled':True}
        times = []
        for _ in range(20):
            start=time.perf_counter(); result=view.preview(payload); times.append((time.perf_counter()-start)*1000)
        tracemalloc.start(); view.preview(payload); _,peak=tracemalloc.get_traced_memory(); tracemalloc.stop()
        resource = {'samples':20,'median_ms':round(statistics.median(times),2),'max_ms':round(max(times),2),
                    'python_peak_bytes':peak,'read_bytes':result['knowledge']['read_bytes'],'context_bytes':result['view']['bytes'],
                    'limits':'Small synthetic fixture and warm filesystem on this PC; Python allocation, not process RSS or an SLA.'}
        spec=importlib.util.spec_from_file_location('memory_view_web',ROOT/'apps/web/server.py'); web=importlib.util.module_from_spec(spec); spec.loader.exec_module(web)
        server=web.create_server(core=core,chat=chat,port=0)
        thread=threading.Thread(target=server.serve_forever,kwargs={'poll_interval':.02},daemon=True); thread.start()
        origin='http://127.0.0.1:'+str(server.server_port); errors=[]; calls=[]; checks=[]
        def probe(config,provider,message,*unused,**kwargs):
            calls.append({'message':message,'history':kwargs['history']})
            return {'status':'SUCCEEDED','text':'项目甲采用 AlphaGate [P1]，项目乙采用 BlueDoor [P2]。','provider':provider,'model':config['providers'][provider]['model'],'outcome_uncertain':False}
        try:
            with patch('jarvis_core.chat.gateway.probe',side_effect=probe), sync_playwright() as p:
                job=DriverJob(p)
                try:
                    browser=p.chromium.launch(channel='msedge',headless=True,chromium_sandbox=True)
                    page=browser.new_page(viewport={'width':1440,'height':1050});page.on('pageerror',lambda e:errors.append(str(e)))
                    page.goto(origin+'/#project='+projects[0]['id']);expect(page.locator('#send')).to_be_enabled()
                    expect(page.locator('.jarvis-cinema')).not_to_be_visible(timeout=15000)
                    def open_panel():
                        page.locator('#open-knowledge').click();expect(page.locator('#knowledge-projects input')).to_have_count(3)
                    def send():
                        count=len(calls);page.locator('#message').fill('比较两个项目的登录设计，乙项目负责人是谁？');page.locator('#composer').evaluate('e=>e.requestSubmit()')
                        expect(page.locator('#message')).to_be_enabled();expect(page.locator('#send')).to_have_attribute('aria-label','发送消息');assert len(calls)==count+1
                    open_panel();page.locator('#knowledge-projects input[value="'+projects[1]['id']+'"]').check()
                    page.locator('#knowledge-query').fill('登录设计');page.get_by_role('button',name='检索资料',exact=True).click()
                    expect(page.locator('#knowledge-status')).to_contain_text('2 条记忆、2 段资料')
                    expect(page.locator('#knowledge-results')).to_contain_text('小林')
                    page.screenshot(path=str(output/'union-desktop.png'),full_page=True)
                    page.locator('#knowledge-close').click();send()
                    assert all(text in calls[-1]['message'] for text in ('AlphaGate','BlueDoor','小林','简洁中文'))
                    assert 'DO_NOT_INCLUDE' not in calls[-1]['message']
                    expect(page.locator('#messages .knowledge-citations button')).to_have_count(2)
                    page.locator('#messages .knowledge-citations button').filter(has_text='项目乙').click()
                    expect(page.locator('#knowledge-excerpt')).to_contain_text('BlueDoor');page.locator('#knowledge-excerpt-close').click()
                    checks.append('UI project selection -> memory and both source excerpts in same chat; unselected project excluded; cross-project citation opens correct file')
                    expect(page.locator('#conversation-status')).to_have_attribute('data-state','saved');page.reload();expect(page.locator('#send')).to_be_enabled()
                    expect(page.locator('#messages .knowledge-citations button')).to_have_count(2)
                    page.locator('#messages .knowledge-citations button').filter(has_text='项目乙').click()
                    expect(page.locator('#knowledge-excerpt')).to_contain_text('BlueDoor');page.locator('#knowledge-excerpt-close').click()
                    send();assert 'BlueDoor' not in calls[-1]['message'];assert not calls[-1]['history']
                    checks.append('Archive keeps source project IDs; refresh resets scope and excludes derived history from broader view')
                    open_panel();page.locator('#knowledge-projects input[value="'+projects[1]['id']+'"]').check()
                    page.set_viewport_size({'width':390,'height':844});page.locator('#knowledge-dialog').evaluate('e=>e.scrollTop=0')
                    assert page.locator('#knowledge-dialog').evaluate('e=>e.scrollWidth<=e.clientWidth')
                    assert page.evaluate('document.documentElement.scrollWidth<=innerWidth')
                    page.screenshot(path=str(output/'union-mobile.png'),full_page=True)
                    page.locator('#knowledge-close').click();page.set_viewport_size({'width':1440,'height':1050})
                    page.locator('#conversation-status').click();page.locator('#conversation-temporary').click();send()
                    assert 'AlphaGate' not in calls[-1]['message'] and '小林' not in calls[-1]['message']
                    checks.append('Temporary chat excludes union; desktop/mobile fit; zero page errors')
                    # The new read-only POST has the same nonce/origin protection.
                    import urllib.request, urllib.error
                    for headers in ({'Content-Type':'application/json'}, {'Content-Type':'application/json','X-Jarvis-Nonce':server.nonce}):
                        try: urllib.request.urlopen(urllib.request.Request(origin+'/api/knowledge/view',data=json.dumps(payload).encode(),headers=headers))
                        except urllib.error.HTTPError as error: assert error.code==403
                        else: raise AssertionError('unprotected union endpoint')
                    checks.append('Union preview POST rejects missing nonce or origin')
                    assert not errors,errors;browser.close()
                finally:job.close()
            report={'version':__version__,'captured_at':datetime.now(timezone.utc).isoformat(),'status':'passed','checks':checks,
                    'fixture_model_calls':len(calls),'page_errors':errors,'resources':resource,
                    'screenshots':[str(output/'union-desktop.png'),str(output/'union-mobile.png')],
                    'limits':['UI model responses are synthetic; real model results recorded separately.','No new database, dependency, background service or model download.']}
            (ROOT/'evals/reports/memory-view-ui.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
            print(json.dumps(report,ensure_ascii=False))
            if args.live:
                observations=[]
                for provider,model in [('vertex','gemini-3.8-flash'),('local',config['providers']['local']['model'])]:
                    answer=chat.reply('仅根据资料：项目甲和项目乙的登录方案代号分别是什么？乙项目负责人是谁？简洁列出，不执行任何任务。',provider=provider,model=model,memory_context=context,knowledge_context=context)
                    complete=answer.get('status')=='SUCCEEDED' and all(token in answer.get('text','') for token in ('AlphaGate','BlueDoor','小林'))
                    observations.append({'provider':provider,'model':model,'status':answer.get('status'),'expected_facts_present':complete,
                        'inline_project_citations_present':all(label in answer.get('text','') for label in ('[P1]','[P2]')),'text':answer.get('text'),
                        'error':answer.get('error'),'usage':answer.get('usage'),'view':answer.get('history_info',{}).get('memory_view'),
                        'citations':len(answer.get('history_info',{}).get('knowledge',{}).get('citations',[])),
                        'memory_references':len(answer.get('history_info',{}).get('memory',{}).get('references',[]))})
                live={'version':__version__,'captured_at':datetime.now(timezone.utc).isoformat(),'status':'passed' if all(o['expected_facts_present'] for o in observations) else 'partial',
                    'observations':observations,'paid_calls':1,'local_calls':1,'limits':['Two fixed synthetic questions, not a general intelligence benchmark.','Local service must already be running; probe does not take ownership.']}
                (ROOT/'evals/reports/memory-view-live.json').write_text(json.dumps(live,ensure_ascii=False,indent=2)+'\n',encoding='utf-8'); print(json.dumps(live,ensure_ascii=False))
        finally:server.shutdown();server.server_close();thread.join(5)


if __name__=='__main__':main()
