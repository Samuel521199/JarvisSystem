"""Idle graceful deployment plus one explicit-provider, temporary model reply."""
import hashlib
import json
from pathlib import Path
import re
import sys
import time
import uuid

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from tools.probe_dialogue_deployment import main as reload_idle,request,get


def main(report_name='conversation-lanes-deployment-2026-10-18.json'):
    reload_report=reload_idle(None)
    token=re.search(r'<meta name="jarvis-nonce" content="([^"]+)"',request('/settings').decode())[1]
    state=get('/api/status')
    before=get('/api/resources',token)['runtime']['dialogue_processes']
    assert before['enabled'] and before['active']==0
    background=get('/api/resources',token)['runtime']['background_processes']
    assert background['enabled'] and background['capacity']==1 and background['active']==0
    provider=get('/api/models')['default_provider']
    value={'instance_id':state['instance_id'],'conversation_id':uuid.uuid4().hex,'request_id':uuid.uuid4().hex,
           'chat':{'message':'请仅回答：连接正常。','provider':provider,'personal_context':{'temporary':True}}}
    started=time.monotonic()
    request('/api/dialogue/turns',value,token)
    path='/api/dialogue/turns/'+value['request_id']+'?conversation_id='+value['conversation_id']+'&instance_id='+value['instance_id']
    seen=[]
    while time.monotonic()-started<120:
        current=get('/api/resources',token)['runtime']['dialogue_processes']
        if current['active']:seen.append(current)
        receipt=get(path,token)
        if receipt.get('finished'):break
        time.sleep(.15)
    else:raise AssertionError('Live reply did not finish')
    result=receipt['result']
    assert result['status']=='SUCCEEDED', {k:result.get(k) for k in ('status','error','error_category')}
    assert result['provider']==provider and result['text'].strip()
    assert not receipt['durable']
    after=get('/api/resources',token)['runtime']['dialogue_processes']
    assert after['active']==0 and after['completed']==before['completed']+1
    assert seen,'No owned child observed'
    assert any(p['phase']=='model' for sample in seen for p in sample['processes'])
    paths=['runtime/node-host/jarvis_core/dialogue_process.py','runtime/node-host/jarvis_core/dialogue_worker.py',
           'runtime/node-host/jarvis_core/chat.py','runtime/node-host/jarvis_core/turns.py','apps/web/server.py',
           'runtime/node-host/jarvis_core/sample_tasks.py','runtime/node-host/jarvis_core/skill_tasks.py',
           'runtime/node-host/jarvis_core/rea_explanation.py','adapters/computer-use/jarvis_computer/web.py',
           'apps/web/resources.js','tools/probe_dialogue_process_deployment.py','tools/probe_dialogue_deployment.py']
    report={'status':'SUCCEEDED','source_version':state['version'],'reload':reload_report,'cloud_calls':1,
            'provider':provider,'model':result['model'],'usage':result.get('usage'), 'billing':result.get('billing'),
            'reply_elapsed_seconds':round(time.monotonic()-started,3),'temporary':True,'observed_process':seen[-1],
            'idle_after':after,'background_idle':background,'text_length':len(result['text']),
            'limits':'One real temporary text request, no task or personal write; cold-call overhead and provider latency are not separated.',
            'source_sha256':{p:hashlib.sha256((ROOT/p).read_bytes()).hexdigest() for p in paths}}
    (ROOT/'evals/reports'/report_name).write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(report,ensure_ascii=False))


if __name__=='__main__':main()
