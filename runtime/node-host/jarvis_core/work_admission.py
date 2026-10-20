"""Small Host admission port; execution remains in the existing bounded queue."""
import hashlib
import json

from . import policy
from .documentation_admission import DocumentationAdmission
from .intent import ENGINE
from .report_intents import RULE, explicit_target, operation, select_report
from .task_revisions import cancel_report, revision
from .workspace import identifier

SETTINGS = policy.REPOSITORY_ROOT/'config/dialogue-automation.json'


def settings():
    raw = policy.safe_path(SETTINGS, directory=False).read_bytes()
    if len(raw) > 4096: raise ValueError('report configuration size')
    value = json.loads(raw)
    if (not isinstance(value, dict) or set(value) != {'schema_version', 'enabled', 'routes', 'rule'}
            or type(value['schema_version']) is not int or value['schema_version'] != 1
            or type(value['enabled']) is not bool or value['rule'] != RULE
            or not isinstance(value['routes'], list) or any(x != 'vertex::gemini-3.8-flash' for x in value['routes'])):
        raise ValueError('report configuration')
    return value


class WorkAdmission:
    def __init__(self, core, tasks):
        self.core, self.tasks = core, tasks
        self.documentation = DocumentationAdmission(core, tasks)

    def capture(self, conversation_id):
        return self.documentation.capture(conversation_id)

    def capture_target(self, conversation_id, message):
        target = explicit_target(message)
        if not target: return None
        from .conversation_tasks import ConversationTasks
        try:
            record = ConversationTasks(self.core, self.tasks)._bound(conversation_id, target)
            if record['action']['capability_id'] != 'sample.report.v1': return None
            return {'task_id': target, 'revision': revision(record)}
        except policy.CoreError:
            return None

    def admit(self, row, payload, result):
        if payload.get('voice_mode') == 'conversation':
            return result
        choice = select_report(payload.get('message', ''), result.get('intent_decision'))
        if choice is None:
            result = self.documentation.admit(row, payload, result)
            if result.get('status') == 'SUCCEEDED' and not result.get('work_admission'):
                items = (result.get('intent_decision') or {}).get('intents', [])
                if any(i.get('kind') in {'action','control'} and i.get('disposition') == 'requested'
                       and operation(i.get('quote', '')) for i in items):
                    result = {**result, 'work_admission': {'status': 'not_submitted', 'automatic': False,
                        'capability': 'sample.report.v1', 'reason_code': 'report_needs_review',
                        'reason': '本轮报告要求尚未通过范围或完整性核对，未派发或修改任务；请明确样例目录及所指报告，或使用任务模式。'}}
            return result
        if result.get('status') != 'SUCCEEDED' or result.get('output_incomplete'): return result
        outcome = {'status': 'not_submitted', 'capability': 'sample.report.v1', 'automatic': False,
                   'operation': choice['operation']}
        result = {**result, 'work_admission': outcome}
        try:
            decision = result['intent_decision']
            config = settings()
            if not config['enabled'] or decision.get('provider', '')+'::'+decision.get('model', '') not in config['routes']:
                outcome.update(reason_code='route_not_enabled', reason='该模型尚未开放混合报告自动受理；可使用任务模式。')
                return result
            if not row.get('durable') or payload.get('attachments') or payload.get('context_note'):
                outcome.update(reason_code='explicit_review_required', reason='临时会话、附件或附加要求请使用任务模式明确提交。')
                return result
            identifier(row['request_id']); identifier(row['conversation_id'])
            expected_id = hashlib.sha256((ENGINE+':'+row['request_id']).encode()).hexdigest()[:32]
            if decision.get('turn_id') != row['request_id'] or decision.get('decision_id') != expected_id:
                raise policy.CoreError('work_binding_invalid', '识别来源不匹配，未受理任务。')
            if self.capture(row['conversation_id']) != row.get('work_scope'):
                raise policy.CoreError('work_scope_changed', '会话项目已变化，未受理报告操作。')
            if row['event'].is_set(): raise policy.CoreError('cancelled', '回复已停止，未受理报告操作。')
            origin = {'kind': 'dialogue', 'turn_id': row['request_id'], 'decision_id': expected_id,
                      'text_digest': policy.digest(payload['message'].encode()), 'rule': RULE}
            key = 'web-'+hashlib.sha256(('sample-report:'+row['conversation_id']+':'+row['request_id']).encode()).hexdigest()[:32]
            target = row.get('work_target')
            if choice['operation'] != 'create' and (not target or target['task_id'] != choice['target']):
                raise policy.CoreError('report_target_not_found', '目标无法唯一核对，请从本会话任务复制完整报告编号。')
            if choice['operation'] == 'cancel':
                accepted = cancel_report(self.core, request_id=key, conversation_id=row['conversation_id'],
                    task_id=target['task_id'], expected=target['revision'], origin=origin)
                self.tasks.queue.wake.set()
                outcome.update(automatic=True, **accepted)
            else:
                # Canonical task parameters exclude companionship/private clauses.
                prompt = '列举指定样例目录，按文件类型统计数量和字节数，并保存 JSON 报告。'
                accepted = self.tasks.queue.enqueue_sample(request_id=key, prompt=prompt,
                    model=decision['provider']+'::'+decision['model'], relative_path=choice['relative_path'],
                    conversation_id=row['conversation_id'], _origin=origin,
                    _replacement=target if choice['operation'] == 'revise' else None)
                outcome.update(status='submitted', automatic=True, **accepted,
                    reason='已原子替换尚未开始的报告，原任务保留取消记录。' if choice['operation'] == 'revise' else '已受理一项样例目录报告，聊天可以继续；进度和产物以任务记录为准。')
                if choice['operation'] == 'revise': outcome['replaces_task_id'] = target['task_id']
            intents = [dict(item) for item in decision['intents']]
            intents[choice['index']].update(execution=outcome['status'], task_id=outcome['task_id'])
            result['intent_decision'] = {**decision, 'mode': 'bounded_sample_report', 'automatic_execution': True, 'intents': intents}
        except Exception as exc:
            outcome.update(reason_code=getattr(exc, 'code', 'admission_unavailable'),
                reason=str(exc) if isinstance(exc, policy.CoreError) else '报告受理结果未确认，请核对本会话任务；没有自动重试。')
        return result
