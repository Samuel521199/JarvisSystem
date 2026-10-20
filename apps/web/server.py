"""Loopback chat and explicit browser task console; no core stop/reset endpoint."""
from __future__ import annotations

import argparse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import queue
import re
import secrets
import socket
import sys
import threading
import time
from urllib.parse import urlsplit, parse_qs

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / 'adapters/models/provider-native'), str(ROOT / 'runtime/node-host'), str(ROOT / 'apps/web')]
from jarvis_core.context_assembly import validate_note
from jarvis_core.memory import MemoryStore, MemoryError, validate as validate_memory, validate_history_references
from jarvis_core.knowledge import KnowledgeStore, KnowledgeError, validate as validate_knowledge, history_references as knowledge_history_references
from jarvis_models.attachments import (validate_message, validate_attachments, text_size,
    image_budget, MAX_CHAT_BODY, MAX_IMAGES_BYTES, MAX_ATTACHMENTS)
INDEX_PATH = Path(__file__).with_name("index.html")


from ui_assets import UIAssets, UNAVAILABLE_PAGE

MAX_BODY_BYTES = 131072
MAX_MESSAGE_BYTES = 65536
MAX_HISTORY_BYTES = 32768
REPLY_TIMEOUT_SECONDS = 120
SOCKET_TIMEOUT_SECONDS = 10
PROVIDERS = {"auto", "vertex", "bailian", "openai", "xai", "local"}


class ChatRequests:
    """Bounded process-local cancellation handles; never stores prompt or reply."""
    def __init__(self):
        self.lock = threading.Lock()
        self.entries = {}
        self.active = 0

    def _entry(self, request_id):
        now = time.monotonic()
        self.entries = {key: row for key, row in self.entries.items()
                        if (row['started'] and not row['finished']) or now - row['touched'] < 600}
        if request_id not in self.entries:
            if len(self.entries) >= 256:
                raise ValueError('request_registry_full')
            self.entries[request_id] = {'event': threading.Event(), 'started': False, 'finished': False, 'touched': now}
        return self.entries[request_id]

    def start(self, request_id):
        with self.lock:
            row = self._entry(request_id)
            if row['started']:
                raise ValueError('request_already_used')
            row['started'] = True
            return row['event']

    def cancel(self, request_id):
        with self.lock:
            row = self._entry(request_id)
            row['event'].set()  # Also fences a cancel that arrives before the chat POST.
            return 'FINISHED' if row['finished'] else 'CANCEL_REQUESTED'

    def finish(self, request_id):
        with self.lock:
            if request_id in self.entries:
                self.entries[request_id].update(finished=True, touched=time.monotonic())

    def cancel_all(self):
        with self.lock:
            for row in self.entries.values():
                row['event'].set()


