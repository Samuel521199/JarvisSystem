"""Conversation-scoped projections of existing tasks; no new state or queue.

The association is part of the immutable, idempotent action arguments. Archive
links are hints only: every detail/cancel/artifact access checks the ledger.
"""
import re

from . import policy
from .policy import CoreError
from .sample_tasks import CAPABILITY
from .storage_budget import interactive


def conversation_id(value):
    if not isinstance(value,str) or not re.fullmatch(r'[a-f0-9]{32}',value):
        raise CoreError('invalid_request','会话标识无效。')
    return value


class ConversationTasks:
    def __init__(self, core, tasks):
        self.core, self.tasks = core, tasks

    def submit(self, ident, payload):
        conversation_id(ident)
        allowed = {'request_id','prompt','model','relative_path'}
        if isinstance(payload, dict) and payload.get('mode') == 'skill':
            allowed = {'request_id','mode','prompt','model','project_id','skill_id','paths','output_path','ratio','theme','target_path','focus','explain','coding','cases','heldout_cases','entrypoint','coding_provider','coding_executor_binding','build_recipe','coding_demand','new_paths'}
        if isinstance(payload, dict) and payload.get('mode') == 'mcp':
            allowed = {'request_id', 'mode', 'prompt', 'library', 'project_id'}
        if not isinstance(payload,dict) or set(payload)-allowed:
            raise CoreError('invalid_request','会话任务只接受请求编号、要求、模型和相对路径。')
        return self.tasks.submit_task({**payload,'mode':payload.get('mode', 'natural')},conversation_id=ident)

    def list(self, ident):
        conversation_id(ident)
        result=self.tasks.list_tasks(all_tasks=True,conversation_id=ident)
        return {**result,'conversation_id':ident}

    def documentation_candidate(self, ident, payload):
        conversation_id(ident)
        if not isinstance(payload, dict) or not {'candidate', 'text'} <= set(payload) or set(payload) - {'candidate', 'text', 'project_id'}:
            raise CoreError('invalid_request', '文档候选只接受本条原文、库名、查询和项目作用域。')
        return self.tasks.mcp.assess_candidate(payload['candidate'], text=payload['text'],
            conversation_id=ident, project_id=payload.get('project_id'))

    def _bound(self, ident, task_id):
        conversation_id(ident)
        if not isinstance(task_id,str) or not re.fullmatch(r'task_[a-f0-9]{32}',task_id):
            raise CoreError('not_found','未找到此会话的任务。')
        record=self.core.ledger.record(task_id=task_id)
        action=record['action']
        if action['capability_id'] not in {CAPABILITY,'skill.report.v1','mcp.documentation.v1'} or action['arguments'].get('conversation_id')!=ident:
            raise CoreError('not_found','未找到此会话的任务。')
        return record

    def lookup(self, ident, request_id):
        conversation_id(ident)
        if not isinstance(request_id,str) or not re.fullmatch(r'web-[a-f0-9]{32}',request_id):
            raise CoreError('invalid_request','任务请求编号无效。')
        with self.core.ledger.connection() as db:
            row=db.execute("SELECT tasks.task_id FROM tasks JOIN actions USING(task_id) WHERE request_key=? AND json_extract(actions.document,'$.capability_id') IN (?, 'skill.report.v1', 'mcp.documentation.v1') AND json_extract(actions.document,'$.arguments.conversation_id')=?",
                           (request_id,CAPABILITY,ident)).fetchone()
        if row is None:raise CoreError('not_found','暂未找到此请求；没有重新提交或重放。')
        record=self._bound(ident,row['task_id'])
        return {'task':record['task'],'conversation_id':ident,
                'action_status':record['action']['status'],'report':None,'steps':[],
                'error':record['action'].get('error'),'kind':{'mcp.documentation.v1':'mcp','skill.report.v1':'skill'}.get(record['action']['capability_id'],'natural')}

    def detail(self, ident, task_id):
        record=self._bound(ident,task_id)
        result={**self.tasks.detail(task_id,all_tasks=True),'conversation_id':ident}
        if record['action']['capability_id']==CAPABILITY:
            from .task_revisions import revision
            import json
            control={'relative_path':record['action']['arguments']['inventory']['relative_path'],
                     'revision':revision(record), 'admission':None}
            with self.core.ledger.connection() as db:
                if db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='report_admissions'").fetchone():
                    row=db.execute('SELECT document FROM report_admissions WHERE task_id=?',(task_id,)).fetchone()
                    if row:control['admission']=json.loads(row['document'])
            result['report_control']=control
        return result

    @interactive
    def cancel(self, ident, task_id, payload):
        if payload!={}:raise CoreError('invalid_request','取消只接受空对象。')
        self._bound(ident,task_id)
        return {**self.tasks.cancel(task_id,all_tasks=True),'conversation_id':ident}

    def artifact(self, ident, task_id):
        record=self._bound(ident,task_id)
        if record['action']['status']!='CONFIRMED':
            raise CoreError('artifact_unavailable','任务尚无已确认产物。')
        artifact=record['artifact']
        self.core._verify_artifact(artifact)
        path=policy.safe_path(self.core.ledger.artifact_dir/artifact['path'],directory=False)
        with path.open('rb') as source:raw=source.read(policy.MAX_OUTPUT_BYTES+1)
        if len(raw)!=artifact['size_bytes'] or policy.digest(raw)!=artifact['digest']:
            raise CoreError('artifact_unavailable','产物已变化，未提供旧内容或重新生成。')
        return raw

    def skill_evidence(self, ident, task_id, *, section=None, offset=0, limit=20, query=''):
        import json
        from .rea_evidence import load, page
        record = self._bound(ident, task_id)
        report = json.loads(self.artifact(ident, task_id))
        evidence = load(self.core, report, record['action']['action_id'])
        if section is not None:
            return page(evidence, report, section, offset, limit, query=query)
        return {'evidence': evidence, **{key: report[key] for key in ('analysis', 'input_manifest', 'runtime', 'checks')}}
