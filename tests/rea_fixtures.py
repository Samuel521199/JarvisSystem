"""Self-owned ASAR fixtures packed by the installed official Electron writer."""
import json
from pathlib import Path
import struct
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT/'tools'), str(ROOT/'runtime/node-host')]
from evaluate_rea_effectiveness import sources
from jarvis_core import rea


def pack(directory, output, *, channels=3, unpack=None):
    directory.mkdir(parents=True, exist_ok=True)
    for name, content in sources(channels).items():
        (directory/name).write_text(content, encoding='utf-8')
    (directory/'secrets.json').write_text('{"key":"fixture-secret-never-parsed"}', encoding='utf-8')
    runtime, _ = rea.runtime()
    argv = [str(runtime/'node.exe'),str(runtime/'node_modules/@electron/asar/bin/asar.mjs'), 'pack',str(directory),str(output)]
    if unpack: argv.extend(['--unpack',unpack])
    subprocess.run(argv,check=True,capture_output=True,timeout=20)
    return output


def raw_archive(path, header, payload=b''):
    raw = json.dumps(header,separators=(',',':')).encode('utf-8')
    padding = (-len(raw)) % 4
    size = 8 + len(raw) + padding
    path.write_bytes(struct.pack('<4I',4,size,size-4,len(raw))+raw+b'\0'*padding+payload)
    return path
