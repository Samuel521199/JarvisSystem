"""Idle-instance graceful reload and deterministic reply receipts; no paid models."""
import ctypes as C
from ctypes import wintypes as W
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys
import time
import urllib.error
import urllib.request
import uuid

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'runtime/node-host'))
from jarvis_core import __version__
BASE='http://127.0.0.1:18181'


def request(path,payload=None,token=None):
    headers={'Origin':BASE}
    if token:headers['X-Jarvis-Nonce']=token
    if payload is not None:headers['Content-Type']='application/json'
    data=None if payload is None else json.dumps(payload).encode()
    return urllib.request.urlopen(urllib.request.Request(BASE+path,data=data,headers=headers),timeout=15).read()


def get(path,token=None):return json.loads(request(path,token=token))


def stop_idle(before):
    token=re.search(r'<meta name="jarvis-nonce" content="([^"]+)"',request('/settings').decode())[1]
    assert before['app']=='Jarvis' and before['core_ready'] and not before['stopped']
    assert before['active_tasks']==before['active_chat_requests']==0,'Active work; do not reload'
    assert not get('/api/modules',token)['maintenance_busy'] and not get('/api/evolution',token)['busy']
    queue=get('/api/resources',token)['runtime']['queue']
    assert queue and not queue.get('unavailable') and not queue['waiting'] and not queue['running'] and not queue.get('unreviewed_unknown'),'Queue needs attention; do not reload'
    assert not queue['paused'] or queue.get('error')=='restart_review','Preserve an intentional queue pause'
    for path in ['/api/speech/primary','/api/speech/fast','/api/speech']:
        assert not get(path,token)['busy']
    kernel=C.WinDLL('kernel32',use_last_error=True)
    kernel.OpenEventW.argtypes=[W.DWORD,W.BOOL,W.LPCWSTR];kernel.OpenEventW.restype=W.HANDLE
    kernel.SetEvent.argtypes=[W.HANDLE];kernel.SetEvent.restype=W.BOOL
    kernel.CloseHandle.argtypes=[W.HANDLE];kernel.CloseHandle.restype=W.BOOL
    handle=kernel.OpenEventW(2,False,'Local\\Jarvis.Tray.'+before['instance_id']+'.quit')
    if not handle:raise C.WinError(C.get_last_error())
    try:
        if not kernel.SetEvent(handle):raise C.WinError(C.get_last_error())
    finally:kernel.CloseHandle(handle)
    deadline=time.monotonic()+15
    while time.monotonic()<deadline:
        try:get('/api/status')
        except (OSError,urllib.error.URLError):break
        time.sleep(.2)
    else:raise AssertionError('Previous instance did not exit normally')


def main(report_name='dialogue-deployment-2026-10-18.json'):
    # Validate the target before stopping anything. A refused connection means
    # this instance is absent; timeouts and other errors are not idle evidence.
    result=subprocess.run([sys.executable,str(ROOT/'tools/start_jarvis.py'),'--check','--no-browser'],cwd=ROOT,capture_output=True,text=True,encoding='utf-8',timeout=15,check=True)
    launch=json.loads(result.stdout)
    expected='C:/Users/samuel/AppData/Local/Packages/OpenAI.Codex_2p2nqsd0c76g0/LocalCache/Local/Jarvis/data'
    assert Path(launch['data_dir']).resolve()==Path(expected).resolve()
    try:before=get('/api/status')
    except urllib.error.URLError as exc:
        if not isinstance(exc.reason,ConnectionRefusedError):raise
        before={}
    if before:stop_idle(before)
    # Launcher/PowerShell diagnostics may use the Windows OEM encoding. Keep
    # bytes here; deployment is verified through the HTTP instance below.
    subprocess.run([sys.executable,str(ROOT/'tools/start_jarvis.py'),'--no-browser'],cwd=ROOT,capture_output=True,timeout=45,check=True)
    token=re.search(r'<meta name="jarvis-nonce" content="([^"]+)"',request('/settings').decode())[1]
    after=get('/api/status');assert after['version']==__version__ and after['instance_id']!=before.get('instance_id') and after['core_ready']
    hashes={}
    for asset in ['dialogue.js','resources.js','workspace.js','conversation_tasks.js','mcp_manager.js']:
        digest=hashlib.sha256(request('/'+asset)).hexdigest()
        assert digest==hashlib.sha256((ROOT/'apps/web'/asset).read_bytes()).hexdigest();hashes[asset]=digest
    assert (ROOT/'apps/web/workspace.css').read_bytes() in request('/')
    def post(value):return json.loads(request('/api/dialogue/turns',value,token))
    def poll(value):
        path='/api/dialogue/turns/'+value['request_id']+'?conversation_id='+value['conversation_id']+'&instance_id='+value['instance_id']
        deadline=time.monotonic()+8
        while time.monotonic()<deadline:
            row=get(path,token)
            if row['finished']:return row
            time.sleep(.05)
        raise AssertionError('Deterministic reply did not complete')
    value=dict(instance_id=after['instance_id'],conversation_id=uuid.uuid4().hex,request_id=uuid.uuid4().hex,chat={'message':'/计算 (19+23)*2'})
    tick=time.perf_counter();post(value);admit_ms=(time.perf_counter()-tick)*1000
    final=poll(value);assert final['status']=='SUCCEEDED' and final['result']['calculation']['exact']=={'numerator':'84','denominator':'1'}
    assert post(value)['result']==final['result']
    personal={**value,'request_id':uuid.uuid4().hex,'chat':{'message':'查看交流设置'}}
    post(personal);assert poll(personal)['result'].get('personal')
    cancel={k:v for k,v in value.items() if k!='chat'};cancel['request_id']=uuid.uuid4().hex
    request('/api/dialogue/cancel',cancel,token)
    assert post({**cancel,'chat':{'message':'/计算 2+2'}})['status']=='CANCELLED'
    try:post({**value,'instance_id':before.get('instance_id') or uuid.uuid4().hex})
    except urllib.error.HTTPError as exc:assert exc.code==409
    else:raise AssertionError('Previous instance was accepted')
    state=get('/api/resources',token)['runtime'];assert state['dialogue']['active']==0
    assert state['counters'].get('calculation_completed')==1
    current_queue=state['queue']
    assert not current_queue['waiting'] and not current_queue['running'] and not current_queue.get('unreviewed_unknown')
    if current_queue['paused']:
        assert current_queue['error']=='restart_review','Preserve an intentional queue pause'
        request('/api/tasks/queue',{'paused':False},token)
    assert not get('/api/resources',token)['runtime']['queue']['paused']
    backups={path:get(path,token)['state'] for path in ['/api/speech/fast','/api/speech']}
    assert all(s=='stopped' for s in backups.values())
    report=dict(status='SUCCEEDED',source_version=after['version'],data_dir=launch['data_dir'],previous_version=before.get('version'),
        previous_instance=before.get('instance_id'),current_instance=after['instance_id'],idle_graceful_reload=bool(before),startup_from_absent=not before,served_sha256=hashes,
        calculation='84',personal_read_only=True,duplicate_did_not_repeat_calculation=True,cancel_before_submit=True,restart_fence=True if before else None,instance_fence=True,
        empty_restart_queue_reviewed_and_resumed=True,
        admission_ms=round(admit_ms,3),backups=backups,cloud_calls=0,
        limits='One local calculator and personal-settings query; no paid model, microphone, task replay, persistent dialogue recovery or physical voice timing.')
    if report_name:
        (ROOT/'evals/reports'/report_name).write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(report,ensure_ascii=False))
    return report


if __name__=='__main__':main()
