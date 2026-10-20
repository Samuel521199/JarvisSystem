"""Disposable native ASR and browser fake-device checks; never opens owner's mic."""
from pathlib import Path
import base64
from contextlib import closing
import json
import sys
import tempfile
import threading
import time
import uuid
import wave

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT/'apps/web'), str(ROOT/'tests'),
               str(ROOT/'runtime/node-host'), str(ROOT/'adapters/computer-use')]
from tools.probe_parallel_runtime import fixture, request, wait, task, detail, PlanChat
from tools.probe_workspace_ui import SyntheticChat
from jarvis_core.speech_input import SpeechInput
from jarvis_computer.browser import DriverJob
from server import create_server
from playwright.sync_api import sync_playwright, expect

OUT = Path('H:/JarvisData/diagnostics/k6-voice-20261020')
WAV = Path('H:/JarvisData/models/stt/sensevoice-small/test_wavs/zh.wav')


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='jarvis-voice-') as directory:
        core = fixture(Path(directory))
        chat = SyntheticChat()
        chat.text = '你好，我们可以一起安排今天的计划。'
        server = create_server(core=core, chat=chat, port=0)
        server.computer.sample.chat_factory = lambda *a, **kw: PlanChat()
        thread = threading.Thread(target=server.serve_forever, kwargs={'poll_interval':.02}, daemon=True)
        thread.start()
        report = dict(scope='publisher audio, real local ASR, browser fake microphone; no owner microphone', native=[], ui={}, paid_model_calls=0)
        try:
            service = server.modules.speech_input
            with wave.open(str(WAV), 'rb') as stream:
                assert stream.getnchannels() == 1 and stream.getsampwidth() == 2 and stream.getframerate() == 16000
                pcm = stream.readframes(stream.getnframes())
            for name, audio in [('publisher_zh', pcm), ('silence', b'\0\0'*16000)]:
                ident = uuid.uuid4().hex
                code, value, _ = request(server, '/api/speech/input', 'POST',
                                         dict(action='transcribe', id=ident, pcm=base64.b64encode(audio).decode(), language='auto'))
                assert code == 202, value
                # Deterministic local chat remains available during ASR.
                chat_code, _, chat_ms = request(server, '/api/chat', 'POST', {'message':'转写期间继续聊天'})
                wait(lambda: not service.snapshot()['busy'], seconds=55)
                value = service.snapshot(ident)
                assert value['status'] == 'SUCCEEDED', value
                assert bool(value['text']) == (name != 'silence')
                report['native'].append(dict(case=name, result=value, parallel_chat_status=chat_code, parallel_chat_ms=chat_ms))
                request(server, '/api/speech/input', 'POST', dict(action='forget', id=ident))
                assert 'text' not in service.snapshot(ident)
            print('native complete', flush=True)
            errors = []
            with sync_playwright() as p, closing(DriverJob(p)):
                browser = p.chromium.launch(channel='msedge', headless=True, chromium_sandbox=True,
                    args=['--use-fake-device-for-media-stream', '--use-fake-ui-for-media-stream',
                          '--use-file-for-fake-audio-capture='+str(WAV)])
                try:
                    page = browser.new_page(viewport={'width':1280,'height':900})
                    page.on('pageerror', lambda e: errors.append(str(e)))
                    page.add_init_script("""window.__media=[];window.__audio=[];const old=navigator.mediaDevices.getUserMedia.bind(navigator.mediaDevices);
                    navigator.mediaDevices.getUserMedia=async c=>{const s=await old(c);window.__media.push(s);return s;};
                    const NativeAudio=window.Audio;window.Audio=function(...args){const a=new NativeAudio(...args);window.__audio.push(a);return a;};""")
                    page.goto('http://127.0.0.1:'+str(server.server_port))
                    page.wait_for_function('()=>Boolean(window.Workspace && !window.Workspace.isBusy() && window.JarvisReadout)')
                    page.wait_for_function('()=>!document.documentElement.hasAttribute("data-brand-cinema")')
                    expect(page.locator('#voice-record')).to_be_enabled()
                    # Record real audio pipeline from a synthetic browser device, no owner permissions.
                    page.locator('#voice-record').click()
                    expect(page.locator('#voice-record')).to_have_attribute('data-state','recording',timeout=10000)
                    item = task(server)
                    page.locator('#message').fill('保留原草稿')
                    page.wait_for_timeout(4500)
                    page.locator('#voice-record').click()
                    expect(page.locator('#voice-preview-wrap')).to_be_visible(timeout=55000)
                    transcript = page.locator('#voice-preview').input_value()
                    assert transcript
                    assert page.evaluate('window.__media.every(s=>s.getTracks().every(t=>t.readyState==="ended"))')
                    expect(page.locator('#message')).to_have_value('保留原草稿')
                    wait(lambda: detail(server,item)['task']['status'] == 'SUCCEEDED', seconds=20)
                    page.screenshot(path=str(OUT/'desktop.png'))
                    page.locator('#voice-preview').fill('请帮我安排今天的计划。')
                    page.locator('#voice-insert').click()
                    expect(page.locator('#message')).to_have_value('保留原草稿\n请帮我安排今天的计划。')
                    assert not page.locator('.message.user').count()
                    # Explicitly enable new-reply playback and send through the usual conversation.
                    page.locator('#voice-panel summary').click()
                    page.locator('#voice-auto').check()
                    page.locator('#send').click()
                    expect(page.locator('.message.assistant')).to_have_count(1, timeout=15000)
                    page.wait_for_function('()=>window.__audio.some(a=>!a.paused)', timeout=180000)
                    print('native readout playing', flush=True)
                    page.locator('#voice-record').click()
                    expect(page.locator('#voice-record')).to_have_attribute('data-state','recording',timeout=15000)
                    assert page.evaluate('window.__audio.every(a=>a.paused)')
                    page.locator('#voice-cancel').click()
                    expect(page.locator('#voice-record')).to_have_attribute('data-state','idle')
                    assert page.evaluate('window.__media.every(s=>s.getTracks().every(t=>t.readyState==="ended"))')
                    # Rejected permission leaves draft and other UI usable.
                    page.evaluate("()=>{navigator.mediaDevices.getUserMedia=async()=>{throw new DOMException('denied','NotAllowedError')};}")
                    page.locator('#message').fill('权限拒绝也保留')
                    page.locator('#voice-record').click()
                    expect(page.locator('#voice-status')).to_contain_text('权限未允许')
                    expect(page.locator('#message')).to_have_value('权限拒绝也保留')
                    page.set_viewport_size({'width':480,'height':850})
                    page.screenshot(path=str(OUT/'narrow.png'))
                    assert page.evaluate('document.documentElement.scrollWidth<=innerWidth')
                    report['ui'] = dict(transcript=transcript, background_task='SUCCEEDED',
                        draft_preserved=True, edited_then_inserted=True, no_auto_send=True,
                        native_readout=True, interrupted_readout=True, released_tracks=True,
                        permission_denied_recoverable=True, no_horizontal_overflow=True, page_errors=errors)
                    assert not errors, errors
                finally:
                    browser.close()
            report['status'] = 'passed'
        except Exception as exc:
            report.update(status='failed', failure_type=type(exc).__name__, failure=str(exc)[:1200])
            raise
        finally:
            (OUT/'report.json').write_text(json.dumps(report, ensure_ascii=False, indent=2)+'\n',encoding='utf-8')
            server.shutdown()
            server.server_close()
            thread.join(3)
            # Owned Job termination is asynchronous for child file handles on Windows.
            time.sleep(2)
    print(json.dumps(report, ensure_ascii=False))


if __name__ == '__main__':
    main()
