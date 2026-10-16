"""Fixed metadata computation. No model, tools, credentials or dynamic code API."""
import hashlib
import json
import os
from pathlib import Path


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'))


def main():
    raw = Path(__file__).with_name('input.json').read_bytes()
    if len(raw) > 2 * 1024 * 1024:
        raise ValueError('Input quota exceeded')
    envelope = json.loads(raw)
    if set(envelope) != {'binding', 'inventory'} or envelope['binding']['operation'] != 'inventory.metadata.v1':
        raise ValueError('Unknown operation/envelope')
    inventory = envelope['inventory']
    if hashlib.sha256(canonical(inventory).encode()).hexdigest() != envelope['binding']['input_sha256']:
        raise ValueError('Input binding mismatch')
    files = inventory['files']
    if len(files) > 1000:
        raise ValueError('File quota exceeded')
    result = {'schema_version': '1.0.0', 'relative_path': inventory['relative_path'],
              'files': sorted(files, key=lambda item: item['path']),
              'total_files': len(files), 'total_bytes': sum(item['size_bytes'] for item in files)}
    output = canonical({'binding': envelope['binding'], 'inventory': result}).encode()
    if len(output) > 2 * 1024 * 1024:
        raise ValueError('Output quota exceeded')
    # pythonw has no console streams; only explicitly inherited pipes are used.
    while output:
        count = os.write(1, output)
        if count <= 0:
            raise OSError('Output pipe closed')
        output = output[count:]


if __name__ == '__main__':
    try:
        main()
    except Exception:
        os.write(2, b'Worker metadata computation failed\n')
        raise SystemExit(1)
