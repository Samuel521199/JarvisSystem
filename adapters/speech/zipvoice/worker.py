"""Small CPU-only ZipVoice-Distill worker; bounded short utterances, no downloads."""
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import argparse
import json
import os
import secrets
import sys
import threading
import time
import traceback
import wave

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / 'runtime/node-host'))
from jarvis_core.policy import safe_path
from jarvis_core.process_memory import process_memory as memory
from jarvis_core.speech_contract import SpeechError, reference_info


class Inference:
    def __init__(self, cfg, data):
        self.cfg, self.data = cfg, data
        os.environ['OMP_NUM_THREADS'] = os.environ['MKL_NUM_THREADS'] = str(cfg['threads'])
        import sherpa_onnx as s
        base = Path(cfg['model_root']); model = base / cfg['model_directory']
        started = time.monotonic()
        config = s.OfflineTtsConfig(model=s.OfflineTtsModelConfig(zipvoice=s.OfflineTtsZipvoiceModelConfig(
            encoder=str(model / 'encoder.int8.onnx'), decoder=str(model / 'decoder.int8.onnx'),
            vocoder=str(base / 'vocos_24khz.onnx'), tokens=str(model / 'tokens.txt'),
            lexicon=str(model / 'lexicon.txt'), data_dir=str(model / 'espeak-ng-data')),
            num_threads=cfg['threads'], provider='cpu'), max_num_sentences=1)
        if not config.validate(): raise SpeechError('Invalid fast TTS configuration')
        self.model = s.OfflineTts(config); self.load_seconds = time.monotonic()-started
        self.loaded_memory = memory(); self.count = 0; self.lock = threading.Lock()

    def synthesize(self, payload):
        import numpy as np
        if set(payload) != {'id','text','mode','emotion','reference_text','reference_path'}:
            raise SpeechError('Invalid worker payload')
        ident = payload['id']; text = payload['text']
        if not isinstance(ident,str) or len(ident)!=32 or any(c not in '0123456789abcdef' for c in ident):
            raise SpeechError('Invalid output identity')
        if not isinstance(text,str) or not 1 <= len(text.strip()) <= self.cfg['max_text_chars']:
            raise SpeechError('Invalid text length')
        if payload['mode'] != 'clone' or payload['emotion'] != 'neutral': raise SpeechError('Unsupported expression mode')
        fixture = Path(self.cfg['model_root']) / self.cfg['reference_file']
        reference = safe_path(payload['reference_path'], directory=False)
        if reference != fixture and not reference.is_relative_to(self.data / 'references'):
            raise SpeechError('Invalid reference path')
        raw = reference.read_bytes(); reference_info(raw, self.cfg['max_reference_seconds'])
        with wave.open(str(reference), 'rb') as wav:
            rate = wav.getframerate(); channels = wav.getnchannels()
            samples = np.frombuffer(wav.readframes(wav.getnframes()), dtype='<i2').astype(np.float32)/32768
        if channels == 2: samples = samples.reshape(-1,2).mean(axis=1)
        transcript = payload['reference_text'] or (self.cfg['reference_text'] if reference == fixture else '')
        if not isinstance(transcript,str) or not 1 <= len(transcript) <= 500: raise SpeechError('Reference transcript required')
        started = time.monotonic(); cpu_started = time.process_time()
        with self.lock:
            audio = self.model.generate(text, transcript, samples.tolist(), rate, speed=1.0, num_steps=self.cfg['num_steps'])
            output_samples = np.asarray(audio.samples)
            if not 0 < len(output_samples) <= self.cfg['max_output_seconds'] * audio.sample_rate or not np.isfinite(output_samples).all():
                raise SpeechError('Invalid or oversized speech output')
            output = safe_path(self.data / 'audio' / (ident+'.wav'), must_exist=False)
            temporary = output.with_suffix('.partial')
            with wave.open(str(temporary),'wb') as wav:
                wav.setnchannels(1); wav.setsampwidth(2); wav.setframerate(audio.sample_rate)
                wav.writeframes((np.clip(output_samples,-1,1)*32767).astype('<i2').tobytes())
            os.replace(temporary,output); self.count += 1
        return {'id':ident, 'sample_rate_hz':audio.sample_rate, 'audio_seconds':len(output_samples)/audio.sample_rate,
                'elapsed_seconds':time.monotonic()-started, 'cpu_seconds':time.process_time()-cpu_started,
                'memory':memory(), 'mode':'clone', 'emotion':'neutral', 'num_steps':self.cfg['num_steps']}


def main():
    parser = argparse.ArgumentParser()
    for name in ('config','data-dir','ready-file','token'): parser.add_argument('--'+name,required=True)
    args = parser.parse_args(); cfg = json.loads(Path(args.config).read_text(encoding='utf-8'))
    data = safe_path(args.data_dir, directory=True)
    log = (data / 'worker.log').open('a',encoding='utf-8',buffering=1); sys.stdout = sys.stderr = log
    engine = Inference(cfg,data)

    class Handler(BaseHTTPRequestHandler):
        def log_message(self,*args): pass
        def send(self,status,value):
            body = json.dumps(value).encode('utf-8'); self.send_response(status)
            self.send_header('Content-Type','application/json'); self.send_header('Content-Length',str(len(body)))
            self.end_headers(); self.wfile.write(body)
        def authorized(self): return secrets.compare_digest(self.headers.get('X-Component-Token',''),args.token)
        def do_GET(self):
            if not self.authorized(): self.send(403,{'error':'unauthorized'}); return
            if self.path != '/health': self.send(404,{'error':'not_found'}); return
            self.send(200,{'ready':True,'pid':os.getpid(),'device':'cpu','load_seconds':engine.load_seconds,
                'memory':memory(),'loaded_memory':engine.loaded_memory,'uses':engine.count,'text_frontend':'sherpa-zipvoice'})
        def do_POST(self):
            if not self.authorized(): self.send(403,{'error':'unauthorized'}); return
            if self.path != '/synthesize': self.send(404,{'error':'not_found'}); return
            try:
                size = int(self.headers.get('Content-Length','0'))
                if not 0 < size <= 16384: raise SpeechError('Invalid request size')
                self.send(200,engine.synthesize(json.loads(self.rfile.read(size))))
            except Exception:
                traceback.print_exc(file=log); self.send(500,{'error':'inference_failed'})
    server = ThreadingHTTPServer(('127.0.0.1',0),Handler); server.daemon_threads = True
    ready = Path(args.ready_file); temporary = ready.with_suffix('.tmp')
    temporary.write_text(json.dumps({'pid':os.getpid(),'port':server.server_port}),encoding='utf-8')
    os.replace(temporary,ready); server.serve_forever(poll_interval=.25)


if __name__ == '__main__': main()
