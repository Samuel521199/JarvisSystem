"""Two idle Host reloads verify a local calculator receipt across restart."""
import json
from pathlib import Path
import re
import time
import urllib.error
import uuid

from probe_dialogue_deployment import main as reload_idle,request,get,ROOT


def token():return re.search(r'<meta name="jarvis-nonce" content="([^"]+)"',request('/settings').decode())[1]


def main():
    first=reload_idle(None);nonce=token();state=get('/api/status')
    conv,ident=uuid.uuid4().hex,uuid.uuid4().hex
    doc={'title':'回复恢复验证 · 本机','project_id':None,'context_note':'','messages':[
        {'role':'user','content':'/计算 14*3','meta':'','short_meta':'','incomplete':False,'attachments_omitted':False,'reply_ref':ident}]}
    request('/api/conversations/'+conv,{'revision':0,'document':doc},nonce)
    payload={'instance_id':state['instance_id'],'conversation_id':conv,'request_id':ident,
             'chat':{'message':'/计算 14*3','personal_context':{'temporary':False}}}
    request('/api/dialogue/turns',payload,nonce)
    path='/api/dialogue/recover/'+ident+'?conversation_id='+conv
    end=time.monotonic()+10
    while time.monotonic()<end:
        receipt=get(path,nonce)
        if receipt['finished']:break
        time.sleep(.05)
    else:raise AssertionError('Calculator reply not finished')
    assert receipt['durable'] and receipt['status']=='SUCCEEDED'
    assert receipt['result']['calculation']['exact']=={'numerator':'42','denominator':'1'}
    second=reload_idle(None);nonce=token();recovered=get(path,nonce)
    assert recovered['origin_instance_id']==state['instance_id']
    assert recovered['instance_id']!=state['instance_id'] and recovered['result']==receipt['result']
    current=get('/api/status')['instance_id']
    repeated=json.loads(request('/api/dialogue/turns',{**payload,'instance_id':current},nonce))
    assert repeated['result']==receipt['result']
    assert get('/api/resources',nonce)['runtime']['counters']['calculation_completed']==1
    # Remove only the test conversation just created here, through its normal API.
    request('/api/conversations/'+conv+'/delete',{'revision':1},nonce)
    try:get(path,nonce)
    except urllib.error.HTTPError as exc:assert exc.code==404
    else:raise AssertionError('Deleted reply still accessible')
    final=get('/api/status');assert final['core_ready'] and not final['active_tasks'] and not final['active_chat_requests']
    report=dict(status='SUCCEEDED',source_version=final['version'],first_reload=first,second_reload=second,
        persistent_reply_survived_restart=True,same_id_not_reexecuted=True,deleted_only_self_created_conversation=conv,
        deleted_reply_unavailable=True,recovery_state=get('/api/resources',nonce)['runtime']['dialogue']['recovery'],cloud_calls=0,
        limits='Original local data directory. Only self-created calculator/archive test record; no cloud calls, microphone or independent Dialogue process.')
    (ROOT/'evals/reports/dialogue-recovery-deployment-2026-10-18.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps({'status':report['status'],'version':final['version'],'recovered_after_restart':True,'no_reexecution':True,'test_conversation_deleted':True}))


if __name__=='__main__':main()
