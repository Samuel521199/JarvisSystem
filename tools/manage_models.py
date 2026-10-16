"""Fetch only explicitly selected, pinned local model artifacts; never execute them.

Examples (no network for list, plan or verify):
  python tools/manage_models.py list
  python tools/manage_models.py plan --profile local-small-cpu
  python tools/manage_models.py download --profile local-small-cpu
  python tools/manage_models.py verify --profile local-small-cpu
"""
from __future__ import annotations

import argparse
import contextlib
import hashlib
import json
import os
from pathlib import Path, PurePosixPath, PureWindowsPath
import re
import shutil
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request

HARD_LIMIT = 2_000_000_000
RESERVE_BYTES = 64 * 1024 * 1024
CHUNK = 1024 * 1024
HF_REPOSITORIES = frozenset({
    'Qwen/Qwen3-0.6B-GGUF',
    'csukuangfj/sherpa-onnx-sense-voice-zh-en-ja-ko-yue-2024-07-17',
    'csukuangfj/icefall-tts-aishell3-vits-low-2024-04-06',
    'csukuangfj/speaker-embedding-models',
    'csukuangfj/vad',
})
GITHUB_REPOSITORIES = frozenset({'ggml-org/llama.cpp', 'k2-fsa/sherpa-onnx'})
# Exact hosts: never allow arbitrary suffixes, user URLs, HTTP, or localhost.
NETWORK_HOSTS = frozenset({
    'huggingface.co', 'github.com', 'raw.githubusercontent.com',
    'cdn-lfs.huggingface.co', 'cdn-lfs.hf.co', 'cdn-lfs-us-1.hf.co',
    'cdn-lfs-eu-1.hf.co', 'cas-bridge.xethub.hf.co',
    'release-assets.githubusercontent.com', 'objects.githubusercontent.com',
    'us.aws.cdn.hf.co',
})
ALLOWED_SUFFIXES = frozenset({'.gguf', '.onnx', '.txt', '.fst', '.json', '.wav'})
RESERVED = re.compile(r'^(CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])(?:\.|$)', re.I)
SHA256 = re.compile(r'^[0-9a-f]{64}$')
REVISION = re.compile(r'^[0-9a-f]{40}$')


class ModelError(Exception):
    pass


def validate_url(url: str, initial: bool = False) -> None:
    if not isinstance(url, str) or any(ord(c) < 32 for c in url):
        raise ModelError('Invalid download URL')
    parsed = urllib.parse.urlsplit(url)
    if (parsed.scheme != 'https' or parsed.hostname not in NETWORK_HOSTS
            or parsed.username or parsed.password or parsed.fragment
            or parsed.port not in (None, 443)):
        raise ModelError('Download URL must use an approved HTTPS host')
    if not initial:
        return
    parts = parsed.path.strip('/').split('/')
    if parsed.hostname == 'huggingface.co':
        if (len(parts) < 5 or '/'.join(parts[:2]) not in HF_REPOSITORIES
                or parts[2] != 'resolve' or not REVISION.fullmatch(parts[3])):
            raise ModelError('Hugging Face source must pin an approved repository commit')
    elif parsed.hostname == 'github.com':
        if (len(parts) < 6 or '/'.join(parts[:2]) not in GITHUB_REPOSITORIES
                or parts[2:4] != ['releases', 'download']
                or parts[4] in {'latest', 'main', 'master'}):
            raise ModelError('GitHub source must pin an approved release artifact')
    else:
        raise ModelError('Only reviewed publisher origins can start a download')


class CheckedRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        validate_url(newurl)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def relative_path(value: str) -> PurePosixPath:
    if (not isinstance(value, str) or not value or '\\' in value
            or PureWindowsPath(value).drive or value.startswith('/')):
        raise ModelError('Artifact path must be a portable relative path')
    path = PurePosixPath(value)
    if any(part in {'', '.', '..'} or part.endswith((' ', '.'))
           or RESERVED.match(part) or any(c in part for c in ':<>"|?*')
           or any(ord(c) < 32 for c in part) for part in value.split('/')):
        raise ModelError('Unsafe artifact path')
    return path


def target_path(root: Path, value: str) -> Path:
    path = root.joinpath(*relative_path(value).parts)
    try:
        path.resolve().relative_to(root.resolve())
    except ValueError as exc:
        raise ModelError('Artifact path escapes destination') from exc
    # Reject even internal links/junctions: a download cannot redirect into other data.
    for item in [path, *path.parents]:
        if item == root.parent:
            break
        if item.is_symlink() or (hasattr(item, 'is_junction') and item.is_junction()):
            raise ModelError('Artifact destination contains a link or junction')
    return path


