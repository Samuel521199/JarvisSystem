"""Two isolated local hosts; synthetic personal/project facts, no owner data."""
from contextlib import closing
from datetime import datetime,timezone
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
from jarvis_core.service import CoreService
from jarvis_core.federation import Federation
from jarvis_core.memory import MemoryStore
from jarvis_core.workspace import WorkspaceService
from jarvis_core.process_usage import process_usage


def fact(core,ident,project=None,text='合成个人偏好：回答简洁',revision=0):
    return MemoryStore(core).put(ident,dict(revision=revision,document=dict(
        title='合成项目记忆' if project else '合成个人偏好',content=text,project_id=project,providers=[])))


def child(directory,source):
    core=CoreService(Path(directory))
    if not core.ledger.db_path.exists():core.initialize(Path(source))
    service=Federation(core)
    try:
        for line in sys.stdin:
            request=json.loads(line)
            try:
                action=request['action']
                if action=='quit':break
                if action=='fact':value=fact(core,request['id'],request.get('project'),request.get('text','合成偏好'),request.get('revision',0))
                elif action=='forget':value=MemoryStore(core).delete(request['id'],{'revision':request['revision']})
                elif action=='project':value=WorkspaceService(core).open_project({'path':request['path']})
                elif action=='metrics':value=process_usage(os.getpid())
                elif action=='status':value=service.status()
                elif action=='offline':
                    value=service.network.change(request['offline'],service.network.snapshot()['revision'])
                    if request['offline']:service.close()
                else:value=service.action(request)
                print(json.dumps({'ok':True,'value':value},ensure_ascii=False),flush=True)
            except Exception as exc:
                print(json.dumps({'ok':False,'code':getattr(exc,'code',type(exc).__name__)}),flush=True)
    finally:service.close()


def options(node,sid):return node.request(action='scope_options',space=sid,kind='memory',project_id=None)
def config(node,sid,selected=None,grants=None):
    value=options(node,sid)
    if selected is None:selected=[{k:r[k] for k in ('kind','source','source_project','expected')} for r in value['selected'].values()]
    return node.request(action='scope_change',space=sid,revision=value['revision'],selected=selected,
                        grants=value['grants'] if grants is None else grants)


def processes():
    with tempfile.TemporaryDirectory(prefix='jarvis-domains-process-') as directory:
        base=Path(directory);source=base/'source';source.mkdir()
        ap=base/'work-a';bp=base/'work-b';ap.mkdir();bp.mkdir()
        a=Node(base/'a',source,__file__);b=Node(base/'b',source,__file__)
        checks=[]
        try:
            for n in (a,b):n.request(action='initialize')
            a.request(action='listen',address='127.0.0.1',port=0)
            invitation=a.request(action='invite',label='双设备分域共享模拟');sid=invitation['space']
            b.request(action='join',invitation=invitation['invitation'])
            config(a,sid,[]);config(b,sid,[])
            pa=a.request(action='project',path=str(ap))['id'];pb=b.request(action='project',path=str(bp))['id']
            personal,work,private=[uuid.uuid4().hex for _ in range(3)]
            for ident,project,text in [(personal,None,'合成个人偏好'),(work,pa,'项目A版本计划'),(private,None,'NEVER_SHARE_PRIVATE')]:
                a.request(action='fact',id=ident,project=project,text=text)
            selected=[]
            for ident,project in [(personal,None),(work,pa)]:
                row=next(r for r in a.request(action='scope_options',space=sid,kind='memory',project_id=project)['sources'] if r['id']==ident)
                selected.append(dict(kind='memory',source=ident,source_project=project,expected=row['expected']))
            config(a,sid,selected)
            b.request(action='scope_catalog',space=sid);opts=options(b,sid)
            assert len(opts['catalog'])==2 and not opts['received']
            assert 'NEVER_SHARE_PRIVATE' not in json.dumps(opts,ensure_ascii=False)
            checks.append('metadata_only_selected_publications_no_private_fact')
            b.request(action='scope_sync',space=sid);assert not options(b,sid)['received']
            checks.append('default_receiver_denial')
            grants={item:{'domain':r['domain'],'source_project':r['source_project'],'project_id':pb if r['domain']=='project' else None} for item,r in opts['catalog'].items()}
            config(b,sid,grants=grants);b.request(action='scope_sync',space=sid)
            received=options(b,sid)['received'];assert len(received)==2
            assert {r['project_id'] for r in received}=={None,pb}
            assert not (base/'b/memory.db').exists()
            checks.append('personal_project_mapping_without_local_memory_writes')
            a.request(action='fact',id=personal,text='偏好已纠正',revision=1)
            b.request(action='scope_sync',space=sid);assert '偏好已纠正' in json.dumps(options(b,sid)['received'],ensure_ascii=False)
            a.request(action='forget',id=personal,revision=2)
            b.request(action='scope_sync',space=sid);assert len(options(b,sid)['received'])==1
            checks.append('correction_and_forgetting_converge')
            b.request(action='offline',offline=True)
            try:b.request(action='scope_sync',space=sid)
            except AssertionError:pass
            else:raise AssertionError('offline exchange allowed')
            assert len(options(b,sid)['received'])==1
            b.request(action='offline',offline=False)
            checks.append('offline_local_inbox_and_no_exchange')
            a.close();a=Node(base/'a',source,__file__)
            assert a.request(action='status')['endpoint'] is None
            endpoint=a.request(action='listen',address='127.0.0.2',port=0)['endpoint']
            plan=b.request(action='connection_preview',space=sid,endpoint=endpoint)
            b.request(action='connection_apply',space=sid,token=plan['token'])
            b.request(action='scope_sync',space=sid);assert len(options(b,sid)['received'])==1
            b.close();b=Node(base/'b',source,__file__)
            assert len(options(b,sid)['received'])==1
            b.request(action='scope_sync',space=sid)
            checks.append('both_process_restarts_and_new_endpoint_preserve_grants')
            config(b,sid,grants={});assert not options(b,sid)['received']
            b.request(action='scope_sync',space=sid);assert not options(b,sid)['received']
            checks.append('receiver_revocation_and_resync_no_resurrection')
            first=[n.request(action='metrics') for n in (a,b)];time.sleep(1)
            last=[n.request(action='metrics') for n in (a,b)]
            return dict(status='passed',checks=checks,resources=dict(private_bytes=[r['private_bytes'] for r in last],
                one_second_idle_cpu_seconds=[round(y['cpu_seconds']-x['cpu_seconds'],4) for x,y in zip(first,last)]),
                limitations=['Two independent OS processes on one PC, loopback TLS; not physical LAN/firewall/sleep.',
                             'One-second idle sample is not long-duration or low-memory acceptance.'])
        finally:a.close();b.close()


