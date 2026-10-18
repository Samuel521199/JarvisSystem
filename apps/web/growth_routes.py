"""Conversation-scoped growth routes; uses the existing owner page boundary."""
import re
from jarvis_core.policy import CoreError
from jarvis_core.evolution.demand import ConversationGrowth
from evolution_routes import failure


def service(handler):
    if handler.server.evolution is None or handler.server.conversation_tasks is None:
        raise CoreError('evolution_unavailable', '成长或目录任务模块暂不可用。')
    return ConversationGrowth(handler.server.core, handler.server.evolution, handler.server.conversation_tasks)


def get(handler):
    if handler.path == '/growth.js':
        handler._send(200, handler.server.growth_script, 'application/javascript; charset=utf-8'); return True
    match = re.fullmatch(r'/api/conversation-growth/([a-f0-9]{32})(?:/([a-f0-9]{32})(/artifact)?|/requests/([a-f0-9]{32}))?', handler.path)
    if not match: return False
    if not handler._workspace_token() or not handler._guard(): return True
    try:
        bridge = service(handler)
        if match[3]:
            raw, _ = bridge.artifact(match[1], match[2]); handler._send(200, raw, 'text/plain; charset=utf-8')
        else:
            value = bridge.lookup(match[1], match[4]) if match[4] else bridge.bound(match[1], match[2]) if match[2] else bridge.list(match[1])
            handler._send(200, value)
    except Exception as exc: failure(handler, exc)
    return True


def post(handler, match, payload):
    try:
        bridge = service(handler)
        if not match[2]: value = bridge.propose(match[1], payload)
        elif match[3] == 'start': value = bridge.start(match[1], match[2], payload)
        elif match[3] == 'reanalyse': value = bridge.reanalyse(match[1], match[2], payload)
        else: value = bridge.cancel(match[1], match[2], payload)
        handler._send(200, value)
    except Exception as exc: failure(handler, exc)
