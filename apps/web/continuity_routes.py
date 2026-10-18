"""Loopback checkpoint management; shares the owner's existing page guard."""
import re
from urllib.parse import urlsplit, parse_qs
from jarvis_core.continuity import ContinuityStore
from jarvis_core.memory import MemoryError, validate


def change(core, ident, payload):
    if not isinstance(payload, dict):
        raise MemoryError('invalid_continuity', '接续操作格式无效。')
    action = payload.get('action')
    required = {'action', 'revision', 'request_id', 'project_id'} | ({'providers'} if action == 'permissions' else {'work_refs'} if action == 'link_work' else set())
    if set(payload) != required or action not in {'permissions', 'close', 'reopen', 'forget', 'link_work'}:
        raise MemoryError('invalid_continuity', '未知接续操作或字段。')
    validate('revision', payload['revision'])
    return ContinuityStore(core).change(action, target=ident, revision=payload['revision'],
        project_id=payload['project_id'], request_id=payload['request_id'], providers=payload.get('providers'),work_refs=payload.get('work_refs'))


def get(handler):
    url=urlsplit(handler.path);match=re.fullmatch(r'/api/continuity/([a-f0-9]{32})/work',url.path)
    if not match:return False
    if not handler._memory_token() or not handler._guard():return True
    try:
        query=parse_qs(url.query,keep_blank_values=True)
        if set(query)-{'project_id'} or any(len(v)!=1 for v in query.values()):raise MemoryError('invalid_continuity','任务关联查询字段无效。')
        handler._send(200,ContinuityStore(handler.server.core).work_view(match[1],query.get('project_id',[None])[0]))
    except Exception as exc:handler._memory_error(exc)
    return True
