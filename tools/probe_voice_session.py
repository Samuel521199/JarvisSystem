"""Continuous voice on disposable data and synthetic mic, never owner's audio."""
import base64
from contextlib import closing
import json
from pathlib import Path
import sys
import tempfile
import threading
import time
import uuid
import wave

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT/'apps/web'), str(ROOT/'runtime/node-host'), str(ROOT/'adapters/computer-use')]
from tools.probe_parallel_runtime import fixture, wait
from tools.probe_workspace_ui import SyntheticChat
from jarvis_computer.browser import DriverJob
from playwright.sync_api import sync_playwright, expect
from server import create_server

OUT = Path('H:/JarvisData/diagnostics/k6-continuous-20261020')
MIC = """
window.__streams=[];window.__contexts=[];window.__requests=[];
window.__audios=[];const NativeAudio=window.Audio;
window.Audio=function(...a){const audio=new NativeAudio(...a);__audios.push(audio);return audio;};
navigator.mediaDevices.getUserMedia=async()=>{
 const a=new AudioContext({sampleRate:16000});await a.resume();const d=a.createMediaStreamDestination();
 window.__mic={audio:a,destination:d};window.__streams.push(d.stream);window.__contexts.push(a);return d.stream;
};
window.__feed=async raw=>{
 const m=window.__mic;await m.audio.resume();
 const bytes=Uint8Array.from(atob(raw),c=>c.charCodeAt(0)),view=new DataView(bytes.buffer);
 const b=m.audio.createBuffer(1,bytes.length/2,16000),samples=b.getChannelData(0);
 for(let i=0;i<samples.length;i++)samples[i]=view.getInt16(i*2,true)/32768;
 const s=m.audio.createBufferSource();s.buffer=b;s.connect(m.destination);s.start();
};
"""


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    report = dict(scope='disposable core; synthetic browser mic; publisher audio; no owner microphone',
                  paid_model_calls=0, native=[], ui={})
    with wave.open('H:/JarvisData/models/stt/sensevoice-small/test_wavs/zh.wav', 'rb') as w:
        pcm = w.readframes(w.getnframes())
    encoded = base64.b64encode(pcm).decode()
    with tempfile.TemporaryDirectory(prefix='jarvis-continuous-') as temp:
        core = fixture(Path(temp));chat = SyntheticChat();chat.text = '你好，我在。'
        server = create_server(core=core, chat=chat, port=0)
        thread = threading.Thread(target=server.serve_forever, kwargs={'poll_interval': .02}, daemon=True);thread.start()
        try:
            import numpy as np
            noise = np.random.default_rng(52).normal(0, .025, 32000)
            tone = .04*np.sin(np.arange(32000)*2*np.pi*440/16000)
            for name,audio in [('speech',pcm),('silence',b'\0\0'*32000),
                               ('noise',(noise*32767).astype('<i2').tobytes()),
                               ('tone',(tone*32767).astype('<i2').tobytes())]:
                ident = uuid.uuid4().hex;s=server.modules.speech_input
                s.submit(dict(action='transcribe',id=ident,language='auto',pcm=base64.b64encode(audio).decode()))
                wait(lambda:s.active is None,seconds=55);row=s.snapshot(ident)
                assert row['status']=='SUCCEEDED',row
                assert bool(row['text'])==(name=='speech'),row
                report['native'].append({'case':name,**row})
                s.submit(dict(action='forget',id=ident))
            print('Native VAD/ASR four cases passed',flush=True)
            errors=[]
            with sync_playwright() as pw,closing(DriverJob(pw)):
                browser=pw.chromium.launch(channel='msedge',headless=True,chromium_sandbox=True)
                try:
                    page=browser.new_page(viewport={'width':1280,'height':900})
                    page.add_init_script(MIC);page.on('pageerror',lambda e:errors.append(str(e)))
                    requests=[]
                    page.on('request',lambda r:requests.append((r.url,r.post_data_json)) if r.method=='POST' else None)
                    page.goto('http://127.0.0.1:'+str(server.server_port))
                    page.wait_for_function('()=>window.JarvisVoiceSession&&window.Workspace&&!Workspace.isBusy()')
                    page.wait_for_function('()=>!document.documentElement.hasAttribute("data-brand-cinema")')
                    page.locator('#voice-session-open').click()
                    page.locator('#message').fill('保留我的键盘草稿')
                    page.evaluate('()=>{document.getElementById("file-mode").checked=true;}')
                    page.locator('#voice-session-toggle').click()
                    page.wait_for_function('()=>JarvisVoiceSession.state()?.phase==="listening"')
                    page.evaluate('raw=>window.__feed(raw)',encoded)
                    page.wait_for_function('()=>JarvisVoiceSession.state()?.phase==="speaking"',timeout=60000)
                    page.wait_for_function('()=>__audios.some(a=>!a.paused&&a.currentTime>0)',timeout=90000)
                    paused=page.evaluate('()=>{window.__pauseToken=JarvisReadout.pause();return __audios.at(-1).currentTime;}')
                    page.wait_for_timeout(180)
                    assert abs(page.evaluate('__audios.at(-1).currentTime')-paused)<.03
                    page.evaluate('()=>JarvisReadout.resume("wrong-playback")')
                    assert page.evaluate('JarvisReadout.state().paused')
                    page.evaluate('()=>JarvisReadout.resume(__pauseToken)')
                    page.wait_for_function('()=>!JarvisReadout.state()?.paused')
                    report['ui']['native_audio_pause_position_and_resume_ownership']=True
                    page.screenshot(path=str(OUT/'desktop.png'))
                    page.wait_for_function('()=>JarvisVoiceSession.state()?.phase==="listening"',timeout=180000)
                    assert chat.calls==1,chat.calls
                    expect(page.locator('#message')).to_have_value('保留我的键盘草稿')
                    assert len(page.locator('.message.assistant').all())==1
                    page.locator('#voice-session-toggle').click()
                    assert page.evaluate('__streams.every(s=>s.getTracks().every(t=>t.readyState==="ended"))')
                    report['ui']['native_capture_vad_asr_chat_tts_next_turn']=True
                    chat_requests=[v for u,v in requests if u.endswith('/api/dialogue/turns')]
                    assert len(chat_requests)==1 and chat_requests[0]['chat']['voice_mode']=='conversation'
                    assert not chat_requests[0]['chat'].get('attachments')
                    assert '请直接输出要保存的文件正文' not in chat_requests[0]['chat']['message']
                    report['ui']['file_mode_bypassed_draft_preserved']=True
                    print('Native continuous round passed',flush=True)
                    # Deterministic transcript/readout fixtures for race and policy boundaries.
                    values=['测试第一轮','嗯','你好，我在','新的问题','停一下']
                    s.runner=lambda *a:dict(text=values.pop(0),backend='boundary-fixture')
                    page.evaluate("""()=>{
                     window.__reader={active:null,paused:0,resumed:0,stops:0};
                     JarvisReadout.speak=article=>{const r=__reader;r.active={id:crypto.randomUUID(),text:article.querySelector('.bubble').textContent,paused:false};
                      return new Promise(resolve=>r.finish=()=>{r.active=null;resolve(true);});};
                     JarvisReadout.state=()=>__reader.active;
                     JarvisReadout.pause=()=>{const r=__reader;if(!r.active||r.active.paused)return null;r.active.paused=true;r.active.ownedPause=true;r.paused++;return r.active.id;};
                     JarvisReadout.resume=async id=>{const r=__reader;if(r.active?.id===id){r.active.paused=false;r.active.ownedPause=false;r.resumed++;}};
                     JarvisReadout.stop=async()=>{__reader.stops++;__reader.finish?.();};
                    }""")
                    page.locator('#voice-session-open').click();page.locator('#voice-duplex').check()
                    page.locator('#voice-session-toggle').click()
                    page.wait_for_function('()=>JarvisVoiceSession.state()?.phase==="listening"')
                    page.evaluate('raw=>window.__feed(raw)',encoded)
                    page.wait_for_function('()=>JarvisVoiceSession.state()?.phase==="speaking"',timeout=20000)
                    for resumed in (1,2):
                        page.evaluate('raw=>window.__feed(raw)',encoded)
                        page.wait_for_function(f'()=>__reader.resumed==={resumed}',timeout=20000)
                        assert chat.calls==2
                    report['ui']['ack_and_exact_echo_resume_without_model']=True
                    page.evaluate('raw=>window.__feed(raw)',encoded)
                    page.wait_for_function('()=>JarvisVoiceSession.state()?.turns===2&&JarvisVoiceSession.state()?.phase==="speaking"',timeout=20000)
                    assert chat.calls==3
                    report['ui']['new_interruption_replaces_readout_once']=True
                    page.evaluate('raw=>window.__feed(raw)',encoded)
                    page.wait_for_function('()=>JarvisVoiceSession.state()?.phase==="listening"',timeout=20000)
                    assert chat.calls==3
                    report['ui']['spoken_stop_no_model_no_background_cancel']=True
                    page.set_viewport_size({'width':480,'height':850})
                    page.screenshot(path=str(OUT/'narrow.png'))
                    page.evaluate('()=>Workspace.newSession(null)')
                    page.wait_for_function('()=>!JarvisVoiceSession.state()')
                    assert page.evaluate('__streams.every(s=>s.getTracks().every(t=>t.readyState==="ended"))')
                    report['ui']['context_change_releases_tracks']=True
                    # Idle expiry uses an advanced UI clock; no owner session or real minute wait.
                    page.locator('#voice-session-open').click();page.locator('#voice-session-toggle').click()
                    page.wait_for_function('()=>JarvisVoiceSession.state()?.phase==="listening"')
                    calls=chat.calls
                    page.evaluate('()=>{window.__now=Date.now;Date.now=()=>__now()+61000;}')
                    page.wait_for_function('()=>!JarvisVoiceSession.state()')
                    assert chat.calls==calls
                    page.evaluate('()=>{Date.now=__now;}')
                    report['ui']['silent_idle_expiry_no_model_advanced_clock']=True
                    # Cancel unresolved permission; late stream must be stopped.
                    page.evaluate("""()=>{const old=navigator.mediaDevices.getUserMedia;
                     navigator.mediaDevices.getUserMedia=()=>new Promise(resolve=>{window.__allow=async()=>resolve(await old());});}""")
                    page.locator('#voice-session-open').click();page.locator('#voice-session-toggle').click()
                    page.wait_for_function('()=>Boolean(window.__allow)')
                    page.locator('#voice-session-toggle').click();page.evaluate('()=>window.__allow()')
                    page.wait_for_function('()=>__streams.every(s=>s.getTracks().every(t=>t.readyState==="ended"))')
                    report['ui']['late_permission_releases_tracks']=True
                    # Readout fixture is confined to this disposable test page.
                    assert not errors,errors
                    report['ui']['page_errors']=errors
                    page.evaluate('()=>Promise.all(__contexts.map(a=>a.close()))')
                finally:browser.close()
        finally:
            server.shutdown();server.server_close();thread.join(2);time.sleep(2)
    (OUT/'report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(report,ensure_ascii=False,indent=2))
    return report


if __name__=='__main__':main()
