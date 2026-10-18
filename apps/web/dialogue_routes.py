"""Receipt polling has no model work and is independent of task/module services."""
import re
import secrets
from urllib.parse import urlsplit, parse_qs

from jarvis_core.turns import TurnError


def error(handler, exc):
    if isinstance(exc, TurnError):
        handler._error(exc.status, exc.code, str(exc))
    elif isinstance(exc, (ValueError, TypeError)):
        handler._error(400, 'invalid_turn', '对话请求字段无效。')
    else:
        handler._error(503, 'dialogue_unavailable', '对话入口暂不可用，没有自动重发。')


def get(handler):
    if handler.path == '/dialogue.js':
        handler._send(200, handler.server.dialogue_script, 'application/javascript; charset=utf-8'); return True
    url = urlsplit(handler.path)
    match = re.fullmatch(r'/api/dialogue/(turns|recover)/([a-f0-9]{32})', url.path)
    if not match: return False
    tokens = handler.headers.get_all('X-Jarvis-Nonce', [])
    if len(tokens) != 1 or not tokens[0].isascii() or not secrets.compare_digest(tokens[0], handler.server.nonce):
        handler._error(403, 'request_token_invalid', '页面会话已失效，请刷新。'); return True
    try:
        query = parse_qs(url.query, keep_blank_values=True)
        fields={'conversation_id'} if match[1]=='recover' else {'conversation_id','instance_id'}
        if set(query) != fields or any(len(v) != 1 for v in query.values()):
            raise ValueError('invalid query')
        value=handler.server.dialogue.recover(query['conversation_id'][0],match[2]) if match[1]=='recover' else handler.server.dialogue.view(query['instance_id'][0], query['conversation_id'][0], match[2])
        handler._send(200, value)
    except Exception as exc: error(handler, exc)
    return True


def post(handler, payload):
    try:
        if not isinstance(payload, dict): raise ValueError('invalid object')
        fields = {'instance_id', 'conversation_id', 'request_id'}
        if handler.path == '/api/dialogue/turns':
            if set(payload) != fields | {'chat'}: raise ValueError('invalid fields')
            message, provider, *_ = handler.server.validate_chat(payload['chat'])
            from jarvis_core.personal import parse
            if not parse(message) and provider != 'auto' and provider not in {p['provider'] for p in handler.server.chat.models()['providers']}:
                raise ValueError('unknown provider')
            result = handler.server.dialogue.submit(payload['instance_id'], payload['conversation_id'],
                                                    payload['request_id'], payload['chat'])
            handler._send(202, result)
        else:
            if set(payload) != fields: raise ValueError('invalid fields')
            handler._send(200, handler.server.dialogue.cancel(payload['instance_id'], payload['conversation_id'], payload['request_id']))
    except Exception as exc: error(handler, exc)
