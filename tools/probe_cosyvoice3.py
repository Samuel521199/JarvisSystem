"""Explicit native component probe: publisher reference only, no microphone/cloud."""
from pathlib import Path
import argparse
import hashlib
import json
import shutil
import sys
import tempfile
import threading
import time
import httpx

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / 'runtime/node-host'), str(ROOT)]
from jarvis_core import __version__
from jarvis_core.service import CoreService
from jarvis_core.speech import SpeechService


def wait(service, seconds, debug_log=None):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        value = service.snapshot()
        if not value['busy']:
            if value['job']['status'] != 'SUCCEEDED':
                if debug_log and (service.data/'worker.log').exists():shutil.copyfile(service.data/'worker.log',debug_log)
                raise RuntimeError(value['job'].get('message', 'Probe failed'))
            return value
        time.sleep(.2)
    service.stop()
    if debug_log and (service.data/'worker.log').exists():shutil.copyfile(service.data/'worker.log',debug_log)
    raise TimeoutError('Native probe exceeded deadline')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--report', type=Path, default=ROOT / 'evals/reports/cosyvoice3-native-2026-10-18.json')
    parser.add_argument('--output', type=Path, default=Path('H:/JarvisData/research/cosyvoice3'))
    parser.add_argument('--case', choices=('all', 'clone', 'happy', 'english'), default='all')
    args = parser.parse_args(); args.output.mkdir(parents=True, exist_ok=True)
    report = {'schema_version':1,'source_version':__version__,'status':'RUNNING','device':'cpu','scope':'Publisher reference; file synthesis, not microphone/owner recognition/full duplex or perceptual quality validation.',
              'paid_calls':0,'cases':[],'limits':['Native CPU process is separate from the web/chat environment.','First internal chunk is not browser playback latency.']}
    core = None; speech = None; server = None; thread = None
    temporary = tempfile.TemporaryDirectory(prefix="jarvis-cosyvoice3-native-")
    try:
        directory = temporary.name
        core = CoreService(Path(directory) / 'data'); core.initialize(ROOT / 'tests/fixtures/workspace')
        sys.path.insert(0,str(ROOT/'apps/web'))
        from server import create_server
        from tools.probe_workspace_ui import SyntheticChat
        server=create_server(core=core,chat=SyntheticChat(),port=0);speech=server.modules.speech
        thread=threading.Thread(target=server.serve_forever,kwargs={'poll_interval':.02},daemon=True);thread.start()
        origin='http://127.0.0.1:'+str(server.server_port)
        started = time.monotonic(); speech.submit({'action':'start'})
        loaded = wait(speech,420,args.output/'worker.log'); report['startup_wall_seconds'] = time.monotonic()-started
        report['loaded'] = loaded['job']['result']['load']
        print('LOADED ' + json.dumps(report['loaded']),flush=True)
        cases = [('clone',{'mode':'clone','emotion':'neutral','text':'你好，我是贾维斯。'}),
                 ('happy',{'mode':'instruct','emotion':'happy','text':'很高兴再次见到你！'}),
                 ('english',{'mode':'cross_lingual','emotion':'neutral','text':'Hello, I am Jarvis.'})]
        for name, payload in cases:
            if args.case != 'all' and args.case != name: continue
            speech.submit({'action':'synthesize',**payload})
            samples=[]
            with httpx.Client(timeout=5,trust_env=False) as client:
                for _ in range(3):
                    active=speech.snapshot()['busy'];tick=time.monotonic()
                    response=client.post(origin+'/api/chat',json={'message':'语音并行检查'},headers={'Origin':origin,'X-Jarvis-Nonce':server.nonce})
                    samples.append({'tts_busy_before_request':active,'http_status':response.status_code,'elapsed_seconds':time.monotonic()-tick,'chat_backend':'synthetic, no cloud'})
                    if response.status_code!=200:raise RuntimeError('Concurrent chat HTTP failed')
                    time.sleep(.2)
            value = wait(speech,330,args.output/'worker.log')
            result = value['job']['result']; content = speech.audio(result['id'])
            output = args.output / (name + '.wav'); output.write_bytes(content)
            result.update(name=name,artifact=str(output),sha256=hashlib.sha256(content).hexdigest(),bytes=len(content),parallel_http=samples)
            report['cases'].append(result); print('SYNTHESIZED '+json.dumps(result,ensure_ascii=False),flush=True)
        report['before_stop'] = speech.snapshot(); speech.stop(); report['after_stop'] = speech.snapshot()
        report['status'] = 'SUCCEEDED'
    except Exception as exc:
        report['status'] = 'FAILED'; report['error'] = {'type':type(exc).__name__,'message':str(exc)}
        if speech and (speech.data/'worker.log').exists():
            shutil.copyfile(speech.data/'worker.log',args.output/'worker.log')
        raise
    finally:
        if server:server.shutdown();server.server_close()
        if thread:thread.join(3)
        if speech:speech.close()
        temporary.cleanup()
        args.report.parent.mkdir(parents=True,exist_ok=True)
        report['source_sha256'] = {str(p.relative_to(ROOT)).replace('\\','/'):hashlib.sha256(p.read_bytes()).hexdigest() for p in (
            ROOT/'runtime/node-host/jarvis_core/speech.py',ROOT/'adapters/speech/cosyvoice3/worker.py',ROOT/'config/model-profiles/cosyvoice3.json')}
        args.report.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')


if __name__ == '__main__': main()
