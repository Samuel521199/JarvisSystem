"""Process-local signed preview codec shared by rule and semantic candidates."""
import base64
import hashlib
import hmac
import json
import time

from .memory import fail

TTL = 1200


def encoded(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()


class CandidateTokens:
    def sign(self, draft):
        body = base64.urlsafe_b64encode(encoded(draft)).decode()
        return body + '.' + hmac.new(self.key, body.encode(), hashlib.sha256).hexdigest()

    def open_token(self, token):
        try:
            if not isinstance(token, str) or len(token) > 32768: raise ValueError('size')
            body, signature = token.split('.')
            if not hmac.compare_digest(signature, hmac.new(self.key, body.encode(), hashlib.sha256).hexdigest()): raise ValueError('signature')
            draft = json.loads(base64.urlsafe_b64decode(body))
            if draft['expires'] < time.time(): raise ValueError('expired')
        except (ValueError, KeyError, TypeError):
            fail('candidate_preview_expired', '候选预览已过期、服务已重启或校验失败，请重新整理。')
        return draft
