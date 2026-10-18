"""Pinned, file-only CPU TTS comparison; never opens a microphone or changes routing.

Use --download explicitly to fetch the three reviewed publisher artifacts (310 MB).
Models live outside the source tree. Each benchmark uses a fresh, finite process.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tarfile
import tempfile
import time
import urllib.request
import wave

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'runtime/node-host'))
from manage_models import CheckedRedirect, destination_lock, download_file, relative_path, target_path, validate_url, verify_file

ASSETS = [
    ('kokoro', 'tts-models', 'kokoro-int8-multi-lang-v1_1.tar.bz2', 147031220,
     'a1e94694776049035c4f2c6529f003aaece993c76aae9a78995831c3c4dcafc6'),
    ('zipvoice', 'tts-models', 'sherpa-onnx-zipvoice-distill-int8-zh-en-emilia.tar.bz2', 109162785,
     '77219c8b40f4ee8d73a7f902305ff6c1128ef9b54461c41b4ca6ed890b6c2803'),
    ('vocos', 'vocoder-models', 'vocos_24khz.onnx', 54157409,
     'bcb3b970e384161c4d634f0bb9e999ff1c471b34c9bc0b1049a5014065ed3cc0'),
]


def sha(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def prepare(base, cache, fetch, selected=None):
    cache.mkdir(parents=True, exist_ok=True)
    base.mkdir(parents=True, exist_ok=True)
    entries = []
    opener = urllib.request.build_opener(CheckedRedirect())
    with destination_lock(cache):
        for name, tag, filename, size, digest in ASSETS:
            if selected is not None and name not in selected: continue
            entry = dict(id=name, path=filename, size_bytes=size, sha256=digest,
                         url=f'https://github.com/k2-fsa/sherpa-onnx/releases/download/{tag}/{filename}')
            validate_url(entry['url'], initial=True)
            archive = target_path(cache, filename)
            if fetch:
                download_file(cache, entry, opener, [0, 400_000_000])
            if not verify_file(archive, entry):
                raise ValueError('Missing or changed pinned artifact: ' + filename)
            if name == 'vocos':
                target = target_path(base, 'vocos_24khz.onnx')
                if not target.exists():
                    shutil.copyfile(archive, target)
                if not verify_file(target, entry):
                    raise ValueError('Changed installed vocoder; refusing overwrite')
            else:
                dirname = filename.removesuffix('.tar.bz2')
                target = target_path(base, dirname)
                inventory = target / 'jarvis-verified-files.json'
                if not target.exists():
                    if not fetch:
                        raise ValueError('Model is not extracted; use --download')
                    # Both staging and final paths are checked within this model directory.
                    with tempfile.TemporaryDirectory(prefix='tts-stage-', dir=base) as stage:
                        stage_path = Path(stage).resolve()
                        stage_path.relative_to(base.resolve())
                        with tarfile.open(archive, 'r:bz2') as bundle:
                            members = bundle.getmembers()
                            if len(members) > 5000 or sum(m.size for m in members) > 1_000_000_000:
                                raise ValueError('Archive exceeds extraction budget')
                            for member in members:
                                path = relative_path(member.name.rstrip('/'))
                                if path.parts[0] != dirname or not (member.isdir() or member.isfile()):
                                    raise ValueError('Unexpected archive member')
                            bundle.extractall(stage_path, members=members, filter='data')
                        source = stage_path / dirname
                        source.resolve().relative_to(base.resolve())
                        target.resolve().relative_to(base.resolve())
                        source.rename(target)
                    records = [{'path': p.relative_to(target).as_posix(), 'size_bytes': p.stat().st_size,
                                'sha256': sha(p)} for p in sorted(target.rglob('*')) if p.is_file()]
                    inventory.write_text(json.dumps({'archive_sha256': digest, 'files': records}, indent=2)+'\n', encoding='utf-8')
                installed = json.loads(inventory.read_text(encoding='utf-8'))
                if installed['archive_sha256'] != digest:
                    raise ValueError('Installed archive revision differs')
                for record in installed['files']:
                    if not verify_file(target_path(target, record['path']), record):
                        raise ValueError('Modified installed data: ' + record['path'])
                entry['extracted_files'] = len(installed['files'])
                entry['extracted_bytes'] = sum(r['size_bytes'] for r in installed['files'])
            entries.append(entry)
    return entries


def worker(args):
    for key in ('OMP_NUM_THREADS', 'OPENBLAS_NUM_THREADS', 'MKL_NUM_THREADS'):
        os.environ[key] = str(args.threads)
    import numpy as np
    import sherpa_onnx as s
    from jarvis_core.process_memory import process_memory
    baseline = process_memory()
    base = args.models
    if args.worker == 'kokoro':
        model = base / 'kokoro-int8-multi-lang-v1_1'
        cfg = s.OfflineTtsModelConfig(kokoro=s.OfflineTtsKokoroModelConfig(
            model=str(model / 'model.int8.onnx'), voices=str(model / 'voices.bin'),
            tokens=str(model / 'tokens.txt'), data_dir=str(model / 'espeak-ng-data'),
            lexicon=','.join(str(model / p) for p in ('lexicon-us-en.txt', 'lexicon-zh.txt')),
            dict_dir=str(model / 'dict')), num_threads=args.threads, provider='cpu')
        rules = ','.join(str(p) for p in (model / 'phone-zh.fst', model / 'date-zh.fst', model / 'number-zh.fst') if p.exists())
    else:
        model = base / 'sherpa-onnx-zipvoice-distill-int8-zh-en-emilia'
        cfg = s.OfflineTtsModelConfig(zipvoice=s.OfflineTtsZipvoiceModelConfig(
            encoder=str(model / 'encoder.int8.onnx'), decoder=str(model / 'decoder.int8.onnx'),
            vocoder=str(base / 'vocos_24khz.onnx'), tokens=str(model / 'tokens.txt'),
            lexicon=str(model / 'lexicon.txt'), data_dir=str(model / 'espeak-ng-data')),
            num_threads=args.threads, provider='cpu')
        rules = ''
    config = s.OfflineTtsConfig(model=cfg, rule_fsts=rules, max_num_sentences=1)
    if not config.validate():
        raise ValueError('Invalid candidate model configuration')
    start = time.perf_counter()
    tts = s.OfflineTts(config)
    result = {'model': args.worker, 'threads': args.threads, 'provider': 'cpu',
              'runtime': s.__version__, 'python': sys.version.split()[0], 'baseline_memory': baseline,
              'load_seconds': time.perf_counter()-start, 'loaded_memory': process_memory(), 'cases': []}
    for label, text in [('first', '你好，我是贾维斯。'), ('warm', '你好，我是贾维斯。'),
                        ('reply', '我在，有什么可以帮你？'),
                        ('mixed', '今天下午三点提醒我开会。Hello, I am Jarvis.'),
                        ('sentences', '我可以陪你聊天。也可以帮你处理事情。我们先从哪一件开始？')]:
        callbacks = []
        start = time.perf_counter()
        cpu_start = time.process_time()
        def on_audio(samples, progress):
            callbacks.append({'seconds': time.perf_counter()-start, 'samples': len(samples), 'progress': float(progress)})
            return 1  # Publisher playback example: 1 continues; 0 cancels.
        if args.worker == 'kokoro':
            audio = tts.generate(text, sid=46, speed=1.0, callback=on_audio)
        else:
            # Use the already verified, publisher-provided CosyVoice reference, not a celebrity fixture.
            with wave.open(str(args.reference), 'rb') as wav:
                reference = np.frombuffer(wav.readframes(wav.getnframes()), dtype='<i2').astype(np.float32)/32768
                rate = wav.getframerate()
            audio = tts.generate(text, '希望你以后能够做的比我还好呦。', reference.tolist(), rate,
                                 speed=1.0, num_steps=4, callback=on_audio)
        elapsed = time.perf_counter()-start
        samples = np.asarray(audio.samples)
        if not len(samples) or not np.isfinite(samples).all():
            raise ValueError('Missing or non-finite output')
        output = args.output / f'{args.worker}-{args.threads}-{label}.wav'
        with wave.open(str(output), 'wb') as wav:
            wav.setnchannels(1); wav.setsampwidth(2); wav.setframerate(audio.sample_rate)
            wav.writeframes((np.clip(samples, -1, 1)*32767).astype('<i2').tobytes())
        duration = len(samples)/audio.sample_rate
        result['cases'].append({'label': label, 'text': text, 'wall_seconds': elapsed,
            'cpu_seconds': time.process_time()-cpu_start, 'audio_seconds': duration,
            'rtf': elapsed/duration, 'callbacks': callbacks, 'memory': process_memory(),
            'output': str(output.resolve()), 'sha256': sha(output)})
    result['peak_memory'] = process_memory()
    (args.output / f'{args.worker}-{args.threads}.json').write_text(json.dumps(result, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--download', action='store_true')
    parser.add_argument('--models', type=Path, default=Path('H:/JarvisData/models/tts'))
    parser.add_argument('--cache', type=Path, default=Path('H:/JarvisData/components/fast-tts/downloads'))
    parser.add_argument('--output', type=Path, default=Path('H:/JarvisData/research/fast-tts'))
    parser.add_argument('--reference', type=Path, default=Path('H:/JarvisData/models/tts/zipvoice-default-reference.wav'))
    parser.add_argument('--threads', type=int, choices=(2,4,8), default=4)
    parser.add_argument('--worker', choices=('kokoro','zipvoice'))
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    if args.worker:
        worker(args)
        return
    entries = prepare(args.models, args.cache, args.download)
    # This benchmark uses a fixed, verified publisher fixture, never personal enrollment.
    # A prepared PCM16 reference is required: no implicit codec/package installation.
    with wave.open(str(args.reference), 'rb') as wav:
        if wav.getnchannels() != 1 or wav.getsampwidth() != 2 or wav.getnframes() > wav.getframerate()*15:
            raise ValueError('Reference must be mono PCM16, at most 15 seconds')
    results = []
    for model in ('kokoro','zipvoice'):
        print('BENCHMARK '+model, flush=True)
        run = subprocess.run([sys.executable, str(Path(__file__).resolve()), '--worker', model,
            '--models', str(args.models), '--output', str(args.output), '--reference', str(args.reference),
            '--threads', str(args.threads)], capture_output=True, text=True, encoding='utf-8', errors='replace', timeout=240)
        (args.output / f'{model}-{args.threads}.log').write_text(run.stdout+'\n'+run.stderr, encoding='utf-8')
        if run.returncode:
            raise ValueError(f'{model} benchmark failed; see external log')
        result = json.loads((args.output / f'{model}-{args.threads}.json').read_text(encoding='utf-8'))
        results.append(result)
        print(model, 'load', round(result['load_seconds'],3), 'seconds;',
              [(c['label'], round(c['wall_seconds'],3), round(c['rtf'],3)) for c in result['cases']], flush=True)
    report = {'schema_version':1, 'date':'2026-10-18', 'status':'measured', 'assets':entries, 'results':results,
              'reference':{'path':str(args.reference.resolve()), 'sha256':sha(args.reference),
                           'text':'希望你以后能够做的比我还好呦。', 'source':'CosyVoice publisher fixture; not owner enrollment'},
              'limits':'File-only isolated CPU benchmark. Internal callback is not browser playback. No microphone, end-to-end chat, emotion, or clone-similarity acceptance.'}
    (ROOT / 'evals/reports/fast-tts-2026-10-18.json').write_text(json.dumps(report, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')


if __name__ == '__main__':
    main()
