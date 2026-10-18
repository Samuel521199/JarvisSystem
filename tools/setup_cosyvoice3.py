"""Explicit optional-component setup. No setup or downloads during chat/startup."""
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path, PurePosixPath
import argparse
import hashlib
import http.client
import json
import os
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'runtime/node-host'))
from jarvis_core.policy import safe_path
from jarvis_core.speech_contract import inference_yaml


def config():
    return json.loads((ROOT / 'config/model-profiles/cosyvoice3.json').read_text(encoding='utf-8'))


def digest(path):
    h = hashlib.sha256()
    with path.open('rb') as stream:
        while block := stream.read(4 * 1024 * 1024): h.update(block)
    return h.hexdigest()


def target(base, relative):
    p = PurePosixPath(relative)
    if p.is_absolute() or '..' in p.parts or '\\' in relative or ':' in relative:
        raise ValueError('Invalid component path')
    return safe_path(Path(base) / Path(p), must_exist=False)


def check_url(url):
    p = urllib.parse.urlsplit(url)
    host = p.hostname or ''
    if p.scheme != 'https' or p.username or p.password or p.port not in (None, 443):
        raise ValueError('Invalid model download URL')
    if host not in {'huggingface.co', 'cdn-lfs.huggingface.co', 'cdn-lfs.hf.co', 'cas-bridge.xethub.hf.co'} and not host.endswith('.xethub.hf.co') and not host.endswith('.cdn.hf.co'):
        raise ValueError('Unapproved model CDN')


class Redirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        check_url(newurl)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def download_one(cfg, item):
    base = Path(cfg['model_root']); path = target(base, item['path'])
    if path.exists():
        if path.stat().st_size == item['size_bytes'] and digest(path) == item['sha256']:
            print('VERIFIED ' + item['path'], flush=True); return
        raise ValueError('Existing asset differs; refusing overwrite: ' + item['path'])
    expected = 'https://huggingface.co/FunAudioLLM/Fun-CosyVoice3-0.5B-2512/resolve/' + cfg['model_revision'] + '/' + item['path']
    if item['url'] != expected: raise ValueError('Unpinned asset URL')
    path.parent.mkdir(parents=True, exist_ok=True)
    part = target(base, item['path'] + '.part')
    for attempt in range(4):
        try:
            offset = part.stat().st_size if part.exists() else 0
            if offset > item['size_bytes']: raise ValueError('Partial asset exceeds pinned size')
            if offset < item['size_bytes']:
                request = urllib.request.Request(item['url'], headers={'User-Agent': 'Jarvis-CosyVoice3/1', **({'Range': 'bytes=' + str(offset) + '-'} if offset else {})})
                with urllib.request.build_opener(Redirect()).open(request, timeout=45) as response:
                    resume = offset and response.status == 206 and response.headers.get('Content-Range', '').startswith('bytes ' + str(offset) + '-')
                    if not resume: offset = 0
                    last = offset
                    with part.open('ab' if resume else 'wb') as output:
                        while block := response.read(1024 * 1024):
                            offset += len(block)
                            if offset > item['size_bytes']: raise ValueError('Asset exceeds pinned size')
                            output.write(block)
                            if offset - last >= 128 * 1024 * 1024:
                                print('DOWNLOADING ' + item['path'] + ' ' + str(round(offset / item['size_bytes'] * 100)) + '%', flush=True); last = offset
            if part.stat().st_size != item['size_bytes']:
                raise ConnectionError('Incomplete asset transfer')
            if digest(part) != item['sha256']:
                raise ValueError('Asset digest mismatch: ' + item['path'])
            os.replace(part, path)
            print('INSTALLED ' + item['path'], flush=True); return
        except (urllib.error.URLError, TimeoutError, ConnectionError, OSError, http.client.IncompleteRead):
            if attempt == 3: raise
            print('RETRY ' + item['path'] + ' from verified-size partial transfer', flush=True)
            time.sleep(1 + attempt)


def download(cfg):
    total = sum(x['size_bytes'] for x in cfg['files'])
    if total > cfg['max_download_bytes'] or cfg['max_download_bytes'] > 6_000_000_000:
        raise ValueError('Optional profile exceeds its explicit 6 GB download budget')
    base = safe_path(cfg['model_root'], must_exist=False); base.mkdir(parents=True, exist_ok=True)
    remaining = sum(x['size_bytes'] for x in cfg['files'] if not target(base, x['path']).exists())
    if shutil.disk_usage(base).free < remaining + 2_000_000_000: raise ValueError('Insufficient disk space')
    print('PINNED DOWNLOAD ' + str(total) + ' bytes', flush=True)
    with ThreadPoolExecutor(max_workers=3) as pool:
        list(pool.map(lambda item: download_one(cfg, item), cfg['files']))


