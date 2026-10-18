"""Install/verify the small fast-TTS profile; --download explicitly enables HTTPS."""
import argparse
import hashlib
import importlib.metadata
import json
from pathlib import Path
import struct
import sys
import urllib.request
import wave

from manage_models import CheckedRedirect, verify_file, target_path
from probe_fast_tts import prepare

ROOT = Path(__file__).resolve().parents[1]


def convert_reference(raw):
    """Decode only the fixed publisher IEEE float WAV, after its SHA-256 check."""
    import numpy as np
    if raw[:4] != b'RIFF' or raw[8:12] != b'WAVE': raise ValueError('Invalid fixture RIFF')
    chunks = {}; pos = 12
    while pos+8 <= len(raw):
        key = raw[pos:pos+4]; size = struct.unpack_from('<I',raw,pos+4)[0]; pos += 8
        if pos+size > len(raw): raise ValueError('Truncated fixture')
        chunks[key] = raw[pos:pos+size]; pos += size+(size%2)
    fmt = struct.unpack_from('<HHIIHH',chunks[b'fmt '])
    if fmt[0:3] != (3,1,24000) or fmt[5] != 32: raise ValueError('Unexpected fixture audio encoding')
    samples = np.frombuffer(chunks[b'data'],dtype='<f4')
    if not np.isfinite(samples).all() or not 24000 <= len(samples) <= 15*24000: raise ValueError('Invalid fixture samples')
    return np.floor(np.clip(samples,-1,1)*32768).clip(-32768,32767).astype('<i2').tobytes()


def main():
    p=argparse.ArgumentParser(description=__doc__); p.add_argument('--download',action='store_true'); args=p.parse_args()
    cfg=json.loads((ROOT/'config/model-profiles/zipvoice.json').read_text(encoding='utf-8'))
    base=Path(cfg['model_root']); cache=Path('H:/JarvisData/components/fast-tts/downloads')
    prepare(base,cache,args.download,selected={'zipvoice','vocos'})
    reference=target_path(base,cfg['reference_file'])
    if not reference.exists():
        if not args.download: raise ValueError('Default reference missing; use --download')
        publisher=cfg['reference_source']
        # This is one reviewed, immutable source URL; profiles cannot choose arbitrary origins.
        expected='https://raw.githubusercontent.com/QwenAudio/CosyVoice/074ca6dc9e80a2f424f1f74b48bdd7d3fea531cc/asset/zero_shot_prompt.wav'
        if publisher['url']!=expected: raise ValueError('Unreviewed reference origin')
        opener=urllib.request.build_opener(CheckedRedirect())
        with opener.open(expected,timeout=30) as response: raw=response.read(publisher['size_bytes']+1)
        if len(raw)!=publisher['size_bytes'] or hashlib.sha256(raw).hexdigest()!=publisher['sha256']:
            raise ValueError('Publisher reference checksum differs')
        pcm=convert_reference(raw)
        with wave.open(str(reference),'wb') as wav:
            wav.setnchannels(1); wav.setsampwidth(2); wav.setframerate(24000); wav.writeframes(pcm)
    for row in cfg['files']:
        if not verify_file(target_path(base,row['path']),row): raise ValueError('Missing/modified file: '+row['path'])
    import sherpa_onnx
    if sherpa_onnx.__version__ != cfg['runtime_version']: raise ValueError('Runtime version differs')
    env=Path(cfg['environment_root']).resolve()
    if Path(sys.prefix).resolve()!=env: raise ValueError('Run setup with this profile environment Python')
    marker={'profile_sha256':hashlib.sha256(json.dumps(cfg,sort_keys=True).encode()).hexdigest(),
            'runtime_version':sherpa_onnx.__version__, 'verified_files':len(cfg['files'])}
    (env/'jarvis-zipvoice-ready.json').write_text(json.dumps(marker,indent=2)+'\n',encoding='utf-8')
    print('VERIFIED ZipVoice files='+str(len(cfg['files']))+' runtime='+importlib.metadata.version('sherpa-onnx'))


if __name__=='__main__': main()
