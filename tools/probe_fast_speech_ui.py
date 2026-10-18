"""Real CPU fast-TTS through the browser UI; temporary core, no cloud or microphone."""
from pathlib import Path
import hashlib
import json
import sys
import tempfile
import threading
import time

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT),str(ROOT/'apps/web'),str(ROOT/'runtime/node-host'),str(ROOT/'adapters/computer-use')]
from jarvis_core import __version__
from jarvis_core.service import CoreService
from tools.probe_workspace_ui import SyntheticChat
from jarvis_computer.browser import DriverJob
from server import create_server
from playwright.sync_api import sync_playwright, expect


def main():
    output=Path('H:/JarvisData/research/fast-tts');output.mkdir(parents=True,exist_ok=True)
    errors=[];cases=[]
    with tempfile.TemporaryDirectory(prefix='jarvis-fast-speech-ui-') as directory:
        core=CoreService(Path(directory)/'data');core.initialize(ROOT/'tests/fixtures/workspace')
        server=create_server(core=core,chat=SyntheticChat(),port=0);speech=server.modules.fast_speech
        thread=threading.Thread(target=server.serve_forever,kwargs={'poll_interval':.02},daemon=True);thread.start()
        try:
            with sync_playwright() as p:
                job=DriverJob(p)
                try:
                    browser=p.chromium.launch(channel='msedge',headless=True,chromium_sandbox=True)
                    page=browser.new_page(viewport={'width':1365,'height':1000});page.on('pageerror',lambda e:errors.append(str(e)))
                    page.goto('http://127.0.0.1:'+str(server.server_port)+'/settings#modules')
                    expect(page.locator('#fast-speech-start')).to_be_enabled()
                    assert not speech.snapshot()['owned'] and not server.modules.speech.snapshot()['owned']
                    start=time.monotonic();page.locator('#fast-speech-start').click()
                    expect(page.locator('#fast-speech-generate')).to_be_enabled(timeout=20000)
                    startup=time.monotonic()-start;loaded=speech.snapshot()['job']['result']['load']
                    for label,text in [('short','我在，有什么可以帮你？'),('mixed','今天下午三点提醒我开会。Hello, I am Jarvis.'),
                                       ('sentences','我可以陪你聊天。也可以帮你处理事情。我们先从哪一件开始？')]:
                        before=page.locator('#fast-speech-audio').get_attribute('src')
                        page.locator('#fast-speech-text').fill(text)
                        start=time.monotonic();page.locator('#fast-speech-generate').click()
                        page.wait_for_function('old=>{const a=document.getElementById("fast-speech-audio");return a.src.startsWith("blob:")&&a.getAttribute("src")!==old}',arg=before,timeout=15000)
                        available=time.monotonic()-start
                        value=speech.snapshot();result=value['job']['result']
                        with page.expect_download() as downloaded:page.locator('#fast-speech-download').click()
                        downloaded.value.save_as(output/f'ui-{label}.wav')
                        artifact=output/f'ui-{label}.wav'
                        cases.append(dict(label=label,text=text,click_to_blob_seconds=available,result=result,
                                          artifact=str(artifact),sha256=hashlib.sha256(artifact.read_bytes()).hexdigest()))
                    page.locator('#fast-speech-panel').screenshot(path=str(output/'fast-speech-panel.png'))
                    page.set_viewport_size({'width':480,'height':900})
                    page.locator('#fast-speech-panel').screenshot(path=str(output/'fast-speech-panel-narrow.png'))
                    page.locator('#fast-speech-stop').click()
                    expect(page.locator('#fast-speech-status')).to_contain_text('未加载',timeout=10000)
                    stopped=speech.snapshot();assert not stopped['owned'] and stopped['pid'] is None
                    assert not server.modules.speech.snapshot()['owned'];assert not errors,errors
                    browser.close()
                finally:job.close()
        finally:server.shutdown();server.server_close();thread.join(3)
    report=dict(status='SUCCEEDED',source_version=__version__,backend='native ZipVoice-Distill int8 CPU 4 threads / 4 steps',
                startup_click_to_ready_seconds=startup,loaded=loaded,cases=cases,browser_errors=errors,
                stopped=dict(owned=stopped['owned'],pid=stopped['pid'],state=stopped['state']),
                limits='Click-to-blob includes UI polling/download, not actual speaker onset, microphone/LLM or full-duplex latency.')
    report['source_sha256']={p:hashlib.sha256((ROOT/p).read_bytes()).hexdigest() for p in
        ['runtime/node-host/jarvis_core/speech.py','runtime/node-host/jarvis_core/fast_speech.py',
         'adapters/speech/zipvoice/worker.py','config/model-profiles/zipvoice.json','apps/web/speech.js']}
    (ROOT/'evals/reports/fast-speech-ui-2026-10-18.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps({'status':report['status'],'startup_seconds':startup,
                     'cases':[(c['label'],round(c['click_to_blob_seconds'],3),round(c['result']['elapsed_seconds'],3)) for c in cases],
                     'peak_memory':cases[-1]['result']['memory'],'errors':errors},ensure_ascii=False))


if __name__=='__main__':main()
