"""Pinned Qwen3-TTS 1.7B CustomVoice Q5_K evaluation, streaming on local Vulkan/CPU.

No fetching at runtime, no HTTP service, no microphone or production model route.
"""
import argparse
import base64
import hashlib
import json
from pathlib import Path
import queue
import subprocess
import sys
import threading
import time
import wave

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'runtime/node-host'))
from jarvis_core.process_memory import process_memory
from tts_eval_resources import GpuMemory


def sha(path):
    with path.open('rb') as f:return hashlib.file_digest(f,'sha256').hexdigest()


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--device',choices=['Vulkan0','cpu'],default='Vulkan0')
    parser.add_argument('--threads',type=int,choices=[4,8],default=4);args=parser.parse_args()
    label=args.device if args.threads==4 else args.device+str(args.threads)
    cfg=json.loads((ROOT/'config/model-profiles/qwen-tts-evaluation.json').read_text(encoding='utf-8'))
    for row in cfg['assets']:
        p=Path(row['local'])
        if p.stat().st_size!=row['size_bytes'] or sha(p)!=row['sha256']:raise ValueError('Changed evaluation artifact')
    exe=Path(cfg['executable']);runtime=exe.parent
    for row in cfg['runtime_files']:
        if sha(runtime/row['path'])!=row['sha256']:raise ValueError('Changed executable/dependency')
    model=Path(cfg['assets'][1]['local']);out=Path('H:/JarvisData/research/qwen-tts');out.mkdir(parents=True,exist_ok=True)
    log=(out/(label+'-worker.log')).open('w',encoding='utf-8')
    argv=[str(exe),'worker',str(model),'--device',args.device,'--threads',str(args.threads),'--voice','serena','--language','zh','--max-seconds','12','--seed','42']
    started=time.monotonic();worker=subprocess.Popen(argv,stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=log,text=True,
        encoding='utf-8',bufsize=1,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
    messages=queue.Queue(maxsize=512);finished=threading.Event();resources=[];gpu=GpuMemory(worker.pid)
    def read():
        try:
            while line:=worker.stdout.readline(65536):messages.put(json.loads(line))
        except Exception as exc:messages.put({'type':'reader_error','message':type(exc).__name__})
        finally:messages.put({'type':'eof'})
    def sample():
        while not finished.is_set():
            resources.append({'seconds':time.monotonic()-started,'memory':process_memory(worker.pid),'gpu':gpu.sample()})
            finished.wait(.15)
    threading.Thread(target=read,daemon=True).start();sampler=threading.Thread(target=sample,daemon=True);sampler.start()
    report=dict(status='RUNNING',model=cfg['model'],backend=cfg['backend'],device=args.device,threads=args.threads,cases=[],paid_calls=0,
                limits='Native worker first PCM; not browser/speaker or complete conversation. WDDM allocation samples are not physical pools to add to process RAM.')
    try:
        ready=messages.get(timeout=180)
        if ready.get('type')!='ready':raise ValueError('Worker did not become ready: '+json.dumps(ready))
        report.update(ready=ready,startup_seconds=time.monotonic()-started,loaded_memory=process_memory(worker.pid),loaded_gpu=gpu.sample())
        print('READY',json.dumps({'startup_seconds':report['startup_seconds'],'memory':report['loaded_memory'],'gpu':report['loaded_gpu']}),flush=True)
        texts=[('neutral','用平静自然的语气说话。','今天下午我们会在这里见面。'),
               ('happy','用非常开心、兴奋的语气说话。','今天下午我们会在这里见面。'),
               ('sad','用明显悲伤、低落的语气说话。','今天下午我们会在这里见面。'),
               ('angry','用明显生气、愤怒的语气说话。','今天下午我们会在这里见面。'),
               ('soft','轻声、温柔地说话。','我在，有什么可以帮你？'),
               ('mixed','自然地说话。','你好，我是贾维斯。Hello, how can I help you today?')]
        for name,instruction,text in texts:
            tick=time.monotonic();first=None;buffered=None;pieces=[];chunk_times=[]
            worker.stdin.write(json.dumps(dict(type='synthesize',id=name,text=text,voice='serena',language='zh',instructions=instruction,seed=42,max_seconds=12),ensure_ascii=False)+'\n');worker.stdin.flush()
            while True:
                message=messages.get(timeout=60)
                if message.get('type')=='progress':continue
                if message.get('id')!=name:raise ValueError('Unexpected worker response: '+str(message.get('type')))
                if message['type']=='chunk':
                    raw=base64.b64decode(message['pcm'],validate=True)
                    if first is None:first=time.monotonic()-tick
                    pieces.append(raw);chunk_times.append(time.monotonic()-tick)
                    if buffered is None and sum(map(len,pieces))>=9600:buffered=time.monotonic()-tick
                    if sum(map(len,pieces))>24000*2*12+48000:raise ValueError('Output exceeds bound')
                elif message['type']=='end':
                    if message.get('stop')!='complete':raise ValueError('Output hit duration/model bound')
                    break
                else:raise ValueError('Worker refused synthesis: '+json.dumps(message))
            elapsed=time.monotonic()-tick;audio=b''.join(pieces);duration=len(audio)/48000
            if not duration or len(audio)//2!=message['samples']:raise ValueError('Missing/mismatched PCM')
            path=out/(label+'-'+name+'.wav')
            with wave.open(str(path),'wb') as wav:wav.setnchannels(1);wav.setsampwidth(2);wav.setframerate(24000);wav.writeframes(audio)
            row=dict(name=name,text=text,instructions=instruction,first_pcm_seconds=first,first_200ms_pcm_seconds=buffered,elapsed_seconds=elapsed,
                     audio_seconds=duration,rtf=elapsed/duration,chunk_times=chunk_times,memory=process_memory(worker.pid),gpu=gpu.sample(),
                     artifact=str(path),sha256=sha(path))
            report['cases'].append(row);print('CASE',name,round(first,3),round(elapsed,3),round(duration,3),row['gpu'],flush=True)
        report.update(status='SUCCEEDED',final_memory=process_memory(worker.pid),final_gpu=gpu.sample())
    except Exception as exc:
        report.update(status='FAILED',error={'type':type(exc).__name__,'message':str(exc)})
        raise
    finally:
        finished.set();sampler.join(3);gpu.close();worker.stdin.close()
        try:worker.wait(timeout=5)
        except subprocess.TimeoutExpired:worker.terminate();worker.wait(timeout=5)
        log.close();report['resource_samples']=resources
        report['source_sha256']=sha(Path(__file__));report['profile_sha256']=sha(ROOT/'config/model-profiles/qwen-tts-evaluation.json')
        (ROOT/('evals/reports/qwen-tts-'+label.lower()+'-2026-10-18.json')).write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')


if __name__=='__main__':main()
