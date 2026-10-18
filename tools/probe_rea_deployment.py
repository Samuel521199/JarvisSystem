"""One explicit local REA smoke task, retained as a usable example in Jarvis."""
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import re
import time
import uuid
import httpx

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__); parser.add_argument('--live', action='store_true')
    args = parser.parse_args()
    if not args.live: parser.error('--live required: adds a sample project, conversation and task to the local app')
    origin = 'http://127.0.0.1:18181'
    with httpx.Client(trust_env=False, timeout=20) as client:
        status = client.get(origin+'/api/status').json()
        if status['version'] != '0.1.45' or status.get('active_tasks') or status.get('active_chat_requests'):
            raise RuntimeError('Expected idle 0.1.45 host')
        nonce = re.search('nonce="([^"]+)"', client.get(origin).text)[1]
        headers = {'X-Jarvis-Nonce': nonce, 'Origin': origin}
        def api(path, payload=None):
            r = client.get(origin+path, headers=headers) if payload is None else client.post(origin+path, headers=headers, json=payload)
            r.raise_for_status(); return r.json()
        queue = api('/api/resources')['runtime']['queue']
        if queue.get('waiting') or queue.get('running') or queue.get('unreviewed_unknown'): raise RuntimeError('Existing work requires review')
        if queue['paused']:
            if queue.get('error') != 'restart_review': raise RuntimeError('Queue intentionally paused; not resumed')
            api('/api/tasks/queue', {'paused':False})
        skills = api('/api/skills'); skill = next(s for s in skills['entries'] if s['id']=='rea.software-analysis')
        if not skill['executable'] or skill['policy']['mode'] != 'auto': raise RuntimeError('REA not ready/default auto')
        directory = Path('H:/JarvisData/examples') / ('rea-analysis-' + uuid.uuid4().hex[:8]); directory.mkdir(parents=True)
        application = directory / 'application'; application.mkdir()
        sources = json.loads((ROOT/'artifacts/rea-review/probe.json').read_text(encoding='utf-8'))['fixture_sources']
        for name, content in sources.items(): (application/name).write_text(content, encoding='utf-8')
        project = api('/api/workspace/projects', {'path':str(directory)})
        cid = uuid.uuid4().hex
        prompt = '自建样例验证：分析 Electron 应用目录的模块结构、桥接 API 和 IPC 调用链，保存完整证据。'
        def message(role, content, **extra):
            return dict(role=role,content=content,meta='',short_meta='',attachments_omitted=False,incomplete=False,**extra)
        document = dict(title='REA 软件解析示例', project_id=project['id'], context_note='', messages=[message('user',prompt)])
        saved = api('/api/conversations/'+cid, {'revision':0,'document':document})
        task = api('/api/conversation-tasks/'+cid, {'mode':'skill','request_id':'web-'+uuid.uuid4().hex,
                    'prompt':prompt,'project_id':project['id'],'skill_id':'rea.software-analysis','target_path':'application','paths':[]})
        deadline = time.monotonic()+125
        while time.monotonic() < deadline:
            detail = api('/api/conversation-tasks/'+cid+'/'+task['task_id'])
            if detail['task']['status'] not in {'READY','RUNNING','CANCELLING'}: break
            time.sleep(.2)
        if detail['action_status'] != 'CONFIRMED': raise RuntimeError(json.dumps(detail.get('error',detail['task']),ensure_ascii=False))
        report = detail['report']
        assert report['analysis']['summary']['ipc']['paired_renderer_transmissions']==1
        assert report['checks']['model_calls']==0
        assert Path(report['output']['path']).read_text(encoding='utf-8') == report['text']
        document['messages'].append(message('assistant', '自建样例解析完成：1 个桥接 API、1 条 jarvis:sum 通道和静态配对。未运行样例代码、未调用模型。打开真实任务可查看报告并下载证据。', task_control=True, task_ref=task['task_id']))
        api('/api/conversations/'+cid, {'revision':saved['revision'],'document':document})
        record = {'version':status['version'],'observed_at':datetime.now(timezone.utc).isoformat(),'status':'passed',
                  'instance_id':status['instance_id'],'project':project,'conversation_id':cid,'task_id':task['task_id'],
                  'ui_assets':status['ui_assets'],'model_calls':0,'report':report}
        (ROOT/'evals/reports/rea-skill-deployment-2026-10-18.json').write_text(json.dumps(record,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
        print(json.dumps({k:v for k,v in record.items() if k not in {'report','project'}},ensure_ascii=False))
        print('Report: '+report['output']['path'])


if __name__ == '__main__': main()
