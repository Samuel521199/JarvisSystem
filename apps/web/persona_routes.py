"""Independent local expression settings with revision and retry fencing."""
import secrets
from jarvis_core.memory import MemoryError, validate
from jarvis_core.persona import PersonaStore


def token(handler):
    values = handler.headers.get_all('X-Jarvis-Nonce', [])
    if len(values) != 1 or not values[0].isascii() or not secrets.compare_digest(values[0],handler.server.nonce):
        handler._error(403,'request_token_invalid','页面会话已失效，请刷新。')
        return False
    return True


UNSET = object()


def respond(handler, payload=UNSET):
    try:
        store = PersonaStore(handler.server.core)
        if payload is UNSET:
            result = store.snapshot()
        else:
            if not isinstance(payload,dict) or set(payload) != {'action','revision','request_id','profile'} or payload['action'] not in ('profile','undo','reset'):
                raise MemoryError('invalid_persona','交流配置字段无效。')
            validate('revision',payload['revision'])
            result = store.change(payload['action'],payload['profile'],request_id=payload['request_id'],revision=payload['revision'])
        handler._send(200,dict(result,schema_version=2))
    except Exception as error:
        code = error.code if isinstance(error,MemoryError) else 'persona_unavailable'
        handler._error(409 if code == 'persona_conflict' else 503 if code == 'persona_unavailable' else 400,
                       code,str(error) if isinstance(error,MemoryError) else '交流设置暂不可用；输入仍保留，未切换到默认配置覆盖它。')