def load_manifest(path: Path):
    try:
        data = json.loads(path.read_text(encoding='utf-8-sig'))
    except (OSError, UnicodeError, ValueError) as exc:
        raise ModelError('Cannot read candidate manifest: ' + str(exc)) from exc
    if not isinstance(data, dict) or type(data.get('schema_version')) is not int or data['schema_version'] != 1:
        raise ModelError('Candidate manifest schema_version must be 1')
    files, paths = {}, set()
    if not isinstance(data.get('files'), list) or not isinstance(data.get('profiles'), dict):
        raise ModelError('Manifest requires files and profiles')
    for entry in data['files']:
        if not isinstance(entry, dict):
            raise ModelError('Each artifact must be an object')
        key = entry.get('id')
        if not isinstance(key, str) or not re.fullmatch(r'[a-z0-9][a-z0-9._-]*', key) or key in files:
            raise ModelError('Invalid or duplicate artifact id')
        path = relative_path(entry.get('path'))
        folded = str(path).casefold()
        if folded in paths:
            raise ModelError('Duplicate artifact destination')
        paths.add(folded)
        if entry.get('kind') == 'runtime_archive':
            if path.suffix != '.zip' or path.parts[0] != 'runtimes':
                raise ModelError('Runtime archives must be ZIP files under runtimes/')
        elif path.suffix.lower() not in ALLOWED_SUFFIXES and path.name != 'LICENSE':
            raise ModelError('Artifact type is not on the data-only allowlist')
        size = entry.get('size_bytes')
        if type(size) is not int or size <= 0 or size > HARD_LIMIT:
            raise ModelError('Invalid artifact size')
        if not isinstance(entry.get('sha256'), str) or not SHA256.fullmatch(entry['sha256']):
            raise ModelError('Every artifact needs a fixed SHA-256')
        if not isinstance(entry.get('revision'), str) or not entry['revision']:
            raise ModelError('Every artifact needs a pinned revision')
        validate_url(entry.get('url'), initial=True)
        parts = urllib.parse.urlsplit(entry['url']).path.strip('/').split('/')
        url_revision = parts[3] if parts[2] == 'resolve' else parts[4]
        if entry['revision'] != url_revision:
            raise ModelError('Artifact revision differs from its URL')
        files[key] = entry
    for name, profile in data['profiles'].items():
        if not isinstance(profile, dict) or not isinstance(profile.get('file_ids'), list):
            raise ModelError('Profile requires explicit file_ids')
        ids = profile['file_ids']
        if not ids or any(not isinstance(i, str) or i not in files for i in ids) or len(ids) != len(set(ids)):
            raise ModelError('Profile has missing, duplicate or unknown artifact ids')
        actual = sum(files[i]['size_bytes'] for i in ids)
        if profile.get('total_bytes') != actual:
            raise ModelError('Profile total_bytes differs from its selected artifacts')
    return data, files


def checked_limit(value, label):
    if type(value) is not int or value <= 0:
        raise ModelError(label + ' must be a positive byte count')
    return min(value, HARD_LIMIT)


def select_profile(data, files, name, cli_limit):
    if name not in data['profiles']:
        raise ModelError('Select a known profile explicitly with --profile')
    profile = data['profiles'][name]
    selected = [files[i] for i in profile['file_ids']]
    limit = min(checked_limit(data.get('max_total_bytes', HARD_LIMIT), 'manifest limit'),
                checked_limit(profile.get('max_total_bytes', HARD_LIMIT), 'profile limit'),
                checked_limit(cli_limit, 'command limit'))
    if sum(e['size_bytes'] for e in selected) > limit:
        raise ModelError('Selected artifacts exceed the total download limit')
    return selected, limit


def digest_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(CHUNK), b''):
            digest.update(block)
    return digest.hexdigest()


def verify_file(path: Path, entry) -> bool:
    return (path.is_file() and path.stat().st_size == entry['size_bytes']
            and digest_file(path) == entry['sha256'])


def free_space(path: Path) -> int:
    while not path.exists():
        if path == path.parent:
            raise ModelError('No existing destination volume')
        path = path.parent
    return shutil.disk_usage(path).free


@contextlib.contextmanager
def destination_lock(root: Path):
    lock = root / '.model-download.lock'
    try:
        fd = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    except FileExistsError as exc:
        raise ModelError('Download lock exists; another download may be active') from exc
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as stream:
            json.dump({'pid': os.getpid(), 'created_unix': time.time()}, stream)
        yield
    finally:
        lock.unlink(missing_ok=True)


