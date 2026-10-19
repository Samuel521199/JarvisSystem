"""Bundled Python/Web with personal state, verified slots and startup fallback."""
import argparse
from datetime import datetime,timezone
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import uuid
import zipfile

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'runtime/node-host'),str(ROOT/'tools')]
from jarvis_core.service import CoreService
from jarvis_core import __version__
from jarvis_core.chat import ChatService
from jarvis_core.conversations import ConversationStore
from jarvis_core.persona import PersonaStore
from jarvis_core.releases import RuntimeSlots
from k2_state_fingerprint import fingerprint
from release_bundle import verify

WEB_SCRIPT=r'''
import sys,json,threading,urllib.request
from pathlib import Path
root=Path(sys.argv[1]);sys.path[:0]=[str(root/'runtime/node-host'),str(root/'apps/web')]
from jarvis_core.service import CoreService
from jarvis_core.chat import ChatService
from jarvis_core.persona import PersonaStore
from jarvis_core.continuity import ContinuityStore
from server import create_server
from jarvis_core.network_policy import NetworkPolicy,activate_process
core=CoreService(sys.argv[2]);chat=ChatService(core)
activate_process(core.data_dir)
assert NetworkPolicy(core.data_dir).snapshot()['offline']
assert PersonaStore(core).snapshot()['preferred_name']=='验证称呼'
assert len(ContinuityStore(core).list()['records'])==1
server=create_server(core=core,chat=chat,port=0)
t=threading.Thread(target=server.serve_forever,kwargs={'poll_interval':.01},daemon=True);t.start()
try:
 base='http://127.0.0.1:'+str(server.server_port)
 opener=urllib.request.build_opener(urllib.request.ProxyHandler({}))
 with opener.open(base+'/') as response:html=response.read().decode('utf-8')
 assert 'persona.js' in html
 with opener.open(urllib.request.Request(base+'/api/persona',headers={'X-Jarvis-Nonce':server.nonce})) as response:profile=json.load(response)
 assert profile['preferred_name']=='验证称呼' and profile['schema_version']==2
 result=chat.reply('/计算 14*3');assert result['calculation']['exact']=={'numerator':'42','denominator':'1'}
 assert '测试偏好' in chat.reply('查看记忆',personal_context={'temporary':False},memory_context={'enabled':True,'project_id':None})['text']
 print(json.dumps({'web_ready':True,'profile_revision':profile['revision'],'calculation':42,'version':core.status()['version'],'python':sys.executable}))
finally:server.shutdown();server.server_close();t.join(3)
'''


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('archive',type=Path);parser.add_argument('--output',type=Path,required=True);args=parser.parse_args()
    if args.output.exists():parser.error('Evidence exists')
    original=verify(args.archive);assert original['version']==__version__
    report={'status':'running','version':original['version'],'captured_at':datetime.now(timezone.utc).isoformat(),
            'archive':str(args.archive),'archive_sha256':hashlib.sha256(args.archive.read_bytes()).hexdigest(),
            'limits':['Two slots of the same compatible runtime, not arbitrary old-schema downgrade.',
                      'Synthetic personal state, installed Windows/Edge environment; optional model/voice weights are not bundled.',
                      'Real startup fallback before business effects; no hot replacement or post-effect automatic replay.']}
    try:
        with tempfile.TemporaryDirectory(prefix='jarvis-k2-package-') as temporary:
            base=Path(temporary);source=base/'sample';source.mkdir();(source/'fixture.txt').write_bytes(b'abc')
            core=CoreService(base/'data');core.initialize(source);chat=ChatService(core);cid=uuid.uuid4().hex
            command='保存接续：验收=已经验证打包｜继续核对回退'
            ConversationStore(core).put(cid,{'revision':0,'document':{'title':'包验证','project_id':None,'context_note':'','messages':[
                {'role':'user','content':command,'meta':'','short_meta':'','attachments_omitted':False,'incomplete':False,'personal_control':True}]}})
            assert chat.reply(command,personal_context={'temporary':False,'source':{'conversation_id':cid,'message_index':0}},memory_context={'enabled':True,'project_id':None})['status']=='SUCCEEDED'
            assert chat.reply('记住：测试偏好=简洁中文',personal_context={'temporary':False},memory_context={'enabled':True,'project_id':None})['status']=='SUCCEEDED'
            PersonaStore(core).change('preferred_name','验证称呼',request_id=uuid.uuid4().hex)
            from jarvis_core.network_policy import NetworkPolicy
            NetworkPolicy(core.data_dir).change(True,0)
            task=core.inventory(request_id='package-preserved-task');assert task['action']['status']=='CONFIRMED'
            # Baseline owns a durable journal before the snapshot; a new Host may
            # change its owner but must not manufacture or lose a business receipt.
            from jarvis_core.dialogue_journal import DialogueJournal
            DialogueJournal(ConversationStore(core),uuid.uuid4().hex)
            # Compare like-for-like Host lifecycles. Lazy empty optional tables
            # first created by either current source or the package are expected;
            # every previously existing business row must still be identical.
            initialized_before=fingerprint(core.data_dir)
            sys.path.insert(0,str(ROOT/'apps/web'))
            from server import create_server
            baseline_server=create_server(core=core,chat=chat,port=0)
            baseline_server.server_close()
            initialized_after=fingerprint(core.data_dir)
            for name,store in initialized_before.items():
                if store['present']:
                    assert initialized_after[name]['present']
                    for table,value in store['tables'].items():assert initialized_after[name]['tables'][table]==value
            report['baseline_host_initialization']={'before':initialized_before,'after':initialized_after,'existing_rows_preserved':True}
            before=fingerprint(core.data_dir)
            variant=base/'variant.zip';manifest=json.loads(json.dumps(original))
            with zipfile.ZipFile(args.archive) as source_zip,zipfile.ZipFile(variant,'w',zipfile.ZIP_DEFLATED) as target:
                for name in original['files']:
                    raw=source_zip.read(name)
                    if name=='source/README.md':raw+=b'\nSynthetic second-slot package fixture.\n'
                    manifest['files'][name]={'size':len(raw),'sha256':hashlib.sha256(raw).hexdigest()};target.writestr(name,raw)
                target.writestr('release.json',json.dumps(manifest).encode())
            slots=RuntimeSlots(base/'slots');a=slots.install(args.archive);b=slots.install(variant)
            report['health']=[slots.health(entry['id']) for entry in (a,b)]
            assert all(row['state']=='verified' for row in report['health']),report['health']
            runs=[]
            for entry in (a,b,a):
                slots.select(entry['id'])
                command=[sys.executable,str(ROOT/'tools/runtime_releases.py'),'--root',str(slots.root),'start','--data-dir',str(core.data_dir),'--mode','status']
                result=subprocess.run(command,capture_output=True,text=True,encoding='utf-8',timeout=90)
                assert result.returncode==0,result.stderr or result.stdout
                slot=slots.slots/entry['id']
                web=subprocess.run([str(slot/'python/python.exe'),'-I','-B','-c',WEB_SCRIPT,str(slot/'source'),str(core.data_dir)],
                    cwd=slot,env=slots._environment(),capture_output=True,text=True,encoding='utf-8',timeout=45)
                assert web.returncode==0,web.stderr or web.stdout
                runs.append(json.loads(web.stdout))
                after=fingerprint(core.data_dir)
                if after!=before:report['state_mismatch']={'before':before,'after':after}
                assert after==before,'Business rows changed by packaged startup'
            slots.select(b['id'])
            (slots.slots/b['id']/'source/README.md').write_bytes(b'fault fixture')
            result=subprocess.run([sys.executable,str(ROOT/'tools/runtime_releases.py'),'--root',str(slots.root),'start','--data-dir',str(core.data_dir),'--mode','status'],
                capture_output=True,text=True,encoding='utf-8',timeout=90)
            assert result.returncode==0,result.stderr
            assert slots.status()['active']==a['id'] and slots.status()['starts'][0]['fallback']
            assert fingerprint(core.data_dir)==before
            report.update(status='passed',runs=runs,personal_state_unchanged=True,corrupt_slot_fallback=True,business_fingerprints=before)
    except Exception as error:report.update(status='failed',error=repr(error));raise
    finally:
        args.output.parent.mkdir(parents=True,exist_ok=True);args.output.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({k:report[k] for k in ('status','version','personal_state_unchanged','corrupt_slot_fallback')},ensure_ascii=False))


if __name__=='__main__':main()