def strict_json(data):
    def unique_pairs(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("duplicate field")
            result[key] = value
        return result

    def invalid_constant(value):
        raise ValueError("nonfinite number")

    return json.loads(data, object_pairs_hook=unique_pairs, parse_constant=invalid_constant)


def validate_chat(payload):
    if not isinstance(payload, dict) or set(payload) - {"message", "provider", "history", "model", "reasoning", "attachments", "context_note", "memory_context", "history_memory", "knowledge_context", "history_knowledge", "skill_context", "personal_context", "continuity_context", "history_continuity", "voice_mode", "shared_context", "history_shared"}:
        raise ValueError("invalid request fields")
    from jarvis_core.voice_turn import validate as validate_voice
    validate_voice(payload.get('voice_mode'))
    from jarvis_core.personal import validate_context as validate_personal_context
    validate_personal_context(payload.get('personal_context'))
    if 'skill_context' in payload:
        from jarvis_core.skills import validate_context
        try: validate_context(payload['skill_context'])
        except Exception as exc: raise ValueError('invalid skill context') from exc
    validate_note(payload.get("context_note"))
    message = payload.get("message")
    if not isinstance(message, str) or not message.strip() or len(message.encode("utf-8")) > MAX_MESSAGE_BYTES:
        raise ValueError("invalid message")
    provider = payload.get("provider", "auto")
    if not isinstance(provider, str) or not re.fullmatch(r"[a-z][a-z0-9_-]{0,63}", provider):
        raise ValueError("invalid provider")
    model = payload.get("model")
    if model is not None and (provider == "auto" or not isinstance(model, str) or not re.fullmatch(r"(?=.{1,128}$)[a-zA-Z0-9][a-zA-Z0-9._:-]*(?:/[a-zA-Z0-9][a-zA-Z0-9._:-]*)?", model)):
        raise ValueError("invalid model")
    reasoning = payload.get("reasoning")
    if reasoning is not None and (provider == "auto" or not isinstance(reasoning, str)
                                  or reasoning not in {"none", "minimal", "low", "medium", "high", "xhigh", "max", "off", "on"}):
        raise ValueError("invalid reasoning level")
    history = payload.get("history", [])
    if not isinstance(history, list) or len(history) > 20:
        raise ValueError("invalid history")
    if payload.get('memory_context') is not None:
        validate_memory('context', payload['memory_context'])
    validate_history_references(payload.get('history_memory'), history)
    from jarvis_core.continuity import validate_context as validate_continuity_context, validate_history_references as continuity_history
    validate_continuity_context(payload.get('continuity_context'))
    continuity_history(payload.get('history_continuity'), history)
    from jarvis_core.federation_access import context as shared_context
    from jarvis_core.policy import CoreError
    try:
        shared_context(payload.get('shared_context'), history, payload.get('history_shared'))
    except CoreError as exc:
        raise ValueError('invalid shared context') from exc
    if payload.get('knowledge_context') is not None:
        validate_knowledge('context', payload['knowledge_context'])
    knowledge_history_references(payload.get('history_knowledge'), history)
    size = 0
    attachments = validate_attachments(payload.get('attachments'))
    current = {'content': message, 'attachments': attachments}
    if text_size(current) > MAX_MESSAGE_BYTES:
        raise ValueError('message and text attachments too large')
    for item in history:
        item = validate_message(item)
        size += text_size(item)
    if size > MAX_HISTORY_BYTES:
        raise ValueError("history too large")
    image_bytes, image_count = image_budget(history + [current])
    if image_bytes > MAX_IMAGES_BYTES or image_count > MAX_ATTACHMENTS:
        raise ValueError('image budget exceeded')
    return message, provider, history, model, reasoning


from jarvis_core.resource_usage import ResourceUsage, collect_usage
from jarvis_core.runtime_metrics import RuntimeMetrics
from jarvis_core.turns import DialogueTurns, invoke_reply
from jarvis_core.process_usage import process_usage


class LocalChatServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = not hasattr(socket, 'SO_EXCLUSIVEADDRUSE')

    def server_bind(self):
        if hasattr(socket, 'SO_EXCLUSIVEADDRUSE'):
            self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        super().server_bind()

    def __init__(self, address, core, chat, *, reply_timeout=REPLY_TIMEOUT_SECONDS, computer=None, workspace=None, version='test'):
        if address[0] != "127.0.0.1":
            raise ValueError("The chat server must bind to 127.0.0.1")
        self.core = core
        self.chat = chat
        self.computer = computer
        self.workspace = workspace
        self.project_files = None
        self.extensions = None
        self.skills = None
        self.skill_previews = {}
        self.skill_preview_lock = threading.Lock()
        self.project_catalog = None
        self.conversations = None
        self.memory = None
        self.knowledge = None
        self.federation = None
        self.admin = None
        self.modules = None
        self.evolution = None
        self.conversation_tasks = None
        self.version = version
        self.instance_id = secrets.token_hex(16)
        self.nonce = secrets.token_urlsafe(32)
        self.slots = threading.BoundedSemaphore(2)
        self.chat_requests = ChatRequests()
        from jarvis_core.semantic_candidates import SemanticCandidates
        self.semantic_candidates = SemanticCandidates(core, chat) if hasattr(core, 'data_dir') else None
        self.reply_timeout = reply_timeout
        self.metrics = RuntimeMetrics()
        self.dialogue = DialogueTurns(core, chat, self.instance_id, self.slots, self.chat_requests, self.metrics)
        self.validate_chat = validate_chat
        self.resource_usage = ResourceUsage(self._collect_usage)
        self.ui_assets = UIAssets(INDEX_PATH.parent)
        asset = self.ui_assets.optional
        self.resource_script = asset('resources.js')
        self.dialogue_script = asset('dialogue.js')
        self.theme_style = self.ui_assets.required('theme.css')
        self.theme_script = asset('theme.js')
        self.attachments_script = self.ui_assets.required('attachments.js')
        self.shared_reference_script = asset('shared-reference.js')
        self.context_script = asset('context.js')
        self.conversation_script = self.ui_assets.required('conversations.js')
        self.conversation_tasks_script = asset('conversation_tasks.js')
        self.memory_script = asset('memory.js')
        self.persona_script = asset('persona.js')
        self.continuity_script = asset('continuity.js')
        self.personal_candidates_script = asset('personal_candidates.js')
        self.knowledge_script = asset('knowledge.js')
        self.explorer_script = asset('explorer.js')
        self.project_menu_script = asset('project_menu.js')
        self.workbench_script = asset('workbench.js')
        self.extensions_script = asset('extensions.js')
        self.mcp_manager_script = asset('mcp_manager.js')
        self.skills_script = asset('skills.js')
        self.skills_manager_script = asset('skills_manager.js')
        # One fixed static file; never derive filesystem paths from a request.
        brand_style = asset('brand/logo.css') + b'\n' + asset('brand/lifecycle.css')
        self.html = self.ui_assets.required('index.html').replace(b"__JARVIS_WORKSPACE_STYLE__", self.ui_assets.required('workspace.css') + b'\n' + asset('context.css')).replace(b'__JARVIS_BRAND_STYLE__', brand_style).replace(b"__JARVIS_NONCE__", self.nonce.encode("ascii")).replace(b'__JARVIS_VERSION__',version.encode('ascii')).replace(b'__JARVIS_THEME_STYLE__', self.theme_style)
        self.html = self.html.replace(b'__JARVIS_MEMORY_STYLE__', asset('memory.css'))
        self.html = self.html.replace(b'__JARVIS_KNOWLEDGE_STYLE__', asset('knowledge.css'))
        self.html = self.html.replace(b'__JARVIS_EXPLORER_STYLE__', asset('explorer.css'))
        self.html = self.html.replace(b'__JARVIS_CONVERSATION_TASKS_STYLE__', asset('conversation_tasks.css'))
        self.html = self.html.replace(b'__JARVIS_WORKBENCH_STYLE__', asset('workbench.css'))
        self.html = self.html.replace(b'__JARVIS_PROJECT_MENU_STYLE__', asset('project_menu.css'))
        # Exact public asset map; source artwork and arbitrary paths stay private.
        brand_files = {
            'logo.js': 'application/javascript; charset=utf-8',
            'preview.js': 'application/javascript; charset=utf-8',
            'sound.js': 'application/javascript; charset=utf-8',
            'lifecycle.js': 'application/javascript; charset=utf-8',
            'lifecycle.css': 'text/css; charset=utf-8',
            'logo.css': 'text/css; charset=utf-8',
            'preview.css': 'text/css; charset=utf-8',
            'jarvis.ico': 'image/x-icon',
            **{name + '.png': 'image/png' for name in ('core', 'icon',
                'icon-16', 'icon-24', 'icon-32', 'icon-48', 'icon-64', 'icon-128', 'icon-256')},
        }
        self.brand_assets = {'/brand/' + name: (asset('brand/' + name), mime)
                             for name, mime in brand_files.items()}
        self.brand_html = asset('brand/preview.html').replace(
            b'<link data-lifecycle-css rel="stylesheet" href="lifecycle.css">', b''
        ).replace(
            b'<link data-brand-css rel="stylesheet" href="logo.css">',
            b'<style nonce="__JARVIS_NONCE__">' + brand_style + b'</style>').replace(
            b'<link data-preview-css rel="stylesheet" href="preview.css">',
            b'<style nonce="__JARVIS_NONCE__">' + asset('brand/preview.css') + b'</style>'
        ).replace(b'__JARVIS_NONCE__', self.nonce.encode('ascii'))
        self.computer_script = asset('computer.js')
        self.html = self.html.replace(b'__JARVIS_ATTACHMENTS_STYLE__', asset('attachments.css') + b'\n' + asset('shared-reference.css'))
        self.workspace_script = self.ui_assets.required('workspace.js')
        self.admin_html = asset('admin.html').replace(b'__JARVIS_ADMIN_STYLE__', asset('admin.css')).replace(b'__JARVIS_NONCE__', self.nonce.encode('ascii')).replace(b'__JARVIS_VERSION__', version.encode('ascii')).replace(b'__JARVIS_THEME_STYLE__', self.theme_style)
        self.admin_script = asset('admin.js')
        self.federation_script = asset('federation.js')
        self.shared_access_script = asset('shared-access.js')
        self.shared_connection_script = asset('shared-connection.js')
        self.network_script = asset('network.js')
        self.coding_script = asset('coding.js')
        self.admin_html = self.admin_html.replace(b'__JARVIS_MODULE_STYLE__', asset('modules.css') + b'\n' + asset('evolution.css') + b'\n' + asset('speech.css') + b'\n' + asset('federation.css')).replace(b'__JARVIS_BRAND_STYLE__', asset('brand/logo.css'))
        self.module_script = asset('modules.js')
        self.speech_script = asset('speech.js')
        self.readout_script = asset('readout.js')
        self.voice_input_script = asset('voice-input.js')
        self.voice_capture_script = asset('voice-capture.js')
        self.voice_session_script = asset('voice-session.js')
        self.voice_session_capture_script = asset('voice-session-capture.js')
        self.html = self.html.replace(b'__JARVIS_READOUT_STYLE__', asset('readout.css'))
        self.evolution_script = asset('evolution.js')
        self.ranking_modules_script = asset('ranking-modules.js')
        self.growth_script = asset('growth.js')
        self.project_tools_script = asset('project-tools.js')
        self.growth_cycles_script = asset('growth-cycles.js')
        self.tool_intents_script = asset('tool-intents.js')
        self.creation_script = asset('creation.js')
        self.tool_contracts_script = asset('tool-contracts.js')
        self.tool_lifecycle_script = asset('tool-lifecycle.js')
        self.html = self.html.replace(b'__JARVIS_GROWTH_STYLE__', asset('growth.css'))
        self.admin_html = self.admin_html.replace(b'__JARVIS_EXTENSIONS_STYLE__', asset('extensions.css') + b'\n' + asset('skills.css') + b'\n' + asset('mcp.css'))
        if not asset('admin.html') or not self.admin_script:
            self.admin_html = UNAVAILABLE_PAGE
        if any(name.startswith('brand/') for name in self.ui_assets.failures):
            self.brand_html = UNAVAILABLE_PAGE
        self.html = self.ui_assets.finish(self.html)
        self.admin_html = self.ui_assets.finish(self.admin_html)
        self.brand_html = self.ui_assets.finish(self.brand_html, base='brand/')
        super().__init__(address, ChatHandler)
        port = self.server_address[1]
        self.allowed_hosts = {f"127.0.0.1:{port}", f"localhost:{port}"}
        self.allowed_origins = {"http://" + host for host in self.allowed_hosts}

    def _owned_processes(self):
        rows = {'host': os.getpid()}
        if self.modules:
            local = self.modules.local_model.snapshot()
            if local.get('owned') and local.get('pid'):
                rows['local_model'] = local['pid']
        return rows

    def _collect_usage(self):
        def read():
            result = {}
            for name, pid in self._owned_processes().items():
                try: result[name] = process_usage(pid)
                except (OSError, AttributeError): pass
            return result
        started = time.monotonic(); before = read()
        data = collect_usage(); after = read(); seconds = time.monotonic()-started
        data['processes'] = []
        for name, pid in self._owned_processes().items():
            first, last = before.get(name), after.get(name)
            valid = last is not None and last['pid'] == pid
            cpu = None
            if valid and first and first['created'] == last['created'] and seconds > 0:
                cpu = round(max(0,min(100,(last['cpu_seconds']-first['cpu_seconds'])/seconds/(os.cpu_count() or 1)*100)),2)
            data['processes'].append({'name':name,'status':'available' if valid else 'unavailable', 'cpu_percent':cpu,
                'working_set_bytes': last['working_set_bytes'] if valid else None,
                'private_bytes': last['private_bytes'] if valid else None})
        return data

    def runtime_snapshot(self):
        result = self.metrics.snapshot()
        result['limits'] = {'chat_slots':2,'task_slots':1}
        result['dialogue'] = self.dialogue.snapshot()
        models = getattr(self.chat, 'dialogue_models', None)
        result['dialogue_processes'] = models.snapshot() if models is not None else {'enabled': False}
        models = getattr(self.chat, 'background_models', None)
        result['background_processes'] = models.snapshot() if models is not None else {'enabled': False}
        result['queue'] = None
        if self.computer:
            try:
                queue = self.computer.queue.snapshot()
                result['queue'] = {key:queue[key] for key in ('paused','owned','waiting','capacity','error','resources')}
                result['queue']['running'] = len(queue['running'])
                result['queue']['unreviewed_unknown'] = queue.get('unreviewed_unknown',False)
            except Exception:
                result['queue'] = {'unavailable':True}
        return result

    def server_close(self):
        try:
            if self.federation:self.federation.close()
            self.chat_requests.cancel_all()
            self.dialogue.close()
            models = getattr(self.chat, 'dialogue_models', None)
            if models is not None: models.close()
            models = getattr(self.chat, 'background_models', None)
            if models is not None: models.close()
            self.resource_usage.close()
            if self.evolution:self.evolution.close()
            if self.modules:self.modules.close()
            if self.computer:self.computer.close()
        finally:
            super().server_close()


class ChatHandler(BaseHTTPRequestHandler):
    server_version = "JarvisLocalChat/0.1"

    def setup(self):
        super().setup()
        self.connection.settimeout(SOCKET_TIMEOUT_SECONDS)
        self._body_read = False

    def log_message(self, format, *args):
        # Do not log messages, history, provider payloads, URLs, or credentials.
        pass

    def _send(self, status, body, content_type="application/json; charset=utf-8"):
        if not isinstance(body, bytes):
            body = json.dumps(body, ensure_ascii=False, allow_nan=False).encode("utf-8")
        try:
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("X-Frame-Options", "DENY")
            self.send_header("Referrer-Policy", "no-referrer")
            self.send_header("Content-Security-Policy", "default-src 'none'; "
                             f"script-src 'nonce-{self.server.nonce}' http://127.0.0.1:{self.server.server_port}/voice-capture.js http://localhost:{self.server.server_port}/voice-capture.js http://127.0.0.1:{self.server.server_port}/voice-session-capture.js http://localhost:{self.server.server_port}/voice-session-capture.js; style-src 'nonce-{self.server.nonce}'; "
                             "connect-src 'self'; img-src 'self' blob:; media-src 'self' blob:; frame-src 'self'; base-uri 'none'; form-action 'none'; frame-ancestors 'none'")
            self.end_headers()
            self.wfile.write(body)
        except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError, socket.timeout):
            pass

    def _discard_small_body(self):
        # Windows can reset a socket closed with an unread POST body, hiding an
        # otherwise correct rejection response. Drain only a bounded, promptly
        # arriving body; never wait for an untrusted declared large payload.
        if self.command != "POST" or self._body_read:
            return
        self._body_read = True
        lengths = self.headers.get_all("Content-Length", [])
        if len(lengths) != 1 or not lengths[0].isdigit():
            return
        size = int(lengths[0])
        if not 0 < size <= MAX_BODY_BYTES + 1:
            return
        try:
            self.connection.settimeout(0.2)
            self.rfile.read(size)
        except (OSError, ValueError):
            pass
        finally:
            self.connection.settimeout(SOCKET_TIMEOUT_SECONDS)

    def _error(self, status, code, message):
        self._discard_small_body()
        self._send(status, {"status": "BLOCKED", "error_category": code, "user_message": message})

    def _boundary(self, *, post=False):
        hosts = self.headers.get_all("Host", [])
        if len(hosts) != 1 or hosts[0] not in self.server.allowed_hosts:
            self._error(403, "request_origin_denied", "仅允许本机页面访问。")
            return False
        origins = self.headers.get_all("Origin", [])
        if len(origins) > 1 or (origins and origins[0] not in self.server.allowed_origins) or (post and not origins):
            self._error(403, "request_origin_denied", "请求来源不匹配，请从本机页面重新打开。")
            return False
        if origins and origins[0] != "http://" + hosts[0]:
            self._error(403, "request_origin_denied", "请求来源与本机地址不一致。")
            return False
        if post:
            tokens = self.headers.get_all("X-Jarvis-Nonce", [])
            if len(tokens) != 1 or not tokens[0].isascii() or not secrets.compare_digest(tokens[0], self.server.nonce):
                self._error(403, "request_token_invalid", "页面会话已失效，请刷新后重试。")
                return False
        return True

    def _computer_token(self):
        tokens=self.headers.get_all('X-Jarvis-Nonce',[])
        if len(tokens)!=1 or not tokens[0].isascii() or not secrets.compare_digest(tokens[0],self.server.nonce):
            self._error(403,'request_token_invalid','页面会话已失效，请刷新。')
            return False
        if self.server.computer is None:
            self._error(503,'computer_unavailable','浏览器模块未启用。')
            return False
        return True

    def _computer_error(self,exc):
        code=getattr(exc,'code','computer_unavailable')
        status=404 if code=='not_found' else 409 if code in {'computer_busy','worker_busy','idempotency_conflict','submission_unknown','queue_full','queue_version_changed','queue_content_changed'} else 503 if code in {'stopped','stale_authorization','computer_unavailable','queue_owner_changed','control_unavailable'} else 400
        # Only these explicitly typed module errors carry user-facing text.
        message=str(exc) if type(exc).__name__ in {'ComputerError','CoreError'} else '浏览器任务请求未完成，请检查任务列表。'
        if code=='control_unavailable':message='任务存储暂忙或不可用，本次结果未确认。请稍后核对任务状态，再重试；没有自动重复执行。'
        self._error(status,code,message)

    def _workspace_token(self):
        tokens = self.headers.get_all('X-Jarvis-Nonce', [])
        if len(tokens) != 1 or not tokens[0].isascii() or not secrets.compare_digest(tokens[0], self.server.nonce):
            self._error(403, 'request_token_invalid', '页面会话已失效，请刷新后重试。')
            return False
        if self.server.workspace is None:
            self._error(503, 'workspace_unavailable', '项目服务未启用。')
            return False
        return True

    def _workspace_error(self, exc):
        code = getattr(exc, 'code', 'workspace_unavailable')
        status = 404 if code in {'not_found','project_not_found'} else 409 if code in {'file_conflict', 'extension_conflict', 'mcp_policy_conflict', 'project_conflict', 'file_exists', 'idempotency_conflict', 'output_changed', 'output_unresolved', 'output_unknown', 'picker_busy', 'project_replaced'} else 503 if code in {'extensions_unavailable', 'project_catalog_unavailable', 'stopped', 'stale_authorization', 'workspace_unavailable'} else 400
        message = str(exc) if type(exc).__name__ == 'CoreError' else '项目操作未完成，请检查文件夹与本机服务。'
        self._error(status, code, message)

    def _conversation_error(self, exc):
        from jarvis_core.conversations import ConversationError
        code = exc.code if isinstance(exc, ConversationError) else 'conversation_unavailable'
        status = 404 if code == 'conversation_not_found' else 409 if code in {'conversation_conflict', 'conversation_deleted'} else 400 if isinstance(exc, ConversationError) else 503
        self._error(status, code, str(exc) if isinstance(exc, ConversationError) else '本机会话保存暂不可用；当前页面内容仍保留，请稍后重试。')

    def _conversation_token(self):
        tokens = self.headers.get_all('X-Jarvis-Nonce', [])
        if len(tokens) != 1 or not tokens[0].isascii() or not secrets.compare_digest(tokens[0], self.server.nonce):
            self._error(403, 'request_token_invalid', '页面会话已失效，请刷新。');return False
        if self.server.conversations is None:
            self._error(503, 'conversation_unavailable', '会话归档服务未启用。');return False
        return True

    def _guard(self):
        try:
            self.server.core.assert_running()
            return True
        except Exception:
            self._error(503, "core_not_ready", "核心未就绪或已停止；网页不会自动初始化或解除停止。")
            return False

    def _memory_token(self):
        tokens = self.headers.get_all('X-Jarvis-Nonce', [])
        if len(tokens) != 1 or not tokens[0].isascii() or not secrets.compare_digest(tokens[0], self.server.nonce):
            self._error(403, 'request_token_invalid', '页面会话已失效，请刷新。');return False
        if self.server.memory is None:
            self._error(503, 'memory_unavailable', '记忆模块未启用。');return False
        return True

    def _memory_error(self, exc):
        code = exc.code if isinstance(exc, MemoryError) else 'memory_unavailable'
        status = 404 if code in {'memory_not_found','continuity_not_found'} else 409 if code in {'memory_conflict', 'memory_deleted','continuity_conflict','continuity_source_conflict','candidate_review_changed','candidate_review_required','candidate_target_changed','candidate_duplicate'} else 503 if code in {'memory_unavailable','continuity_unavailable'} else 400
        self._error(status, code, str(exc) if isinstance(exc, MemoryError) else '记忆操作未确认，请重试；输入仍保留。')

    def _knowledge_token(self):
        tokens = self.headers.get_all('X-Jarvis-Nonce', [])
        if len(tokens) != 1 or not tokens[0].isascii() or not secrets.compare_digest(tokens[0], self.server.nonce):
            self._error(403, 'request_token_invalid', '页面会话已失效，请刷新。');return False
        if self.server.knowledge is None:
            self._error(503, 'knowledge_unavailable', '项目资料模块未启用。');return False
        return True

    def _knowledge_error(self, exc):
        code = exc.code if isinstance(exc, KnowledgeError) else 'knowledge_unavailable'
        status = 404 if code == 'source_not_found' else 409 if code in {'source_stale','source_conflict','source_deleted'} else 503 if code in {'knowledge_unavailable','project_unavailable'} else 400
        self._error(status, code, str(exc) if isinstance(exc, KnowledgeError) else '项目资料暂不可用，未采用旧内容；请检查文件与运行状态。')

    def do_GET(self):
        if not self._boundary():
            return
        if self.path.lstrip('/') in self.server.ui_assets.failures:
            self._error(503, 'ui_asset_unavailable', '此界面资源暂不可用；聊天核心继续可用。')
            return
        from speech_routes import get as speech_get
        from dialogue_routes import get as dialogue_get
        if dialogue_get(self): return
        if speech_get(self): return
        from project_tool_routes import get as project_tools_get
        if project_tools_get(self): return
        from skill_routes import get as skill_get
        if skill_get(self): return
        from growth_routes import get as growth_get
        if growth_get(self): return
        from continuity_routes import get as continuity_get
        if continuity_get(self): return
        if self.path == '/api/persona':
            from persona_routes import token, respond
            if token(self) and self._guard(): respond(self)
            return
        from evolution_routes import get as evolution_get
        if evolution_get(self): return
        if self.path == '/project_menu.js':
            self._send(200, self.server.project_menu_script, 'application/javascript; charset=utf-8')
            return
        if self.path == '/api/workspace/organization':
            if not self._workspace_token():return
            if self.server.project_catalog is None:
                self._error(503,'project_catalog_unavailable','项目管理模块尚未启用。');return
            try:self._send(200,self.server.project_catalog.snapshot())
            except Exception as exc:self._workspace_error(exc)
            return
        if self.path == '/knowledge.js':
            self._send(200, self.server.knowledge_script, 'application/javascript; charset=utf-8')
        elif urlsplit(self.path).path == '/api/knowledge':
            if not self._knowledge_token() or not self._guard():return
            try:
                query = parse_qs(urlsplit(self.path).query, keep_blank_values=True)
                if set(query) != {'project_id'} or len(query['project_id']) != 1:
                    raise KnowledgeError('invalid_knowledge','请选择一个项目。')
                self._send(200, self.server.knowledge.list(query['project_id'][0]))
            except Exception as exc:self._knowledge_error(exc)
        elif self.path == '/memory.js':
            self._send(200, self.server.memory_script, 'application/javascript; charset=utf-8')
        elif self.path == '/persona.js':
            self._send(200, self.server.persona_script, 'application/javascript; charset=utf-8')
        elif self.path == '/continuity.js':
            self._send(200, self.server.continuity_script, 'application/javascript; charset=utf-8')
        elif self.path == '/personal_candidates.js':
            self._send(200, self.server.personal_candidates_script, 'application/javascript; charset=utf-8')
        elif urlsplit(self.path).path == '/api/continuity':
            if not self._memory_token() or not self._guard():return
            try:
                query = parse_qs(urlsplit(self.path).query, keep_blank_values=True)
                if set(query)-{'project_id','q','provider'} or any(len(v)!=1 for v in query.values()):
                    raise MemoryError('invalid_continuity', '接续查询字段无效。')
                from jarvis_core.continuity import ContinuityStore
                store=ContinuityStore(self.server.core);project_id=query.get('project_id',[None])[0]
                self._send(200,store.suggest(query['q'][0],project_id,query.get('provider',['local'])[0]) if 'q' in query else store.list(project_id))
            except Exception as exc:self._memory_error(exc)
        elif urlsplit(self.path).path == '/api/memory':
            if not self._memory_token() or not self._guard():return
            try:
                query = parse_qs(urlsplit(self.path).query, keep_blank_values=True)
                if set(query) - {'project_id', 'q'} or any(len(v) != 1 for v in query.values()):
                    raise MemoryError('invalid_memory', '记忆查询字段无效。')
                self._send(200, self.server.memory.list(project_id=query.get('project_id', [None])[0], query=query.get('q', [''])[0]))
            except Exception as exc:self._memory_error(exc)
        elif self.path == '/conversations.js':
            self._send(200, self.server.conversation_script, 'application/javascript; charset=utf-8')
        elif self.path == '/team-workbench.js':
            self._send(200, (ROOT/'apps/web/team-workbench.js').read_bytes(), 'application/javascript; charset=utf-8')
        elif self.path == '/conversation_tasks.js':
            self._send(200, self.server.conversation_tasks_script, 'application/javascript; charset=utf-8')
        elif self.path.startswith('/api/conversation-tasks/'):
            if not self._computer_token():return
            if self.server.conversation_tasks is None:
                self._error(503,'computer_unavailable','会话任务模块未启用。');return
            match=re.fullmatch(r'/api/conversation-tasks/([a-f0-9]{32})(?:/(task_[a-f0-9]{32})(/artifact)?|/requests/(web-[a-f0-9]{32}))?',self.path)
            if not match:self._error(404,'not_found','此入口不存在。');return
            try:
                if match[4]:result=self.server.conversation_tasks.lookup(match[1],match[4])
                elif match[3]:
                    self._send(200,self.server.conversation_tasks.artifact(match[1],match[2]),'application/json; charset=utf-8');return
                elif match[2]:result=self.server.conversation_tasks.detail(match[1],match[2])
                else:result=self.server.conversation_tasks.list(match[1])
                self._send(200,result)
            except Exception as exc:self._computer_error(exc)
        elif self.path == '/api/conversations' or re.fullmatch(r'/api/conversations/[a-f0-9]{32}', self.path):
            if not self._conversation_token():return
            try:
                self._send(200, self.server.conversations.list() if self.path == '/api/conversations' else self.server.conversations.get(self.path.rsplit('/', 1)[1]))
            except Exception as exc:self._conversation_error(exc)
        elif self.path == "/theme.js":
            self._send(200, self.server.theme_script, "application/javascript; charset=utf-8")
        elif self.path == '/context.js':
            self._send(200, self.server.context_script, 'application/javascript; charset=utf-8')
        elif self.path == '/shared-reference.js':
            self._send(200, self.server.shared_reference_script, 'application/javascript; charset=utf-8')
        elif self.path == '/attachments.js':
            self._send(200, self.server.attachments_script, 'application/javascript; charset=utf-8')
        elif self.path == '/brand/':
            self._send(200, self.server.brand_html, 'text/html; charset=utf-8')
        elif self.path in self.server.brand_assets:
            body, mime = self.server.brand_assets[self.path]
            self._send(200, body, mime)
        elif self.path in {"/settings", "/settings/", "/admin", "/admin/"}:
            self._send(200, self.server.admin_html, "text/html; charset=utf-8")
        elif self.path == '/resources.js':
            self._send(200, self.server.resource_script, 'application/javascript; charset=utf-8')
        elif self.path == '/api/resources':
            tokens = self.headers.get_all('X-Jarvis-Nonce', [])
            if len(tokens) != 1 or not tokens[0].isascii() or not secrets.compare_digest(tokens[0], self.server.nonce):
                self._error(403, 'request_token_invalid', '页面会话已失效，请刷新。')
                return
            self._send(200, {**self.server.resource_usage.snapshot(), 'runtime':self.server.runtime_snapshot()})
        elif self.path == "/admin.js":
            self._send(200, self.server.admin_script, "application/javascript; charset=utf-8")
        elif self.path == '/federation.js':
            self._send(200, self.server.federation_script, 'application/javascript; charset=utf-8')
        elif self.path == '/shared-access.js':
            self._send(200, self.server.shared_access_script, 'application/javascript; charset=utf-8')
        elif self.path == '/shared-connection.js':
            self._send(200, self.server.shared_connection_script, 'application/javascript; charset=utf-8')
        elif self.path == '/api/federation':
            if not self._admin_token():return
            try:self._send(200, self.server.federation.view())
            except Exception as exc:self._admin_error(exc)
        elif self.path == '/network.js':
            self._send(200, self.server.network_script, 'application/javascript; charset=utf-8')
        elif self.path == '/api/network':
            if not self._admin_token():return
            self._send(200, self.server.network.snapshot())
        elif self.path == '/modules.js':
            self._send(200, self.server.module_script, 'application/javascript; charset=utf-8')
        elif self.path == '/api/modules':
            if not self._module_token():return
            self._send(200, self.server.modules.snapshot())
        elif self.path.startswith('/api/admin/'):
            if not self._admin_token():return
            try:
                parsed = urlsplit(self.path)
                if parsed.path == '/api/admin/config' and not parsed.query:
                    self._send(200, self.server.admin.snapshot())
                elif parsed.path == '/api/admin/usage':
                    from jarvis_models.billing import report
                    query = parse_qs(parsed.query, keep_blank_values=True, strict_parsing=True)
                    if set(query) - {'start', 'end', 'provider', 'model', 'key_id', 'offset'} or any(len(v)!=1 for v in query.values()):
                        raise ValueError('统计筛选条件无效。')
                    values = {k:v[0] for k,v in query.items()}
                    if 'offset' in values:values['offset']=int(values['offset'])
                    self._send(200, report(self.server.core.data_dir, **values))
                else:self._error(404, 'not_found', '此入口不存在。')
            except Exception as exc:self._admin_error(exc)
        elif self.path == "/":
            self._send(200, self.server.html, "text/html; charset=utf-8")
        elif self.path == '/computer.js':
            self._send(200,self.server.computer_script,'application/javascript; charset=utf-8')
        elif self.path == '/workbench.js':
            self._send(200, self.server.workbench_script, 'application/javascript; charset=utf-8')
        elif self.path in {'/explorer.js', '/extensions.js'}:
            self._send(200, self.server.explorer_script if self.path == '/explorer.js' else self.server.extensions_script, 'application/javascript; charset=utf-8')
        elif self.path == '/api/extensions':
            if not self._workspace_token() or not self._guard():return
            try:self._send(200, self.server.extensions.list())
            except Exception as exc:self._workspace_error(exc)
        elif self.path == '/mcp_manager.js':
            self._send(200, self.server.mcp_manager_script, 'application/javascript; charset=utf-8')
        elif self.path == '/api/mcp/catalog':
            if not self._workspace_token() or not self._guard():return
            try:
                from jarvis_core.mcp_catalog import McpManager
                self._send(200, McpManager(self.server.core).snapshot())
            except Exception as exc:self._workspace_error(exc)
        elif self.path == '/creation.js':
            self._send(200,self.server.creation_script,'application/javascript; charset=utf-8')
        elif self.path == '/workspace.js':
            self._send(200,self.server.workspace_script,'application/javascript; charset=utf-8')
        elif self.path in {'/api/workspace/projects', '/api/workspace/outputs'}:
            if not self._workspace_token():return
            try:
                result = self.server.workspace.projects() if self.path.endswith('/projects') else self.server.workspace.outputs()
                self._send(200, result)
            except Exception as exc:self._workspace_error(exc)
        elif self.path.startswith('/api/computer/') or self.path.startswith('/api/tasks'):
            if not self._computer_token():return
            try:
                if self.path in {'/api/computer/tasks', '/api/tasks'}:
                    self._send(200,self.server.computer.list_tasks(all_tasks=self.path=='/api/tasks'))
                else:
                    match=re.fullmatch(r'/api/(?:computer/tasks|tasks)/(task_[a-f0-9]{32})(/screenshot)?',self.path)
                    if not match:
                        self._error(404,'not_found','此入口不存在。');return
                    if match[2]:self._send(200,self.server.computer.screenshot(match[1]),'image/png')
                    else:self._send(200,self.server.computer.detail(match[1],all_tasks=self.path.startswith('/api/tasks/')))
            except Exception as exc:self._computer_error(exc)
        elif self.path == "/api/status":
            try:
                self.server.core.assert_running()
                queue_state = self.server.computer.queue.snapshot() if self.server.computer else {"running": []}
                active_tasks = len(queue_state["running"])
                assistant_state = "working" if self.server.chat_requests.active or active_tasks else "standby"
                self._send(200, {"app": "Jarvis", "version": self.server.version, "instance_id": self.server.instance_id,
                                 "ui_assets": self.server.ui_assets.snapshot(), "web_online": True, "core_ready": True, "stopped": False,
                                 "assistant_state": assistant_state, "active_tasks": active_tasks,
                                 "text_only": self.server.computer is None, "chat_text_only":True, "computer_tasks":self.server.computer is not None, "max_parallel_requests": 2, "active_chat_requests": self.server.chat_requests.active})
            except Exception:
                self._send(200, {"app": "Jarvis", "version": self.server.version, "instance_id": self.server.instance_id,
                                 "ui_assets": self.server.ui_assets.snapshot(), "web_online": True, "core_ready": False, "stopped": True,
                                 "assistant_state": "needs_attention",
                                 "text_only": self.server.computer is None, "chat_text_only":True, "computer_tasks":self.server.computer is not None, "max_parallel_requests": 2,
                                 "user_message": "核心未就绪或已停止。"})
        elif self.path == "/api/models":
            if not self._guard():
                return
            try:
                self._send(200, self.server.chat.models())
            except Exception:
                self._error(503, "models_unavailable", "暂时无法读取模型配置。")
        else:
            self._error(404, "not_found", "此入口不存在。")

    def do_POST(self):
        if not self._boundary(post=True):
            return
        conversation_action = re.fullmatch(r'/api/conversations/([a-f0-9]{32})(/delete)?', self.path)
        conversation_task_action = re.fullmatch(r'/api/conversation-tasks/([a-f0-9]{32})(?:/(task_[a-f0-9]{32})/cancel|/(documentation-candidate))?',self.path)
        memory_action = re.fullmatch(r'/api/memory/([a-f0-9]{32})(/delete)?', self.path)
        persona_action = self.path == '/api/persona'
        continuity_action = re.fullmatch(r'/api/continuity/([a-f0-9]{32})', self.path)
        candidate_action = self.path in {'/api/personal-candidates/suggest', '/api/personal-candidates/confirm', '/api/personal-candidates/rule-review', '/api/personal-candidates/rule-resolve', '/api/personal-candidates/semantic', '/api/personal-candidates/semantic-confirm', '/api/personal-candidates/semantic-review', '/api/personal-candidates/semantic-resolve'}
        knowledge_source = re.fullmatch(r'/api/knowledge/([a-f0-9]{32})(/delete)?', self.path)
        knowledge_action = knowledge_source or self.path in {'/api/knowledge/search','/api/knowledge/read','/api/knowledge/view'}
        computer_start=self.path in {'/api/computer/tasks','/api/tasks'}
        admin_action=self.path in {'/api/admin/config','/api/admin/balance','/api/network','/api/federation'}
        module_action=self.path in {'/api/modules/refresh','/api/modules/maintenance'}
        speech_action=self.path in {'/api/speech','/api/speech/fast','/api/speech/primary','/api/speech/readout','/api/speech/input'}
        growth_action=re.fullmatch(r'/api/conversation-growth/([a-f0-9]{32})(?:/([a-f0-9]{32})/(start|cancel|reanalyse))?',self.path)
        evolution_action=self.path in {'/api/evolution/jobs','/api/evolution/policy','/api/evolution/cancel','/api/evolution/maintenance','/api/evolution/ranking/generate','/api/evolution/ranking/select'}
        chat_cancel = self.path == '/api/chat/cancel'
        dialogue_action = self.path in {'/api/dialogue/turns', '/api/dialogue/cancel'}
        computer_queue=self.path in {'/api/computer/queue','/api/tasks/queue'}
        computer_cancel=re.fullmatch(r'/api/(?:computer/tasks|tasks)/(task_[a-f0-9]{32})/cancel',self.path)
        workspace_save = re.fullmatch(r'/api/workspace/outputs/([a-f0-9]{32})', self.path)
        project_organization = re.fullmatch(r'/api/workspace/projects/([a-f0-9]{32})/(edit|archive|reveal)', self.path)
        workspace_action = self.path in {'/api/workspace/projects', '/api/workspace/create-project', '/api/workspace/pick-folder', '/api/workspace/outputs/prepare'} or workspace_save or project_organization
        files_action = re.fullmatch(r'/api/project-files/(tree|read|write|mkdir|save-project|open-project)', self.path)
        extension_action = re.fullmatch(r'/api/extensions/([a-f0-9]{32})(?:/(delete|inspect))?', self.path)
        skill_action = bool(re.fullmatch(r'/api/project-tools/[a-f0-9]{32}/growth(?:/policy|/[a-f0-9]{32}/cancel)?',self.path)) or bool(re.fullmatch(r'/api/project-tools/[a-f0-9]{32}(?:/jobs/[a-f0-9]{32}/cancel|/plans(?:/[a-f0-9]{32}/(?:start|coding|cancel)|/[a-f0-9]{32}/contracts(?:/[a-f0-9]{32}/(?:review|cancel))?)?)?',self.path)) or self.path in {'/api/coding','/api/skills/policy','/api/skills/select','/api/skills/preview','/api/skills/coding-apply','/api/skills/coding-rollback'}
        mcp_action = self.path in {'/api/mcp/policy', '/api/mcp/view'}
        if self.path != "/api/chat" and not chat_cancel and not dialogue_action and not computer_start and not computer_cancel and not computer_queue and not workspace_action and not admin_action and not module_action and not speech_action and not conversation_action and not conversation_task_action and not memory_action and not knowledge_action and not files_action and not extension_action and not skill_action and not mcp_action and not evolution_action and not continuity_action and not growth_action and not candidate_action and not persona_action:
            self._error(404, "not_found", "此入口不存在。")
            return
        if (self.path.startswith('/api/computer/') or self.path.startswith('/api/tasks')) and not self._computer_token():
            return
        if conversation_task_action:
            if not self._computer_token():return
            if self.server.conversation_tasks is None:
                self._error(503,'computer_unavailable','会话任务模块未启用。');return
        if conversation_action and not self._conversation_token():return
        if memory_action and not self._memory_token():return
        if persona_action:
            from persona_routes import token
            if not token(self): return
        if continuity_action and not self._memory_token():return
        if candidate_action and not self._memory_token():return
        if knowledge_action and not self._knowledge_token():return
        if workspace_action and not self._workspace_token():return
        if (evolution_action or growth_action) and not self._workspace_token():return
        if (files_action or extension_action or skill_action or mcp_action) and not self._workspace_token():return
        if admin_action and not self._admin_token():return
        if module_action and not self._module_token():return
        if speech_action and not self._module_token():return
        if not chat_cancel and self.path != '/api/dialogue/cancel' and not computer_cancel and not (conversation_task_action and conversation_task_action[2]) and not computer_queue and self.path != '/api/modules/refresh' and not self._guard():
            return
        lengths = self.headers.get_all("Content-Length", [])
        if self.headers.get_all("Transfer-Encoding") or len(lengths) != 1 or not lengths[0].isdigit():
            self._error(400, "invalid_request", "请求长度无效。")
            return
        size = int(lengths[0])
        body_limit = 4_010_000 if speech_action else 2 * 1024 * 1024 + 65536 if conversation_action else MAX_CHAT_BODY if self.path == '/api/chat' else MAX_CHAT_BODY + 1024 if self.path == '/api/dialogue/turns' else 6 * 1024 * 1024 + 65536 if workspace_save or files_action and files_action[1] == 'write' else MAX_BODY_BYTES
        if not 0 < size <= body_limit:
            self._error(413, "request_too_large", "消息和历史合计过长，请清空部分对话后重试。")
            return
        content_type = self.headers.get("Content-Type", "").split(";", 1)[0].strip().lower()
        if content_type != "application/json":
            self._error(415, "invalid_content_type", "仅接受 JSON 消息。")
            return
        try:
            self._body_read = True
            body = self.rfile.read(size)
            if len(body) != size:
                raise ValueError("incomplete request")
            payload=strict_json(body)
            if self.path=='/api/chat':
                message, provider, history, model, reasoning = validate_chat(payload)
                from jarvis_core.personal import parse as personal_command
                if not personal_command(message) and provider != 'auto' and provider not in {p['provider'] for p in self.server.chat.models()['providers']}:
                    raise ValueError('unknown_provider')
                ids = self.headers.get_all('X-Jarvis-Request', [])
                if len(ids) > 1 or (ids and not re.fullmatch(r'[a-f0-9]{32}', ids[0])):
                    raise ValueError('invalid request id')
                request_id = ids[0] if ids else None
        except (ValueError, TypeError, UnicodeError, RecursionError, socket.timeout, OSError):
            self._error(400, "invalid_request", "消息或对话历史格式无效，或超过当前限制。")
            return
        if dialogue_action:
            from dialogue_routes import post as dialogue_post
            dialogue_post(self, payload)
            return
        if persona_action:
            from persona_routes import respond
            respond(self,payload)
            return
        if skill_action:
            from skill_routes import post as skill_post
            skill_post(self, payload)
            return
        if candidate_action:
            from candidate_routes import post as candidate_post
            candidate_post(self, payload)
            return
        if growth_action:
            from growth_routes import post as growth_post
            growth_post(self, growth_action, payload)
            return
        if evolution_action:
            from evolution_routes import post as evolution_post
            evolution_post(self, payload)
            return
        if mcp_action:
            try:
                from jarvis_core.mcp_catalog import McpManager
                manager = McpManager(self.server.core)
                self._send(200, manager.put_policy(payload) if self.path.endswith('/policy') else manager.snapshot(payload))
            except Exception as exc:self._workspace_error(exc)
            return
        if conversation_task_action:
            try:
                if conversation_task_action[3]:
                    self._send(200,self.server.conversation_tasks.documentation_candidate(conversation_task_action[1],payload))
                elif conversation_task_action[2]:
                    result=self.server.conversation_tasks.cancel(conversation_task_action[1],conversation_task_action[2],payload)
                    self._send(200,result)
                else:self._send(202,self.server.conversation_tasks.submit(conversation_task_action[1],payload))
            except Exception as exc:self._computer_error(exc)
            return
        if files_action or extension_action:
            try:
                if files_action:
                    result = getattr(self.server.project_files, files_action[1].replace('-', '_'))(payload)
                else:
                    result = getattr(self.server.extensions, extension_action[2] or 'put')(extension_action[1], payload)
                self._send(200, result)
            except Exception as exc:self._workspace_error(exc)
            return
        if knowledge_action:
            try:
                if self.path == '/api/knowledge/view':
                    from jarvis_core.memory_view import MemoryView
                    result = MemoryView(self.server.core, memory=self.server.memory, knowledge=self.server.knowledge).preview(payload)
                elif knowledge_source:
                    action = self.server.knowledge.delete if knowledge_source[2] else self.server.knowledge.put
                    result = action(knowledge_source[1],payload)
                else:
                    action = self.server.knowledge.search if self.path.endswith('/search') else self.server.knowledge.read_excerpt
                    result = action(payload)
                self._send(200,result)
            except Exception as exc:self._knowledge_error(exc)
            return
        if memory_action:
            try:
                action = self.server.memory.delete if memory_action[2] else self.server.memory.put
                self._send(200, action(memory_action[1], payload))
            except Exception as exc:self._memory_error(exc)
            return
        if continuity_action:
            try:
                from continuity_routes import change
                self._send(200, change(self.server.core, continuity_action[1], payload))
            except Exception as exc:self._memory_error(exc)
            return
        if conversation_action:
            try:
                action = self.server.conversations.delete if conversation_action[2] else self.server.conversations.put
                self._send(200, action(conversation_action[1], payload))
            except Exception as exc:self._conversation_error(exc)
            return
        if speech_action:
            from speech_routes import post as speech_post
            speech_post(self, payload)
            return
        if module_action:
            try:
                if self.path.endswith('/refresh'):
                    if payload != {}:raise ValueError('刷新只接受空对象。')
                    self._send(200,self.server.modules.snapshot(refresh=True))
                else:self._send(202,self.server.modules.submit(payload))
            except ValueError as exc:self._error(400,'module_request_invalid',str(exc))
            except Exception:self._error(503,'module_maintenance_unavailable','维护状态暂不可用，聊天与任务服务仍独立运行。')
            return
        if admin_action:
            try:
                if self.path == '/api/federation':
                    result = self.server.federation.action(payload)
                elif self.path == '/api/network':
                    if not isinstance(payload, dict) or set(payload) != {'offline', 'revision'}:
                        raise ValueError('只接受离线开关与当前修订号。')
                    # Native browser jobs cannot be fenced by a Python socket hook.
                    # Require an idle transition rather than pretend active sockets disappear.
                    network_queue = self.server.computer.queue.snapshot() if self.server.computer else {}
                    evolution = self.server.evolution
                    if payload.get('offline') is True and (self.server.chat_requests.active or network_queue.get('running')
                            or (evolution is not None and evolution.snapshot().get('busy'))
                            or self.server.modules.snapshot().get('maintenance_busy')):
                        from jarvis_core.policy import CoreError
                        raise CoreError('network_busy', '当前仍有对话或后台工作，请先停止或等待结束，再启用仅此软件离线。')
                    result = self.server.network.change(payload['offline'], payload['revision'])
                    if result['offline'] and self.server.federation:self.server.federation.close()
                elif self.path.endswith('/balance'):
                    if not isinstance(payload,dict) or set(payload)!={'connection'} or not isinstance(payload['connection'],str):raise ValueError('余额查询参数无效。')
                    result=self.server.admin.balance(payload['connection'])
                else:result=self.server.admin.mutate(payload)
                self._send(200,result)
            except Exception as exc:self._admin_error(exc)
            return
        if chat_cancel:
            if not isinstance(payload, dict) or set(payload) != {'request_id'} or not isinstance(payload['request_id'], str) or not re.fullmatch(r'[a-f0-9]{32}', payload['request_id']):
                self._error(400, 'invalid_request', '停止请求标识无效。');return
            try:
                state = self.server.chat_requests.cancel(payload['request_id'])
                self._send(200, {'status': state, 'request_id': payload['request_id']})
            except ValueError:
                self._error(429, 'chat_control_busy', '停止请求过多，请稍后重试。')
            return
        if workspace_action:
            try:
                if project_organization:
                    if self.server.project_catalog is None:raise ValueError('Project catalog unavailable')
                    method={'edit':'update','archive':'archive','reveal':'reveal'}[project_organization[2]]
                    result=getattr(self.server.project_catalog,method)(project_organization[1],payload)
                elif workspace_save:result = self.server.workspace.save(workspace_save[1], payload)
                elif self.path.endswith('/projects'):result = self.server.workspace.open_project(payload)
                elif self.path.endswith('/create-project'):result = self.server.workspace.create_project(payload)
                elif self.path.endswith('/pick-folder'):result = self.server.workspace.choose_project(payload)
                else:result = self.server.workspace.prepare(payload)
                self._send(200, result)
            except Exception as exc:self._workspace_error(exc)
            return
        if computer_start or computer_cancel or computer_queue:
            try:
                if computer_queue:
                    self._send(200,self.server.computer.queue_control(payload))
                elif computer_cancel:
                    if payload!={}:raise ValueError('Cancel accepts an empty object')
                    self._send(200,self.server.computer.cancel(computer_cancel[1],all_tasks=self.path.startswith('/api/tasks/')))
                else:self._send(202,self.server.computer.submit_task(payload) if self.path=='/api/tasks' else self.server.computer.submit(payload))
            except Exception as exc:self._computer_error(exc)
            return
        if not self.server.slots.acquire(blocking=False):
            self.server.metrics.event('chat_busy')
            self._error(429, "chat_busy", "已有两个请求正在处理，请等待完成后再发送。")
            return
        try:
            cancel_event = self.server.chat_requests.start(request_id) if request_id else None
        except ValueError as exc:
            self.server.slots.release()
            self._error(409, str(exc), '该请求标识已使用或控制记录已满，请稍后发起新的请求。')
            return
        with self.server.chat_requests.lock:
            self.server.chat_requests.active += 1
        result_queue = queue.Queue(maxsize=1)
        metric_token = self.server.metrics.begin('chat')

        def work():
            outcome = 'UNKNOWN'
            try:
                result = invoke_reply(self.server.core, self.server.chat, payload, cancel_event, request_id)
                if result.get('status')=='SUCCEEDED' and result.get('calculation'):
                    self.server.metrics.event('calculation_completed')
                result_queue.put((200, result))
                outcome = result.get('status','UNKNOWN')
            except Exception:
                outcome = 'FAILED'
                result_queue.put((503, {"status": "FAILED", "error_category": "chat_unavailable",
                                       "user_message": "本次对话未完成，请检查核心和模型状态。"}))
            finally:
                self.server.metrics.finish(metric_token,outcome)
                self.server.chat_requests.finish(request_id)
                with self.server.chat_requests.lock:
                    self.server.chat_requests.active -= 1
                self.server.slots.release()

        # Daemon workers allow closing this web process without resetting the core.
        # A timed-out request retains its slot until the actual worker finishes.
        try:
            threading.Thread(target=work, daemon=True, name="jarvis-web-chat").start()
        except Exception:
            self.server.chat_requests.finish(request_id)
            with self.server.chat_requests.lock:self.server.chat_requests.active -= 1
            self.server.slots.release()
            self.server.metrics.finish(metric_token,'FAILED')
            self.server.metrics.event('chat_thread_failed')
            self._error(503,'chat_unavailable','对话线程未启动，请稍后重试。')
            return
        try:
            status, result = result_queue.get(timeout=self.server.reply_timeout)
            self._send(status, result)
        except queue.Empty:
            self.server.metrics.event('http_wait_timeout')
            self._send(504, {"status": "UNKNOWN", "error_category": "web_wait_timeout",
                             "user_message": "等待超时，后台请求可能仍在完成。没有自动重试，请勿立即重复发送。"})

    def do_OPTIONS(self):
        self._error(405, "method_not_allowed", "此方法不可用。")


    def _admin_token(self):
        if self.server.admin is None and self.path not in {'/api/network','/api/federation'}:
            self._error(503, 'admin_unavailable', '配置后台未初始化。');return False
        values=self.headers.get_all('X-Jarvis-Nonce',[])
        if len(values)!=1 or not values[0].isascii() or not secrets.compare_digest(values[0],self.server.nonce):
            self._error(403,'invalid_token','页面已失效，请刷新配置后台。');return False
        return self._guard()

    def _admin_error(self, exc):
        # Only local validation messages are public; never reflect provider/vault errors.
        from jarvis_core.policy import CoreError
        if isinstance(exc, CoreError) and exc.code.startswith('federation_'):
            self._error(409, exc.code, str(exc))
        elif isinstance(exc, CoreError) and exc.code.startswith('network_'):
            self._error(409 if exc.code in {'network_conflict','network_busy'} else 503 if exc.code == 'network_policy_unavailable' else 400, exc.code, str(exc))
        elif type(exc) is ValueError:
            message=str(exc)
            if not any('\u4e00'<=char<='\u9fff' for char in message):message='配置或筛选条件无效，请检查填写内容。'
            self._error(400,'invalid_admin_request',message)
        else:self._error(503,'admin_unavailable','暂时无法读取或保存配置，请检查本机数据与凭据存储。')


    def _module_token(self):
        tokens=self.headers.get_all('X-Jarvis-Nonce',[])
        if len(tokens)!=1 or not tokens[0].isascii() or not secrets.compare_digest(tokens[0],self.server.nonce):
            self._error(403,'request_token_invalid','页面会话已失效，请刷新。');return False
        if self.server.modules is None:
            self._error(503,'module_monitor_unavailable','模块观察器未启用；其他功能仍可使用。');return False
        return True


