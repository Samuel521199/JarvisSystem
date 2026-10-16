"""Explicit local runtime installation, validation, selection and rollback."""
import argparse
import json
import os
from pathlib import Path
import sys

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'runtime/node-host'))
from jarvis_core.releases import RuntimeSlots


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root',type=Path,default=Path(os.environ['LOCALAPPDATA'])/'Jarvis/runtime')
    commands = parser.add_subparsers(dest='command',required=True)
    commands.add_parser('status')
    commands.add_parser('rollback')
    command = commands.add_parser('install');command.add_argument('archive',type=Path)
    for name in ('health','select'):
        command = commands.add_parser(name);command.add_argument('release_id')
    for name in ('run','start'):
        command = commands.add_parser(name)
        command.add_argument('--data-dir',type=Path,required=True)
        command.add_argument('--mode',choices=('status','inventory','web'),default='web' if name=='start' else 'status')
        command.add_argument('--port',type=int,default=18181)
    args = parser.parse_args()
    try:
        slots = RuntimeSlots(args.root)
        if args.command == 'status': result = slots.status()
        elif args.command == 'install': result = slots.install(args.archive)
        elif args.command == 'health': result = slots.health(args.release_id)
        elif args.command == 'select': result = slots.select(args.release_id)
        elif args.command == 'rollback': result = slots.select(rollback=True)
        elif args.command == 'start':
            result = slots.start(data_dir=args.data_dir,mode=args.mode,port=args.port,
                notify=lambda event:print(json.dumps(event,ensure_ascii=False),file=sys.stderr,flush=True))
            return result['exit_code']
        else: return slots.run(data_dir=args.data_dir,mode=args.mode,port=args.port)
        print(json.dumps(result,ensure_ascii=False,indent=2))
        return 1 if result.get('state') == 'failed' else 0
    except Exception as exc:
        print(json.dumps({'error':getattr(exc,'code',type(exc).__name__),'message':str(exc)},ensure_ascii=False),file=sys.stderr)
        return 2


if __name__ == '__main__':
    sys.stdout.reconfigure(encoding='utf-8');sys.stderr.reconfigure(encoding='utf-8')
    raise SystemExit(main())
