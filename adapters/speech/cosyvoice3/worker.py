"""Pinned native CosyVoice3 CPU inference in a separate, explicitly owned process."""
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import argparse
import gc
import json
import logging
import os
import secrets
import sys
import threading
import time
import traceback

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / 'runtime/node-host'))
from jarvis_core.speech_contract import EMOTIONS, SpeechError, reference_info
from jarvis_core.policy import safe_path
from jarvis_core.process_memory import process_memory as memory


def load_model(cfg):
    for name in ('HF_HUB_OFFLINE', 'TRANSFORMERS_OFFLINE', 'HF_HUB_DISABLE_TELEMETRY'): os.environ[name] = '1'
    os.environ['CUDA_VISIBLE_DEVICES'] = ''
    cache = safe_path(Path(cfg['source_root']).parent / 'cache', must_exist=False)
    cache.mkdir(parents=True, exist_ok=True)
    for name, sub in (('HF_HOME','huggingface'),('MODELSCOPE_CACHE','modelscope'),('MPLCONFIGDIR','matplotlib'),('NUMBA_CACHE_DIR','numba')):
        directory = safe_path(cache / sub, must_exist=False); directory.mkdir(parents=True,exist_ok=True)
        os.environ[name] = str(directory)
    os.environ['OMP_NUM_THREADS'] = os.environ['MKL_NUM_THREADS'] = str(cfg['threads'])
    source = safe_path(cfg['source_root'], directory=True); base = safe_path(cfg['model_root'], directory=True)
    sys.path[:0] = [str(source), str(source / 'third_party/Matcha-TTS')]
    import torch
    torch.set_num_threads(cfg['threads']); torch.set_num_interop_threads(1)
    if torch.cuda.is_available(): raise RuntimeError('This profile requires CPU-only PyTorch')
    from hyperpyyaml import load_hyperpyyaml
    from cosyvoice.cli.cosyvoice import CosyVoice3
    from cosyvoice.cli.frontend import CosyVoiceFrontEnd
    from cosyvoice.cli.model import CosyVoice3Model
    with (base / 'jarvis-inference.yaml').open(encoding='utf-8') as stream:
        settings = load_hyperpyyaml(stream, overrides={'qwen_pretrain_path': str(base / 'CosyVoice-BlankEN')})
    # Native inference methods are preserved; only unused training YAML nodes are omitted.
    model = CosyVoice3.__new__(CosyVoice3)
    model.model_dir = str(base); model.fp16 = False; model.sample_rate = settings['sample_rate']
    model.frontend = CosyVoiceFrontEnd(settings['get_tokenizer'], settings['feat_extractor'],
        str(base / 'campplus.onnx'), str(base / 'speech_tokenizer_v3.onnx'), '', settings['allowed_special'])
    model.model = CosyVoice3Model(settings['llm'], settings['flow'], settings['hift'], False)
    model.model.load(str(base / 'llm.pt'), str(base / 'flow.pt'), str(base / 'hift.pt'))
    del settings
    gc.collect()
    return model


