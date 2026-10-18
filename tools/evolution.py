"""Run one bounded growth transaction; normally use the workbench settings panel."""
import argparse
import json
from pathlib import Path
import sys
import time
import uuid

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'runtime/node-host'))
from jarvis_core.service import CoreService
from jarvis_core.evolution import EvolutionManager


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['status','ensure','check','execute','rollback'])
    parser.add_argument('--data-dir', type=Path, required=True)
    parser.add_argument('--revision', type=int, choices=[1,2], default=1)
    parser.add_argument('--input', type=Path, help='Bounded JSON metadata file for execute')
    args = parser.parse_args()
    manager = EvolutionManager(CoreService(args.data_dir), monitor=False)
    try:
        if args.action == 'status': result = manager.snapshot()
        else:
            request = {'action': args.action, 'request_id': 'cli-'+uuid.uuid4().hex}
            if args.action == 'ensure': request['target_revision'] = args.revision
            if args.action == 'execute':
                if args.input is None or args.input.stat().st_size > 65536: parser.error('--input up to 64 KiB required')
                request['input'] = json.loads(args.input.read_text(encoding='utf-8'))
            job = manager.submit(request)
            while manager.busy: time.sleep(.1)
            result = manager.store.job(job['id'])
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0 if result.get('status','SUCCEEDED') == 'SUCCEEDED' else 1
    except KeyboardInterrupt:
        manager.cancel_event.set()
        return 130
    finally: manager.close()


if __name__ == '__main__': raise SystemExit(main())
