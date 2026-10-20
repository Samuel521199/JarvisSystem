"""Fault injection on a disposable core and fake microphone; no owner recording."""
import base64
from contextlib import closing
import json
from pathlib import Path
import sys
import tempfile
import threading
import time
import uuid

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT), str(ROOT/'apps/web'), str(ROOT/'runtime/node-host'),str(ROOT/'adapters/computer-use')]
from tools.probe_parallel_runtime import fixture, wait
from tools.probe_workspace_ui import SyntheticChat
from jarvis_core.speech_input import SpeechInput
from jarvis_core.process_memory import process_memory
from jarvis_computer.browser import DriverJob
from playwright.sync_api import sync_playwright, expect
from server import create_server


def main():
    out=Path('H:/JarvisData/diagnostics/k6-voice-20261020')
    out.mkdir(parents=True,exist_ok=True)
    report={}
    with tempfile.TemporaryDirectory(prefix='jarvis-voice-faults-') as tmp:
        core=fixture(Path(tmp))
        server=create_server(core=core,chat=SyntheticChat(),port=0)
        thread=threading.Thread(target=server.serve_forever,kwargs={'poll_interval':.02},daemon=True);thread.start()
        service=server.modules.speech_input
        try:
            # Native missing-file failure and real process cancellation.
            service.model_root=Path(tmp)/'missing-models'
            p=dict(action='transcribe',id=uuid.uuid4().hex,language='auto',pcm=base64.b64encode(b'\1\0'*16000).decode())
            service.submit(p);wait(lambda:service.active is None,seconds=10)
            assert service.snapshot(p['id'])['status']=='FAILED'
            service.model_root=None
            p={**p,'id':uuid.uuid4().hex,'pcm':base64.b64encode(b'\xff\x03'*320000).decode()}
            service.submit(p);pid=wait(lambda:service.pid,seconds=10)
            started=time.monotonic()
            service.submit(dict(action='cancel',id=p['id']))
            wait(lambda:service.active is None and service.pid is None,seconds=5)
            assert process_memory(pid) is None and service.snapshot(p['id'])['status']=='CANCELLED'
            report['native']=dict(missing_model_failed=True,cancelled_owned_process=True,
                cancellation_seconds=round(time.monotonic()-started,3))
            # Use synthetic recognition for UI fault scenarios; distinguish from native report.
            calls=[]
            def recognize(pcm,lang,cancel):
                calls.append(len(pcm))
                return dict(text='模拟转写，请检查。',backend='fault-fixture')
            service.runner=recognize
            errors=[]
            with sync_playwright() as pw,closing(DriverJob(pw)):
                browser=pw.chromium.launch(channel='msedge',headless=True,chromium_sandbox=True,
                    args=['--use-fake-device-for-media-stream','--use-fake-ui-for-media-stream'])
                try:
                    page=browser.new_page(viewport={'width':480,'height':850})
                    page.on('pageerror',lambda e:errors.append(str(e)))
                    page.add_init_script("""window.__streams=[];const original=navigator.mediaDevices.getUserMedia.bind(navigator.mediaDevices);
                    window.__getMedia=async c=>{const s=await original(c);window.__streams.push(s);return s;};
                    navigator.mediaDevices.getUserMedia=window.__getMedia;""")
                    page.goto('http://127.0.0.1:'+str(server.server_port))
                    page.wait_for_function('()=>window.Workspace&&!Workspace.isBusy()')
                    page.wait_for_function('()=>!document.documentElement.hasAttribute("data-brand-cinema")')
                    # Cancelling while browser permission is unresolved must release the late stream.
                    page.evaluate("()=>{navigator.mediaDevices.getUserMedia=c=>new Promise(resolve=>{window.__allow=async()=>resolve(await window.__getMedia(c));});}")
                    page.locator('#voice-record').click()
                    page.wait_for_function('()=>Boolean(window.__allow)')
                    page.locator('#voice-cancel').click()
                    page.evaluate('()=>window.__allow()')
                    page.wait_for_function('()=>window.__streams.every(s=>s.getTracks().every(t=>t.readyState==="ended"))')
                    page.evaluate('()=>{navigator.mediaDevices.getUserMedia=window.__getMedia;}')
                    # Real conversation changes, including replaceState, cancel capture.
                    page.locator('#voice-record').click()
                    expect(page.locator('#voice-record')).to_have_attribute('data-state','recording')
                    page.evaluate('()=>Workspace.newSession(null)')
                    expect(page.locator('#voice-status')).to_contain_text('切换会话')
                    assert page.evaluate('window.__streams.every(s=>s.getTracks().every(t=>t.readyState==="ended"))')
                    # Device unplug signal is recoverable.
                    page.locator('#voice-record').click()
                    expect(page.locator('#voice-record')).to_have_attribute('data-state','recording')
                    page.evaluate('()=>window.__streams.at(-1).getAudioTracks()[0].dispatchEvent(new Event("ended"))')
                    expect(page.locator('#voice-status')).to_contain_text('麦克风已断开')
                    # Drop a successful POST response: browser must query its receipt, not resubmit.
                    dropped=[]
                    def route(request):
                        data=request.request.post_data_json
                        if data.get('action')=='transcribe' and not dropped:
                            request.fetch();dropped.append(True);request.abort()
                        else:request.continue_()
                    page.route('**/api/speech/input',route)
                    page.locator('#message').fill('不会覆盖的草稿')
                    page.locator('#voice-record').click()
                    expect(page.locator('#voice-record')).to_have_attribute('data-state','recording')
                    # Let the actual capture clock terminate at 20 seconds.
                    expect(page.locator('#voice-preview-wrap')).to_be_visible(timeout=30000)
                    assert len(calls)==1 and calls[0]<=640000
                    expect(page.locator('#message')).to_have_value('不会覆盖的草稿')
                    assert page.locator('.message.user').count()==0
                    page.locator('#voice-insert').click()
                    expect(page.locator('#message')).to_have_value('不会覆盖的草稿\n模拟转写，请检查。')
                    assert page.evaluate('window.__streams.every(s=>s.getTracks().every(t=>t.readyState==="ended"))')
                    rect=page.locator('#voice-record').bounding_box()
                    send=page.locator('#send').bounding_box()
                    assert 0<=send['x']-(rect['x']+rect['width'])<20
                    page.screenshot(path=str(out/'narrow-current.png'))
                    page.set_viewport_size({'width':1280,'height':900})
                    page.screenshot(path=str(out/'desktop-current.png'))
                    assert not errors,errors
                    report['ui']=dict(cancel_permission_pending=True,conversation_change_cancels=True,
                        device_disconnect=True,lost_response_reconciled=True,recognition_calls=len(calls),
                        max_pcm_bytes=calls[0],auto_stop_20_seconds=True,draft_preserved=True,
                        microphone_adjacent_to_send=True,page_errors=errors)
                finally:browser.close()
            report['status']='passed'
        finally:
            server.shutdown();server.server_close();thread.join(3)
            (out/'boundaries.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(report,ensure_ascii=False))


if __name__=='__main__':main()