def download_file(root, entry, opener, budget):
    destination = target_path(root, entry['path'])
    if destination.exists():
        if not verify_file(destination, entry):
            raise ModelError('Existing file failed verification; refusing overwrite: ' + entry['path'])
        print('VERIFIED existing ' + entry['path'], flush=True)
        return
    if free_space(root) < entry['size_bytes'] + RESERVE_BYTES:
        raise ModelError('Insufficient free disk space')
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination = target_path(root, entry['path'])
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode='wb', dir=destination.parent,
                prefix=destination.name + '.', suffix='.partial', delete=False) as stream:
            temporary = Path(stream.name)
            request = urllib.request.Request(entry['url'], headers={
                'User-Agent': 'Jarvis-reviewed-model-fetcher/1.0', 'Accept-Encoding': 'identity'})
            digest, received = hashlib.sha256(), 0
            print('DOWNLOADING ' + entry['path'] + ' bytes=' + str(entry['size_bytes']), flush=True)
            with opener.open(request, timeout=45) as response:
                validate_url(response.geturl())
                if response.status != 200:
                    raise ModelError('Unexpected HTTP response status')
                length = response.headers.get('Content-Length')
                if length is not None and int(length) != entry['size_bytes']:
                    raise ModelError('Server Content-Length differs from pinned size')
                if response.headers.get('Content-Encoding', 'identity').lower() != 'identity':
                    raise ModelError('Encoded responses are not supported')
                last_report = time.monotonic()
                while True:
                    # One extra byte detects overlong bodies without unbounded reads.
                    block = response.read(min(CHUNK, entry['size_bytes'] - received + 1))
                    if not block:
                        break
                    budget[0] += len(block)
                    received += len(block)
                    if budget[0] > budget[1] or received > entry['size_bytes']:
                        raise ModelError('Download exceeded byte limit')
                    stream.write(block)
                    digest.update(block)
                    if time.monotonic() - last_report >= 15:
                        print('PROGRESS ' + entry['id'] + ' ' + str(received) + '/' + str(entry['size_bytes']), flush=True)
                        last_report = time.monotonic()
            if received != entry['size_bytes'] or digest.hexdigest() != entry['sha256']:
                raise ModelError('Size or SHA-256 mismatch: ' + entry['path'])
            stream.flush()
            os.fsync(stream.fileno())
        target_path(root, entry['path'])
        if destination.exists():
            raise ModelError('Destination appeared during download; refusing overwrite')
        os.replace(temporary, destination)
        temporary = None
        print('VERIFIED new ' + entry['path'], flush=True)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=['list', 'plan', 'download', 'verify'])
    parser.add_argument('--manifest', type=Path, default=Path(__file__).resolve().parent.parent / 'config/model-profiles/local-candidates.json')
    parser.add_argument('--profile')
    parser.add_argument('--root', type=Path)
    parser.add_argument('--max-total-bytes', type=int, default=HARD_LIMIT)
    args = parser.parse_args(argv)
    try:
        data, files = load_manifest(args.manifest)
        if args.command == 'list':
            for name, p in data['profiles'].items():
                print(name + ' files=' + str(len(p['file_ids'])) + ' bytes=' + str(p['total_bytes']))
            return 0
        selected, limit = select_profile(data, files, args.profile, args.max_total_bytes)
        root = args.root or Path(data.get('default_root', 'H:/JarvisData/models'))
        if not root.is_absolute():
            raise ModelError('Destination root must be absolute')
        if root.is_symlink() or (hasattr(root, 'is_junction') and root.is_junction()):
            raise ModelError('Destination root may not be a link or junction')
        root = root.resolve()
        for entry in selected:
            target_path(root, entry['path'])
        total = sum(e['size_bytes'] for e in selected)
        print('PROFILE ' + args.profile + ' files=' + str(len(selected)) + ' bytes=' + str(total) + ' root=' + str(root))
        if args.command == 'plan':
            for entry in selected:
                print(entry['id'] + ' ' + str(entry['size_bytes']) + ' ' + entry['path'])
            print('NO NETWORK; use the download command to fetch exactly this profile')
            return 0
        if args.command == 'verify':
            errors = 0
            for entry in selected:
                valid = verify_file(target_path(root, entry['path']), entry)
                errors += not valid
                print(('OK ' if valid else 'MISSING_OR_INVALID ') + entry['path'])
            print('VERIFICATION errors=' + str(errors))
            return 1 if errors else 0
        remaining = 0
        for entry in selected:
            destination = target_path(root, entry['path'])
            if destination.exists():
                if not verify_file(destination, entry):
                    raise ModelError('Existing file failed verification; refusing overwrite: ' + entry['path'])
            else:
                remaining += entry['size_bytes']
        if free_space(root) < remaining + RESERVE_BYTES:
            raise ModelError('Insufficient disk space for the selected profile plus reserve')
        root.mkdir(parents=True, exist_ok=True)
        opener = urllib.request.build_opener(CheckedRedirect())
        with destination_lock(root):
            budget = [0, limit]
            for entry in selected:
                download_file(root, entry, opener, budget)
        print('COMPLETE verified_files=' + str(len(selected)) + ' downloaded_bytes=' + str(budget[0]) + '; no artifacts executed')
        return 0
    except (ModelError, OSError, ValueError, urllib.error.URLError) as exc:
        # Never print a redirect URL containing signed query credentials.
        if isinstance(exc, urllib.error.URLError):
            print('ERROR HTTPS request failed: ' + type(exc).__name__, file=sys.stderr)
        else:
            print('ERROR ' + str(exc), file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print('INTERRUPTED; unverified partial file removed', file=sys.stderr)
        return 130


if __name__ == '__main__':
    sys.exit(main())
