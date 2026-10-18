"""Loopback broker for a pinned native worker; descendants remain in the host Job."""
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import argparse
import json
import os
import secrets
import subprocess
import sys
import threading
import time
import traceback
import wave

ROOT=Path(__file__).resolve().parents[3]
sys.path.insert(0,str(ROOT/'runtime/node-host'))
from jarvis_core.policy import safe_path
from jarvis_core.qwen_protocol import NativeProtocol
from jarvis_core.qwen_speech_contract import validate, expression_plan
from jarvis_core.speech_audio import SpeechAudio, RATE
from jarvis_core.speech_contract import SpeechError


class Inference:
    def __init__(self,cfg,data,log):
        self.cfg,self.data=cfg,data; self.lock=threading.Lock(); self.count=0
        argv=[str(Path(cfg['runtime_root'])/'speech.exe'),'worker',str(Path(cfg['model_root'])/cfg['model_file']),
              '--device',cfg['device'],'--threads',str(cfg['threads']),'--voice','serena','--language','zh',
              '--max-seconds',str(cfg['max_output_seconds']),'--seed','42']
        started=time.monotonic()
        self.process=subprocess.Popen(argv,stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=log,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name=='nt' else 0)
        self.protocol=NativeProtocol(self.process.stdout)
        ready=self.protocol.next(started+cfg['startup_timeout_seconds']-5)
        if ready.get('type')!='ready' or ready.get('protocol')!=3 or ready.get('version')!=cfg['backend_version']:
            raise SpeechError('原生语音版本或协议不匹配。')
        self.load_seconds=time.monotonic()-started
        def watch():
            self.process.wait()
            os._exit(1)  # Let the owning host reclaim the failed broker and its Job.
        threading.Thread(target=watch,name='qwen-native-lifetime',daemon=True).start()

    def synthesize(self,payload):
        if not isinstance(payload,dict) or set(payload)-{'id','text','voice','emotion','language','direction'}: raise SpeechError('Invalid fields')
        ident=payload['id']
        if not isinstance(ident,str) or len(ident)!=32 or any(c not in '0123456789abcdef' for c in ident): raise SpeechError('Invalid identity')
        parsed=validate(dict(action='synthesize',**{k:v for k,v in payload.items() if k!='id'}),self.cfg['max_text_chars'])
        plan=expression_plan(parsed)
        with self.lock:
            started=time.monotonic();deadline=started+self.cfg['request_timeout_seconds']-2
            audio=SpeechAudio(self.cfg['max_output_seconds']);first=None;reserved_pause=plan['pause_ms']*RATE//1000
            speech_rows=[r for r in plan['segments'] if r['type']=='speech']
            for index,row in enumerate(plan['segments']):
                if time.monotonic()>=deadline:raise SpeechError('分段语音整体请求超时。')
                if row['type']=='pause':
                    audio.pause(row['milliseconds']);reserved_pause-=row['milliseconds']*RATE//1000;continue
                remaining=(audio.limit-len(audio.pcm)//2-reserved_pause)//RATE
                if remaining<1:raise SpeechError('剩余输出时长不足；请缩短正文或停顿。')
                native_id=ident+'-'+str(index);tick=time.monotonic()
                request=dict(type='synthesize',id=native_id,text=row['text'],voice=parsed['voice'],language=parsed['language'],
                    instructions=row['instructions'],seed=42,max_seconds=remaining)
                self.process.stdin.write((json.dumps(request,ensure_ascii=False)+'\n').encode('utf-8'));self.process.stdin.flush()
                pcm,native_first=self.protocol.audio(native_id,remaining,deadline-time.monotonic())
                if first is None:first=tick-started+native_first
                info={k:v for k,v in row.items() if k!='instructions'}
                audio.speech(pcm,info,fade=len(speech_rows)>1)
            pcm=bytes(audio.pcm)
            output=safe_path(self.data/'audio'/(ident+'.wav'),must_exist=False); temporary=output.with_suffix('.partial')
            try:
                with wave.open(str(temporary),'wb') as wav:
                    wav.setnchannels(1); wav.setsampwidth(2); wav.setframerate(24000); wav.writeframes(pcm)
                os.replace(temporary,output)
            finally:
                if temporary.exists(): temporary.unlink()
            self.count+=1
            expressions=[r['expression'] for r in speech_rows]
            return dict(id=ident,sample_rate_hz=RATE,audio_seconds=len(pcm)/(RATE*2),elapsed_seconds=time.monotonic()-started,
                        first_pcm_seconds=first,voice=parsed['voice'],emotion=speech_rows[0]['emotion'],language=parsed['language'],
                        expression=' → '.join(expressions),segments=audio.timeline,speech_segments=plan['speech_segments'],
                        pause_ms=plan['pause_ms'],warnings=plan['warnings'],direction=parsed['direction'],
                        join_method='5ms_edge_fade_without_trimming' if len(speech_rows)>1 else 'single_utterance')


def main():
    parser=argparse.ArgumentParser()
    for name in ('config','data-dir','ready-file','token'): parser.add_argument('--'+name,required=True)
    args=parser.parse_args(); cfg=json.loads(Path(args.config).read_text(encoding='utf-8'))
    data=safe_path(args.data_dir,directory=True)
    log=(data/'worker.log').open('a',encoding='utf-8',buffering=1); sys.stdout=sys.stderr=log
    engine=Inference(cfg,data,log)
    class Handler(BaseHTTPRequestHandler):
        def log_message(self,*args): pass
        def send(self,status,value):
            body=json.dumps(value).encode(); self.send_response(status); self.send_header('Content-Type','application/json')
            self.send_header('Content-Length',str(len(body))); self.end_headers(); self.wfile.write(body)
        def authorized(self): return secrets.compare_digest(self.headers.get('X-Component-Token',''),args.token)
        def do_GET(self):
            if not self.authorized(): self.send(403,{'error':'unauthorized'}); return
            if self.path!='/health': self.send(404,{'error':'not_found'}); return
            self.send(200,dict(ready=engine.process.poll() is None,pid=os.getpid(),inference_pid=engine.process.pid,
                protocol=3,device=cfg['device'],load_seconds=engine.load_seconds,uses=engine.count))
        def do_POST(self):
            if not self.authorized(): self.send(403,{'error':'unauthorized'}); return
            if self.path!='/synthesize': self.send(404,{'error':'not_found'}); return
            try:
                size=int(self.headers.get('Content-Length','0'))
                if not 0<size<=16384: raise SpeechError('Invalid request size')
                self.send(200,engine.synthesize(json.loads(self.rfile.read(size))))
            except Exception:
                traceback.print_exc(file=log); self.send(500,{'error':'inference_failed'})
    server=ThreadingHTTPServer(('127.0.0.1',0),Handler); server.daemon_threads=True
    ready=Path(args.ready_file); temporary=ready.with_suffix('.tmp')
    temporary.write_text(json.dumps(dict(pid=os.getpid(),port=server.server_port)),encoding='utf-8')
    os.replace(temporary,ready); server.serve_forever(poll_interval=.25)


if __name__=='__main__': main()
