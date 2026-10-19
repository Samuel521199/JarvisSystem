"""Detect obvious credentials in selected coding material before dispatch/storage."""
import re
from . import policy

PATTERNS=(r'-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----',
          r'\b(?:sk-(?:proj-)?|xai-|ghp_|github_pat_)[A-Za-z0-9_-]{20,}',
          r'\bAIza[A-Za-z0-9_-]{30,}',
          r'(?i)\b(?:api[_-]?key|access[_-]?token|client[_-]?secret|password)\s*[=:]\s*[\"\x27][^\"\x27\r\n]{20,}[\"\x27]')


def ensure(text):
    if any(re.search(pattern,text) for pattern in PATTERNS):
        raise policy.CoreError('coding_sensitive_material','编码资料含疑似凭据；请移除字面密钥并改用环境配置，再重新提交。未发送该资料。')
