"""Cold-start and slot-recovery probe using the bundled Python, synthetic data only."""
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile

from release_bundle import build, extract, verify

SCRIPT = r'''
import sys,json
from pathlib import Path
def no_network(event,args):
    if event in {'socket.connect','socket.connect_ex','socket.getaddrinfo'}: raise RuntimeError('network disabled by probe')
sys.addaudithook(no_network)
root=Path(sys.argv[1]);sys.path.insert(0,str(root/'runtime/node-host'))
from jarvis_core.service import CoreService
from jarvis_core.worker import verify_bundle
import cryptography
import httpx,jsonschema,google.auth,requests
core=CoreService(Path(sys.argv[2]))
if sys.argv[3]=='first':
    core.initialize(root/'tests/fixtures/workspace')
    record=core.inventory(request_id='packaged-inventory')
    assert record['action']['status']=='CONFIRMED',record
    core._verify_artifact(record['artifact'])
    from jarvis_core.coding_js import Runner
    values,evidence=Runner().run({'scene.js':'function transform(data){return String(data.phase+1);}'},'scene.js',[{'phase':3}],lambda:None)
    assert values==['4'] and evidence['lpac']
    from jarvis_core.coding_build import build
    from jarvis_core.evolution.runner import IsolatedRunner
    artifact=build({'tool/__init__.py':'','tool/run.py':'def transform(data):\n    return str(sum(data))\n'},'tool/run.py','sha256:'+'0'*64,'python-package-v1')
    assert IsolatedRunner().run_build(artifact,[[1,2]],lambda:None)[0]==['3']
    from jarvis_core.team_tasks import TeamTaskService
    from jarvis_core.team_protocol import validate
    TeamTaskService(core)
    assert validate({'prompt':'Package smoke','criteria':['bounded'],
                     'planner_model':'local::fixture','reviewer_model':'local::fixture'})['criteria']==['bounded']
    sys.path.insert(0,str(root/'adapters/models/provider-native'))
    from jarvis_core.federation import Federation
    sharing=Federation(core)
    assert not sharing.status()['initialized']
    sharing.initialize()
    assert sharing.status()['fingerprint'] and sharing.status()['endpoint'] is None
    from jarvis_core.federation_lifecycle import make_export, validate_export
    identity=sharing._identity().load()
    data={'id':'a'*32,'label':'Package probe','members':{sharing.node:identity.pem},'peer':None,'items':{}}
    assert validate_export(make_export(data,identity))['space']==data
    from jarvis_core.federation_access import context, empty_policy, destination
    assert not empty_policy()['providers']
    assert context(None)[0]['references']==[]
    from jarvis_models.gateway import read_config
    assert len(destination(read_config(root/'config/model-profiles/providers.json'),'local'))==64
    core.stop('synthetic release recovery probe')
else:
    state=core.status();assert state['stopped']
    assert len(state['tasks'])==1
    record=core.ledger.record(task_id=state['tasks'][0]['task_id'])
    core._verify_artifact(record['artifact'])
    assert record['action']['status']=='CONFIRMED'
print(json.dumps({'executable':sys.executable,'version':core.status()['version'],'stopped':core.status()['stopped'],
                  'task_id':record['task']['task_id'],'artifact_digest':record['artifact']['digest'],
                  'worker_manifest':verify_bundle()[1]['manifest_sha256'],'network':'Python audit hook denies connect/DNS; not an OS network isolation test'}))
'''


def main():
    archive=Path(sys.argv[1]).absolute()
    package=build(archive)
    results=[]
    with tempfile.TemporaryDirectory(prefix='jarvis-package-probe-') as directory:
        base=Path(directory)
        # Separate complete runtime slots; no copying/mutating the user's state.
        for name,operation in (('candidate','first'),('fallback','reopen')):
            slot=base/name;extract(archive,slot)
            env={k:os.environ[k] for k in ('SystemRoot','WINDIR','USERPROFILE','LOCALAPPDATA','TEMP','TMP') if k in os.environ}
            command=[str(slot/'python/python.exe'),'-I','-B','-c',SCRIPT,str(slot/'source'),str(base/'data'),operation]
            result=subprocess.run(command,capture_output=True,text=True,encoding='utf-8',env=env,cwd=slot,timeout=45,
                                  creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
            if result.returncode:raise RuntimeError(result.stderr or result.stdout)
            results.append(json.loads(result.stdout))
        assert results[0]['task_id']==results[1]['task_id']
        assert results[0]['artifact_digest']==results[1]['artifact_digest']
        assert all(r['stopped'] for r in results)
    report={'captured_at':datetime.now(timezone.utc).isoformat(),'status':'passed','package':package,'runs':results,
            'limitations':['Same-version fallback slot; no cross-version schema migration or protected service activation.',
                           'Python network-denial hook only; machine-wide disconnected boot not tested.',
                           'Optional browser/speech, model weights, owner keys and live state are excluded.']}
    output=Path(sys.argv[2]).absolute() if len(sys.argv)>2 else Path(os.environ['LOCALAPPDATA'])/'Jarvis/data/diagnostics/k1-progress/runtime-package.json'
    output.parent.mkdir(parents=True,exist_ok=True);output.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({'status':'passed','package':package,'report':str(output)}))


if __name__=='__main__':main()
