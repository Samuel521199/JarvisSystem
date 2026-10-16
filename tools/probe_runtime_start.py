"""Exercise real packaged startup and corruption recovery with synthetic data."""
import argparse
from contextlib import closing
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'runtime/node-host'))
from jarvis_core.releases import RuntimeSlots
from release_bundle import build,verify,sha


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('previous',type=Path)
    parser.add_argument('candidate',type=Path)
    args=parser.parse_args()
    if args.candidate.exists():
        manifest=verify(args.candidate)
        package={'version':manifest['version'],'path':str(args.candidate.absolute()),
                 'sha256':sha(args.candidate.read_bytes()),'files':len(manifest['files']),
                 'bytes':args.candidate.stat().st_size}
    else:package=build(args.candidate)
    with tempfile.TemporaryDirectory(prefix='jarvis-startup-probe-') as temporary:
        base=Path(temporary);data=base/'data';sample=base/'input';sample.mkdir()
        (sample/'sample.txt').write_text('synthetic startup recovery fixture',encoding='utf-8')
        slots=RuntimeSlots(base/'runtime')
        old=slots.install(args.previous);new=slots.install(args.candidate)
        for item in (old,new):
            assert slots.health(item['id'])['state']=='verified'
            slots.select(item['id'])
        candidate=slots.slots/new['id'];fallback=slots.slots/old['id']
        def cli(*arguments):
            response=subprocess.run([str(candidate/'python/python.exe'),'-I','-B',
                str(candidate/'source/apps/cli/main.py'),*arguments,'--data-dir',str(data)],
                env=slots._environment(),capture_output=True,text=True,encoding='utf-8',timeout=30)
            assert response.returncode==0,response.stderr
            return json.loads(response.stdout)
        cli('init','--allowed-root',str(sample))
        confirmed=cli('inventory','--request-id','startup-confirmed')
        cli('inventory','--request-id','startup-waiting','--prepare-only')
        def business():
            databases={}
            for relative in ('control.db','safety/control.db'):
                with closing(sqlite3.connect((data/relative).as_uri()+'?mode=ro',uri=True)) as db:
                    databases[relative]='\n'.join(db.iterdump())
            artifacts={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in (data/'artifacts').iterdir()}
            return {'databases':databases,'artifacts':artifacts}
        before=business()
        def invoke():
            response=subprocess.run([sys.executable,'-B',str(ROOT/'tools/runtime_releases.py'),
                '--root',str(slots.root),'start','--data-dir',str(data),'--mode','status'],
                env={**os.environ,'PYTHONUTF8':'1'},capture_output=True,text=True,encoding='utf-8',timeout=150)
            return response
        healthy=invoke();assert healthy.returncode==0,healthy.stderr
        active_start=slots.status()['starts'][0]
        assert not active_start['fallback'] and active_start['selected']==new['id']
        assert json.loads(healthy.stdout)['version']==new['version']
        assert business()==before
        (candidate/'source/README.md').write_text('synthetic corruption',encoding='utf-8')
        recovered=invoke();assert recovered.returncode==0,recovered.stderr
        fallback_start=slots.status()['starts'][0]
        assert fallback_start['fallback'] and fallback_start['selected']==old['id']
        assert json.loads(recovered.stdout)['version']==old['version']
        assert business()==before
        assert slots.status()['active']==old['id']
        (fallback/'source/README.md').write_text('second synthetic corruption',encoding='utf-8')
        failed=invoke();assert failed.returncode==2,failed.stdout
        failed_start=slots.status()['starts'][0]
        assert failed_start['status']=='failed' and len(failed_start['attempts'])==2
        assert not failed_start['selection_committed']
        assert slots.status()['active']==old['id'] and business()==before
        report={'captured_at':datetime.now(timezone.utc).isoformat(),'status':'passed','package':package,
            'versions':[old['version'],new['version']], 'healthy_start':active_start,
            'recovered_start':fallback_start,'both_unusable':failed_start,
            'business_data_unchanged':True,'tasks_preserved':2,
            'confirmed_artifact':confirmed['artifact']['digest'],
            'limits':['Synthetic v2 data; default service not modified.',
                      'Only pre-launch integrity/health failures trigger one previous-version attempt.',
                      'No process-crash watchdog, machine-wide network disconnect or schema downgrade.']}
    output=Path(os.environ['LOCALAPPDATA'])/'Jarvis/data/diagnostics/runtime-start/result.json'
    output.parent.mkdir(parents=True,exist_ok=True)
    output.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps({'status':report['status'],'versions':report['versions'],'report':str(output),'package':package}))


if __name__=='__main__':main()
