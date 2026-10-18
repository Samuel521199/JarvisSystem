"""Explicit idle reload and retained 20-channel REA example; zero model calls."""
import argparse
import ctypes as C
from ctypes import wintypes as W
from datetime import datetime, timezone
import json
from pathlib import Path
import re
import subprocess
import sys
import time
import uuid
import httpx

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT/'tools'), str(ROOT/'runtime/node-host')]
from evaluate_rea_effectiveness import sources
from jarvis_core import __version__


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--live', action='store_true')
    args=parser.parse_args()
    if not args.live: parser.error('--live is required; reloads idle app and adds a retained example')
    origin='http://127.0.0.1:18181'
    with httpx.Client(trust_env=False,timeout=20) as client:
        def token(): return re.search('nonce="([^"]+)"',client.get(origin).text)[1]
        nonce=token()
        def api(path, payload=None):
            headers={'X-Jarvis-Nonce':nonce,'Origin':origin}
            response=client.get(origin+path,headers=headers) if payload is None else client.post(origin+path,headers=headers,json=payload)
            response.raise_for_status(); return response.json()
        before=api('/api/status')
        assert not before['stopped'] and not before['active_tasks'] and not before['active_chat_requests']
        queue=api('/api/resources')['runtime']['queue']
        assert not queue.get('waiting') and not queue.get('running') and not queue.get('unreviewed_unknown')
        assert not api('/api/modules')['maintenance_busy'] and not api('/api/evolution')['busy']
        for path in ('/api/speech/primary','/api/speech/fast','/api/speech'):
            assert not api(path)['busy']
        if before['version'] != __version__:
            assert not queue['paused'] or queue.get('error')=='restart_review', 'Preserve a manual queue pause'
            kernel=C.WinDLL('kernel32',use_last_error=True)
            kernel.OpenEventW.argtypes=[W.DWORD,W.BOOL,W.LPCWSTR];kernel.OpenEventW.restype=W.HANDLE
            kernel.SetEvent.argtypes=[W.HANDLE];kernel.SetEvent.restype=W.BOOL
            kernel.CloseHandle.argtypes=[W.HANDLE];kernel.CloseHandle.restype=W.BOOL
            handle=kernel.OpenEventW(2,False,'Local\\Jarvis.Tray.'+before['instance_id']+'.quit')
            if not handle: raise C.WinError(C.get_last_error())
            try:
                if not kernel.SetEvent(handle): raise C.WinError(C.get_last_error())
            finally: kernel.CloseHandle(handle)
            until=time.monotonic()+20
            while time.monotonic()<until:
                try: client.get(origin+'/api/status')
                except httpx.TransportError: break
                time.sleep(.2)
            else: raise RuntimeError('Old instance did not exit normally')
            launch=subprocess.run([sys.executable,'-X','utf8',str(ROOT/'tools/start_jarvis.py'),'--check','--no-browser'],cwd=ROOT,
                                  capture_output=True,text=True,encoding='utf-8',timeout=20,check=True)
            data=json.loads(launch.stdout)['data_dir']
            expected=Path('C:/Users/samuel/AppData/Local/Packages/OpenAI.Codex_2p2nqsd0c76g0/LocalCache/Local/Jarvis/data')
            assert Path(data).resolve()==expected.resolve()
            subprocess.run([sys.executable,'-X','utf8',str(ROOT/'tools/start_jarvis.py'),'--no-browser'],cwd=ROOT,
                           capture_output=True,text=True,encoding='utf-8',timeout=45,check=True)
            nonce=token()
        after=api('/api/status'); assert after['version']==__version__
        queue=api('/api/resources')['runtime']['queue']
        assert not queue.get('waiting') and not queue.get('running') and not queue.get('unreviewed_unknown')
        if queue['paused']:
            assert queue.get('error')=='restart_review' and not before.get('stopped')
            api('/api/tasks/queue',{'paused':False})
        # Read a pre-upgrade embedded receipt via the new endpoint, without replay.
        old=json.loads((ROOT/'evals/reports/rea-skill-deployment-2026-10-18.json').read_bytes())
        legacy=api('/api/skills/evidence/'+old['conversation_id']+'/'+old['task_id'])
        assert legacy['evidence']==old['report']['evidence']
        project_path=Path('H:/JarvisData/examples')/('rea-improvement-'+uuid.uuid4().hex[:8])
        app=project_path/'application'; (app/'dist').mkdir(parents=True)
        for name, content in sources(20).items():
            if name=='package.json':
                value=json.loads(content);value['main']='dist/main.js';content=json.dumps(value)
            (app/(name if name=='package.json' else 'dist/'+name)).write_text(content,encoding='utf-8')
        project=api('/api/workspace/projects',{'path':str(project_path)})
        cid=uuid.uuid4().hex
        prompt='分析这个自建 Electron 应用目录的 20 条 IPC 调用链，包含 dist 发布目录，保存报告并提供完整证据。'
        def message(role, content, **extra):
            return dict(role=role,content=content,meta='',short_meta='',attachments_omitted=False,incomplete=False,**extra)
        document=dict(title='REA 改进验证示例',project_id=project['id'],context_note='',messages=[message('user',prompt)])
        saved=api('/api/conversations/'+cid,{'revision':0,'document':document})
        task=api('/api/conversation-tasks/'+cid,{'mode':'skill','request_id':'web-'+uuid.uuid4().hex,
                    'prompt':prompt,'project_id':project['id'],'skill_id':'rea.software-analysis','target_path':'application','paths':[]})
        until=time.monotonic()+125
        while time.monotonic()<until:
            detail=api('/api/conversation-tasks/'+cid+'/'+task['task_id'])
            if detail['task']['status'] not in {'READY','RUNNING','CANCELLING'}: break
            time.sleep(.3)
        assert detail['action_status']=='CONFIRMED', detail.get('error')
        report=detail['report'];assert 'evidence_ref' in report and 'evidence' not in report
        assert report['analysis']['summary']['ipc']['paired_renderer_transmissions']==20
        assert Path(report['output']['path']).read_text(encoding='utf-8')==report['text']
        full=api('/api/skills/evidence/'+cid+'/'+task['task_id'])
        assert full['evidence']['evidence_id']==report['evidence_ref']['evidence_id']
        page=api('/api/skills/evidence/'+cid+'/'+task['task_id']+'?section=links&offset=40&limit=20')
        assert page['items'] and page['total']>40
        document['messages'].append(message('assistant','改进版已完成：20 条静态 IPC 配对，已包含 dist 发布目录。打开真实任务可查看报告、翻页浏览证据并下载完整结果。没有运行目标或调用模型。',task_control=True,task_ref=task['task_id']))
        api('/api/conversations/'+cid,{'revision':saved['revision'],'document':document})
        record={'version':after['version'],'observed_at':datetime.now(timezone.utc).isoformat(),'status':'passed',
                'before_instance':before['instance_id'],'instance_id':after['instance_id'],
                'legacy_receipt_readable':True,'conversation_id':cid,'task_id':task['task_id'],
                'project':project,'report':report,'ui_assets':after['ui_assets'],'model_calls':0,
                'target':'self-owned 20-channel dist fixture'}
        (ROOT/'evals/reports/rea-improvement-deployment-2026-10-18.json').write_text(json.dumps(record,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
        print(json.dumps({k:v for k,v in record.items() if k not in {'project','report'}},ensure_ascii=True))


if __name__=='__main__':main()