def ui(output):
    from probe_parallel_runtime import fixture,web,serve,wait
    from probe_workspace_ui import SyntheticChat
    from jarvis_computer.browser import DriverJob
    from playwright.sync_api import sync_playwright,expect
    errors=[];checks=[]
    with tempfile.TemporaryDirectory(prefix='jarvis-domains-ui-') as directory:
        base=Path(directory);left=base/'left';right=base/'right';left.mkdir();right.mkdir()
        peer=Federation(fixture(left))
        server=web.create_server(core=fixture(right),chat=SyntheticChat(),port=0);thread=serve(server);local=server.federation
        try:
            for n in (peer,local):n.initialize()
            peer.listen('127.0.0.1',0);inv=peer.invite('分域共享验收');sid=inv['space'];local.join(inv['invitation'])
            ident=uuid.uuid4().hex;fact(peer.core,ident,text='合成偏好：喜欢条理清楚的回答')
            selected=peer.scoped.options(sid)['sources'][0]
            peer.scoped.configure(sid,0,[dict(kind='memory',source=ident,source_project=None,expected=selected['expected'])],{})
            with sync_playwright() as pw,closing(DriverJob(pw)):
                browser=pw.chromium.launch(channel='msedge',headless=True,chromium_sandbox=True)
                page=browser.new_page(viewport={'width':1400,'height':1050});page.on('pageerror',lambda e:errors.append(str(e)))
                page.goto(f'http://127.0.0.1:{server.server_port}/settings#federation')
                panel=page.locator('#shared-scopes-root');expect(panel).to_be_visible()
                panel.get_by_role('button',name='启用分域接收控制',exact=True).click()
                expect(panel.locator('[data-form]')).to_be_visible()
                expect(page.locator('#shared-sync')).to_be_disabled()
                checks.append('enable_disables_legacy_sync')
                panel.get_by_role('button',name='只交换候选目录',exact=True).click()
                check=panel.locator('[data-grants] input[type=checkbox]');expect(check).to_have_count(1)
                assert local.status()['spaces'][0]['received_cards']==[]
                check.check();panel.get_by_role('button',name='保存发送与接收许可',exact=True).click()
                expect(panel.get_by_role('button',name='按许可同步正文',exact=True)).to_be_enabled()
                panel.get_by_role('button',name='按许可同步正文',exact=True).click()
                expect(panel.locator('[data-inbox]')).to_contain_text('合成个人偏好')
                assert len(local.status()['spaces'][0]['received_cards'])==1
                checks.append('catalog_grant_and_explicit_body_sync')
                expect(page.locator('#shared-access-root [data-cards]')).to_contain_text('接收')
                checks.append('separate_model_authorization_options')
                output.mkdir(parents=True,exist_ok=True)
                panel.screenshot(path=str(output/'scopes-light.png'))
                page.emulate_media(color_scheme='dark');page.set_viewport_size({'width':390,'height':844})
                panel.screenshot(path=str(output/'scopes-mobile.png'))
                assert page.evaluate('document.documentElement.scrollWidth<=innerWidth+1')
                checks.append('light_dark_narrow_layout')
                check.uncheck();panel.get_by_role('button',name='保存发送与接收许可',exact=True).click()
                expect(panel.locator('[data-inbox]')).to_contain_text('尚无获准')
                assert local.status()['spaces'][0]['received_cards']==[]
                checks.append('receiver_revocation_removes_local_body')
                browser.close()
            assert not errors,errors
            return dict(status='passed',checks=checks,page_errors=errors,screenshots=[str(p) for p in sorted(output.glob('*.png'))])
        finally:peer.close();server.shutdown();server.server_close();thread.join(5);time.sleep(2)


def main():
    report=dict(version=__version__,captured_at=datetime.now(timezone.utc).isoformat(),
                processes=processes(),ui=ui(Path('H:/JarvisData/diagnostics/k6-scoped-20261020')),
                cloud_model_calls=0,physical_second_device='simulated_on_one_pc_at_user_request')
    path=ROOT/'evals/reports/k6-scoped-sharing-2026-10-20.json'
    path.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps({'status':'passed','report':str(path)}))


if __name__=='__main__':
    if len(sys.argv)>1 and sys.argv[1]=='--node':child(sys.argv[2],sys.argv[3])
    else:main()
