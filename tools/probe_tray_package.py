"""Run the real tray from a complete runtime package, using synthetic data only."""
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import time
from urllib.request import ProxyHandler, build_opener

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'apps/tray'),str(ROOT/'runtime/node-host')]
from companion import NamedEvent
from jarvis_core.releases import RuntimeSlots
from release_bundle import verify, sha


def run(archive):
    manifest=verify(archive)
    report={'version':manifest['version'],'captured_at':datetime.now(timezone.utc).isoformat(),
            'package_sha256':sha(archive.read_bytes()),'status':'incomplete_or_failed'}
    changed=[]
    for path,item in manifest['files'].items():
        if path.startswith(('source/apps/','source/runtime/','source/adapters/','source/config/')):
            source=ROOT/path[len('source/'):]
            if not source.is_file() or sha(source.read_bytes())!=item['sha256']:changed.append(path)
    if changed: raise AssertionError('Candidate runtime sources differ: '+str(changed))
    report['runtime_sources_match']=True
    with tempfile.TemporaryDirectory(prefix='jarvis-packaged-tray-') as temporary:
        base=Path(temporary);slots=RuntimeSlots(base/'runtime');release=slots.install(archive)
        root=slots.slots/release['id'];data=base/'data';sample=base/'input';sample.mkdir()
        command=[str(root/'python/python.exe'),'-I','-B',str(root/'source/apps/cli/main.py')]
        init=subprocess.run([*command,'init','--allowed-root',str(sample),'--data-dir',str(data)],
            capture_output=True,text=True,encoding='utf-8',timeout=30,env=slots._environment(),creationflags=subprocess.CREATE_NO_WINDOW)
        if init.returncode:raise AssertionError(init.stderr)
        with socket.socket() as sock:
            sock.bind(('127.0.0.1',0));port=sock.getsockname()[1]
        opener=build_opener(ProxyHandler({}));state=None
        with (base/'host.log').open('wb') as log:
            child=subprocess.Popen([str(root/'python/python.exe'),'-I','-B',str(root/'source/apps/web/server.py'),
                '--data-dir',str(data),'--port',str(port)],env=slots._environment(),
                stdin=subprocess.DEVNULL,stdout=log,stderr=log,creationflags=subprocess.CREATE_NO_WINDOW)
            try:
                deadline=time.monotonic()+30
                while time.monotonic()<deadline and child.poll() is None:
                    try:
                        with opener.open(f'http://127.0.0.1:{port}/api/status',timeout=1) as response:status=json.load(response)
                        state=json.loads((data/'diagnostics/tray/state.json').read_text(encoding='utf-8'))
                        if state['state']=='standby' and state['icon_visible'] and state['instance_id']==status['instance_id']:break
                    except (OSError,ValueError):pass
                    time.sleep(.25)
                else:raise AssertionError('Packaged tray did not reach standby')
                if state['owner_pid']!=child.pid or status['version']!=manifest['version']:raise AssertionError('Host identity differs')
                report['status_response']=status;report['tray']=state
                event=NamedEvent('Local\\Jarvis.Tray.'+state['instance_id']+'.quit')
                try:event.set()
                finally:event.close()
                child.wait(timeout=20)
                report['exit_code']=child.returncode
                if child.returncode:raise AssertionError('Packaged Host did not exit cleanly')
                report['status']='passed'
            finally:
                if child.poll() is None:
                    # This exact fresh subprocess only, never a discovered PID.
                    child.terminate();child.wait(timeout=10)
        report['host_log']=(base/'host.log').read_text(encoding='utf-8',errors='replace')
    report['limits']='Real bundled Python/Windows Forms on this development PC; no cloud requests, machine-wide offline, long-running watchdog or real user data.'
    return report


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('archive',type=Path)
    parser.add_argument('--output',type=Path,default=ROOT/'evals/reports/tray-package.json')
    args=parser.parse_args();report=run(args.archive.resolve())
    args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps({'status':report['status'],'version':report['version'],'report':str(args.output)}))


if __name__=='__main__':main()
