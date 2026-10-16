"""Explicit CLI entry for the optional browser module; chat does not execute it."""
import argparse
import json
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[2]
sys.path[:0]=[str(ROOT/'runtime/node-host'),str(ROOT/'adapters/computer-use')]
from jarvis_core.service import CoreService
from jarvis_computer.protocol import strict_json
from jarvis_computer.service import ComputerService


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command',choices=['demo','run','status','cancel'])
    parser.add_argument('--task',type=Path,help='Explicit task scope JSON for run')
    parser.add_argument('--task-id')
    parser.add_argument('--request-id')
    parser.add_argument('--model',default='auto',help='Registered model ID; provider is selected automatically')
    parser.add_argument('--scripted',action='store_true',help='Non-AI offline demo verification only')
    parser.add_argument('--headed',action='store_true',help='Show the dedicated browser window')
    parser.add_argument('--data-dir',type=Path)
    args=parser.parse_args(argv)
    try:
        core=CoreService(args.data_dir);service=ComputerService(core)
        if args.command in {'status','cancel'}:
            if not args.task_id:raise ValueError('--task-id is required')
            result=service.inspect(args.task_id) if args.command=='status' else core.cancel(args.task_id)
        else:
            if args.scripted and args.command!='demo':raise ValueError('--scripted is only available for the synthetic demo')
            path=ROOT/'config/computer-use/demo-task.json' if args.command=='demo' else args.task
            if path is None:raise ValueError('--task is required')
            if path.stat().st_size>32768:raise ValueError('Task file too large')
            task=strict_json(path.read_bytes())
            html=(ROOT/'apps/computer-use/demo.html').read_text(encoding='utf-8') if args.command=='demo' else None
            result=service.run(task,request_id=args.request_id,model=args.model,scripted=args.scripted,headed=args.headed,demo_html=html)
        print(json.dumps(result,ensure_ascii=False,indent=2))
        record=result.get('record',result)
        if record.get('artifact'):
            print('产物：'+str(core.ledger.artifact_dir/record['artifact']['path']),file=sys.stderr)
        return 0 if record['task']['status']=='SUCCEEDED' else 3
    except Exception as exc:
        print(json.dumps({'error':getattr(exc,'code',type(exc).__name__),'message':str(exc)},ensure_ascii=False),file=sys.stderr)
        return 2


if __name__=='__main__':
    sys.stdout.reconfigure(encoding='utf-8');sys.stderr.reconfigure(encoding='utf-8')
    raise SystemExit(main())
