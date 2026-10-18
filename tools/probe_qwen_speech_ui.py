"""Finite native Vulkan TTS UI/parallel-chat/restart check using temporary data."""
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
from jarvis_core.process_memory import process_memory
from tools.probe_workspace_ui import SyntheticChat
from jarvis_computer.browser import DriverJob
from server import create_server
from playwright.sync_api import sync_playwright, expect


def wait_exit(pid):
    # Windows can retain a terminated process object/counters while handles exist.
    # The signalled process handle, rather than readable memory, proves exit.
    import ctypes as C
    from ctypes import wintypes as W
    api=C.WinDLL('kernel32');api.OpenProcess.argtypes=[W.DWORD,W.BOOL,W.DWORD];api.OpenProcess.restype=W.HANDLE
    api.WaitForSingleObject.argtypes=[W.HANDLE,W.DWORD];api.WaitForSingleObject.restype=W.DWORD
    api.CloseHandle.argtypes=[W.HANDLE]
    handle=api.OpenProcess(0x100000,False,pid)
    if handle:
        try: assert api.WaitForSingleObject(handle,5000)==0,'owned inference process did not exit'
        finally: api.CloseHandle(handle)


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--emotion-tags',action='store_true');args=parser.parse_args()
    output=Path('H:/JarvisData/research/qwen-tts')/('emotion-tags' if args.emotion_tags else 'integration');output.mkdir(parents=True,exist_ok=True)
    errors=[];cases=[]
    with tempfile.TemporaryDirectory(prefix='jarvis-qwen-speech-ui-') as directory:
        core=CoreService(Path(directory)/'data');core.initialize(ROOT/'tests/fixtures/workspace')
        server=create_server(core=core,chat=SyntheticChat(),port=0);speech=server.modules.primary_speech
        thread=threading.Thread(target=server.serve_forever,kwargs={'poll_interval':.02},daemon=True);thread.start()
        try:
            with sync_playwright() as p:
                job=DriverJob(p)
                try:
                    browser=p.chromium.launch(channel='msedge',headless=True,chromium_sandbox=True)
                    page=browser.new_page(viewport={'width':1365,'height':1100});page.on('pageerror',lambda e:errors.append(str(e)))
                    page.goto('http://127.0.0.1:'+str(server.server_port)+'/settings#modules')
                    expect(page.locator('#primary-speech-start')).to_be_enabled()
                    assert not speech.snapshot()['owned']
                    assert not server.modules.fast_speech.snapshot()['owned'] and not server.modules.speech.snapshot()['owned']
                    start=time.monotonic();page.locator('#primary-speech-start').click()
                    expect(page.locator('#primary-speech-generate')).to_be_enabled(timeout=120000)
                    startup=time.monotonic()-start;loaded=speech.snapshot();native_pid=loaded['pid']
                    assert native_pid and native_pid!=loaded['broker_pid']
                    expect(page.locator('#primary-speech-voice option')).to_have_count(9)
                    for label,voice,emotion in [('happy','serena','happy'),('sad','serena','sad'),('vivian','vivian','neutral')]:
                        before=page.locator('#primary-speech-audio').get_attribute('src')
                        prefix={'happy':'[开心]','sad':'【悲伤】','vivian':'[neutral]'}[label] if args.emotion_tags else ''
                        page.locator('#primary-speech-text').fill(prefix+'今天下午我们会在这里见面。')
                        page.locator('#primary-speech-voice').select_option(voice);page.locator('#primary-speech-emotion').select_option('angry' if args.emotion_tags else emotion)
                        start=time.monotonic();page.locator('#primary-speech-generate').click()
                        if label=='happy':
                            deadline=time.monotonic()+2
                            while not speech.snapshot()['busy'] and time.monotonic()<deadline: time.sleep(.005)
                            assert speech.snapshot()['busy'],'real synthesis did not overlap chat check'
                            chat_start=time.monotonic()
                            response=page.evaluate("""async()=>{const nonce=document.querySelector('meta[name="jarvis-nonce"]').content;
                            const r=await fetch('/api/chat',{method:'POST',headers:{'Content-Type':'application/json','X-Jarvis-Nonce':nonce},body:JSON.stringify({message:'hello'})});return {status:r.status,body:await r.json()};}""")
                            chat_seconds=time.monotonic()-chat_start;assert response['status']==200
                        page.wait_for_function('old=>{const a=document.getElementById("primary-speech-audio");return a.src.startsWith("blob:")&&a.getAttribute("src")!==old}',arg=before,timeout=60000)
                        available=time.monotonic()-start;value=speech.snapshot();result=value['job']['result']
                        assert result['emotion']==emotion
                        if args.emotion_tags:
                            expect(page.locator('#primary-speech-result-info')).to_contain_text('应用表达：'+value['capabilities']['emotions'][emotion])
                        with page.expect_download() as downloaded:page.locator('#primary-speech-download').click()
                        artifact=output/f'ui-{label}.wav';downloaded.value.save_as(artifact)
                        cases.append(dict(label=label,source_text=prefix+'今天下午我们会在这里见面。',selector='angry' if args.emotion_tags else emotion,click_to_blob_seconds=available,result=result,memory=value['memory'],gpu_memory=value['gpu_memory'],
                            artifact=str(artifact),sha256=hashlib.sha256(artifact.read_bytes()).hexdigest()))
                    page.locator('#primary-speech-panel').screenshot(path=str(output/'primary-speech-panel.png'))
                    page.set_viewport_size({'width':480,'height':950})
                    page.locator('#primary-speech-panel').screenshot(path=str(output/'primary-speech-panel-narrow.png'))
                    if args.emotion_tags:
                        for invalid in ['[laugh]今天见面。','你好。【悲伤']:
                            page.locator('#primary-speech-text').fill(invalid);page.locator('#primary-speech-generate').click()
                            expect(page.locator('#primary-speech-error')).to_be_visible()
                            assert speech.snapshot()['state']=='ready' and speech.snapshot()['uses']==3
                    page.locator('#primary-speech-stop').click()
                    expect(page.locator('#primary-speech-status')).to_contain_text('未加载',timeout=10000);wait_exit(native_pid)
                    assert speech.snapshot()['gpu_memory'] is None
                    page.locator('#primary-speech-start').click()
                    expect(page.locator('#primary-speech-generate')).to_be_enabled(timeout=120000)
                    restarted_pid=speech.snapshot()['pid'];assert restarted_pid!=native_pid
                    # Real in-flight cancellation reclaims the native process; cancelled work is not replayed.
                    page.locator('#primary-speech-text').fill('我会在这里陪伴你，帮助你处理今天的工作。'*5)
                    page.locator('#primary-speech-generate').click()
                    deadline=time.monotonic()+2
                    while not speech.snapshot()['busy'] and time.monotonic()<deadline: time.sleep(.005)
                    assert speech.snapshot()['busy']
                    page.locator('#primary-speech-stop').click()
                    expect(page.locator('#primary-speech-status')).to_contain_text('未加载',timeout=10000);wait_exit(restarted_pid)
                    stopped=speech.snapshot();assert stopped['job']['status']=='CANCELLED' and stopped['uses']==3
                    assert not server.modules.fast_speech.snapshot()['owned'] and not server.modules.speech.snapshot()['owned']
                    assert not errors,errors;browser.close()
                finally:job.close()
        finally:server.shutdown();server.server_close();thread.join(3)
    report=dict(status='SUCCEEDED',source_version=__version__,backend='speech.cpp 0.8.10 / Qwen3-TTS 1.7B Q5_K / Vulkan0',
        startup_click_to_ready_seconds=startup,loaded=loaded,cases=cases,parallel_synthetic_chat_seconds=chat_seconds,
        restart_and_inflight_stop='verified; both owned native PIDs exited; no replay; backup models stayed stopped',browser_errors=errors,
        user_listening_acceptance='2026-10-18: 用户确认此前 Serena 开心/悲伤/生气样本自然、情绪明显，可以作为主力。',
        limits='Complete WAV delivery; native first PCM is not speaker onset. Synthetic local chat proves lane independence, not cloud/LLM latency. Only finite voices and utterances tested.')
    paths=['runtime/node-host/jarvis_core/'+n for n in ['speech.py','qwen_speech.py','qwen_speech_contract.py','qwen_protocol.py','gpu_memory.py']]
    paths+=['adapters/speech/qwen/worker.py','config/model-profiles/qwen-tts.json','apps/web/speech.js','apps/web/speech_routes.py','apps/web/admin.html']
    report['source_sha256']={p:hashlib.sha256((ROOT/p).read_bytes()).hexdigest() for p in paths}
    report['emotion_tag_mode']=args.emotion_tags
    report['source_sha256']['tools/probe_qwen_speech_ui.py']=hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    name='qwen-emotion-tags-ui' if args.emotion_tags else 'qwen-speech-ui'
    (ROOT/('evals/reports/'+name+'-2026-10-18.json')).write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(dict(status=report['status'],startup_seconds=startup,cases=[(c['label'],round(c['click_to_blob_seconds'],3)) for c in cases],
        parallel_synthetic_chat_seconds=chat_seconds,memory=cases[-1]['memory'],gpu_memory=cases[-1]['gpu_memory'],errors=errors),ensure_ascii=False))


if __name__=='__main__':main()
