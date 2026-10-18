"""Optional speech endpoints share the existing module nonce and host boundary."""
import re
from jarvis_core.speech_contract import SpeechError
from jarvis_core.policy import CoreError


def get(handler):
    path = handler.path
    if path == '/speech.js':
        handler._send(200, handler.server.speech_script, 'application/javascript; charset=utf-8'); return True
    if path == '/readout.js':
        handler._send(200, handler.server.readout_script, 'application/javascript; charset=utf-8'); return True
    readout = re.fullmatch(r'/api/speech/readout/([a-f0-9]{32})',path)
    if readout:
        if not handler._module_token():return True
        try:handler._send(200,handler.server.modules.primary_speech.reader.view(readout[1]))
        except Exception:handler._error(503,'readout_unavailable','朗读状态暂不可用，没有自动重放。')
        return True
    match = re.fullmatch(r'/api/speech(/fast|/primary)?/audio/([a-f0-9]{32})', path)
    if path not in {'/api/speech','/api/speech/fast','/api/speech/primary'} and not match: return False
    if not handler._module_token(): return True
    service = select(handler, '/api/speech'+(match[1] or '') if match else path)
    try:
        if match: handler._send(200, service.audio(match[2]), 'audio/wav')
        else: handler._send(200, service.snapshot())
    except (SpeechError, OSError, CoreError): handler._error(404, 'speech_audio_missing', '此语音尚未生成或已不可用。')
    return True


def post(handler, payload):
    if handler.path=='/api/speech/readout':
        try:handler._send(200,handler.server.modules.primary_speech.reader.submit(payload))
        except SpeechError as exc:handler._error(400,'readout_invalid',str(exc))
        except Exception:handler._error(503,'readout_unavailable','朗读暂不可用；聊天与任务可以继续。')
        return
    service = select(handler,handler.path)
    try: handler._send(200 if handler.path=='/api/speech/primary' and isinstance(payload,dict) and payload.get('action')=='preview' else 202, service.submit(payload))
    except SpeechError as exc: handler._error(400, 'speech_request_invalid', str(exc))
    except Exception: handler._error(503, 'speech_unavailable', '语音组件暂不可用，聊天与任务服务仍独立运行。')


def select(handler,path):
    names={'/api/speech':'speech','/api/speech/fast':'fast_speech','/api/speech/primary':'primary_speech'}
    return getattr(handler.server.modules,names[path])
