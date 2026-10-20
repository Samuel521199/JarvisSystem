"""Real process restart/address recovery and browser checks using disposable nodes."""
from contextlib import closing
from datetime import datetime, timezone
import json
from pathlib import Path
import sys
import tempfile
import time
import uuid

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT/'tools'), str(ROOT/'runtime/node-host'),
               str(ROOT/'adapters/computer-use')]
from probe_federation import Node
from probe_parallel_runtime import fixture, web, serve, wait
from probe_workspace_ui import SyntheticChat
from jarvis_core import __version__, federation_protocol as p
from jarvis_core.federation import Federation
from jarvis_computer.browser import DriverJob
from playwright.sync_api import sync_playwright, expect


def processes():
    with tempfile.TemporaryDirectory(prefix='jarvis-connection-process-') as directory:
        base=Path(directory); source=base/'source';source.mkdir()
        a,b=Node(base/'a',source),Node(base/'b',source)
        try:
            for node in (a,b):node.request(action='initialize')
            a.request(action='listen',address='127.0.0.1',port=0)
            invitation=a.request(action='invite',label='进程重连检查');sid=invitation['space']
            b.request(action='join',invitation=invitation['invitation'])
            item=uuid.uuid4().hex
            b.request(action='edit',space=sid,item=item,expected=p.heads_token([]),
                      title='本地计划',text='仍在本机',deleted=False)
            before=b.request(action='status')
            checked=b.request(action='connection_check',space=sid)
            assert checked['reachable'] and b.request(action='status')['spaces']==before['spaces']
            a.close();a=Node(base/'a',source)
            assert a.request(action='status')['endpoint'] is None
            b.request(action='offline',offline=True)
            assert not b.request(action='connection_check',space=sid)['reachable']
            b.request(action='offline',offline=False)
            moved=a.request(action='listen',address='127.0.0.2',port=0)['endpoint']
            preview=b.request(action='connection_preview',space=sid,endpoint=moved)
            assert b.request(action='status')['spaces']==before['spaces']
            receipt=b.request(action='connection_apply',space=sid,token=preview['token'])
            assert receipt['changed']
            assert b.request(action='connection_apply',space=sid,token=preview['token'])==receipt
            b.request(action='sync',space=sid)
            assert a.request(action='status')['spaces'][0]['cards'][0]['versions'][0]['text']=='仍在本机'
            b.close();b=Node(base/'b',source)
            assert b.request(action='status')['spaces'][0]['endpoint']==moved
            assert b.request(action='connection_check',space=sid)['reachable']
            first=[n.request(action='metrics') for n in (a,b)]
            time.sleep(1)
            last=[n.request(action='metrics') for n in (a,b)]
            return {'status':'passed','checks':['separate_process_readonly_probe','host_restart_listener_stays_off',
                        'offline_no_probe','different_loopback_address_and_port','preview_no_write',
                        'explicit_commit_and_duplicate_receipt','sync_after_recovery','client_restart_keeps_new_address'],
                    'resources':{'private_bytes':[r['private_bytes'] for r in last],
                                 'one_second_idle_cpu_seconds':[round(y['cpu_seconds']-x['cpu_seconds'],4) for x,y in zip(first,last)]},
                    'limits':['Two OS processes on the same Windows PC; 127.0.0.2 is loopback, not a second machine.',
                              'One-second idle sample is not a long-run or low-memory PC benchmark.']}
        finally:
            a.close();b.close()


