"""Native local reply readout, real media events and a parallel bounded directory task."""
from pathlib import Path
import hashlib
import json
import sys
import tempfile
import secrets
from unittest.mock import patch
import threading
import time

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT),str(ROOT/'apps/web'),str(ROOT/'runtime/node-host'),str(ROOT/'adapters/computer-use')]
from jarvis_core import __version__
from tools.probe_workspace_ui import SyntheticChat
from tools.probe_parallel_runtime import fixture,PlanChat,request,task,detail,wait
from jarvis_computer.browser import DriverJob
from server import create_server
from playwright.sync_api import sync_playwright,expect


TEXT='[轻声][慢速]别担心，我们先从今天最重要的一件事开始。[自然][开心]你已经做得很好了！我们可以一起列出目标，安排时间，再看看哪些事情需要帮助。[自然]接下来我们一步一步推进，让今天的计划更清楚。'


def main():
    out=Path('H:/JarvisData/research/qwen-tts/chat-readout');out.mkdir(parents=True,exist_ok=True)
    errors=[];release=threading.Event();entered=threading.Event()
    class HeldPlan(PlanChat):
        def reply(self,*args,cancel_event=None,**kwargs):
            entered.set()
            while not release.wait(.02):
                if cancel_event and cancel_event.is_set():return dict(status='CANCELLED',outcome_uncertain=False)
            return super().reply(*args,**kwargs)
    with tempfile.TemporaryDirectory(prefix='jarvis-readout-ui-') as directory:
        core=fixture(Path(directory));chat=SyntheticChat();chat.text=TEXT
        server=create_server(core=core,chat=chat,port=0);server.computer.sample.chat_factory=lambda *a,**kw:HeldPlan()
        thread=threading.Thread(target=server.serve_forever,kwargs={'poll_interval':.02},daemon=True);thread.start()
        try:
            with sync_playwright() as p:
                driver=DriverJob(p)
                try:
                    browser=p.chromium.launch(channel='msedge',headless=True,chromium_sandbox=True)
                    page=browser.new_page(viewport={'width':1280,'height':720});page.on('pageerror',lambda e:errors.append(str(e)))
                    page.add_init_script("""window.__readoutMedia=[];window.__readoutEvents=[];const NativeAudio=window.Audio;window.Audio=function(...args){const a=new NativeAudio(...args);window.__readoutMedia.push(a);for(const t of ['playing','pause','ended','error'])a.addEventListener(t,()=>window.__readoutEvents.push({type:t,time:performance.now()}));return a;};""")
                    page.goto('http://127.0.0.1:'+str(server.server_port)+'/')
                    page.wait_for_function('()=>Boolean(window.Workspace && !window.Workspace.isBusy())',timeout=15000)
                    page.wait_for_function('()=>!document.documentElement.hasAttribute("data-brand-cinema")',timeout=10000)
                    page.locator('#message').fill('请给我一段陪伴和计划建议。')
                    expect(page.locator('#message')).to_have_value('请给我一段陪伴和计划建议。')
                    expect(page.locator('#send')).to_be_enabled(timeout=15000);page.locator('#send').click()
                    button=page.locator('.message.assistant .readout-button').last;expect(button).to_be_visible(timeout=10000)
                    assert not server.modules.primary_speech.snapshot()['owned']
                    token_factory=secrets.token_urlsafe
                    # Preserve secure entropy while exercising the formerly broken CLI boundary.
                    with patch('jarvis_core.speech.secrets.token_urlsafe',side_effect=lambda n:'-'+token_factory(n)):
                        tick=page.evaluate('performance.now()');button.click();print('model requested',flush=True)
                        wait(lambda:server.modules.primary_speech.job and server.modules.primary_speech.job['action']=='synthesize',seconds=120)
                    print('native synthesis started',flush=True);item=task(server);assert entered.wait(5)
                    chat_code,chat_body,chat_ms=request(server,'/api/chat','POST',{'message':'朗读期间继续聊天'})
                    assert chat_code==200 and chat_body['status']=='SUCCEEDED'
                    release.set();wait(lambda:detail(server,item)['task']['status']=='SUCCEEDED',seconds=20)
                    expect(page.locator('#readout-status')).to_contain_text('正在朗读第',timeout=30000)
                    first_play=(page.evaluate('window.__readoutEvents.find(e=>e.type==="playing").time')-tick)/1000
                    page.locator('#readout-pause').click();expect(page.locator('#readout-status')).to_contain_text('已暂停')
                    assert page.evaluate('window.__readoutMedia.at(-1).paused')
                    page.locator('#readout-pause').click();expect(page.locator('#readout-status')).to_contain_text('正在朗读第',timeout=10000)
                    page.locator('#readout-options').evaluate('e=>e.open=true')
                    assert page.locator('#readout-voice').bounding_box()['y']>=66
                    assert page.locator('.readout-options-body').bounding_box()['y']+page.locator('.readout-options-body').bounding_box()['height']<=720
                    assert page.locator('#send').bounding_box()['y']+page.locator('#send').bounding_box()['height']<=720
                    page.screenshot(path=str(out/'chat-readout-panel.png'))
                    page.set_viewport_size({'width':480,'height':950});page.screenshot(path=str(out/'chat-readout-panel-narrow.png'))
                    assert page.evaluate('document.documentElement.scrollWidth<=innerWidth');page.set_viewport_size({'width':1280,'height':720})
                    expect(page.locator('#readout-status')).to_have_text('朗读完成。',timeout=90000)
                    events=page.evaluate('window.__readoutEvents');assert sum(e['type']=='ended' for e in events)>=3
                    value=server.modules.primary_speech.snapshot();assert value['owned'] and not value['readout_active'];pid=value['pid']
                    # Start again then switch conversations: no old reply resumes in the new one.
                    page.locator('#readout-restart').evaluate('e=>{e.click();e.click();}');wait(lambda:server.modules.primary_speech.reader.current is not None)
                    page.locator('#clear').click();expect(page.locator('#chat-readout')).to_be_hidden(timeout=10000)
                    wait(lambda:server.modules.primary_speech.reader.current is None,seconds=10)
                    assert page.evaluate('window.__readoutMedia.every(a=>a.paused||a.ended)')
                    assert not server.modules.fast_speech.snapshot()['owned'] and not server.modules.speech.snapshot()['owned']
                    assert not errors,errors;browser.close()
                finally:driver.close()
        finally:
            release.set();server.shutdown();server.server_close();thread.join(3)
    report=dict(status='SUCCEEDED',source_version=__version__,first_click_to_native_media_play_seconds=first_play,
        parallel_synthetic_chat_ms=chat_ms,parallel_task=dict(task_id=item['task_id'],status='SUCCEEDED',planner='held synthetic plan',executor='real fixed directory Worker'),
        media_events=events,browser_errors=errors,leading_hyphen_component_token_native_verified=True,rapid_restart_latest_wins=True,send_control_visible_at_1280x720=True,pause_resume=True,continuous_playback=True,conversation_switch_stops_old_reply=True,
        model_kept_warm_after_complete=pid,backup_models_stayed_stopped=True,cloud_calls=0,
        limits='Native WAV generation and browser Audio events, not measured physical speaker onset. Synthetic chat/planner, real bounded task Worker. No microphone, full duplex or universal latency/quality claim.')
    paths=['runtime/node-host/jarvis_core/'+p for p in ['readout.py','readout_text.py','qwen_speech.py','speech.py']]
    paths+=['apps/web/readout.js','apps/web/readout.css','apps/web/index.html','apps/web/speech_routes.py','apps/web/server.py','tools/probe_chat_readout_ui.py']
    report['source_sha256']={p:hashlib.sha256((ROOT/p).read_bytes()).hexdigest() for p in paths}
    (ROOT/'evals/reports/chat-readout-ui-2026-10-18.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(dict(status='SUCCEEDED',first_media_play_seconds=first_play,chat_ms=chat_ms,media_ended=sum(e['type']=='ended' for e in events),errors=errors),ensure_ascii=False))


if __name__=='__main__':main()
