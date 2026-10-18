"""Explicit idle-instance reload and local readout checks; no cloud requests."""
import ctypes as C
from ctypes import wintypes as W
import hashlib
import io
import json
from pathlib import Path
import re
import subprocess
import sys
import time
import urllib.error
import urllib.request
import uuid
import wave

ROOT=Path(__file__).resolve().parents[1]
BASE='http://127.0.0.1:18181'


def request(path,payload=None,token=None):
    headers={'Origin':BASE}
    if token:headers['X-Jarvis-Nonce']=token
    if payload is not None:headers['Content-Type']='application/json'
    data=None if payload is None else json.dumps(payload).encode()
    return urllib.request.urlopen(urllib.request.Request(BASE+path,data=data,headers=headers),timeout=15).read()


def get(path,token=None):return json.loads(request(path,token=token))


def main():
    token=re.search(r'<meta name="jarvis-nonce" content="([^"]+)"',request('/settings').decode())[1]
    before=get('/api/status')
    assert before['app']=='Jarvis' and not before['stopped']
    assert before['active_tasks']==before['active_chat_requests']==0
    assert not get('/api/modules',token)['maintenance_busy'] and not get('/api/evolution',token)['busy']
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
    else:raise AssertionError('Existing instance did not exit')
    result=subprocess.run([sys.executable,str(ROOT/'tools/start_jarvis.py'),'--check','--no-browser'],cwd=ROOT,capture_output=True,text=True,encoding='utf-8',timeout=15,check=True)
    launch=json.loads(result.stdout)
    expected='C:/Users/samuel/AppData/Local/Packages/OpenAI.Codex_2p2nqsd0c76g0/LocalCache/Local/Jarvis/data'
    assert Path(launch['data_dir']).resolve()==Path(expected).resolve()
    subprocess.run([sys.executable,str(ROOT/'tools/start_jarvis.py'),'--no-browser'],cwd=ROOT,capture_output=True,text=True,encoding='utf-8',timeout=40,check=True)
    token=re.search(r'<meta name="jarvis-nonce" content="([^"]+)"',request('/settings').decode())[1]
    after=get('/api/status');assert after['instance_id']!=before['instance_id'] and after['core_ready']
    asset_hash=hashlib.sha256(request('/readout.js')).hexdigest()
    assert asset_hash==hashlib.sha256((ROOT/'apps/web/readout.js').read_bytes()).hexdigest()
    assert (ROOT/'apps/web/readout.css').read_bytes() in request('/')
    ident=uuid.uuid4().hex
    try:request('/api/speech/readout/'+ident)
    except urllib.error.HTTPError as exc:assert exc.code==403
    else:raise AssertionError('Readout receipt lacked nonce protection')
    def post(payload):return json.loads(request('/api/speech/readout',payload,token))
    payload=dict(action='start',id=ident,text='[轻声]别担心，我在这里。[自然][开心]我们一起继续！',voice='serena',emotion='neutral',language='zh',direction='')
    tick=time.monotonic();view=post(payload);assert view['active'] and view['total']==2
    assert post(payload)['id']==ident
    clips=[]
    try:
        for index in range(view['total']):
            deadline=time.monotonic()+125
            while time.monotonic()<deadline:
                view=post(dict(action='next',id=ident,index=index))
                assert view['active'],view
                row=view['items'][index] if len(view['items'])>index else None
                if row and row['status']=='SUCCEEDED':break
                assert not row or row['status'] not in ('FAILED','CANCELLED'),row
                time.sleep(.15)
            else:raise AssertionError('Native speech deadline exceeded')
            assert post(dict(action='next',id=ident,index=index))['items'][index]['job_id']==row['job_id']
            raw=request(row['result']['audio_url'],token=token)
            with wave.open(io.BytesIO(raw),'rb') as audio:
                clips.append(dict(index=index,seconds=audio.getnframes()/audio.getframerate(),sample_rate=audio.getframerate(),channels=audio.getnchannels(),sha256=hashlib.sha256(raw).hexdigest()))
        complete=post(dict(action='finish',id=ident));assert not complete['active']
    finally:
        post(dict(action='stop',id=ident))
    value=get('/api/speech/primary',token);assert value['owned'] and not value['readout_active'] and not value['busy']
    newer=uuid.uuid4().hex;post(dict(payload,id=newer));post(dict(action='stop',id=ident))
    assert get('/api/speech/readout/'+newer,token)['active']
    post(dict(action='stop',id=newer))
    backups={path:get(path,token)['state'] for path in ['/api/speech/fast','/api/speech']}
    assert all(v=='stopped' for v in backups.values())
    final=get('/api/status');assert final['core_ready'] and not final['stopped']
    report=dict(status='SUCCEEDED',source_version=final['version'],data_dir=launch['data_dir'],graceful_idle_reload=True,
        previous_instance=before['instance_id'],current_instance=after['instance_id'],served_readout_sha256=asset_hash,
        embedded_readout_css_sha256=hashlib.sha256((ROOT/'apps/web/readout.css').read_bytes()).hexdigest(),nonce_protected=True,idempotent_start_and_next=True,old_stop_did_not_cancel_new_readout=True,clips=clips,
        two_clip_generation_including_load_seconds=time.monotonic()-tick,primary={k:value.get(k) for k in ['state','owned','pid','memory','gpu_memory','readout_active']},
        backups=backups,cloud_calls=0,prior_attempt=dict(status='FAILED',phase='model startup before worker log',explicit_reload_recovered=True,original_cause_unconfirmed=True,independent_reproduced_fix='Bind URL-safe token using --token=value to accept leading hyphens without reducing randomness'),limits='Original data directory, local native synthesis; no physical speaker timing, microphone, STT or universal quality claim.')
    (ROOT/'evals/reports/chat-readout-deployment-2026-10-18.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(dict(status='SUCCEEDED',source_version=final['version'],clips=len(clips),primary_ready=value['state']=='ready',backups=backups),ensure_ascii=False))


if __name__=='__main__':main()
