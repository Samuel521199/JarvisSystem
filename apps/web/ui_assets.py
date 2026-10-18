"""Startup-only asset reads; optional presentation failures stay visible and local."""
from html import escape
import re

CORE_ASSETS = frozenset({'index.html', 'theme.css', 'workspace.css', 'attachments.js',
                         'conversations.js', 'workspace.js'})
DEGRADED_STYLE = b'''
body[data-ui-degraded]{display:flex;flex-direction:column;height:100dvh}
body[data-ui-degraded]>.app{flex:1;height:auto;min-height:0}
.asset-warning{flex:none;padding:8px 20px;border-bottom:1px solid var(--warning-line,#c5a674);
background:var(--warning-bg,#fff3dd);color:var(--ink,#18283a);font:13px/1.5 system-ui;overflow-wrap:anywhere}
.asset-warning details{display:inline}.asset-warning summary{display:inline;cursor:pointer;margin-left:8px}
.asset-warning details[open]{display:block;max-height:100px;overflow:auto}
'''


class UIAssets:
    def __init__(self, root):
        self.root = root
        self.failures = {}
        self.cache = {}

    def required(self, name):
        body = (self.root / name).read_bytes()
        if not body:
            raise ValueError('Required UI asset is empty: ' + name)
        return body

    def optional(self, name):
        # Names come only from the server's static asset list, never a URL.
        if name in CORE_ASSETS:
            raise ValueError('Core assets cannot be loaded as optional')
        if name not in self.cache:
            try:
                body = self.required(name)
            except (OSError, ValueError) as exc:
                self.failures[name] = ('missing' if isinstance(exc, FileNotFoundError)
                                       else 'empty' if isinstance(exc, ValueError) else 'unreadable')
                body = b''
            self.cache[name] = body
        return self.cache[name]

    def snapshot(self):
        return {'status': 'degraded' if self.failures else 'ready',
                'unavailable': [{'asset': name, 'reason': reason}
                                for name, reason in sorted(self.failures.items())]}

    def finish(self, body, *, base=''):
        if not self.failures:
            return body
        def script(match):
            src = re.search(rb'\bsrc="([^"]+)"', match[0])
            if src:
                path = src[1].decode('utf-8')
                name = path.lstrip('/') if path.startswith('/') else base + path
                if name in self.failures:
                    return b''
            return match[0]
        body = re.sub(rb'<script\b[^>]*>.*?</script>', script, body, flags=re.DOTALL)
        details = '、'.join(escape(name) for name in sorted(self.failures))
        notice = ('<aside role="status" class="asset-warning">部分界面资源不可用；相关入口或外观可能降级。'
                  '聊天核心可继续使用。<details><summary>查看缺失或无法读取的资源</summary>'
                  + details + '</details></aside>').encode('utf-8')
        body = body.replace(b'</style>', DEGRADED_STYLE + b'</style>', 1)
        return re.sub(rb'(<body\b[^>]*>)', lambda m: m[0][:-1] + b' data-ui-degraded>' + notice, body, count=1)


UNAVAILABLE_PAGE = ('<!doctype html><html lang="zh-CN"><meta charset="utf-8">'
                    '<title>Jarvis · 页面暂不可用</title><body><h1>此页面暂不可用</h1>'
                    '<p>界面资源不完整，请修复安装后重新启动。</p><a href="/">返回聊天</a></body></html>').encode('utf-8')