def source(cfg):
    dest = safe_path(cfg['source_root'], must_exist=False)
    if not dest.exists():
        dest.parent.mkdir(parents=True, exist_ok=True)
        subprocess.run(['git', 'clone', '--filter=blob:none', '--no-checkout', cfg['source_repository'], str(dest)], check=True)
        subprocess.run(['git', '-c', 'safe.directory=' + str(dest), '-C', str(dest), 'checkout', '--detach', cfg['source_revision']], check=True)
    sub = dest / 'third_party/Matcha-TTS'
    git = ['git', '-c', 'safe.directory=' + str(dest), '-c', 'safe.directory=' + str(sub), '-C', str(dest)]
    if subprocess.check_output(git + ['rev-parse', 'HEAD'], text=True).strip() != cfg['source_revision']:
        raise ValueError('Unexpected source revision; no reset performed')
    subprocess.run(git + ['submodule', 'update', '--init', '--depth', '1', 'third_party/Matcha-TTS'], check=True)
    if subprocess.check_output(['git', '-c', 'safe.directory=' + str(sub), '-C', str(sub), 'rev-parse', 'HEAD'], text=True).strip() != cfg['matcha_revision']:
        raise ValueError('Unexpected Matcha revision')


def inference_config(cfg):
    """Keep inference nodes; do not instantiate unused GAN/training/data pipelines."""
    base = Path(cfg['model_root']); original = (base / 'cosyvoice3.yaml').read_text(encoding='utf-8')
    result = inference_yaml(original)
    (base / 'jarvis-inference.yaml').write_text(result, encoding='utf-8')
    return result


def environment(cfg, python):
    env = safe_path(cfg['environment_root'], must_exist=False)
    exe = env / ('Scripts/python.exe' if os.name == 'nt' else 'bin/python')
    if not exe.exists(): subprocess.run(['uv', 'venv', '--python', python, str(env)], check=True)
    subprocess.run(['uv', 'pip', 'install', '--python', str(exe), 'torch==2.7.1', 'torchaudio==2.7.1', '--index-url', 'https://download.pytorch.org/whl/cpu'], check=True)
    subprocess.run(['uv', 'pip', 'install', '--python', str(exe), 'wheel==0.45.1'], check=True)
    requirements = ROOT / 'config/cosyvoice3.lock.txt'
    if not requirements.exists(): requirements = ROOT / 'config/cosyvoice3-requirements.txt'
    subprocess.run(['uv', 'pip', 'install', '--python', str(exe), '--no-build-isolation-package', 'openai-whisper', '-r', str(requirements)], check=True)
    frozen = subprocess.check_output(['uv', 'pip', 'freeze', '--python', str(exe)], text=True)
    (env / 'jarvis-cosyvoice3-freeze.txt').write_text(frozen, encoding='utf-8')
    validate_environment(cfg)


def validate_environment(cfg):
    env = Path(cfg['environment_root']); exe = env / ('Scripts/python.exe' if os.name == 'nt' else 'bin/python')
    code = "import sys,json,torch,onnxruntime;sys.path[:0]=[sys.argv[1],sys.argv[1]+'/third_party/Matcha-TTS'];from cosyvoice.cli.cosyvoice import CosyVoice3;assert not torch.cuda.is_available();print(json.dumps({'torch':torch.__version__,'onnxruntime':onnxruntime.__version__,'device':'cpu'}))"
    child_env = {k:os.environ[k] for k in ('SystemRoot','WINDIR','TEMP','TMP','PATH','USERPROFILE') if k in os.environ}
    child_env.update(HF_HUB_OFFLINE='1',TRANSFORMERS_OFFLINE='1',HF_HUB_DISABLE_TELEMETRY='1')
    cache = Path(cfg['source_root']).parent / 'cache'
    for name, sub in (('HF_HOME','huggingface'),('MODELSCOPE_CACHE','modelscope'),('MPLCONFIGDIR','matplotlib'),('NUMBA_CACHE_DIR','numba')):
        directory = safe_path(cache / sub,must_exist=False); directory.mkdir(parents=True,exist_ok=True)
        child_env[name] = str(directory)
    info = json.loads(subprocess.check_output([str(exe), '-c', code, cfg['source_root']], text=True, env=child_env))
    marker = {'profile_sha256':hashlib.sha256(json.dumps(cfg,sort_keys=True).encode()).hexdigest(), 'runtime':info}
    (env / 'jarvis-cosyvoice3-ready.json').write_text(json.dumps(marker,indent=2)+'\n',encoding='utf-8')
    print('ENVIRONMENT READY '+json.dumps(info),flush=True)


def verify(cfg):
    for item in cfg['files']:
        path = target(cfg['model_root'], item['path'])
        if not path.is_file() or path.stat().st_size != item['size_bytes'] or digest(path) != item['sha256']:
            raise ValueError('Missing/modified asset: ' + item['path'])
    inference_config(cfg)
    print('VERIFIED pinned assets and generated inference-only YAML', flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=('download', 'source', 'environment', 'verify-environment', 'verify', 'install'))
    parser.add_argument('--python', default='3.12')
    args = parser.parse_args(); cfg = config()
    if args.action in {'source', 'install'}: source(cfg)
    if args.action in {'download', 'install'}: download(cfg)
    if args.action in {'environment', 'install'}: environment(cfg, args.python)
    if args.action == 'verify-environment': validate_environment(cfg)
    if args.action in {'verify', 'install'}: verify(cfg)


if __name__ == '__main__': main()
