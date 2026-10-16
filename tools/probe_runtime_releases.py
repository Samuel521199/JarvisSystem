"""Exercise real A -> B -> A slots against one synthetic data directory."""
import argparse
from contextlib import closing
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import subprocess
import sqlite3
import sys
import tempfile

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'runtime/node-host'))
from jarvis_core.releases import RuntimeSlots
from release_bundle import build, verify, sha


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('previous',type=Path)
    parser.add_argument('candidate',type=Path)
    args=parser.parse_args()
    if args.candidate.exists():
        manifest=verify(args.candidate)
        package={'version':manifest['version'],'path':str(args.candidate.absolute()),
                 'sha256':sha(args.candidate.read_bytes()),'files':len(manifest['files']),
                 'bytes':args.candidate.stat().st_size,'status':'candidate_verified'}
    else:
        package=build(args.candidate)
    with tempfile.TemporaryDirectory(prefix='jarvis-runtime-rollback-') as temporary:
        base=Path(temporary);runtime=base/'runtime';data=base/'data';sample=base/'input';sample.mkdir()
        (sample/'sample.txt').write_text('synthetic runtime rollback data',encoding='utf-8')
        slots=RuntimeSlots(runtime)
        previous=slots.install(args.previous);candidate=slots.install(args.candidate)
        health=[slots.health(entry['id']) for entry in (previous,candidate)]
        assert all(r['state']=='verified' for r in health),health
        slots.select(previous['id'])
        old=slots.slots/previous['id']
        env=slots._environment()
        init=subprocess.run([str(old/'python/python.exe'),'-I','-B',str(old/'source/apps/cli/main.py'),
                             'init','--data-dir',str(data),'--allowed-root',str(sample)],
                            capture_output=True,text=True,encoding='utf-8',env=env,timeout=30)
        assert init.returncode==0,init.stderr
        def control():
            with closing(sqlite3.connect((data/'safety/control.db').as_uri()+'?mode=ro',uri=True)) as db:
                return list(db.execute('SELECT node_id,epoch,stopped FROM state').fetchone())
        original_control=control()
        def invoke(mode):
            result=subprocess.run([sys.executable,'-B',str(ROOT/'tools/runtime_releases.py'),'--root',str(runtime),
                                   'run','--data-dir',str(data),'--mode',mode],
                                  capture_output=True,text=True,encoding='utf-8',env={**os.environ,'PYTHONUTF8':'1'},timeout=45)
            assert result.returncode==0,result.stderr or result.stdout
            return json.loads(result.stdout)
        first=invoke('inventory')
        slots.select(candidate['id'])
        second=invoke('inventory')
        before=invoke('status')
        selected=slots.select(rollback=True)
        after=invoke('status')
        assert selected['active']==previous['id']
        assert control()==original_control
        assert before['tasks']==after['tasks'] and len(after['tasks'])==2
        assert not before['stopped'] and not after['stopped']
        # A rejected corrupt candidate leaves the verified fallback selected.
        damaged=slots.slots/candidate['id']/'source/README.md'
        damaged.write_text('synthetic package corruption',encoding='utf-8')
        try:slots.select(candidate['id'])
        except ValueError:pass
        else:raise AssertionError('Corrupted package selected')
        assert slots.status()['active']==previous['id']
        result={'captured_at':datetime.now(timezone.utc).isoformat(),'status':'passed','package':package,
                'versions':[previous['version'],candidate['version'],after['version']],
                'health':health,'node_preserved':True,'tasks_preserved':2,'epoch_preserved':True,
                'artifacts':[first['artifact']['digest'],second['artifact']['digest']],
                'corrupt_candidate_rejected':True,'selection_generation':selected['generation'],
                'limitations':['Synthetic data only; existing 18181 service untouched.',
                    'Runtime health blocks connect/DNS with a Python audit hook, not a machine-wide network disconnect.',
                    'No database schema downgrade, protected supervisor, browser/speech dependency bundle or hot swap.']}
    output=Path(os.environ['LOCALAPPDATA'])/'Jarvis/data/diagnostics/runtime-continuity/releases.json'
    output.parent.mkdir(parents=True,exist_ok=True)
    output.write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps({'status':'passed','versions':result['versions'],'report':str(output),'package':package}))


if __name__=='__main__':main()
