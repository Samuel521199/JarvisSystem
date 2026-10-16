"""Loopback chat and explicit browser task console; no core stop/reset endpoint."""
from __future__ import annotations

import argparse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import queue
import re
import secrets
import socket
import sys
import threading
import time

ROOT = Path(__file__).resolve().parents[2]
INDEX_PATH = Path(__file__).with_name("index.html")
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
    if not isinstance(payload, dict) or set(payload) - {"message", "provider", "history", "model", "reasoning"}:
        raise ValueError("invalid request fields")
    message = payload.get("message")
    if not isinstance(message, str) or not message.strip() or len(message.encode("utf-8")) > MAX_MESSAGE_BYTES:
        raise ValueError("invalid message")
    provider = payload.get("provider", "auto")
    if not isinstance(provider, str) or provider not in PROVIDERS:
        raise ValueError("invalid provider")
    model = payload.get("model")
    if model is not None and (provider == "auto" or not isinstance(model, str) or not re.fullmatch(r"[a-zA-Z0-9._:-]{1,128}", model)):
        raise ValueError("invalid model")
    reasoning = payload.get("reasoning")
    if reasoning is not None and (provider == "auto" or not isinstance(reasoning, str)
                                  or reasoning not in {"none", "minimal", "low", "medium", "high", "xhigh", "max", "off", "on"}):
        raise ValueError("invalid reasoning level")
    history = payload.get("history", [])
    if not isinstance(history, list) or len(history) > 20:
        raise ValueError("invalid history")
    size = 0
    for item in history:
        if not isinstance(item, dict) or set(item) != {"role", "content"}:
            raise ValueError("invalid history item")
        if item["role"] not in {"user", "assistant"} or not isinstance(item["content"], str):
            raise ValueError("invalid history role/content")
        size += len(item["content"].encode("utf-8"))
    if size > MAX_HISTORY_BYTES:
        raise ValueError("history too large")
    return message, provider, history, model, reasoning


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
        self.nonce = secrets.token_urlsafe(32)
        self.slots = threading.BoundedSemaphore(2)
        self.chat_requests = ChatRequests()
        self.reply_timeout = reply_timeout
        # One fixed static file; never derive filesystem paths from a request.
        self.html = INDEX_PATH.read_bytes().replace(b"__JARVIS_WORKSPACE_STYLE__", INDEX_PATH.with_name('workspace.css').read_bytes()).replace(b"__JARVIS_NONCE__", self.nonce.encode("ascii")).replace(b'__JARVIS_VERSION__',version.encode('ascii'))
        self.computer_script = INDEX_PATH.with_name('computer.js').read_bytes()
        self.workspace_script = INDEX_PATH.with_name('workspace.js').read_bytes()
        super().__init__(address, ChatHandler)
        port = self.server_address[1]
        self.allowed_hosts = {f"127.0.0.1:{port}", f"localhost:{port}"}
        self.allowed_origins = {"http://" + host for host in self.allowed_hosts}

    def server_close(self):
        try:
            self.chat_requests.cancel_all()
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
                             f"script-src 'nonce-{self.server.nonce}'; style-src 'nonce-{self.server.nonce}'; "
                             "connect-src 'self'; img-src blob:; base-uri 'none'; form-action 'none'; frame-ancestors 'none'")
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
        status=404 if code=='not_found' else 409 if code in {'computer_busy','worker_busy','idempotency_conflict','submission_unknown','queue_full','queue_version_changed','queue_content_changed'} else 503 if code in {'stopped','stale_authorization','computer_unavailable','queue_owner_changed'} else 400
        # Only these explicitly typed module errors carry user-facing text.
        message=str(exc) if type(exc).__name__ in {'ComputerError','CoreError'} else '浏览器任务请求未完成，请检查任务列表。'
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
        status = 404 if code == 'not_found' else 409 if code in {'file_exists', 'idempotency_conflict', 'output_changed', 'output_unresolved', 'output_unknown', 'picker_busy', 'project_replaced'} else 503 if code in {'stopped', 'stale_authorization', 'workspace_unavailable'} else 400
        message = str(exc) if type(exc).__name__ == 'CoreError' else '项目操作未完成，请检查文件夹与本机服务。'
        self._error(status, code, message)

    def _guard(self):
        try:
            self.server.core.assert_running()
            return True
        except Exception:
            self._error(503, "core_not_ready", "核心未就绪或已停止；网页不会自动初始化或解除停止。")
            return False

    def do_GET(self):
        if not self._boundary():
            return
        if self.path == "/":
            self._send(200, self.server.html, "text/html; charset=utf-8")
        elif self.path == '/computer.js':
            self._send(200,self.server.computer_script,'application/javascript; charset=utf-8')
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
                self._send(200, {"web_online": True, "core_ready": True, "stopped": False,
                                 "assistant_state": assistant_state, "active_tasks": active_tasks,
                                 "text_only": self.server.computer is None, "chat_text_only":True, "computer_tasks":self.server.computer is not None, "max_parallel_requests": 2, "active_chat_requests": self.server.chat_requests.active})
            except Exception:
                self._send(200, {"web_online": True, "core_ready": False, "stopped": True,
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
        computer_start=self.path in {'/api/computer/tasks','/api/tasks'}
        chat_cancel = self.path == '/api/chat/cancel'
        computer_queue=self.path in {'/api/computer/queue','/api/tasks/queue'}
        computer_cancel=re.fullmatch(r'/api/(?:computer/tasks|tasks)/(task_[a-f0-9]{32})/cancel',self.path)
        workspace_save = re.fullmatch(r'/api/workspace/outputs/([a-f0-9]{32})', self.path)
        workspace_action = self.path in {'/api/workspace/projects', '/api/workspace/pick-folder', '/api/workspace/outputs/prepare'} or workspace_save
        if self.path != "/api/chat" and not chat_cancel and not computer_start and not computer_cancel and not computer_queue and not workspace_action:
            self._error(404, "not_found", "此入口不存在。")
            return
        if (self.path.startswith('/api/computer/') or self.path.startswith('/api/tasks')) and not self._computer_token():
            return
        if workspace_action and not self._workspace_token():return
        if not chat_cancel and not computer_cancel and not computer_queue and not self._guard():
            return
        lengths = self.headers.get_all("Content-Length", [])
        if self.headers.get_all("Transfer-Encoding") or len(lengths) != 1 or not lengths[0].isdigit():
            self._error(400, "invalid_request", "请求长度无效。")
            return
        size = int(lengths[0])
        body_limit = 6 * 1024 * 1024 + 1024 if workspace_save else MAX_BODY_BYTES
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
                ids = self.headers.get_all('X-Jarvis-Request', [])
                if len(ids) > 1 or (ids and not re.fullmatch(r'[a-f0-9]{32}', ids[0])):
                    raise ValueError('invalid request id')
                request_id = ids[0] if ids else None
        except (ValueError, TypeError, UnicodeError, RecursionError, socket.timeout, OSError):
            self._error(400, "invalid_request", "消息或对话历史格式无效，或超过当前限制。")
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
                if workspace_save:result = self.server.workspace.save(workspace_save[1], payload)
                elif self.path.endswith('/projects'):result = self.server.workspace.open_project(payload)
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

        def work():
            try:
                self.server.core.assert_running()
                if cancel_event is not None and cancel_event.is_set():
                    result_queue.put((200, {'status': 'CANCELLED', 'cancel_requested': True,
                                           'outcome_uncertain': False, 'user_message': '已停止，本次未调用模型。'}))
                    return
                selection = {"model": model} if model is not None else {}
                if reasoning is not None:
                    selection["reasoning"] = reasoning
                if cancel_event is not None:
                    selection['cancel_event'] = cancel_event
                result = self.server.chat.reply(message, provider=provider, history=history, **selection)
                if cancel_event is not None and cancel_event.is_set():
                    result = {'status': 'CANCELLED', 'cancel_requested': True,
                              'user_message': '已停止本次生成，后续输出不再采用；远端用量可能仍在结算。',
                              'outcome_uncertain': result.get('outcome_uncertain', True)}
                result_queue.put((200, result))
            except Exception:
                result_queue.put((503, {"status": "FAILED", "error_category": "chat_unavailable",
                                       "user_message": "本次对话未完成，请检查核心和模型状态。"}))
            finally:
                self.server.chat_requests.finish(request_id)
                with self.server.chat_requests.lock:
                    self.server.chat_requests.active -= 1
                self.server.slots.release()

        # Daemon workers allow closing this web process without resetting the core.
        # A timed-out request retains its slot until the actual worker finishes.
        threading.Thread(target=work, daemon=True, name="jarvis-web-chat").start()
        try:
            status, result = result_queue.get(timeout=self.server.reply_timeout)
            self._send(status, result)
        except queue.Empty:
            self._send(504, {"status": "UNKNOWN", "error_category": "web_wait_timeout",
                             "user_message": "等待超时，后台请求可能仍在完成。没有自动重试，请勿立即重复发送。"})

    def do_OPTIONS(self):
        self._error(405, "method_not_allowed", "此方法不可用。")


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
    try:
        server.computer = ComputerWeb(core,chat)
    except BaseException:
        server.server_close()
        raise
    return server


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", type=Path)
    parser.add_argument("--config", type=Path)
    parser.add_argument("--port", type=int, default=18181)
    args = parser.parse_args(argv)
    server = create_server(data_dir=args.data_dir, config_path=args.config, port=args.port)
    print(f"Jarvis: http://127.0.0.1:{server.server_address[1]} (projects, chat and browser tasks; Ctrl+C closes this web service)", flush=True)
    try:
        server.serve_forever(poll_interval=0.2)
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
