"""Real layered TTS, whole-utterance direction and exact pause A/B/C in a temporary UI."""
from pathlib import Path
import argparse
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
from tools.probe_qwen_speech_ui import wait_exit
from jarvis_computer.browser import DriverJob
from server import create_server
from playwright.sync_api import sync_playwright,expect


TEXT='别担心，我在这里。你已经做得很好了！我们一起试试看。'
LAYERED='[轻声][慢速]别担心，我在这里。[停顿350ms][自然][开心]你已经做得很好了！[自然]我们一起试试看。'
CASES=[('fixed',TEXT,'soft','',1),
       ('direction',TEXT,'neutral','像朋友聊天。开头轻声安慰，中间带着笑意真诚肯定，最后充满期待地鼓励。语气有自然起伏，保持同一音色。',1),
       ('layered',LAYERED,'neutral','像朋友自然聊天，保持原来的音色，转折柔和，不要播音腔。',3),
       ('soft_slow','【轻声】别担心，我在这里。','slow','',1)]


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--run-label',choices=['initial','final'],default='initial');args=parser.parse_args()
    output=Path('H:/JarvisData/research/qwen-tts/expression-score')
    if args.run_label!='initial':output=output/args.run_label
    output.mkdir(parents=True,exist_ok=True)
    cases=[];errors=[]
    with tempfile.TemporaryDirectory(prefix='jarvis-expression-ui-') as directory:
        core=CoreService(Path(directory)/'data');core.initialize(ROOT/'tests/fixtures/workspace')
        server=create_server(core=core,chat=SyntheticChat(),port=0);speech=server.modules.primary_speech
        thread=threading.Thread(target=server.serve_forever,kwargs={'poll_interval':.02},daemon=True);thread.start()
        try:
            with sync_playwright() as p:
                driver=DriverJob(p)
                try:
                    browser=p.chromium.launch(channel='msedge',headless=True,chromium_sandbox=True)
                    page=browser.new_page(viewport={'width':1365,'height':1200});page.on('pageerror',lambda e:errors.append(str(e)))
                    page.goto('http://127.0.0.1:'+str(server.server_port)+'/settings#modules')
                    expect(page.locator('#primary-speech-start')).to_be_enabled()
                    page.locator('#primary-speech-text').fill(LAYERED)
                    page.locator('#primary-speech-preview').click()
                    expect(page.locator('#primary-speech-preview-summary')).to_contain_text('预览 3 段表达')
                    expect(page.locator('#primary-speech-preview-list li')).to_have_count(4)
                    assert not speech.snapshot()['owned'] and not speech.data.exists()
                    preview_without_model=True
                    page.locator('#primary-speech-start').click()
                    expect(page.locator('#primary-speech-generate')).to_be_enabled(timeout=120000)
                    pid=speech.snapshot()['pid']
                    for label,text,emotion,direction,segments in CASES:
                        page.locator('#primary-speech-text').fill(text);page.locator('#primary-speech-emotion').select_option(emotion)
                        page.locator('#primary-speech-direction').fill(direction)
                        before=page.locator('#primary-speech-audio').get_attribute('src');tick=time.monotonic()
                        page.locator('#primary-speech-generate').click()
                        if label=='layered':
                            deadline=time.monotonic()+2
                            while not speech.snapshot()['busy'] and time.monotonic()<deadline:time.sleep(.005)
                            assert speech.snapshot()['busy'];start=time.monotonic()
                            chat=page.evaluate("""async()=>{const n=document.querySelector('meta[name="jarvis-nonce"]').content;const r=await fetch('/api/chat',{method:'POST',headers:{'Content-Type':'application/json','X-Jarvis-Nonce':n},body:JSON.stringify({message:'hello'})});return r.status;}""")
                            parallel_chat=time.monotonic()-start;assert chat==200
                        page.wait_for_function('old=>{const a=document.getElementById("primary-speech-audio");return a.src.startsWith("blob:")&&a.getAttribute("src")!==old}',arg=before,timeout=65000)
                        available=time.monotonic()-tick;value=speech.snapshot();result=value['job']['result']
                        assert result['speech_segments']==segments
                        if label=='layered':
                            assert result['pause_ms']==350 and len(result['segments'])==4
                            rows=result['segments'];assert rows[1]['end_sample']-rows[1]['start_sample']==8400
                            assert rows[0]['delivery']=='soft' and rows[0]['pace']=='slow' and rows[2]['emotion']=='happy'
                        if label=='soft_slow':assert result['segments'][0]['delivery']=='soft' and result['segments'][0]['pace']=='slow'
                        expect(page.locator('#primary-speech-preview-summary')).to_contain_text('已生成 '+str(segments)+' 段表达')
                        with page.expect_download() as d:page.locator('#primary-speech-download').click()
                        artifact=output/(label+'.wav');d.value.save_as(artifact)
                        cases.append(dict(label=label,source_text=text,default_expression=emotion,direction=direction,click_to_blob_seconds=available,
                            result=result,memory=value['memory'],gpu_memory=value['gpu_memory'],artifact=str(artifact),sha256=hashlib.sha256(artifact.read_bytes()).hexdigest()))
                        if label=='layered':
                            page.locator('#primary-speech-panel').screenshot(path=str(output/'expression-panel.png'))
                            page.set_viewport_size({'width':480,'height':1000});page.locator('#primary-speech-panel').screenshot(path=str(output/'expression-panel-narrow.png'))
                            page.set_viewport_size({'width':1365,'height':1200})
                    for invalid in ['你好[laugh]','你好[停顿1001ms]','你好[开心]']:
                        page.locator('#primary-speech-text').fill(invalid);page.locator('#primary-speech-preview').click()
                        expect(page.locator('#primary-speech-error')).to_be_visible()
                        assert speech.snapshot()['state']=='ready' and speech.snapshot()['uses']==4
                    page.locator('#primary-speech-text').fill(LAYERED);page.locator('#primary-speech-direction').fill('')
                    page.locator('#primary-speech-generate').click();deadline=time.monotonic()+2
                    while not speech.snapshot()['busy'] and time.monotonic()<deadline:time.sleep(.005)
                    assert speech.snapshot()['busy'];page.locator('#primary-speech-stop').click()
                    expect(page.locator('#primary-speech-status')).to_contain_text('未加载',timeout=10000);wait_exit(pid)
                    assert speech.snapshot()['job']['status']=='CANCELLED' and speech.snapshot()['uses']==4
                    assert not server.modules.fast_speech.snapshot()['owned'] and not server.modules.speech.snapshot()['owned']
                    assert not errors,errors;browser.close()
                finally:driver.close()
        finally:server.shutdown();server.server_close();thread.join(3)
    report=dict(status='SUCCEEDED',run_label=args.run_label,source_version=__version__,backend='Qwen3-TTS 1.7B Q5_K / speech.cpp 0.8.10 Vulkan0',
        cases=cases,preview_without_model=preview_without_model,parallel_synthetic_chat_seconds=parallel_chat,
        invalid_preview_does_not_stop_model=True,cancelled_owned_native_exited=True,browser_errors=errors,
        limits='A/B/C audio generated for listening, no subjective smoothness/identity acceptance yet. Same selected voice and seed, not an acoustic identity guarantee. Complete WAV, not streaming playback. No cloud calls.')
    paths=['runtime/node-host/jarvis_core/'+p for p in ['qwen_speech_contract.py','qwen_speech.py','speech_audio.py']]
    paths+=['adapters/speech/qwen/worker.py','apps/web/admin.html','apps/web/speech.js','apps/web/speech_routes.py','tools/probe_speech_expression_ui.py']
    report['source_sha256']={p:hashlib.sha256((ROOT/p).read_bytes()).hexdigest() for p in paths}
    name='speech-expression-ui'+('-'+args.run_label if args.run_label!='initial' else '')
    (ROOT/('evals/reports/'+name+'-2026-10-18.json')).write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(dict(status='SUCCEEDED',cases=[dict(label=c['label'],click_to_blob_seconds=round(c['click_to_blob_seconds'],3),audio_seconds=c['result']['audio_seconds'],native_seconds=round(c['result']['elapsed_seconds'],3)) for c in cases],parallel_chat_seconds=parallel_chat,errors=errors),ensure_ascii=False))


if __name__=='__main__':main()