class Inference:
    def __init__(self, cfg, data):
        started = time.monotonic(); self.cfg = cfg; self.data = data
        self.model = load_model(cfg); self.load_seconds = time.monotonic() - started
        self.loaded_memory = memory(); self.lock = threading.Lock(); self.count = 0

    def synthesize(self, payload):
        if set(payload) != {'id', 'text', 'mode', 'emotion', 'reference_text', 'reference_path'}:
            raise SpeechError('Invalid worker payload')
        ident = payload['id']
        if not isinstance(ident, str) or len(ident) != 32 or any(c not in '0123456789abcdef' for c in ident):
            raise SpeechError('Invalid output identity')
        if not isinstance(payload['text'], str) or not 1 <= len(payload['text']) <= self.cfg['max_text_chars']:
            raise SpeechError('Text exceeds inference bound')
        if payload['emotion'] not in EMOTIONS or payload['mode'] not in {'clone', 'instruct', 'cross_lingual'}:
            raise SpeechError('Invalid inference mode')
        fixture = Path(self.cfg['source_root']) / 'asset/zero_shot_prompt.wav'
        ref = safe_path(payload['reference_path'], directory=False)
        if ref != fixture and not ref.is_relative_to(self.data / 'references'): raise SpeechError('Invalid reference path')
        import torch
        import soundfile as sf
        if ref == fixture:
            # The fixed publisher fixture is IEEE-float WAV, not a user upload.
            info = sf.info(str(ref))
            if info.channels not in (1,2) or not 8000 <= info.samplerate <= 48000 or not 1 <= info.duration <= self.cfg['max_reference_seconds']:
                raise SpeechError('Invalid publisher reference fixture')
        else:
            reference_info(ref.read_bytes(), self.cfg['max_reference_seconds'])
        mode = payload['mode']; started = time.monotonic(); cpu_started = time.process_time()
        with self.lock, torch.inference_mode():
            if mode == 'clone':
                transcript = payload['reference_text'] or '希望你以后能够做的比我还好呦。'
                generator = self.model.inference_zero_shot(payload['text'],
                    'You are a helpful assistant.<|endofprompt|>' + transcript, str(ref), stream=True)
            elif mode == 'instruct':
                instruction = 'You are a helpful assistant. ' + EMOTIONS[payload['emotion']] + '<|endofprompt|>'
                generator = self.model.inference_instruct2(payload['text'], instruction, str(ref), stream=True)
            else:
                generator = self.model.inference_cross_lingual('You are a helpful assistant.<|endofprompt|>' + payload['text'], str(ref), stream=True)
            pieces = []; total = 0; first = None
            for piece in generator:
                samples = piece['tts_speech'].detach().cpu().reshape(-1)
                if first is None: first = time.monotonic() - started
                total += samples.numel()
                if total > self.cfg['max_output_seconds'] * self.model.sample_rate:
                    raise SpeechError('Generated audio exceeds duration bound')
                pieces.append(samples)
            if not pieces or not total: raise SpeechError('No speech produced')
            audio = torch.cat(pieces).numpy()
            output = safe_path(self.data / 'audio' / (ident + '.wav'), must_exist=False)
            temporary = output.with_suffix('.partial')
            sf.write(str(temporary), audio, self.model.sample_rate, subtype='PCM_16', format='WAV')
            os.replace(temporary, output); self.count += 1
        return {'id': ident, 'sample_rate_hz': self.model.sample_rate, 'audio_seconds': total / self.model.sample_rate,
                'elapsed_seconds': time.monotonic() - started, 'cpu_seconds': time.process_time() - cpu_started,
                'first_internal_chunk_seconds': first, 'memory': memory(), 'mode': mode, 'emotion': payload['emotion']}


def main():
    parser = argparse.ArgumentParser(); parser.add_argument('--config', required=True); parser.add_argument('--data-dir', required=True)
    parser.add_argument('--ready-file', required=True); parser.add_argument('--token', required=True)
    args = parser.parse_args(); cfg = json.loads(Path(args.config).read_text(encoding='utf-8'))
    data = safe_path(args.data_dir, directory=True)
    log = (data / 'worker.log').open('a', encoding='utf-8', buffering=1)
    sys.stdout = sys.stderr = log; logging.basicConfig(stream=log, level=logging.INFO)
    try: engine = Inference(cfg, data)
    except Exception:
        traceback.print_exc(file=log); raise

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args): pass
        def send(self, status, value):
            body = json.dumps(value).encode('utf-8'); self.send_response(status)
            self.send_header('Content-Type', 'application/json'); self.send_header('Content-Length', str(len(body)))
            self.end_headers(); self.wfile.write(body)
        def authorized(self): return secrets.compare_digest(self.headers.get('X-Component-Token', ''), args.token)
        def do_GET(self):
            if not self.authorized(): self.send(403, {'error': 'unauthorized'}); return
            if self.path != '/health': self.send(404, {'error': 'not_found'}); return
            self.send(200, {'ready': True, 'pid': os.getpid(), 'device': 'cpu', 'load_seconds': engine.load_seconds,
                'memory': memory(), 'loaded_memory': engine.loaded_memory, 'uses': engine.count,
                'text_frontend': engine.model.frontend.text_frontend or 'basic'})
        def do_POST(self):
            if not self.authorized(): self.send(403, {'error': 'unauthorized'}); return
            if self.path != '/synthesize': self.send(404, {'error': 'not_found'}); return
            try:
                size = int(self.headers.get('Content-Length', '0'))
                if not 0 < size <= 16384: raise SpeechError('Invalid worker request size')
                payload = json.loads(self.rfile.read(size))
                self.send(200, engine.synthesize(payload))
            except Exception:
                traceback.print_exc(file=log); self.send(500, {'error': 'inference_failed'})

    server = ThreadingHTTPServer(('127.0.0.1', 0), Handler); server.daemon_threads = True
    ready = Path(args.ready_file); temporary = ready.with_suffix('.tmp')
    temporary.write_text(json.dumps({'pid': os.getpid(), 'port': server.server_port}), encoding='utf-8')
    os.replace(temporary, ready)
    server.serve_forever(poll_interval=.25)


if __name__ == '__main__': main()
