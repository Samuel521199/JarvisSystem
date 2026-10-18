"""Bounded Context7 Streamable HTTP subset; remote text never grants authority."""
import asyncio
import json
import re
import time

import httpx

from . import __version__, policy

ENDPOINT = 'https://mcp.context7.com/mcp'
VERSIONS = {'2025-03-26', '2025-06-18', '2025-11-25'}
MAX_RESPONSE = 256 * 1024
LIBRARY_ID = r'/[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+(?:/[A-Za-z0-9_.-]+)?'
TOOLS = {'resolve-library-id': {'query', 'libraryName'}, 'query-docs': {'query', 'libraryId'}}


def failure(code, message):
    raise policy.CoreError(code, message)


class Context7Client:
    def __init__(self, checkpoint=lambda: None, *, transport=None):
        self.checkpoint, self.transport = checkpoint, transport
        self.headers = {'Accept': 'application/json, text/event-stream'}
        self.trace, self.ordinal, self.dispatched = [], 0, False

    async def _response(self, client, payload):
        async with client.stream('POST', ENDPOINT, json=payload, headers=self.headers) as response:
            if response.status_code in (401, 403, 429):
                failure('mcp_access_unavailable', 'Context7 要求授权或当前额度不足；没有自动重试。')
            if response.status_code == 404:
                failure('mcp_session_expired', 'MCP 会话已失效；此次请求没有自动重放。')
            if response.status_code == 202 and 'id' not in payload:
                return None
            if response.status_code != 200:
                failure('mcp_http_error', 'MCP 返回 HTTP ' + str(response.status_code) + '；没有自动重试。')
            session = response.headers.get('mcp-session-id')
            if session:
                if payload.get('method') != 'initialize' or not re.fullmatch(r'[\x21-\x7e]{1,256}', session):
                    failure('mcp_protocol_error', 'MCP 会话头无效。')
                self.headers['Mcp-Session-Id'] = session
            kind = response.headers.get('content-type', '').split(';')[0].strip().lower()
            if kind not in {'application/json', 'text/event-stream'}:
                failure('mcp_protocol_error', 'MCP 返回了不支持的内容类型。')
            raw = bytearray()
            pending = bytearray()
            async for chunk in response.aiter_bytes():
                self.checkpoint()
                raw.extend(chunk)
                if len(raw) > MAX_RESPONSE:
                    failure('mcp_output_limit', 'MCP 响应超过 256 KiB，未截断为成功结果。')
                if kind == 'text/event-stream':
                    pending.extend(chunk)
                    # SSE lines may be split across arbitrary HTTP chunks.
                    while b'\n\n' in pending.replace(b'\r\n', b'\n'):
                        normalized = pending.replace(b'\r\n', b'\n')
                        event, rest = normalized.split(b'\n\n', 1)
                        pending = bytearray(rest)
                        data = b'\n'.join(line[5:].lstrip(b' ') for line in event.split(b'\n') if line.startswith(b'data:'))
                        if data:
                            value = self._message(data, payload.get('id'))
                            if value is not None:
                                return value
            if kind == 'application/json':
                value = self._message(bytes(raw), payload.get('id'))
                if value is not None:
                    return value
            failure('mcp_incomplete', 'MCP 流已结束，但没有完整的对应结果。')

    @staticmethod
    def _message(raw, ident):
        try:
            value = json.loads(raw)
        except (ValueError, UnicodeError):
            failure('mcp_protocol_error', 'MCP 响应不是有效 JSON。')
        if not isinstance(value, dict) or value.get('jsonrpc') != '2.0':
            failure('mcp_protocol_error', 'MCP 消息格式无效。')
        if 'method' in value:
            if 'id' in value:
                failure('mcp_unsupported_request', '服务器要求了未启用的反向调用。')
            return None  # Notifications are data; never run remote instructions.
        if value.get('id') != ident or type(value.get('id')) is not int or ident is None:
            failure('mcp_protocol_error', 'MCP 回执编号不匹配。')
        if 'error' in value:
            failure('mcp_remote_error', 'MCP 返回协议错误，未执行自动重试。')
        if not isinstance(value.get('result'), dict):
            failure('mcp_protocol_error', 'MCP 缺少结果对象。')
        return value['result']

    async def _request(self, client, method, params=None, *, notification=False):
        self.checkpoint()
        payload = {'jsonrpc': '2.0', 'method': method}
        if not notification:
            self.ordinal += 1
            payload['id'] = self.ordinal
        if params is not None:
            payload['params'] = params
        row = {'method': method, 'id': payload.get('id'), 'status': 'started'}
        if method == 'tools/call':
            row.update(tool=params['name'], arguments_digest=policy.digest(policy.canonical_json(params['arguments']).encode()))
            self.dispatched = True
        self.trace.append(row)
        work = asyncio.create_task(self._response(client, payload))
        deadline = time.monotonic() + 25
        try:
            while not work.done():
                await asyncio.wait({work}, timeout=.1)
                self.checkpoint()
                if time.monotonic() > deadline:
                    failure('mcp_timeout', 'MCP 等待超过 25 秒；请求结果待核对，没有自动重试。')
            result = await work
            row['status'] = 'received'
            return result
        except BaseException as exc:
            row['status'] = getattr(exc, 'code', 'network_error')
            work.cancel()
            await asyncio.gather(work, return_exceptions=True)
            if method == 'tools/call':
                # Cancellation is best effort; it cannot retract the sent query.
                try:
                    await asyncio.wait_for(client.post(ENDPOINT, headers=self.headers, json={
                        'jsonrpc': '2.0', 'method': 'notifications/cancelled',
                        'params': {'requestId': payload['id'], 'reason': 'Client stopped waiting'}}), 1)
                except Exception:
                    pass
            raise

    async def query(self, library, prompt):
        async with httpx.AsyncClient(transport=self.transport, timeout=10, follow_redirects=False) as client:
            try:
                init = await self._request(client, 'initialize', {'protocolVersion': '2025-11-25', 'capabilities': {},
                    'clientInfo': {'name': 'Jarvis', 'version': __version__}})
                version = init.get('protocolVersion')
                if version not in VERSIONS or not isinstance(init.get('capabilities'), dict) or not isinstance(init['capabilities'].get('tools'), dict):
                    failure('mcp_protocol_error', '服务器未提供兼容版本和工具能力。')
                self.headers['MCP-Protocol-Version'] = version
                await self._request(client, 'notifications/initialized', notification=True)
                listing = await self._request(client, 'tools/list')
                rows = listing.get('tools')
                if not isinstance(rows, list) or len(rows) > 32 or listing.get('nextCursor'):
                    failure('mcp_tools_changed', '工具目录超过此适配器的已核对范围。')
                name = 'query-docs' if re.fullmatch(LIBRARY_ID, library) else 'resolve-library-id'
                matches = [r for r in rows if isinstance(r, dict) and r.get('name') == name]
                if len(matches) != 1:
                    failure('mcp_tools_changed', '所需文档工具缺失或重复。')
                schema = matches[0].get('inputSchema', {})
                properties = schema.get('properties', {}) if isinstance(schema, dict) else {}
                required = schema.get('required') if isinstance(schema, dict) else None
                # Do not resolve server-supplied schema URLs or trust readOnlyHint.
                if schema.get('type') != 'object' or not isinstance(properties, dict) or not isinstance(required, list) or set(required) != TOOLS[name] or any(properties.get(k, {}).get('type') != 'string' for k in TOOLS[name]):
                    failure('mcp_tools_changed', '工具参数已变化，需更新适配器后使用。')
                arguments = {'query': prompt, 'libraryId' if name == 'query-docs' else 'libraryName': library}
                result = await self._request(client, 'tools/call', {'name': name, 'arguments': arguments})
                if result.get('isError'):
                    failure('mcp_tool_failed', 'Context7 工具报告失败；未作为有效文档交付。')
                content = result.get('content')
                if not isinstance(content, list) or not content or len(content) > 64 or any(not isinstance(r, dict) or r.get('type') != 'text' or not isinstance(r.get('text'), str) for r in content):
                    failure('mcp_result_invalid', '文档工具返回了不支持的内容。')
                text = '\n\n'.join(r['text'] for r in content)
                if not text.strip() or len(text.encode()) > 192 * 1024:
                    failure('mcp_result_invalid', '文档结果为空或超过 192 KiB。')
                candidates = list(dict.fromkeys(re.findall(r'^- Context7-compatible library ID: (' + LIBRARY_ID + r')\s*$', text, re.M)))[:12] if name == 'resolve-library-id' else []
                return {'kind': 'jarvis.mcp-report', 'mcp_id': 'context7', 'endpoint': ENDPOINT, 'protocol_version': version,
                        'tool': name, 'library': library, 'query': prompt, 'text': text, 'candidates': candidates,
                        'trace': self.trace, 'checks': {'model_calls': 0, 'tool_calls': 1, 'remote_text_verified': False,
                            'local_files_sent': False, 'target_code_executed': False}}
            finally:
                if self.headers.get('Mcp-Session-Id'):
                    try:
                        await asyncio.wait_for(client.delete(ENDPOINT, headers=self.headers), 1)
                    except Exception:
                        pass
