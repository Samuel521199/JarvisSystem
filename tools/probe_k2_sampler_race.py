"""Reproduce counter reads racing short real LPAC Workers; synthetic files only."""
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import threading
import time
import os

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'runtime/node-host'),str(ROOT/'tools')]
from jarvis_core.service import CoreService
from jarvis_core.process_usage import process_usage
from probe_idle_resources import WindowsProcesses


def main():
    target=Path(sys.argv[1])
    if target.exists():raise FileExistsError(target)
    reader=WindowsProcesses();stop=threading.Event();errors=[];samples=0
    def sample():
        nonlocal samples
        while not stop.wait(.002):
            for row in reader.tree(os.getpid()):
                try:process_usage(row['pid']);samples+=1
                except OSError as error:
                    present=row['pid'] in {p['pid'] for p in reader.tree(os.getpid())}
                    errors.append({**row,'error':repr(error),'present_on_reenumeration':present})
    worker=threading.Thread(target=sample,daemon=True)
    with tempfile.TemporaryDirectory(prefix='jarvis-k2-sampler-') as temp:
        base=Path(temp);folder=base/'source';folder.mkdir();(folder/'a.txt').write_bytes(b'abc')
        core=CoreService(base/'data');core.initialize(folder);worker.start()
        try:
            for index in range(50):
                result=core.inventory(request_id='sampler-'+str(index))
                assert result['action']['status']=='CONFIRMED'
        finally:stop.set();worker.join(5)
    result={'samples':samples,'errors':errors,'tasks':50,
            'sampler_sha256':hashlib.sha256((ROOT/'tools/probe_k2_runtime.py').read_bytes()).hexdigest(),
            'scope':'Diagnosis only, not a resource acceptance run or network test.'}
    target.write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(result,ensure_ascii=False))


if __name__=='__main__':main()
