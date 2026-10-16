"""Measure real isolated inventory tasks on synthetic input; no cloud requests."""
from pathlib import Path
import json
import sys
import tempfile
import time

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'runtime/node-host'))
from jarvis_core.service import CoreService


def main():
    with tempfile.TemporaryDirectory(prefix='jarvis-worker-measure-') as directory:
        base=Path(directory);source=base/'input';source.mkdir()
        for i in range(20):(source/f'sample-{i:02}.txt').write_text('synthetic input',encoding='utf-8')
        service=CoreService(base/'data');service.initialize(source)
        measurements=[]
        for i in range(3):
            start=time.monotonic();result=service.inventory(request_id=f'worker-measure-{i}')
            if result['action']['status']!='CONFIRMED':
                raise RuntimeError(result['action']['error'])
            measurements.append({'task_seconds':round(time.monotonic()-start,4),**service.last_worker_evidence})
        print(json.dumps({'status':'passed','sample_files':20,'samples':measurements,
                          'scope':'Worker and inventory only, not whole-system idle/cold-start or minimum-PC certification'}))


if __name__=='__main__':
    main()
