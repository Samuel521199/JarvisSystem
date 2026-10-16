"""Start one local Jarvis web Host with its tray icon, without a console window."""
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import time
from urllib.request import ProxyHandler, build_opener

ROOT = Path(__file__).resolve().parents[2]


def status(port):
    with build_opener(ProxyHandler({})).open(f'http://127.0.0.1:{port}/api/status', timeout=1) as response:
        return json.loads(response.read(16384))


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--data-dir',type=Path)
    parser.add_argument('--config',type=Path)
    parser.add_argument('--port',type=int,default=18181)
    args=parser.parse_args(argv)
    if os.name!='nt': parser.error('The tray launcher requires Windows')
    try: current=status(args.port)
    except (OSError,ValueError): current=None
    if current and current.get('app')=='Jarvis':
        print(json.dumps({'status':'already_running','url':f'http://127.0.0.1:{args.port}/','version':current.get('version')}))
        return 0
    data=args.data_dir or Path(os.environ['LOCALAPPDATA'])/'Jarvis/data'
    directory=data/'diagnostics/tray'; directory.mkdir(parents=True,exist_ok=True)
    command=[sys.executable,'-B',str(ROOT/'apps/web/server.py'),'--port',str(args.port),'--data-dir',str(data.resolve())]
    if args.config: command+=['--config',str(args.config.resolve())]
    with (directory/'server.log').open('ab') as log:
        child=subprocess.Popen(command,cwd=ROOT,stdin=subprocess.DEVNULL,stdout=log,stderr=log,
                               creationflags=subprocess.CREATE_NO_WINDOW)
    for _ in range(80):
        if child.poll() is not None: raise RuntimeError('Jarvis could not start; inspect '+str(directory/'server.log'))
        try:
            current=status(args.port)
            if current.get('app')=='Jarvis':
                print(json.dumps({'status':'started','pid':child.pid,'url':f'http://127.0.0.1:{args.port}/','version':current['version']}))
                return 0
        except (OSError,ValueError): pass
        time.sleep(.25)
    raise RuntimeError('Jarvis is not ready; inspect '+str(directory/'server.log'))


if __name__=='__main__': raise SystemExit(main())
