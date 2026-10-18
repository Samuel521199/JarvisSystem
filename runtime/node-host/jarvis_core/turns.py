"""Bounded reply receipts with optional recovery, no task execution or replay.

HTTP reception never waits for a model. Legacy and receipt requests share the
same inference slots; cancellation only releases a slot when its worker exits.
An instance fence makes a restart explicit instead of replaying an old input.
"""
from copy import deepcopy
import hashlib
import json
import re
import threading
import time


class TurnError(ValueError):
    def __init__(self, code, message, status=400):
        self.code, self.status = code, status
        super().__init__(message)


def identifier(value):
    if not isinstance(value, str) or not re.fullmatch(r'[a-f0-9]{32}', value):
        raise TurnError('invalid_turn', '对话标识无效。')
    return value


def invoke_reply(core, chat, payload, cancel_event, request_id):
    """One invocation boundary for old synchronous and new receipt endpoints."""
    from .personal import parse
    core.assert_running()
    if cancel_event is not None and cancel_event.is_set():
        return {'status': 'CANCELLED', 'cancel_requested': True,
                'outcome_uncertain': False, 'user_message': '已停止，本次未调用模型。'}
    selection = {k: payload[k] for k in ('model', 'reasoning', 'context_note', 'attachments',
        'memory_context', 'history_memory', 'knowledge_context', 'history_knowledge',
        'skill_context', 'personal_context', 'continuity_context', 'history_continuity')
        if payload.get(k) is not None}
    if cancel_event is not None:
        selection['cancel_event'] = cancel_event
    for key in ('context_note', 'attachments'):
        if not selection.get(key): selection.pop(key, None)
    if parse(payload['message']):
        selection['_request_id'] = request_id
    from .chat import ChatService
    if isinstance(chat, ChatService):
        selection['_intent_shadow'] = True
    from .dialogue_process import in_dialogue
    token = in_dialogue.set(True)
    try:
        from .calculator import select_request
        pool = getattr(chat, 'dialogue_models', None)
        computation = select_request(payload['message'])
        host_calculation = computation and (computation['explicit'] or not (
            payload.get('attachments') or payload.get('context_note') or (payload.get('skill_context') or {}).get('explicit')))
        # Bounded deterministic/committing commands retain their Host authority.
        if pool is not None and not parse(payload['message']) and not host_calculation:
            result = pool.reply(chat, payload['message'], provider=payload.get('provider','auto'),
                                history=payload.get('history',[]), **selection)
        else:
            result = chat.reply(payload['message'], provider=payload.get('provider', 'auto'),
                                history=payload.get('history', []), **selection)
    finally:
        in_dialogue.reset(token)
    if cancel_event is not None and cancel_event.is_set() and not result.get('personal', {}).get('committed'):
        return {'status': 'CANCELLED', 'cancel_requested': True,
                'user_message': '已停止本次回复，后续输出不再采用；远端用量可能仍在结算。',
                'outcome_uncertain': result.get('outcome_uncertain', True)}
    from .intent import bind
    return bind(result, request_id)


