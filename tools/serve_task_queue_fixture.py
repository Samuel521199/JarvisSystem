"""Disposable task queue UI, synthetic chat and delayed real LPAC inventory."""
import importlib.util
import json
import os
from pathlib import Path
import sys
import tempfile
import time
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'runtime/node-host'),str(ROOT/'tools')]
from jarvis_core import policy
from jarvis_core.service import CoreService
from probe_workspace_ui import SyntheticChat


def main():
    output=Path(os.environ['LOCALAPPDATA'])/'Jarvis/data/diagnostics/k1-progress'
    output.mkdir(parents=True,exist_ok=True)
    original=policy.collect_inventory
    def slow(config,args,checkpoint):
        for _ in range(100):checkpoint();time.sleep(.1)
        return original(config,args,checkpoint)
    # Delay is below the action deadline, leaving time for the real Worker.
    with tempfile.TemporaryDirectory(prefix='jarvis-task-queue-ui-') as directory:
        base=Path(directory);source=base/'sample';source.mkdir()
        (source/'sample.txt').write_text('synthetic input')
        core=CoreService(base/'data');core.initialize(source)
        spec=importlib.util.spec_from_file_location('task_queue_fixture',ROOT/'apps/web/server.py')
        module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
        with patch.object(policy,'collect_inventory',slow),patch.object(policy,'MAX_SECONDS',20):
            server=module.create_server(core=core,chat=SyntheticChat(),port=18182)
            print(json.dumps({'url':'http://127.0.0.1:18182/','root':str(source)}),flush=True)
            try:server.serve_forever(poll_interval=.1)
            except KeyboardInterrupt:pass
            finally:
                server.server_close()
                (output/'ui-state.json').write_text(json.dumps(core.status(),ensure_ascii=False,indent=2),encoding='utf-8')


if __name__=='__main__':main()
