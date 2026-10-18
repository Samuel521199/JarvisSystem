"""Nonce protected native skill settings and receipt-bound sandbox previews."""
import base64
import hashlib
import json
import re
import secrets
import time
from urllib.parse import parse_qs, urlsplit

from jarvis_core.policy import CoreError
from jarvis_core.workspace import fields


def confirmed(host, conversation, task):
    if host.conversation_tasks is None:
        raise CoreError('skill_unavailable', '任务模块尚未准备。')
    report = json.loads(host.conversation_tasks.artifact(conversation, task))
    if report.get('kind') != 'jarvis.skill-report' or report.get('skill_id') != 'anatomy.explainer' or not isinstance(report.get('html'), str):
        raise CoreError('artifact_unavailable', '此任务没有已确认的科普页面。')
    # Revalidate the actual delivered project file, not only the ledger JSON.
    output = report['output']
    with host.workspace.connection() as db:
        row = db.execute('SELECT * FROM outputs WHERE id=?', (output['request_id'],)).fetchone()
        if row is None or row['state'] != 'SAVED':
            raise CoreError('artifact_unavailable', '项目产物没有已确认的保存回执。')
        host.workspace._project(db, row['project_id'])
        host.workspace._validate_binding(row)
        host.workspace._verify(row)
    return report['html'].encode('utf-8')


def get(handler):
    host = handler.server
    parsed = urlsplit(handler.path)
    evidence_match = re.fullmatch(r'/api/skills/evidence/([a-f0-9]{32})/(task_[a-f0-9]{32})', parsed.path)
    if evidence_match:
        if not handler._workspace_token() or not handler._guard(): return True
        try:
            query = parse_qs(parsed.query, keep_blank_values=True)
            if set(query) - {'section', 'offset', 'limit', 'query'} or any(len(v) != 1 for v in query.values()):
                raise CoreError('invalid_request', '证据查询参数无效。')
            if query and 'section' not in query:
                raise CoreError('invalid_request', '分页查询必须指定证据类型。')
            try:
                offset, limit = int(query.get('offset', ['0'])[0]), int(query.get('limit', ['20'])[0])
            except ValueError: raise CoreError('invalid_request', '证据分页参数无效。') from None
            handler._send(200, host.conversation_tasks.skill_evidence(*evidence_match.groups(),
                          section=query.get('section', [None])[0], offset=offset, limit=limit, query=query.get('query', [''])[0]))
        except Exception as exc: handler._workspace_error(exc)
        return True
    if handler.path in {'/skills.js', '/skills_manager.js'}:
        handler._send(200, host.skills_script if handler.path == '/skills.js' else host.skills_manager_script, 'application/javascript; charset=utf-8')
        return True
    if parsed.path in {'/api/skills', '/api/skills/decisions'}:
        if not handler._workspace_token() or not handler._guard(): return True
        try:
            if host.skills is None: raise CoreError('skill_unavailable', '技能模块尚未启用。')
            query = parse_qs(parsed.query, keep_blank_values=True)
            if set(query) - {'project_id','conversation_id'} or any(len(v) != 1 for v in query.values()):
                raise CoreError('invalid_skill_context', '技能作用域无效。')
            handler._send(200, host.skills.decisions() if parsed.path.endswith('decisions') else host.skills.snapshot({k:v[0] for k,v in query.items()}))
        except Exception as exc: handler._workspace_error(exc)
        return True
    match = re.fullmatch(r'/api/skill-previews/([a-f0-9]{64})', handler.path)
    if not match: return False
    try:
        with host.skill_preview_lock:
            item = host.skill_previews.get(match[1])
        if item is None or item['expires'] < time.monotonic():
            raise CoreError('not_found', '预览已过期，请从任务重新打开。')
        raw = confirmed(host, item['conversation_id'], item['task_id'])
        scripts = re.findall(rb'<script type="module">([\s\S]*?)</script>', raw)
        if len(scripts) != 1:
            raise CoreError('artifact_unavailable', '页面脚本结构未通过检查。')
        binding = base64.b64encode(hashlib.sha256(scripts[0]).digest()).decode('ascii')
        handler.send_response(200)
        for key, value in {'Content-Type':'text/html; charset=utf-8', 'Content-Length':str(len(raw)),
                           'Cache-Control':'no-store', 'X-Content-Type-Options':'nosniff', 'Referrer-Policy':'no-referrer',
                           'Content-Security-Policy':"default-src 'none'; script-src 'sha256-"+binding+"'; style-src 'unsafe-inline'; img-src data: blob:; connect-src 'none'; base-uri 'none'; form-action 'none'; frame-ancestors 'self'; sandbox allow-scripts"}.items():
            handler.send_header(key,value)
        handler.end_headers()
        handler.wfile.write(raw)
    except (BrokenPipeError, ConnectionResetError): pass
    except Exception as exc: handler._workspace_error(exc)
    return True


def post(handler, payload):
    host = handler.server
    try:
        if host.skills is None: raise CoreError('skill_unavailable','技能模块尚未启用。')
        if handler.path in {'/api/skills/coding-apply','/api/skills/coding-rollback'}:
            fields(payload, {'conversation_id','task_id'}, set())
            report=json.loads(host.conversation_tasks.artifact(payload['conversation_id'],payload['task_id']))
            from jarvis_core.coding_workflow import apply_result
            result=apply_result(host.core,report,'apply' if handler.path.endswith('-apply') else 'rollback')
        elif handler.path.endswith('/policy'):
            result = host.skills.put_policy(payload)
        elif handler.path.endswith('/select'):
            fields(payload, {'message'}, {'context','purpose'})
            if payload.get('purpose', 'chat') not in {'chat','task'}:
                raise CoreError('invalid_skill_request', '技能选择用途无效。')
            result = host.skills.select(payload['message'],payload.get('context'),purpose=payload.get('purpose','chat'))
        else:
            fields(payload, {'conversation_id','task_id'}, set())
            confirmed(host, payload['conversation_id'], payload['task_id'])
            token = secrets.token_hex(32)
            with host.skill_preview_lock:
                host.skill_previews = {k:v for k,v in host.skill_previews.items() if v['expires'] > time.monotonic()}
                while len(host.skill_previews) >= 64: host.skill_previews.pop(next(iter(host.skill_previews)))
                host.skill_previews[token] = {**payload,'expires':time.monotonic()+600}
            result = {'url':'/api/skill-previews/'+token,'expires_in':600}
        handler._send(200, result)
    except Exception as exc: handler._workspace_error(exc)
