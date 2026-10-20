"""Deterministic UI faults: injected worklet messages, synthetic ASR/model/TTS."""
from contextlib import closing
import json
from pathlib import Path
import sys
import tempfile
import threading
import time

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT),str(ROOT/'apps/web'),str(ROOT/'runtime/node-host'),str(ROOT/'adapters/computer-use')]
from tools.probe_voice_session import MIC, OUT
from tools.probe_parallel_runtime import fixture
from tools.probe_workspace_ui import SyntheticChat
from jarvis_computer.browser import DriverJob
from playwright.sync_api import sync_playwright
from server import create_server


def main():
    report={'scope':'synthetic recognition, chat and readout; injected worklet messages and advanced clock','paid_model_calls':0}
    with tempfile.TemporaryDirectory(prefix='jarvis-voice-limits-') as temp:
        core=fixture(Path(temp));chat=SyntheticChat();server=create_server(core=core,chat=chat,port=0)
        recognized=[]
        def recognize(*args):
            recognized.append(1)
            return dict(text='继续聊一聊',backend='fault-fixture')
        server.modules.speech_input.runner=recognize
        thread=threading.Thread(target=server.serve_forever,kwargs={'poll_interval':.02},daemon=True);thread.start()
        try:
            with sync_playwright() as pw,closing(DriverJob(pw)):
                browser=pw.chromium.launch(channel='msedge',headless=True,chromium_sandbox=True)
                try:
                    page=browser.new_page();errors=[];page.on('pageerror',lambda e:errors.append(str(e)))
                    page.add_init_script(MIC+"""
const Node=window.AudioWorkletNode;
window.AudioWorkletNode=function(context,name,...rest){const node=new Node(context,name,...rest);if(name==='jarvis-session-capture'){
 window.__node=node;const post=node.port.postMessage.bind(node.port);node.port.postMessage=value=>{window.__captureEpoch=value.epoch;post(value);};
}return node;};
window.__segment=(stale=false)=>__node.port.onmessage({data:{type:'segment',epoch:__captureEpoch-(stale?1:0),samples:new Float32Array(16000)}});
""")
                    page.goto('http://127.0.0.1:'+str(server.server_port))
                    page.wait_for_function('()=>window.JarvisVoiceSession&&window.Workspace&&!Workspace.isBusy()')
                    page.wait_for_function('()=>!document.documentElement.hasAttribute("data-brand-cinema")')
                    page.evaluate('()=>{JarvisReadout.speak=async()=>true;}')
                    def start():
                        page.locator('#voice-session-open').click();page.locator('#voice-session-toggle').click()
                        page.wait_for_function('()=>JarvisVoiceSession.state()?.phase==="listening"')
                    def stopped():
                        page.wait_for_function('()=>!JarvisVoiceSession.state()')
                        assert page.evaluate('__streams.every(s=>s.getTracks().every(t=>t.readyState==="ended"))')
                    start()
                    page.evaluate('()=>__segment(true)')
                    page.wait_for_timeout(150)
                    assert not recognized and chat.calls==0
                    report['late_capture_epoch_rejected']=True
                    # Lost successful POST: same receipt query, no repeated recognition.
                    dropped=[]
                    def route(r):
                        if r.request.post_data_json.get('action')=='transcribe' and not dropped:
                            r.fetch();dropped.append(1);r.abort()
                        else:r.continue_()
                    page.route('**/api/speech/input',route)
                    for n in range(20):
                        page.evaluate('()=>__segment()')
                        if n<19:
                            page.wait_for_function(f'()=>JarvisVoiceSession.state()?.turns==={n+1}&&JarvisVoiceSession.state()?.phase==="listening"')
                    stopped()
                    assert chat.calls==20 and len(recognized)==20 and len(dropped)==1
                    report.update(turn_limit_20=True,lost_post_queried_once=True,no_duplicate_inference=True)
                    page.unroute('**/api/speech/input',route)
                    start();chat.failure=True;page.evaluate('()=>__segment()');stopped()
                    assert chat.calls==21
                    report['model_failure_exits_without_retry']=True;chat.failure=False
                    start()
                    # Cancel while a model is blocked; late success cannot synthesize or restart.
                    hold=threading.Event();entered=threading.Event()
                    chat.hook=lambda:(entered.set(),hold.wait(5))
                    page.evaluate('()=>__segment()');page.wait_for_function('()=>JarvisVoiceSession.state()?.phase==="thinking"')
                    assert entered.wait(3)
                    page.locator('#voice-session-toggle').click();hold.set();stopped()
                    page.wait_for_function('()=>JarvisConversation.ready()')
                    assert not page.evaluate('JarvisReadout.state()')
                    report['late_reply_after_exit_no_playback']=True;chat.hook=None
                    start();page.evaluate('()=>{window.__oldNow=Date.now;Date.now=()=>__oldNow()+601000;}')
                    stopped();page.evaluate('()=>{Date.now=__oldNow;}')
                    report['ten_minute_cap_advanced_clock']=True
                    start();page.evaluate('()=>__streams.at(-1).getTracks()[0].dispatchEvent(new Event("ended"))');stopped()
                    report['device_disconnect_releases_tracks']=True
                    assert not errors,errors
                    report['page_errors']=errors
                    page.evaluate('()=>Promise.all(__contexts.map(a=>a.close()))')
                finally:browser.close()
        finally:server.shutdown();server.server_close();thread.join(2);time.sleep(2)
    OUT.mkdir(parents=True,exist_ok=True)
    (OUT/'limits.json').write_text(json.dumps(report,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(report,indent=2))


if __name__=='__main__':main()