class DialogueTurns:
    MAX_IDS = 4096
    MAX_RESULTS = 64
    MAX_BYTES = 32 * 1024 * 1024
    MAX_RESULT_BYTES = 2 * 1024 * 1024
    RESULT_TTL = 600

    def __init__(self, core, chat, instance_id, slots, requests, metrics, *, clock=time.monotonic):
        self.core, self.chat, self.instance_id = core, chat, instance_id
        self.slots, self.requests, self.metrics, self.clock = slots, requests, metrics, clock
        self.lock = threading.RLock()
        self.rows = {}
        self.closed = False
        self.bytes = 0
        self.journal = None
        self.journal_error = False
        self.work_admission = None

    def enable_recovery(self, conversations):
        from .dialogue_journal import DialogueJournal
        try:self.journal = DialogueJournal(conversations, self.instance_id)
        except Exception:self.journal_error = True

    def _scope(self, instance_id, conversation_id, request_id):
        identifier(instance_id); identifier(conversation_id); identifier(request_id)
        if instance_id != self.instance_id:
            raise TurnError('dialogue_instance_changed', '服务已经重启，旧回复不会自动重发；请核对会话及任务记录。', 409)
        row = self.rows.get(request_id)
        if row and row['conversation_id'] != conversation_id:
            raise TurnError('turn_not_found', '当前会话中没有此回复。', 404)
        return row

    def _trim(self):
        # Drop content only; retain the issued ID until instance shutdown.
        completed = [r for r in self.rows.values() if r['finished'] and r.get('result') is not None]
        for i, row in enumerate(completed):
            if self.clock()-row['touched'] > self.RESULT_TTL or len(completed)-i > self.MAX_RESULTS:
                self.bytes -= row['bytes']; row['bytes'] = 0
                row['result'] = None; row['expired'] = True

    def _view(self, row):
        if row.get('durable') and not row.get('persistence_error'):
            value = self.journal.get(row['conversation_id'], row['request_id'])
            if value is not None:return value
        value = {k: row[k] for k in ('request_id', 'conversation_id', 'status', 'revision', 'finished')}
        value.update(instance_id=self.instance_id, expired=row.get('expired', False),
                     cancel_requested=row['event'].is_set(), durable=False)
        if row.get('result') is not None:
            value['result'] = deepcopy(row['result'])
        if value['expired']:
            value['user_message'] = '回复正文缓存已过期；请查看已保存会话，没有自动重发。'
        return value

    def view(self, instance_id, conversation_id, request_id):
        with self.lock:
            row = self._scope(instance_id, conversation_id, request_id)
            if row is None:
                raise TurnError('turn_not_found', '尚未查到该回复；没有自动重发。', 404)
            self._trim()
            return self._view(row)

    def recover(self, conversation_id, request_id):
        identifier(conversation_id);identifier(request_id)
        with self.lock:
            row=self._scope(self.instance_id, conversation_id, request_id)
            if row:return self._view(row)
            if self.journal:
                result=self.journal.get(conversation_id, request_id)
                if result is not None:return result
            raise TurnError('turn_not_found','未找到可恢复的回复；临时会话、未受理或过期记录不会自动重发。',404)

    def submit(self, instance_id, conversation_id, request_id, payload):
        encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()
        digest = hashlib.sha256(encoded).hexdigest()
        with self.lock:
            row = self._scope(instance_id, conversation_id, request_id)
            if row:
                if row['digest'] is not None and row['digest'] != digest:
                    raise TurnError('turn_conflict', '同一回复编号不能更换内容。', 409)
                self._trim()
                return self._view(row)
            if self.closed:
                raise TurnError('dialogue_closed', '对话入口正在关闭。', 503)
            persistent=(payload.get('personal_context') or {}).get('temporary') is False
            if persistent and self.journal_error:
                raise TurnError('dialogue_storage_unavailable','回复恢复存储不可用，本条尚未调用模型；临时会话仍可使用。',503)
            if persistent and self.journal:
                previous=self.journal.lookup(conversation_id, request_id, digest)
                if previous is not None:return previous
            self.core.assert_running()
            self._trim()
            if len(self.rows) >= self.MAX_IDS or self.bytes+len(encoded)+self.MAX_RESULT_BYTES > self.MAX_BYTES:
                raise TurnError('dialogue_capacity', '对话缓存已满，原消息未受理；请保留草稿并稍后重试。', 429)
            if any(r['conversation_id'] == conversation_id and not r['finished'] for r in self.rows.values()):
                raise TurnError('conversation_busy', '此会话仍有回复正在收尾；下一条消息尚未受理。', 409)
            if not self.slots.acquire(blocking=False):
                raise TurnError('chat_busy', '对话推理槽暂满，后台任务和控制仍可使用；本条尚未受理。', 429)
            try:
                event = self.requests.start(request_id)
            except ValueError as exc:
                self.slots.release()
                raise TurnError('turn_conflict', '回复编号已使用或取消登记已满。', 409) from exc
            row = dict(request_id=request_id, conversation_id=conversation_id, digest=digest,
                       event=event, status='RUNNING', revision=1, finished=False,
                       result=None, bytes=len(encoded)+self.MAX_RESULT_BYTES, touched=self.clock())
            if self.work_admission is not None:
                try: row['work_scope'] = self.work_admission.capture(conversation_id)
                except Exception: row['work_scope'] = None
            if persistent and self.journal:
                try:
                    self.journal.admit(conversation_id, request_id, digest)
                    row['durable']=True
                except Exception:
                    self.requests.finish(request_id)
                    self.slots.release()
                    raise
            self.rows[request_id] = row; self.bytes += row['bytes']
            with self.requests.lock:
                self.requests.active += 1
            metric = self.metrics.begin('chat')
            snapshot = deepcopy(payload)
            row['work_payload'] = snapshot
            try:
                threading.Thread(target=self._work, args=(row, snapshot, metric),
                                 daemon=True, name='jarvis-dialogue-reply').start()
            except Exception:
                self._complete(row, {'status': 'FAILED', 'outcome_uncertain': False,
                    'user_message': '回复线程未启动；本次未调用模型。'}, metric)
            return self._view(row)

    def _work(self, row, payload, metric):
        try:
            result = invoke_reply(self.core, self.chat, payload, row['event'], row['request_id'])
            if not isinstance(result, dict) or result.get('status') not in {'SUCCEEDED', 'FAILED', 'UNKNOWN', 'CANCELLED'}:
                raise ValueError('bad reply')
            if len(json.dumps(result, ensure_ascii=False, allow_nan=False).encode()) > self.MAX_RESULT_BYTES:
                result = {'status': 'FAILED', 'user_message': '回复超过缓存上限，没有静默截断或自动重发。'}
        except Exception:
            result = {'status': 'UNKNOWN', 'outcome_uncertain': True,
                      'user_message': '回复结果未确认，请核对状态；没有自动重发。'}
        self._complete(row, result, metric)

    def _complete(self, row, result, metric):
        with self.lock:
            # Cancellation may arrive between invoke_reply returning and publication.
            if row['event'].is_set() and not result.get('personal', {}).get('committed'):
                result = {'status': 'CANCELLED', 'cancel_requested': True,
                          'outcome_uncertain': result.get('outcome_uncertain', True),
                          'user_message': '本次回复已停止；远端请求可能仍有用量。'}
            # Under the same per-turn lock as cancellation/publication. Only a
            # local queue admission is allowed here; remote work runs in FIFO.
            elif self.work_admission is not None:
                try: result = self.work_admission.admit(row, row.get('work_payload', {}), result)
                except Exception:
                    result = {**result, 'work_admission': {'status': 'unconfirmed', 'automatic': False,
                        'reason': '文档受理结果未确认，请查询本会话任务；没有自动重试。'}}
            row.pop('work_payload', None)
            if row.get('durable'):
                try:
                    self.journal.finish(row['conversation_id'],row['request_id'],result)
                    row['persistence_error']=False
                except Exception:
                    row['persistence_error']=True
                    result={'status':'UNKNOWN','outcome_uncertain':True,
                            'user_message':'回复的持久结果未确认；没有重新调用模型，请核对会话或本会话任务记录。',
                            **({'work_admission': result['work_admission']} if result.get('work_admission') else {})}
            self.bytes -= row['bytes']
            row.update(status=result['status'], result=result, finished=True,
                       revision=row['revision']+1, touched=self.clock(),
                       bytes=len(json.dumps(result, ensure_ascii=False).encode()))
            self.bytes += row['bytes']
            self.requests.finish(row['request_id'])
            with self.requests.lock:
                self.requests.active -= 1
            self.slots.release()
            self.metrics.finish(metric, result['status'])
            if result['status'] == 'SUCCEEDED' and result.get('calculation'):
                self.metrics.event('calculation_completed')
            self._trim()

    def cancel(self, instance_id, conversation_id, request_id):
        with self.lock:
            row = self._scope(instance_id, conversation_id, request_id)
            if row is None:
                if self.journal:
                    previous=self.journal.get(conversation_id, request_id)
                    if previous is not None:return previous
                if len(self.rows) >= self.MAX_IDS:
                    raise TurnError('dialogue_capacity', '取消登记已满，请核对运行状态。', 429)
                event = threading.Event(); event.set()
                row = dict(request_id=request_id, conversation_id=conversation_id, digest=None,
                           event=event, status='CANCELLED', revision=1, finished=True,
                           result={'status':'CANCELLED','outcome_uncertain':False,
                                   'user_message':'已在受理前取消，本次未调用模型。'},
                           bytes=0, touched=self.clock())
                self.rows[request_id] = row
                row['bytes'] = len(json.dumps(row['result'], ensure_ascii=False).encode())
                self.bytes += row['bytes']
                self._trim()
            elif not row['finished']:
                if row.get('durable'):
                    try:self.journal.cancel(conversation_id,request_id)
                    except Exception:row['persistence_error']=True
                row['event'].set(); row['status'] = 'CANCELLING'; row['revision'] += 1
            return self._view(row)

    def snapshot(self):
        with self.lock:
            self._trim()
            return {'active': sum(not r['finished'] for r in self.rows.values()),
                    'retained_results':sum(r.get('result') is not None for r in self.rows.values()),
                    'issued_ids':len(self.rows), 'capacity_ids':self.MAX_IDS,
                    'reserved_bytes':self.bytes, 'capacity_bytes':self.MAX_BYTES,
                    'result_ttl_seconds':self.RESULT_TTL, 'instance_scoped':True,
                    'recovery': 'unavailable' if self.journal_error else 'enabled' if self.journal else 'disabled'}

    def close(self):
        with self.lock:
            self.closed = True
            for row in self.rows.values():
                if not row['finished']:
                    row['event'].set()