def create_server(*, core=None, chat=None, data_dir=None, config_path=None, port=18181):
    if core is None or chat is None:
        sys.path.insert(0, str(ROOT / "runtime/node-host"))
        if core is None:
            from jarvis_core.service import CoreService
            core = CoreService(data_dir)
        if chat is None:
            from jarvis_core.chat import ChatService
            chat = ChatService(core, config_path=config_path)
    sys.path[:0]=[str(ROOT/'runtime/node-host'),str(ROOT/'adapters/computer-use')]
    from jarvis_core import __version__
    from jarvis_core.workspace import WorkspaceService
    from jarvis_computer.web import ComputerWeb
    # Bind first: a failed duplicate launch must not fence the live dispatcher.
    server = LocalChatServer(("127.0.0.1", port), core, chat, version=__version__, workspace=WorkspaceService(core))
    from jarvis_core.network_policy import NetworkPolicy
    server.network = NetworkPolicy(core.data_dir)
    from jarvis_core.federation import Federation
    server.federation = Federation(core, getattr(chat, 'config_path', None))
    try:
        from jarvis_core.chat import ChatService
        if isinstance(chat, ChatService) and chat.dialogue_models is None:
            from jarvis_core.dialogue_process import DialogueProcesses
            chat.dialogue_models = DialogueProcesses(core)
            chat.background_models = DialogueProcesses(core, capacity=1)
        from jarvis_core.conversations import ConversationStore
        server.conversations = ConversationStore(core)
        server.dialogue.enable_recovery(server.conversations)
        from jarvis_core.project_catalog import ProjectCatalog
        server.project_catalog = ProjectCatalog(core,server.workspace,server.conversations)
        server.memory = MemoryStore(core)
        server.knowledge = KnowledgeStore(core)
        from jarvis_core.project_files import ProjectFiles
        from jarvis_core.extensions import ExtensionCatalog
        server.project_files = ProjectFiles(core)
        server.extensions = ExtensionCatalog(core)
        from jarvis_core.skills import SkillManager
        server.skills = SkillManager(core)
        from jarvis_core.evolution import EvolutionManager
        try:
            server.evolution = EvolutionManager(core, config_path=getattr(chat,'config_path',None))
        except Exception:
            # Optional growth storage/runtime failure must not take down chat.
            # Routes report unavailable; no unrestricted fallback or repair replay.
            server.evolution = None
        if hasattr(chat, 'config_path'):
            from jarvis_models.registry import Registry
            server.admin = Registry(core.data_dir, chat.config_path)
        server.computer = ComputerWeb(core,chat,metrics=server.metrics)
        from jarvis_core.conversation_tasks import ConversationTasks
        server.conversation_tasks = ConversationTasks(core,server.computer)
        if server.evolution is not None:
            from jarvis_core.evolution.growth_cycle import GrowthCycles
            server.evolution.growth = GrowthCycles(server.evolution,server.conversation_tasks)
            from jarvis_core.evolution.ranking_module import RankingModules
            server.evolution.ranking_modules = RankingModules(server.evolution, getattr(chat, 'background_models', None))
            try: server.evolution.ranking_modules.recover()
            except Exception: server.evolution.ranking_modules = None  # Optional corruption cannot take down chat.
        from jarvis_core.work_admission import WorkAdmission
        server.dialogue.work_admission = WorkAdmission(core,server.computer)
        from jarvis_core.modules import ModuleMonitor
        server.modules = ModuleMonitor(core,lambda:{'chat':server.chat_requests.active,
            'calculator_uses':server.metrics.snapshot()['counters'].get('calculation_completed',0),
            'computer':server.computer is not None,
            'memory':server.memory is not None, 'knowledge':server.knowledge is not None,
            'personal':isinstance(server.chat,ChatService),
            'extensions':server.extensions is not None,
            'tasks':server.computer.queue.snapshot()['running'] if server.computer else []},
            config_path=getattr(chat,'config_path',None))
    except BaseException:
        server.server_close()
        raise
    return server


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", type=Path)
    parser.add_argument("--config", type=Path)
    parser.add_argument("--port", type=int, default=18181)
    parser.add_argument("--no-tray", action="store_true", help="Run without the Windows notification-area icon")
    args = parser.parse_args(argv)
    from jarvis_core.network_policy import activate_process
    from jarvis_core.policy import default_data_dir
    activate_process(args.data_dir or default_data_dir())
    server = create_server(data_dir=args.data_dir, config_path=args.config, port=args.port)
    print(f"Jarvis: http://127.0.0.1:{server.server_address[1]} (projects, chat and browser tasks; Ctrl+C closes this web service)", flush=True)
    tray = None
    try:
        if os.name == 'nt' and not args.no_tray:
            sys.path.insert(0, str(ROOT/'apps/tray'))
            from companion import TrayCompanion
            tray = TrayCompanion(server, server.core.data_dir)
        server.serve_forever(poll_interval=0.2)
    except KeyboardInterrupt:
        pass
    finally:
        try: server.server_close()
        finally:
            if tray: tray.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
