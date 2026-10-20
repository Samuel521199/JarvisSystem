"""Disposable two-process delegation and actual Edge UI; no owner data or cloud."""
from contextlib import closing
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import sys
import tempfile
import time
import uuid

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT),str(ROOT/'tools'),str(ROOT/'runtime/node-host'),str(ROOT/'adapters/models/provider-native'),str(ROOT/'adapters/computer-use')]
from probe_federation import Node
from jarvis_core import __version__
from jarvis_core.federation import Federation
from jarvis_core.service import CoreService
from jarvis_core.process_usage import process_usage


def child(directory, source):
    core=CoreService(Path(directory))
    if not core.ledger.db_path.exists():core.initialize(Path(source))
    service=Federation(core)
    try:
        for line in sys.stdin:
            request=json.loads(line)
            try:
                if request['action']=='quit':break
                if request['action']=='crash_after_reservation':
                    # Private fixture hook, never exposed through the production HTTP API.
                    from jarvis_core import federation_tasks
                    federation_tasks.report=lambda text:os._exit(93)
                    service.delegation.run(request['space'],request['task'])
                elif request['action']=='metrics':value=process_usage(os.getpid())
                elif request['action']=='offline':
                    value=service.network.change(request['offline'],service.network.snapshot()['revision'])
                    if request['offline']:service.close()
                else:value=service.action(request)
                print(json.dumps({'ok':True,'value':value},ensure_ascii=False),flush=True)
            except Exception as exc:
                print(json.dumps({'ok':False,'code':getattr(exc,'code',type(exc).__name__)}),flush=True)
    finally:service.close()


def processes():
    with tempfile.TemporaryDirectory(prefix='jarvis-cooperation-') as directory:
        base=Path(directory); source=base/'source';source.mkdir()
        a,b=Node(base/'a',source,__file__),Node(base/'b',source,__file__)
        checks=[]
        try:
            for node in (a,b):node.request(action='initialize')
            a.request(action='listen',address='127.0.0.1',port=0)
            invite=a.request(action='invite',label='任务共同体模拟');sid=invite['space']
            b.request(action='join',invitation=invite['invitation'])
            for node in (a,b):node.request(action='task_policy',space=sid,revision=0,enabled=True)
            tid=uuid.uuid4().hex
            b.request(action='task_create',space=sid,task=tid,title='测试资料',text='alpha beta\n中文资料')
            b.request(action='task_sync',space=sid)
            assert a.request(action='task_view',space=sid)['tasks'][tid]['state']=='WAITING_APPROVAL'
            a.request(action='task_run',space=sid,task=tid)
            result=b.request(action='task_sync',space=sid)['tasks'][tid]
            assert result['state']=='SUCCEEDED' and result['result']['lines']==2
            checks.append('two_process_offer_approval_independent_result_check')
            again=b.request(action='task_sync',space=sid)['tasks'][tid]
            assert result['version']==again['version'];checks.append('duplicate_exchange_no_reexecution')
            tid2=uuid.uuid4().hex
            b.request(action='task_create',space=sid,task=tid2,title='待取消',text='do not run')
            b.request(action='task_sync',space=sid)
            b.request(action='offline',offline=True);b.request(action='task_cancel',space=sid,task=tid2)
            items=b.request(action='task_continuation',space=sid)['items']
            assert next(r for r in items if r['id']==tid2)['cancel_pending']
            b.request(action='offline',offline=False)
            assert b.request(action='task_sync',space=sid)['tasks'][tid2]['state']=='CANCELLED'
            checks.append('offline_cancel_pending_then_acknowledged')
            a.close();b.close()
            a,b=Node(base/'a',source,__file__),Node(base/'b',source,__file__)
            endpoint=a.request(action='listen',address='127.0.0.1',port=0)['endpoint']
            preview=b.request(action='connection_preview',space=sid,endpoint=endpoint)
            b.request(action='connection_apply',space=sid,token=preview['token'])
            after=b.request(action='task_sync',space=sid)
            assert after['tasks'][tid]['result']==result['result']
            assert after['tasks'][tid2]['state']=='CANCELLED'
            checks.append('both_processes_restart_receipts_survive_endpoint_recovery')
            tid3=uuid.uuid4().hex
            b.request(action='task_create',space=sid,task=tid3,title='中断测试',text='reservation must survive crash')
            b.request(action='task_sync',space=sid)
            a.proc.stdin.write(json.dumps(dict(action='crash_after_reservation',space=sid,task=tid3))+'\n')
            a.proc.stdin.flush();assert a.proc.wait(timeout=10)==93
            a.close();a=Node(base/'a',source,__file__)
            assert a.request(action='task_view',space=sid)['tasks'][tid3]['state']=='UNKNOWN'
            endpoint=a.request(action='listen',address='127.0.0.1',port=0)['endpoint']
            preview=b.request(action='connection_preview',space=sid,endpoint=endpoint)
            b.request(action='connection_apply',space=sid,token=preview['token'])
            assert b.request(action='task_sync',space=sid)['tasks'][tid3]['state']=='UNKNOWN'
            checks.append('executor_process_crash_after_durable_reservation_no_replay')
            return dict(checks=checks,status='passed',memory=[node.request(action='metrics') for node in (a,b)])
        finally:a.close();b.close()


