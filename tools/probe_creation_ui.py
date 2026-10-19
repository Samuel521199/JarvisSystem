"""Real browser: create project/subfolder, generate and play a tank-game artifact.

Default uses a synthetic level response. --live makes one actual model call;
--project can preserve a real output directory while all control data stays isolated.
"""
import argparse
import json
from pathlib import Path
import sys
import tempfile
import threading
import sqlite3
from contextlib import closing
import time
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'tests'),str(ROOT/'runtime/node-host'),str(ROOT/'adapters/computer-use'),str(ROOT/'apps/web')]
from jarvis_core import __version__
from jarvis_core.service import CoreService
from jarvis_core.chat import ChatService
from jarvis_core.web_game import verify_browser
from jarvis_core.evolution.provider import gateway
from jarvis_computer.browser import DriverJob
from probe_workspace_ui import SyntheticChat
from test_web_game import DESIGN
from playwright.sync_api import sync_playwright,expect
import server as web


class Chat(SyntheticChat):
    def models(self):
        return {'default_provider':'vertex','providers':[{'provider':'vertex'}],
                'models':[{'provider':'vertex','model':'gemini-3.8-flash','label':'游戏验证模型','reasoning_levels':['low'],'reasoning_default':'low'}]}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',required=True,type=Path);parser.add_argument('--live',action='store_true')
    parser.add_argument('--project',type=Path);parser.add_argument('--model',default='gemini-4-argon')
    parser.add_argument('--design',type=Path,help='Replay saved level data without another paid call')
    args=parser.parse_args();args.output.mkdir(parents=True,exist_ok=False)
    report={'status':'running','version':__version__,'live':args.live};errors=[]
    def save():(args.output/'report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    save()
    with tempfile.TemporaryDirectory(prefix='jarvis-game-ui-') as tmp:
        base=Path(tmp);initial=base/'initial';initial.mkdir();project=args.project or base/'new-game'
        core=CoreService(base/'data');core.initialize(initial)
        host=web.create_server(core=core,chat=ChatService(core) if args.live else Chat(),port=0)
        calls=[]
        actual=gateway.probe
        def generate(*a,**kw):
            calls.append(True)
            design=json.loads(args.design.read_text(encoding='utf-8')) if args.design else DESIGN
            return {'status':'SUCCEEDED','text':json.dumps(design),'outcome_uncertain':False}
        mock=patch('jarvis_core.evolution.provider.gateway.probe',side_effect=generate) if not args.live else patch('jarvis_core.evolution.provider.gateway.probe',side_effect=actual)
        worker=threading.Thread(target=host.serve_forever,kwargs={'poll_interval':.02},daemon=True);worker.start()
        url='http://127.0.0.1:'+str(host.server_port)
        try:
            with mock,sync_playwright() as pw:
                owner=DriverJob(pw)
                try:
                    browser=pw.chromium.launch(channel='msedge',headless=True,chromium_sandbox=True)
                    page=browser.new_page(viewport={'width':1480,'height':1040});page.on('pageerror',lambda e:errors.append(str(e)))
                    page.goto(url);expect(page.locator('#send')).to_be_enabled(timeout=15000)
                    expect(page.locator('.jarvis-cinema')).not_to_be_visible(timeout=15000)
                    cases={'在d盘创建一个tankGame文件夹并写一个tank游戏':'D:\\tankGame',
                           '创建 D:\\tankGame 文件夹':'D:\\tankGame',
                           '不要创建D:\\tankGame':None,'如果创建文件夹会怎样':None,
                           '创建 D:\\file.txt':None,
                           '解释如何制作坦克游戏':None,'例如在D盘创建一个tankGame文件夹':None}
                    for text,path in cases.items():
                        got=page.evaluate('s=>Creation.classify(s)',text)
                        assert (got and got['path'])==path,(text,got)
                    page.locator('#message').fill('在d盘创建一个tankGame文件夹并写一个tank游戏')
                    page.locator('#composer').evaluate('e=>e.requestSubmit()')
                    expect(page.locator('#project-dialog')).to_be_visible();expect(page.locator('#folder-path')).to_have_value('D:\\tankGame')
                    page.locator('#folder-path').fill(str(project));page.locator('#project-create').click()
                    expect(page.locator('#context-project')).to_contain_text(str(project),timeout=15000)
                    expect(page.locator('#composer-mode')).to_have_value('skill')
                    expect(page.locator('#skill-explicit')).to_have_value('jarvis.tank-game')
                    page.locator('#composer-mode').select_option('chat')
                    page.locator('#message').fill('制作一个简单的坦克游戏')
                    page.locator('#composer').evaluate('e=>e.requestSubmit()')
                    expect(page.locator('#composer-mode')).to_have_value('skill')
                    assert not calls
                    page.locator('#explorer-mkdir').click()
                    dialog=page.get_by_role('dialog').filter(has=page.get_by_role('heading',name='新建文件夹'))
                    dialog.get_by_label('项目内路径').fill('assets');dialog.get_by_role('button',name='创建文件夹',exact=True).click()
                    expect(dialog).not_to_be_visible();assert (project/'assets').is_dir()
                    page.locator('#model-trigger').click();page.locator('#model-search').fill(args.model if args.live else '游戏验证模型')
                    page.locator('#model-options button').first.click()
                    if args.live:
                        page.locator('#composer-mode').select_option('chat')
                        page.locator('#message').fill('只回复 JARVIS_ARGON_CHAT_OK')
                        page.locator('#composer').evaluate('e=>e.requestSubmit()')
                        expect(page.locator('#messages .assistant .bubble').last).to_have_text('JARVIS_ARGON_CHAT_OK',timeout=150000)
                        expect(page.locator('#send')).to_be_enabled(timeout=10000)
                        page.evaluate("Creation.prepareGame('制作简单坦克游戏')")
                    page.locator('#message').fill('制作一个简单的坦克守卫基地游戏，两到三波敌军，单机离线，绿色我方、棕色敌方。')
                    page.locator('#composer').evaluate('e=>e.requestSubmit()')
                    expect(page.locator('#messages')).to_contain_text('技能任务已受理',timeout=10000)
                    cid=page.evaluate('Workspace.currentConversation().id')
                    end=time.monotonic()+115
                    while time.monotonic()<end:
                        rows=host.conversation_tasks.list(cid)['tasks']
                        if rows:
                            detail=host.conversation_tasks.detail(cid,rows[0]['task_id'])
                            if detail['task']['status'] not in {'READY','RUNNING','CANCELLING'}:break
                        page.wait_for_timeout(100)
                    assert detail['task']['status']=='SUCCEEDED',detail
                    task=detail['task']['task_id'];result=detail['report']
                    assert result['checks']['browser']['win'] and result['checks']['browser']['base_damage_and_loss']
                    page.get_by_role('button',name='试玩游戏',exact=True).click()
                    frame=page.frame_locator('#skill-preview iframe');expect(frame.locator('#start')).to_be_visible(timeout=10000)
                    frame.locator('#start').click();expect(frame.locator('#overlay')).not_to_be_visible()
                    frame.locator('#pause').click();expect(frame.locator('#pause')).to_have_text('继续')
                    frame.locator('body').evaluate('()=>scrollTo(0,0)')
                    page.screenshot(path=str(args.output/'jarvis-game-preview.png'))
                    page.locator('#skill-preview button').first.click()
                    # A persisted terminal failed reply can be hidden without replaying it.
                    recovery_id='f'*32
                    page.route('**/api/dialogue/recover/'+recovery_id+'?*',lambda r:r.fulfill(json={'finished':True,'status':'UNKNOWN','result':{'status':'UNKNOWN','user_message':'连接中断或等待超时，远端结果可能未知。'}}))
                    page.evaluate("id=>{const n=addMessage('user','历史未确认请求');n.dataset.replyRef=id;Dialogue.sessionChanged();}",recovery_id)
                    expect(page.locator('#dialogue-recovery')).to_be_visible(timeout=5000)
                    page.locator('#dialogue-recovery').get_by_role('button',name='收起此提示').click()
                    expect(page.locator('#dialogue-recovery')).not_to_be_visible()
                    assert page.request.post(url+'/api/workspace/create-project',data={'path':str(base/'forbidden')}).status==403
                    assert not (base/'forbidden').exists()
                    token=page.evaluate('NONCE')
                    assert page.request.post(url+'/api/project-files/mkdir',headers={'X-Jarvis-Nonce':token,'Origin':'https://example.invalid'},data={'project_id':page.evaluate('Workspace.currentProject().id'),'path':'foreign'}).status==403
                    assert not (project/'foreign').exists()
                    page.set_viewport_size({'width':390,'height':844});assert page.evaluate('document.documentElement.scrollWidth<=innerWidth')
                    assert not errors
                    report.update(status='passed',task_id=task,output=result['output'],model=result.get('model'),
                                  game_checks=result['checks'],page_errors=errors,synthetic_model_calls=len(calls),
                                  checks=['natural folder/game draft','browser creates project and subfolder','explicit game task and offline HTML delivery',
                                          'receipt-bound sandbox preview plays/pauses','terminal recovery hint dismisses without retry','nonce and foreign-Origin guard','390px workbench'])
                    if args.live:
                        with closing(sqlite3.connect(core.data_dir/'model-probes.db')) as db:
                            report['live_receipts']=[{'status':status,**{k:v for k,v in json.loads(raw).items() if k in {'provider','model','request_id','http_status','response_deadline_seconds','elapsed_seconds','usage','billing','output_incomplete','outcome_uncertain'}}} for status,raw in db.execute('SELECT status,metadata FROM probes ORDER BY rowid')]
                        report['live_model_calls']=len(report['live_receipts'])
                    save();browser.close()
                finally:owner.close()
        except Exception as exc:
            report.update(status='failed',error=str(exc),page_errors=errors);save();raise
        finally:host.shutdown();host.server_close();worker.join(5)
    print(json.dumps({'status':report['status'],'report':str(args.output/'report.json')},ensure_ascii=False))


if __name__=='__main__':main()
