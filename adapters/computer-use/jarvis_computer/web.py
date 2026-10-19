"""Thin bounded web admission, using the core ledger as the only task authority."""
import importlib.util
import json
from pathlib import Path
import re

from jarvis_core.policy import CoreError, safe_path
from .protocol import ComputerError, validate_task, ROOT
from .service import ComputerService
from .planner import ModelPlanner
from .task_queue import ComputerQueue
from jarvis_core.sample_tasks import SampleTaskService
from jarvis_core.skill_tasks import SkillTaskService
from jarvis_core.mcp_tasks import McpTaskService
from jarvis_core.storage_budget import interactive


class ComputerWeb:
    def __init__(self, core, chat, *, service=None, metrics=None):
        self.core, self.chat = core, chat
        self.service = service or ComputerService(core,planner_factory=lambda scoped,model:
            ModelPlanner(scoped,model,config_path=getattr(chat,'config_path',None)))
        self.sample = SampleTaskService(core, config_path=getattr(chat, 'config_path', None), model_calls=getattr(chat,'background_models',None))
        self.skills = SkillTaskService(core, config_path=getattr(chat, 'config_path', None), model_calls=getattr(chat,'background_models',None))
        self.mcp = McpTaskService(core)
        self.queue = ComputerQueue(core, lambda: self.service, sample_executor=lambda: self.sample, skill_executor=lambda: self.skills, mcp_executor=lambda: self.mcp, metrics=metrics)

    def _validate(self, payload):
        if not isinstance(payload,dict) or set(payload)-{'request_id','mode','model','task'}:
            raise ComputerError('invalid_request','任务请求字段无效。')
        key=payload.get('request_id')
        if not isinstance(key,str) or not re.fullmatch(r'web-[a-f0-9]{32}',key):
            raise ComputerError('invalid_request','请求 ID 无效。')
        mode=payload.get('mode')
        if mode not in ('demo','scripted','custom'):
            raise ComputerError('invalid_request','请选择任务类型。')
        model=payload.get('model')
        if not isinstance(model,str) or model not in {'auto',*(m['model'] for m in self.chat.models().get('models',[])),*(m['provider']+'::'+m['model'] for m in self.chat.models().get('models',[]))}:
            raise ComputerError('invalid_request','请选择已注册模型。')
        if mode=='custom':
            task=validate_task(payload.get('task'))
            html=None
        else:
            if 'task' in payload:
                raise ComputerError('invalid_request','演示任务不接受外部内容。')
            task=json.loads((ROOT/'config/computer-use/demo-task.json').read_text(encoding='utf-8'))
            html=(ROOT/'apps/computer-use/demo.html').read_text(encoding='utf-8')
        return task, dict(request_id=key,model=model,scripted=mode=='scripted',demo_html=html)

    def submit(self, payload):
        self.core.assert_running()
        task, options = self._validate(payload)
        return self.queue.enqueue(task, options)

    def submit_task(self, payload, *, conversation_id=None):
        if isinstance(payload, dict) and payload.get('mode') == 'mcp':
            if not isinstance(payload.get('request_id'), str) or not re.fullmatch(r'web-[a-f0-9]{32}', payload['request_id']):
                raise ComputerError('invalid_request', 'MCP 任务请求编号无效。')
            args = {k: v for k, v in payload.items() if k not in {'request_id', 'mode'}}
            if conversation_id is not None: args['conversation_id'] = conversation_id
            return self.queue.enqueue_mcp(request_id=payload['request_id'], payload=args)
        if isinstance(payload, dict) and payload.get('mode') == 'skill':
            if not isinstance(payload.get('request_id'), str) or not re.fullmatch(r'web-[a-f0-9]{32}', payload['request_id']):
                raise ComputerError('invalid_request', '技能任务请求 ID 无效。')
            args = {k: v for k, v in payload.items() if k not in {'request_id', 'mode'}}
            if conversation_id is not None:
                args['conversation_id'] = conversation_id
            return self.queue.enqueue_skill(request_id=payload['request_id'], payload=args)
        if isinstance(payload, dict) and payload.get('mode') == 'natural':
            if set(payload) - {'request_id','mode','prompt','model','relative_path'} or not isinstance(payload.get('request_id'),str) or not re.fullmatch(r'web-[a-f0-9]{32}',payload['request_id']):
                raise ComputerError('invalid_request','自然语言任务字段无效。')
            model=payload.get('model','auto')
            models=self.chat.models().get('models',[])
            if not isinstance(model,str) or model not in {'auto',*(m['model'] for m in models),*(m['provider']+'::'+m['model'] for m in models)}:
                raise ComputerError('invalid_request','请选择已登记模型。')
            return self.queue.enqueue_sample(request_id=payload['request_id'], prompt=payload.get('prompt'),
                model=model, relative_path=payload.get('relative_path','.'), conversation_id=conversation_id)
        if conversation_id is not None:
            raise ComputerError('invalid_request','会话任务当前只接入固定目录报告。')
        if not isinstance(payload, dict) or payload.get('mode') != 'inventory':
            return self.submit(payload)
        if set(payload) - {'request_id', 'mode', 'relative_path'} or not isinstance(payload.get('request_id'), str) or not re.fullmatch(r'web-[a-f0-9]{32}', payload['request_id']):
            raise ComputerError('invalid_request', '目录任务只接受请求 ID 和相对路径。')
        return self.queue.enqueue_inventory(request_id=payload['request_id'], relative_path=payload.get('relative_path', '.'))

    def queue_control(self, payload):
        if not isinstance(payload,dict) or set(payload)!={'paused'}:
            raise ComputerError('invalid_request','队列控制只接受 paused 字段。')
        return self.queue.set_paused(payload['paused'])

    def list_tasks(self, *, all_tasks=False, conversation_id=None):
        self.core._recover()
        try:self.core.assert_running();ready=True
        except CoreError:ready=False
        with self.core.ledger.connection() as db:
            rows=db.execute("SELECT request_key,tasks.document AS task,actions.document AS action FROM tasks JOIN actions USING(task_id) WHERE (? OR json_extract(actions.document,'$.capability_id')='browser.operate.v1') AND (? IS NULL OR (json_extract(actions.document,'$.capability_id') IN ('sample.report.v1','skill.report.v1','mcp.documentation.v1') AND json_extract(actions.document,'$.arguments.conversation_id')=?)) ORDER BY (json_extract(actions.document,'$.status') IN ('PREPARED','DISPATCHING')) DESC,tasks.rowid DESC LIMIT 30", (all_tasks,conversation_id,conversation_id)).fetchall()
        tasks=[]
        for row in rows:
            action=json.loads(row['action'])
            task=json.loads(row['task']);args=action['arguments']
            inventory=action['capability_id']=='filesystem.read_sample.v1'
            natural=action['capability_id']=='sample.report.v1'
            skill=action['capability_id']=='skill.report.v1'
            mcp=action['capability_id']=='mcp.documentation.v1'
            tasks.append({'task_id':task['task_id'],'request_id':row['request_key'],'status':task['status'],
                          'kind':'mcp' if mcp else 'inventory' if inventory else 'skill' if skill else 'natural' if natural else 'browser',
                          'goal':('目录清单 · '+args['relative_path']) if inventory else args['prompt'] if natural or skill or mcp else args['task']['goal'],
                          'model':'Context7 · 零模型调用' if mcp else '本地固定能力' if inventory else args['model'] if natural or skill else ('固定动作测试' if args['scripted'] else args['model']),
                          'created_at':task['created_at'],'updated_at':task['updated_at']})
            if len(tasks)>=30:break
        queue = self.queue.snapshot()
        for task in tasks:task['queue_position'] = queue['positions'].get(task['task_id'])
        return {'tasks':tasks,'available':importlib.util.find_spec('playwright') is not None,'ready':ready,
                'inventory_root':self.core.ledger.control()['config']['allowed_root'],
                'active':bool(queue['running']), 'queue':queue}

    def detail(self,task_id, *, all_tasks=False):
        if all_tasks:
            self.core._recover()
            record=self.core.ledger.record(task_id=task_id)
            if record['action']['capability_id'] in {'filesystem.read_sample.v1','sample.report.v1','skill.report.v1','mcp.documentation.v1'}:
                natural=record['action']['capability_id']=='sample.report.v1'
                artifact=record['artifact']
                if record['action']['status']=='CONFIRMED':self.core._verify_artifact(artifact)
                report=None
                if artifact:
                    report=json.loads((self.core.ledger.artifact_dir/artifact['path']).read_text(encoding='utf-8'))
                return {'task':record['task'],'kind':'mcp' if record['action']['capability_id']=='mcp.documentation.v1' else 'skill' if record['action']['capability_id']=='skill.report.v1' else 'natural' if natural else 'inventory','action_status':record['action']['status'],
                        'error':record['action'].get('error'),'cancel_requested':record['cancel_requested'],
                        'steps':self.sample.steps(task_id) if natural else [],'has_screenshot':False,'artifact':artifact,'report':report,
                        'artifact_path':str(self.core.ledger.artifact_dir/artifact['path']) if artifact else None}
        result=self.service.inspect(task_id)
        return {'task':result['record']['task'],'kind':'browser','action_status':result['record']['action']['status'],
                'error':result['record']['action'].get('error'),'cancel_requested':result['record']['cancel_requested'],
                'steps':[{'ordinal':s['ordinal'],'state':s['state'],'action':json.loads(s['action_json']),
                          'model':json.loads(s['model_json'])} for s in result['steps']],
                'has_screenshot':result['report'] is not None}

    @interactive
    def cancel(self,task_id, *, all_tasks=False):
        record=self.core.ledger.record(task_id=task_id)
        if record['action']['capability_id']!='browser.operate.v1' and not all_tasks:
            raise ComputerError('wrong_executor','此入口只能取消浏览器任务。')
        self.core.cancel(task_id)
        self.queue.wake.set()
        return self.detail(task_id, all_tasks=all_tasks)

    def screenshot(self,task_id):
        result=self.service.inspect(task_id)
        if result['report'] is None:raise ComputerError('not_found','任务尚无已确认截图。')
        # Receipt was verified above; never accept a client filesystem path.
        path=safe_path(self.core.ledger.artifact_dir/result['report']['screenshot']['path'],directory=False)
        raw=path.read_bytes()
        from jarvis_core.policy import digest
        if len(raw)>2*1024*1024 or digest(raw)!=result['report']['screenshot']['digest']:
            raise ComputerError('artifact_unavailable','截图与回执不一致。')
        return raw

    def close(self):
        self.queue.close()
