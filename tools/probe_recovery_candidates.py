"""Real Edge/HTTP recovery and candidate review; synthetic models and temp data."""
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
sys.path[:0]=[str(ROOT/'tests'),str(ROOT/'tools'),str(ROOT/'runtime/node-host'),str(ROOT/'adapters/computer-use')]
from jarvis_core import __version__
from jarvis_core.chat import ChatService
from jarvis_core.service import CoreService
from jarvis_core.evolution import EvolutionManager
from jarvis_core.continuity import ContinuityStore
from jarvis_computer.browser import DriverJob
from test_evolution import Provider
from probe_sample_tasks_ui import Planner
from playwright.sync_api import sync_playwright,expect


def run(out,report):
    spec=importlib.util.spec_from_file_location('recovery_candidate_web',ROOT/'apps/web/server.py')
    web=importlib.util.module_from_spec(spec);spec.loader.exec_module(web)
    calls=[];provider=Provider();planner=Planner()
    def model(config,route,message,*args,**kwargs):
        calls.append(message);return {'status':'SUCCEEDED','text':'我会根据本轮的信息与你讨论。','provider':route,'model':config['providers'][route]['model']}
    with tempfile.TemporaryDirectory(prefix='jarvis-recovery-candidates-') as folder:
        base=Path(folder);source=base/'sample';source.mkdir();(source/'a.txt').write_text('sample',encoding='utf-8')
        core=CoreService(base/'data');core.initialize(source);chat=ChatService(core)
        server=web.create_server(core=core,chat=chat,port=0);server.evolution.close()
        server.evolution=EvolutionManager(core,provider=provider,monitor=False);server.computer.sample.chat_factory=lambda *a,**kw:planner
        thread=threading.Thread(target=server.serve_forever,kwargs={'poll_interval':.02},daemon=True);thread.start()
        try:
            with patch('jarvis_core.chat.gateway.probe',side_effect=model),sync_playwright() as p:
                driver=DriverJob(p)
                try:
                    browser=p.chromium.launch(channel='msedge',headless=True,chromium_sandbox=True)
                    page=browser.new_page(viewport={'width':1440,'height':1000});page.on('pageerror',lambda e:report['page_errors'].append(str(e)))
                    page.goto('http://127.0.0.1:'+str(server.server_port));expect(page.locator('#send')).to_be_enabled();expect(page.locator('.jarvis-cinema')).not_to_be_visible(timeout=15000)
                    def send(text,expected=None):
                        count=page.locator('.message.assistant').count();page.locator('#message').fill(text);page.locator('#composer').evaluate('e=>e.requestSubmit()')
                        if expected:
                            expect(page.locator('.message.assistant')).to_have_count(count+1);expect(page.locator('.message.assistant').last).to_contain_text(expected)
                            expect(page.locator('#conversation-status')).to_have_attribute('data-state','saved');expect(page.locator('#send')).to_have_attribute('aria-label','发送消息')
                    send('/任务 列出样例目录文件并保存报告')
                    expect(page.locator('#conversation-task-list')).to_contain_text('已核验：1 个文件',timeout=20000)
                    send('/改进 导出 TSV');expect(page.locator('.growth-card')).to_have_count(1)
                    old=page.locator('.growth-card').get_attribute('data-growth-id')
                    # Durable queued fixture, then real manager recreation; no worker dispatched.
                    server.evolution.store.queue_proposal(old);server.evolution.close()
                    server.evolution=EvolutionManager(core,provider=provider,monitor=False)
                    page.locator('#growth-refresh').click();expect(page.locator('.growth-card')).to_contain_text('运行中断')
                    page.locator('#growth-close').click();page.locator('#message').fill('这里有尚未发送的草稿')
                    page.locator('.growth-link').last.click()
                    def lost(route):route.fetch();route.abort('failed')
                    page.route('**/'+old+'/reanalyse',lost)
                    page.get_by_role('button',name='重新分析这项需求',exact=True).click();expect(page.locator('#growth-error')).to_contain_text('不会自动重发')
                    page.unroute('**/'+old+'/reanalyse',lost)
                    expect(page.locator('#message')).to_have_value('这里有尚未发送的草稿')
                    page.locator('#growth-close').click();page.locator('.growth-link').last.click()
                    expect(page.locator('.growth-card')).to_have_count(2);expect(page.locator('.growth-card').first).to_contain_text('待开始')
                    fresh=page.locator('.growth-card').first.get_attribute('data-growth-id')
                    assert fresh!=old and server.evolution.store.job(fresh)['request']['origin']['previous_job']==old
                    assert not provider.calls and not calls
                    page.get_by_role('button',name='补齐能力并导出',exact=True).click()
                    expect(page.locator('.growth-card').first).to_contain_text('已完成',timeout=45000)
                    assert len(provider.calls)==1 and server.evolution.store.job(old)['status']=='INTERRUPTED'
                    page.screenshot(path=str(out/'recovery-desktop.png'))
                    report['checks'].append('New recovery entry preserves draft/old receipt; dropped response recovered by original request ID; one fresh proposal, no model until explicit start; actual LPAC delivery')
                    page.locator('#growth-close').click();page.locator('#message').fill('')
                    send('我更喜欢简洁回答。我们下次继续讨论学习计划。','我会根据')
                    page.locator('.candidate-entry').last.click();expect(page.locator('.candidate-card')).to_have_count(2)
                    assert chat.memory.list()['facts']==[] and ContinuityStore(core).list()['records']==[] and len(calls)==1
                    first=page.locator('.candidate-card').first;first.get_by_label('名称',exact=True).fill('回复风格');first.get_by_label('记忆内容',exact=True).fill('喜欢简洁但保留依据')
                    page.route('**/api/personal-candidates/confirm',lost);first.get_by_role('button',name='确认并保存',exact=True).click()
                    expect(first).to_contain_text('重试相同内容使用同一回执');page.unroute('**/api/personal-candidates/confirm',lost)
                    first.get_by_role('button',name='确认并保存',exact=True).click();expect(first).to_contain_text('此确认已处理')
                    assert len(chat.memory.list()['facts'])==1 and chat.memory.list()['facts'][0]['document']['providers']==[]
                    second=page.locator('.candidate-card').nth(1);second.get_by_label('名称',exact=True).fill('学习计划')
                    second.get_by_role('button',name='确认并保存',exact=True).click();expect(second).to_contain_text('已保存未结事项')
                    note=ContinuityStore(core).list()['records'][0];assert note['document']['source']['owner_confirmed_candidate']
                    assert len(calls)==1 and len(provider.calls)==1
                    page.screenshot(path=str(out/'candidates-desktop.png'));page.set_viewport_size({'width':390,'height':844})
                    assert page.evaluate('document.documentElement.scrollWidth<=innerWidth');page.screenshot(path=str(out/'candidates-mobile.png'))
                    report['checks'].append('Natural fact/unfinished candidates reviewed and edited; lost confirmation response replays without duplication; local permissions, ordinary source binding, zero extra model calls; 390px fits')
                    page.locator('#personal-candidates').get_by_role('button',name='关闭',exact=True).click()
                    page.set_viewport_size({'width':1440,'height':1000})
                    page.locator('#clear').click();send('继续话题：学习计划','已选择这条接续')
                    send('查看记忆','喜欢简洁但保留依据')
                    send('忘记：回复风格','已忘记');send('忘记接续：学习计划','已忘记')
                    assert chat.memory.list()['facts']==[] and ContinuityStore(core).list()['records']==[]
                    send('假如我说“我喜欢咖啡”只是示例','我会根据');page.locator('.candidate-entry').last.click()
                    expect(page.locator('#personal-candidates')).to_contain_text('未匹配');expect(page.locator('.candidate-card')).to_have_count(0)
                    page.locator('#personal-candidates').get_by_role('button',name='关闭',exact=True).click()
                    page.locator('#conversation-status').click();page.locator('#conversation-temporary').click();send('我喜欢无糖茶')
                    expect(page.locator('.message.assistant')).to_have_count(1);page.locator('.candidate-entry').last.click();expect(page.locator('#toast')).to_contain_text('临时会话')
                    assert not report['page_errors'],report['page_errors']
                    report['checks'].append('New conversation resumes confirmed note; explicit forget works; quoted/hypothetical input yields no candidates; temporary context cannot create candidates')
                    report.update(synthetic_chat_calls=len(calls),synthetic_coding_calls=len(provider.calls),paid_calls=0)
                    browser.close()
                except Exception:
                    if 'page' in locals():page.screenshot(path=str(out/'failure.png'))
                    raise
                finally:driver.close()
        finally:server.shutdown();server.server_close();thread.join(3)


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--output',type=Path,required=True);args=parser.parse_args();args.output.mkdir(parents=True,exist_ok=False)
    report={'version':__version__,'captured_at':datetime.now(timezone.utc).isoformat(),'checks':[],'page_errors':[]}
    try:run(args.output,report);report['status']='passed'
    except Exception:report['status']='failed';report['failure']=traceback.format_exc()
    (args.output/'report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8');print(json.dumps(report,ensure_ascii=False));return 0 if report['status']=='passed' else 1


if __name__=='__main__':raise SystemExit(main())
