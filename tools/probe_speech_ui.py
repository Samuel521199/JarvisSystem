"""Real loopback browser UI; synthetic PCM backend, no native quality claim."""
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
import io
import json
import sys
import tempfile
import threading
import wave

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT),str(ROOT/'apps/web'),str(ROOT/'runtime/node-host'),str(ROOT/'adapters/computer-use')]
from jarvis_core.service import CoreService
from tools.probe_workspace_ui import SyntheticChat
from jarvis_computer.browser import DriverJob
from server import create_server
from playwright.sync_api import sync_playwright, expect


def main():
    output=Path('H:/JarvisData/research/cosyvoice3');output.mkdir(parents=True,exist_ok=True)
    errors=[];checks=[]
    with tempfile.TemporaryDirectory(prefix='jarvis-speech-ui-') as directory:
        core=CoreService(Path(directory)/'data');core.initialize(ROOT/'tests/fixtures/workspace')
        server=create_server(core=core,chat=SyntheticChat(),port=0);speech=server.modules.speech
        def start(epoch):
            speech._checkpoint(epoch)
            speech.data.joinpath('audio').mkdir(parents=True,exist_ok=True)
            speech.engine=SimpleNamespace(pid=999999,poll=lambda:None,stop=lambda:None)
            speech.state='ready';return {'message':'Synthetic UI fixture'}
        def call(path,*,payload=None,**kwargs):
            stream=io.BytesIO()
            with wave.open(stream,'wb') as audio:
                audio.setnchannels(1);audio.setsampwidth(2);audio.setframerate(24000);audio.writeframes(b'\0\0'*24000)
            (speech.data/'audio'/(payload['id']+'.wav')).write_bytes(stream.getvalue())
            return {'id':payload['id'],'audio_seconds':1,'elapsed_seconds':.1,'sample_rate_hz':24000}
        thread=threading.Thread(target=server.serve_forever,kwargs={'poll_interval':.02},daemon=True);thread.start()
        try:
            with patch.object(speech,'installed',return_value=True),patch.object(speech,'_start',side_effect=start),patch.object(speech,'_call',side_effect=call),sync_playwright() as p:
                job=DriverJob(p)
                try:
                    browser=p.chromium.launch(channel='msedge',headless=True,chromium_sandbox=True)
                    page=browser.new_page(viewport={'width':1365,'height':1000});page.on('pageerror',lambda e:errors.append(str(e)))
                    page.goto('http://127.0.0.1:'+str(server.server_port)+'/settings#modules')
                    expect(page.locator('#speech-start')).to_be_enabled();page.locator('#speech-start').click()
                    expect(page.locator('#speech-generate')).to_be_enabled(timeout=10000)
                    page.locator('#speech-emotion').select_option('happy');page.locator('#speech-generate').click()
                    expect(page.locator('#speech-result')).to_be_visible(timeout=10000)
                    expect(page.locator('#speech-result-info')).to_contain_text('24000 Hz')
                    assert page.locator('#speech-audio').get_attribute('src').startswith('blob:')
                    with page.expect_download() as downloaded:page.locator('#speech-download').click()
                    downloaded.value.save_as(output/'ui-fixture.wav')
                    checks.append('load, emotion selection, async synthesis, blob audio and WAV download')
                    page.locator('#speech-panel').screenshot(path=str(output/'speech-panel.png'))
                    page.locator('#speech-stop').click();expect(page.locator('#speech-status')).to_contain_text('未加载',timeout=10000)
                    checks.append('stop restores unloaded state; opening settings never loads a native model')
                    page.set_viewport_size({'width':480,'height':900});page.locator('#speech-panel').screenshot(path=str(output/'speech-panel-narrow.png'))
                    assert not errors,errors
                    browser.close()
                finally:job.close()
        finally:server.shutdown();server.server_close();thread.join(3)
    report={'status':'SUCCEEDED','checks':checks,'browser_errors':errors,'backend':'synthetic PCM only; native evidence separate'}
    (ROOT/'evals/reports/cosyvoice3-ui-2026-10-18.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(report,ensure_ascii=False))


if __name__=='__main__':main()