def ui(output):
    errors,checks=[],[]
    with tempfile.TemporaryDirectory(prefix='jarvis-connection-ui-') as directory:
        base=Path(directory);left,right=base/'left',base/'right';left.mkdir();right.mkdir()
        peer=Federation(fixture(left))
        server=web.create_server(core=fixture(right),chat=SyntheticChat(),port=0);thread=serve(server)
        local=server.federation
        try:
            for node in (peer,local):node.initialize()
            peer.listen('127.0.0.1',0)
            invitation=peer.invite('同一设备的新地址');sid=invitation['space'];local.join(invitation['invitation'])
            item=uuid.uuid4().hex
            peer.edit(sid,item,p.heads_token([]),'合成测试计划','重连后的计划内容')
            with sync_playwright() as pw, closing(DriverJob(pw)):
                browser=pw.chromium.launch(channel='msedge',headless=True,chromium_sandbox=True)
                page=browser.new_page(viewport={'width':1440,'height':1100})
                page.on('pageerror',lambda error:errors.append(str(error)))
                page.goto(f'http://127.0.0.1:{server.server_port}/settings#federation')
                panel=page.locator('#shared-connection-root')
                expect(panel).to_be_visible()
                status=panel.locator('[data-status]')
                before=local.store.read(local.node)
                panel.get_by_role('button',name='检查原设备连接').click()
                expect(status).to_contain_text('原配对设备可达')
                assert local.store.read(local.node)==before
                checks.append('browser_diagnosis_does_not_sync_or_mutate')
                local.network.change(True,0)
                panel.get_by_role('button',name='检查原设备连接').click()
                expect(status).to_contain_text('离线')
                local.network.change(False,1)
                checks.append('offline_diagnostic_shows_local_policy')
                peer.close();peer.listen('127.0.0.2',0)
                endpoint=peer.status()['endpoint']
                panel.locator('summary').click()
                panel.locator('[data-endpoint]').fill(endpoint)
                panel.get_by_role('button',name='核验新地址').click()
                expect(panel.locator('[data-plan]')).to_be_visible()
                assert local.store.read(local.node)==before
                checks.append('preview_shows_identity_and_leaves_address_unchanged')
                panel.locator('[data-endpoint]').fill(endpoint+'0')
                expect(panel.locator('[data-plan]')).to_be_hidden()
                panel.locator('[data-endpoint]').fill(endpoint)
                panel.get_by_role('button',name='核验新地址').click()
                expect(panel.locator('[data-plan]')).to_be_visible()
                checks.append('editing_address_invalidates_visible_confirmation')
                panel.get_by_role('button',name='确认更新连接地址').click()
                expect(status).to_contain_text('已保存原设备的新地址')
                wait(lambda:local.status()['spaces'][0]['endpoint']==endpoint)
                assert local.status()['spaces'][0]['cards']==[]
                page.locator('#shared-sync').click()
                wait(lambda:len(local.status()['spaces'][0]['cards'])==1)
                checks.append('confirmation_preserves_space_and_sync_is_separate')
                local.listen('127.0.0.1',0)
                panel.locator('[data-endpoint]').fill(local.status()['endpoint'])
                panel.get_by_role('button',name='核验新地址').click()
                expect(status).to_contain_text('证书已变化')
                assert local.status()['spaces'][0]['endpoint']==endpoint
                expect(panel.locator('[data-plan]')).to_be_hidden()
                checks.append('wrong_device_rejected_without_address_replacement')
                panel.locator('[data-endpoint]').fill(endpoint)
                panel.get_by_role('button',name='核验新地址').click()
                expect(panel.locator('[data-plan]')).to_be_visible()
                output.mkdir(parents=True,exist_ok=True)
                panel.screenshot(path=str(output/'connection-panel-light.png'))
                page.emulate_media(color_scheme='dark')
                panel.screenshot(path=str(output/'connection-panel-dark.png'))
                page.set_viewport_size({'width':390,'height':844})
                panel.screenshot(path=str(output/'connection-panel-mobile.png'))
                assert page.evaluate('document.documentElement.scrollWidth<=innerWidth+1')
                checks.append('light_dark_mobile_layout_and_accessible_controls')
                browser.close()
            assert not errors,errors
            return {'status':'passed','checks':checks,'page_errors':errors,
                    'screenshots':[str(path) for path in sorted(output.glob('*.png'))],
                    'limits':['Loopback HTTPS only; no physical NIC, firewall or actual sleep test.']}
        finally:
            peer.close();server.shutdown();server.server_close();thread.join(timeout=5);time.sleep(2)


def main():
    result={'version':__version__,'captured_at':datetime.now(timezone.utc).isoformat(),
            'processes':processes(),'ui':ui(Path('H:/JarvisData/diagnostics/k6-connection-20261020')),
            'cloud_model_calls':0,'physical_second_device':'not_available_user_deferred'}
    path=ROOT/'evals/reports/k6-connection-recovery-2026-10-20.json'
    path.write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps({'status':'passed','report':str(path)}))


if __name__=='__main__':
    main()
