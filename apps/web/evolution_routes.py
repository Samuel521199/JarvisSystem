"""Exact local routes; shares the workbench's Origin, nonce and core boundary."""
import re

from jarvis_core.policy import CoreError


def failure(handler, exc):
    code = exc.code if isinstance(exc, CoreError) else 'evolution_unavailable'
    status = 409 if code in {'evolution_busy', 'evolution_conflict'} else 404 if code == 'not_found' else 400 if isinstance(exc, CoreError) else 503
    handler._error(status, code, str(exc) if isinstance(exc, CoreError) else '成长模块暂不可用；聊天继续可用。')


def get(handler):
    if handler.path == '/ranking-modules.js':
        handler._send(200, handler.server.ranking_modules_script, 'application/javascript; charset=utf-8')
        return True
    if handler.path == '/api/evolution/ranking':
        if not handler._workspace_token() or not handler._guard(): return True
        try: handler._send(200, handler.server.evolution.ranking_modules.snapshot())
        except Exception as exc: failure(handler, exc)
        return True
    if handler.path == '/evolution.js':
        handler._send(200, handler.server.evolution_script, 'application/javascript; charset=utf-8')
        return True
    if handler.path == '/api/evolution/maintenance':
        if not handler._workspace_token() or not handler._guard(): return True
        try:
            from jarvis_core.evolution.maintenance import LedgerMaintenance
            handler._send(200, LedgerMaintenance(handler.server.evolution).preview())
        except Exception as exc: failure(handler, exc)
        return True
    match = re.fullmatch(r'/api/evolution(?:/(jobs|packages)/([a-f0-9]{32}|[a-f0-9]{64}))?', handler.path)
    if not match: return False
    if not handler._workspace_token() or not handler._guard(): return True
    try:
        manager = handler.server.evolution
        if manager is None: raise CoreError('evolution_unavailable', '成长模块未初始化。')
        if match[1] == 'jobs': result = manager.store.job(match[2])
        elif match[1] == 'packages':
            record, files = manager.store.read_package(match[2])
            result = {'record': record, 'files': files}
        else: result = manager.snapshot()
        handler._send(200, result)
    except Exception as exc: failure(handler, exc)
    return True


def post(handler, payload):
    try:
        manager = handler.server.evolution
        if manager is None: raise CoreError('evolution_unavailable', '成长模块未初始化。')
        if handler.path == '/api/evolution/ranking/generate':
            result = manager.ranking_modules.submit(payload)
        elif handler.path == '/api/evolution/ranking/select':
            result = manager.ranking_modules.transition(payload)
        elif handler.path == '/api/evolution/maintenance':
            from jarvis_core.evolution.maintenance import LedgerMaintenance
            result = LedgerMaintenance(manager).apply(payload)
        elif handler.path == '/api/evolution/policy':
            result = manager.configure(payload)
        elif handler.path == '/api/evolution/jobs':
            result = manager.submit(payload)
        else:
            if not isinstance(payload, dict) or set(payload) != {'job_id'}:
                raise CoreError('evolution_request_invalid', '停止请求需要 job_id。')
            result = manager.cancel(payload['job_id'])
        handler._send(202 if handler.path.endswith('/jobs') else 200, result)
    except Exception as exc: failure(handler, exc)