def ui(output):
    from probe_parallel_runtime import fixture,web,serve
    from probe_workspace_ui import SyntheticChat
    from jarvis_computer.browser import DriverJob
    from playwright.sync_api import sync_playwright,expect
    from jarvis_core.conversations import ConversationStore
    from jarvis_core.evolution.learning_loop import LearningLoop
    sys.path.insert(0,str(ROOT/'tests'))
    from test_conversations import document
    checks=[];errors=[]
    with tempfile.TemporaryDirectory(prefix='jarvis-cooperation-ui-') as directory:
        base=Path(directory); left=base/'left';right=base/'right';left.mkdir();right.mkdir()
        peer=Federation(fixture(left));server=web.create_server(core=fixture(right),chat=SyntheticChat(),port=0)
        thread=serve(server);local=server.federation
        try:
            for n in (peer,local):n.initialize()
            peer.listen('127.0.0.1',0);inv=peer.invite('共同任务界面');sid=inv['space'];local.join(inv['invitation'])
            peer.delegation.configure(sid,0,True)
            cid=uuid.uuid4().hex;ConversationStore(server.core).put(cid,{'revision':0,'document':document()})
            with sync_playwright() as pw,closing(DriverJob(pw)):
                browser=pw.chromium.launch(channel='msedge',headless=True,chromium_sandbox=True)
                page=browser.new_page(viewport={'width':1400,'height':1050});page.on('pageerror',lambda e:errors.append(str(e)))
                page.goto(f'http://127.0.0.1:{server.server_port}/settings#federation')
                panel=page.locator('#shared-tasks-root');expect(panel).to_be_visible()
                panel.locator('[data-policy]').click()
                expect(panel.locator('[data-submit]')).to_be_enabled()
                panel.locator('[data-title]').fill('跨设备清单');panel.locator('[data-text]').fill('first line\nsecond line')
                panel.locator('[data-submit]').click();expect(panel.locator('[data-tasks]')).to_contain_text('待交接')
                panel.locator('[data-sync]').click();expect(panel.locator('[data-tasks]')).to_contain_text('等待执行端许可')
                tid=next(iter(peer.delegation.view(sid)['tasks']))
                peer.delegation.run(sid,tid)
                panel.locator('[data-sync]').click();expect(panel.locator('[data-tasks]')).to_contain_text('已完成')
                panel.locator('details').last.click();expect(panel.locator('[data-continuation]')).to_contain_text('跨设备清单：已完成')
                checks.append('ui_task_submit_sync_result_and_continuation')
                page.screenshot(path=str(output/'cooperation.png'),full_page=True)
                page.goto(f'http://127.0.0.1:{server.server_port}/settings#growth')
                page.locator('#evolution-tab-evolve').click()
                learning=page.locator('#learning-loop-panel');learning.locator('summary').first.click()
                expect(learning.locator('[data-conversation] option')).to_have_count(1)
                learning.locator('[data-goal]').fill('提高多关键词资料检索的覆盖质量。')
                learning.locator('[data-create]').click();expect(learning.locator('[data-work]')).to_be_visible()
                learning.locator('[data-source]').fill('合成研究资料')
                learning.locator('[data-notes]').fill('覆盖不同词优于重复单词；需要独立检索测试。')
                learning.locator('[data-evidence]').click();expect(learning.locator('[data-receipt]')).to_contain_text('EVIDENCE_READY')
                learning.locator('[data-review]').fill('核对适用范围，保持原验收标准和只读资料边界。')
                learning.locator('[data-approve]').click();expect(learning.locator('[data-receipt]')).to_contain_text('REVIEWED')
                learning.locator('[data-feedback]').fill('暂未执行生成，不能声称有收益。')
                learning.locator('[data-unhelpful]').click();expect(learning.locator('[data-receipt]')).to_contain_text('暂未执行')
                learning.locator('[data-withdraw]').click();expect(learning.locator('[data-receipt]')).to_contain_text('WITHDRAWN')
                checks.append('ui_learning_provenance_review_feedback_withdrawal')
                page.screenshot(path=str(output/'learning.png'),full_page=True)
                page.set_viewport_size({'width':390,'height':844})
                assert page.evaluate('document.documentElement.scrollWidth <= innerWidth + 1')
                page.screenshot(path=str(output/'learning-mobile.png'),full_page=True)
                checks.append('mobile_layout_capture')
                browser.close()
            assert not errors,errors
            return dict(status='passed',checks=checks,page_errors=errors)
        finally:peer.close();server.shutdown();server.server_close();thread.join(5);time.sleep(2)


def main():
    output=Path('H:/JarvisData/diagnostics/k6-cooperation-20261021');output.mkdir(parents=True,exist_ok=True)
    result=dict(version=__version__,at=datetime.now(timezone.utc).isoformat(),
                processes=processes(),ui=ui(output),physical_second_device=False,cloud_calls=0)
    path=ROOT/'evals/reports/k6-cooperation-learning-2026-10-21.json'
    path.write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(result,ensure_ascii=False,indent=2))


if __name__=='__main__':
    if len(sys.argv)>1 and sys.argv[1]=='--node':child(sys.argv[2],sys.argv[3])
    else:main()
