"""Offline loopback HTTP tests. No cloud calls, microphone, or credential access."""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import http.client
import importlib.util
import json
from pathlib import Path
import threading
import unittest
import uuid
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("jarvis_web_server", ROOT / "apps/web/server.py")
assert SPEC and SPEC.loader
web = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(web)


class FakeCore:
    def __init__(self):
        self.stopped = False
        self.checks = 0

    def assert_running(self):
        self.checks += 1
        if self.stopped:
            raise RuntimeError("never expose private control details")
        return {"config": {}}


class FakeChat:
    def __init__(self):
        self.calls = []
        self.hook = None

    def models(self):
        return {"default_provider": "vertex", "automatic_fallback": True,
                "fallback_order": ["vertex", "bailian", "openai", "xai", "local"],
                "providers": [{"provider": name, "model": name + "-test", "is_default": name == "vertex",
                               "historical_requests": 0, "credential_status": "not_checked"}
                              for name in ("vertex", "bailian", "openai", "xai", "local")],
                "balance_status": "not_queried"}

    def reply(self, message, provider="auto", history=None, model=None, reasoning=None, cancel_event=None, context_note=None):
        self.context_note = context_note
        self.cancel_event = cancel_event
        self.calls.append({"message": message, "provider": provider, "history": history,
                           **({"model": model} if model else {}), **({"reasoning": reasoning} if reasoning else {})})
        if self.hook:
            self.hook()
        return {"status": "SUCCEEDED", "text": "<script>not executed</script>",
                "provider": "vertex" if provider == "auto" else provider,
                "model": "mock-model", "usage": {"input_tokens": 3, "output_tokens": 2},
                "attempts": [], "notice": [], "history_info": {"truncated": False}}


class WebTests(unittest.TestCase):
    def test_optional_asset_faults_keep_http_chat_and_report_degradation(self):
        original = Path.read_bytes
        faults = {'evolution.css', 'logo.js', 'preview.html', 'memory.js', 'admin.html', 'dialogue.js'}
        def read(path):
            if path.name in faults:
                raise FileNotFoundError('private-path-must-not-leak')
            return original(path)
        with patch.object(Path, 'read_bytes', read):
            candidate = web.LocalChatServer(('127.0.0.1', 0), FakeCore(), FakeChat())
        thread = threading.Thread(target=candidate.serve_forever, kwargs={'poll_interval': .01}, daemon=True)
        thread.start()
        original_server, original_host, original_origin = self.server, self.host, self.origin
        self.server = candidate
        self.host = '127.0.0.1:' + str(candidate.server_address[1]); self.origin = 'http://' + self.host
        try:
            status, _, body = self.request('GET', '/')
            self.assertEqual(status, 200)
            self.assertIn('部分界面资源不可用'.encode(), body)
            self.assertNotIn(b'src="/brand/logo.js"', body)
            self.assertNotIn(b'src="/memory.js"', body)
            self.assertNotIn(b'src="/dialogue.js"', body)
            self.assertNotIn(b'private-path', body)
            state = json.loads(self.request('GET', '/api/status')[2])
            self.assertTrue(state['core_ready'])
            self.assertEqual(state['ui_assets']['status'], 'degraded')
            self.assertEqual(len(state['ui_assets']['unavailable']), len(faults))
            self.assertEqual(json.loads(self.request('POST', '/api/chat', {'message': 'hello'})[2])['status'], 'SUCCEEDED')
            for route in ('/brand/logo.js', '/memory.js', '/dialogue.js'):
                self.assertEqual(self.request('GET', route)[0], 503)
            for route in ('/settings/', '/brand/'):
                self.assertIn('返回聊天'.encode(), self.request('GET', route)[2])
            self.assertEqual(self.request('GET', '/brand/../server.py')[0], 404)
        finally:
            candidate.shutdown(); candidate.server_close(); thread.join(2)
            self.server, self.host, self.origin = original_server, original_host, original_origin

    def test_core_assets_still_required_and_optional_empty_or_denied_is_visible(self):
        original = Path.read_bytes
        for name in ('index.html', 'attachments.js', 'theme.css', 'workspace.css', 'conversations.js', 'workspace.js'):
            def read(path):
                if path.name == name: raise FileNotFoundError('fixture')
                return original(path)
            with self.subTest(name=name), patch.object(Path, 'read_bytes', read):
                with self.assertRaises(FileNotFoundError):
                    web.LocalChatServer(('127.0.0.1', 0), FakeCore(), FakeChat())
        for value, expected in ((b'', 'empty'), (PermissionError('private'), 'unreadable')):
            def read(path):
                if path.name == 'evolution.css':
                    if isinstance(value, Exception): raise value
                    return value
                return original(path)
            with self.subTest(reason=expected), patch.object(Path, 'read_bytes', read):
                candidate = web.LocalChatServer(('127.0.0.1', 0), FakeCore(), FakeChat())
            try:
                self.assertEqual(candidate.ui_assets.failures, {'evolution.css': expected})
            finally: candidate.server_close()

    def test_brand_assets_are_bounded_and_preview_uses_nonce(self):
        status, headers, body = self.request('GET', '/brand/')
        self.assertEqual(status, 200)
        self.assertNotIn(b'__JARVIS_', body)
        self.assertIn(self.server.nonce.encode(), body)
        self.assertIn("img-src 'self' blob:", headers['Content-Security-Policy'])
        for path in ('/brand/icon.png', '/brand/core.png'):
            status, headers, body = self.request('GET', path)
            self.assertEqual((status, headers['Content-Type']), (200, 'image/png'))
            self.assertTrue(body.startswith(b'\x89PNG\r\n\x1a\n'))
        for path in ('/brand/source/core.png', '/brand/orbit.png', '/brand/robot.png', '/brand/blink.png', '/brand/../server.py', '/brand/%2e%2e/server.py',
                     '/brand/icon.png?path=../../config', '/brand/missing.png'):
            self.assertEqual(self.request('GET', path)[0], 404)
        self.assertEqual(self.chat.calls, [])

    def test_runtime_package_contains_served_brand_assets(self):
        from tools.release_bundle import source_files
        packaged = set(source_files())
        for route in self.server.brand_assets:
            self.assertIn('apps/web' + route, packaged)
        self.assertFalse(any(path.startswith('apps/web/brand/source/') for path in packaged))

    def test_context_note_boundary_and_served_module(self):
        response=self.request('POST','/api/chat',{'message':'hello','context_note':'只用中文'})
        self.assertEqual(response[0],200)
        self.assertEqual(self.chat.context_note,'只用中文')
        for note in ({'role':'system'},'汉'*3000):
            self.assertEqual(self.request('POST','/api/chat',{'message':'hi','context_note':note})[0],400)
        self.assertEqual(len(self.chat.calls),1)
        self.assertEqual(self.request('GET','/context.js')[0],200)
        self.assertEqual(self.request('GET','/context.js?path=../../config')[0],404)

    def test_cancel_before_chat_admission_and_duplicate_id(self):
        ident = uuid.uuid4().hex
        self.assertEqual(self.request('POST', '/api/chat/cancel', {'request_id':ident})[0],200)
        result = self.request('POST','/api/chat',{'message':'test'},headers={'X-Jarvis-Request':ident})
        self.assertEqual(json.loads(result[2])['status'],'CANCELLED')
        self.assertEqual(self.chat.calls,[])
        self.assertEqual(self.request('POST','/api/chat',{'message':'different'},headers={'X-Jarvis-Request':ident})[0],409)
        self.assertEqual(self.request('POST','/api/chat',{'message':'fresh'})[0],200)

    def test_cancel_inflight_is_scoped_discards_reply_and_releases_slot(self):
        ident=uuid.uuid4().hex
        started=threading.Event()
        def wait_for_cancel():
            started.set()
            self.assertTrue(self.chat.cancel_event.wait(3))
        self.chat.hook=wait_for_cancel
        with ThreadPoolExecutor(max_workers=1) as pool:
            response=pool.submit(self.request,'POST','/api/chat',{'message':'slow'},headers={'X-Jarvis-Request':ident})
            self.assertTrue(started.wait(2))
            self.assertEqual(self.request('POST','/api/chat/cancel',{'request_id':uuid.uuid4().hex})[0],200)
            self.assertFalse(self.chat.cancel_event.is_set())
            self.assertEqual(self.request('POST','/api/chat/cancel',{'request_id':ident})[0],200)
            status,_,body=response.result(timeout=3)
        result=json.loads(body)
        self.assertEqual((status,result['status']),(200,'CANCELLED'))
        self.assertNotIn('text',result)
        self.assertFalse(self.core.stopped)
        self.chat.hook=None
        self.assertEqual(self.request('POST','/api/chat',{'message':'next'})[0],200)

    def test_cancel_requires_nonce_origin_strict_id_and_still_works_when_core_stopped(self):
        payload={'request_id':uuid.uuid4().hex}
        for headers in [{'Origin':None},{'X-Jarvis-Nonce':None},{'Origin':'https://evil.example'}]:
            self.assertEqual(self.request('POST','/api/chat/cancel',payload,headers=headers)[0],403)
        for body in [{},{'request_id':'bad'},{**payload,'stop_all':True}]:
            self.assertEqual(self.request('POST','/api/chat/cancel',body)[0],400)
        self.assertEqual(self.request('POST','/api/chat',{'message':'test'},headers={'X-Jarvis-Request':'bad'})[0],400)
        self.core.stopped=True
        self.assertEqual(self.request('POST','/api/chat/cancel',payload)[0],200)
        self.assertTrue(self.core.stopped)

    def test_stop_one_session_keeps_other_session_and_background_task_running(self):
        from types import SimpleNamespace
        first_id, second_id = uuid.uuid4().hex, uuid.uuid4().hex
        started = {name: threading.Event() for name in ("first", "second")}
        releases = {name: threading.Event() for name in started}
        cancellations = {}
        running_tasks = ["existing-background-task"]
        self.server.computer = SimpleNamespace(queue=SimpleNamespace(
            snapshot=lambda: {"running": list(running_tasks)}))
        self.addCleanup(lambda: setattr(self.server, "computer", None))

        def reply(message, cancel_event=None, **kwargs):
            cancellations[message] = cancel_event
            started[message].set()
            if message == "first":
                self.assertTrue(cancel_event.wait(3))
            else:
                self.assertTrue(releases[message].wait(3))
            return {"status": "SUCCEEDED", "text": message + " finished"}

        self.chat.reply = reply
        with ThreadPoolExecutor(max_workers=2) as pool:
            first = pool.submit(self.request, "POST", "/api/chat", {"message": "first"},
                                headers={"X-Jarvis-Request": first_id})
            second = pool.submit(self.request, "POST", "/api/chat", {"message": "second"},
                                 headers={"X-Jarvis-Request": second_id})
            try:
                for event in started.values():
                    self.assertTrue(event.wait(2))
                active = json.loads(self.request("GET", "/api/status")[2])
                self.assertEqual((active["assistant_state"], active["active_tasks"]), ("working", 1))
                self.assertEqual(self.request("POST", "/api/chat/cancel", {"request_id": first_id})[0], 200)
                self.assertEqual(json.loads(first.result(timeout=3)[2])["status"], "CANCELLED")
                self.assertFalse(cancellations["second"].is_set())
                self.assertFalse(second.done())
                self.assertEqual(running_tasks, ["existing-background-task"])
                self.assertFalse(self.core.stopped)
            finally:
                releases["second"].set()
            self.assertEqual(json.loads(second.result(timeout=3)[2])["text"], "second finished")
        background = json.loads(self.request("GET", "/api/status")[2])
        self.assertEqual(background["assistant_state"], "working")
        running_tasks.clear()
        idle = json.loads(self.request("GET", "/api/status")[2])
        self.assertEqual(idle["assistant_state"], "standby")
        self.assertTrue(idle["core_ready"])

    def test_reasoning_is_forwarded_and_rejects_non_enums_before_dispatch(self):
        payload = {'message': 'test', 'provider': 'openai', 'model': 'gpt-6-astra', 'reasoning': 'medium'}
        self.assertEqual(self.request('POST', '/api/chat', payload)[0], 200)
        self.assertEqual(self.chat.calls[-1]['reasoning'], 'medium')
        before = len(self.chat.calls)
        for reasoning in ['', [], {'effort': 'high'}, True, 'ultra', 'https://evil.example']:
            self.assertEqual(self.request('POST', '/api/chat', {**payload, 'reasoning': reasoning})[0], 400)
        self.assertEqual(self.request('POST', '/api/chat', {'message': 'test', 'reasoning': 'high'})[0], 400)
        self.assertEqual(len(self.chat.calls), before)

    def test_explicit_model_is_forwarded_without_allowing_transport_settings(self):
        result = self.request('POST', '/api/chat', {'message': 'test', 'provider': 'openai', 'model': 'gpt-6-astra'})
        self.assertEqual(result[0], 200)
        self.assertEqual(self.chat.calls[-1]['model'], 'gpt-6-astra')
        for model in ['https://evil.example', ['gpt-6-astra'], '']:
            self.assertEqual(self.request('POST', '/api/chat', {'message': 'test', 'provider': 'openai', 'model': model})[0], 400)
        self.assertEqual(self.request('POST', '/api/chat', {'message': 'test', 'model': 'gpt-6-astra'})[0], 400)

    def setUp(self):
        self.core = FakeCore()
        self.chat = FakeChat()
        self.server = web.LocalChatServer(("127.0.0.1", 0), self.core, self.chat, reply_timeout=2)
        self.thread = threading.Thread(target=self.server.serve_forever, kwargs={"poll_interval": 0.01}, daemon=True)
        self.thread.start()
        self.addCleanup(self.server.server_close)
        self.addCleanup(self.server.shutdown)
        self.host = "127.0.0.1:" + str(self.server.server_address[1])
        self.origin = "http://" + self.host

    def request(self, method, path, payload=None, *, headers=None, raw=None):
        connection = http.client.HTTPConnection("127.0.0.1", self.server.server_address[1], timeout=5)
        request_headers = {"Host": self.host}
        body = raw
        if method == "POST":
            request_headers.update({"Origin": self.origin, "X-Jarvis-Nonce": self.server.nonce,
                                    "Content-Type": "application/json"})
            if raw is None:
                body = json.dumps(payload if payload is not None else {"message": "hello"}).encode("utf-8")
        if headers:
            for key, value in headers.items():
                if value is None:
                    request_headers.pop(key, None)
                else:
                    request_headers[key] = value
        try:
            connection.request(method, path, body=body, headers=request_headers)
            response = connection.getresponse()
            return response.status, dict(response.getheaders()), response.read()
        finally:
            connection.close()

    def test_index_has_nonce_and_restrictive_headers(self):
        status, headers, body = self.request("GET", "/")
        self.assertEqual(200, status)
        self.assertIn(self.server.nonce.encode("ascii"), body)
        self.assertNotIn(b"__JARVIS_NONCE__", body)
        self.assertEqual("no-store", headers["Cache-Control"])
        self.assertIn("frame-ancestors 'none'", headers["Content-Security-Policy"])
        self.assertNotIn("Access-Control-Allow-Origin", headers)
        source = body.decode("utf-8")
        self.assertIn("textContent", source)
        self.assertNotIn("innerHTML", source)
        self.assertNotIn("localStorage", source)
        self.assertNotIn("sessionStorage", source)

    def test_non_loopback_binding_is_rejected(self):
        with self.assertRaises(ValueError):
            web.LocalChatServer(("0.0.0.0", 0), self.core, self.chat)

    def test_foreign_host_and_origin_are_rejected(self):
        for headers in ({"Host": "evil.example"}, {"Origin": "https://evil.example"},
                        {"Origin": "null"}, {"Origin": "http://localhost:" + str(self.server.server_address[1])}):
            with self.subTest(headers=headers):
                self.assertEqual(403, self.request("GET", "/api/status", headers=headers)[0])
        self.assertEqual([], self.chat.calls)

    def test_post_requires_origin_and_nonce(self):
        for headers in ({"Origin": None}, {"X-Jarvis-Nonce": None}, {"X-Jarvis-Nonce": "wrong"}, {"X-Jarvis-Nonce": "é"}):
            with self.subTest(headers=headers):
                self.assertEqual(403, self.request("POST", "/api/chat", headers=headers)[0])
        self.assertEqual([], self.chat.calls)

    def test_only_fixed_routes_are_available(self):
        for path in ("/../AGENTS.md", "/index.html", "/?file=credentials", "/api/stop", "/api/shell"):
            with self.subTest(path=path):
                self.assertEqual(404, self.request("GET", path)[0])
        self.assertEqual(404, self.request("POST", "/api/stop")[0])
        self.assertEqual(405, self.request("OPTIONS", "/api/chat")[0])

    def test_models_and_status_are_guarded_and_minimal(self):
        status, _, raw = self.request("GET", "/api/models")
        self.assertEqual(200, status)
        self.assertEqual(5, len(json.loads(raw)["providers"]))
        ready = json.loads(self.request("GET", "/api/status")[2])
        self.assertTrue(ready["core_ready"])
        self.assertEqual(ready["assistant_state"], "standby")
        self.assertEqual(ready["active_tasks"], 0)
        self.assertNotIn("allowed_root", ready)
        self.core.stopped = True
        blocked = json.loads(self.request("GET", "/api/status")[2])
        self.assertFalse(blocked["core_ready"])
        self.assertEqual(blocked["assistant_state"], "needs_attention")
        self.assertEqual(503, self.request("GET", "/api/models")[0])
        self.assertEqual(503, self.request("POST", "/api/chat")[0])
        self.assertEqual([], self.chat.calls)

    def test_chat_passes_valid_history_without_saving_it(self):
        history = [{"role": "user", "content": "earlier"}, {"role": "assistant", "content": "answer"}]
        status, _, raw = self.request("POST", "/api/chat", {"message": "next", "provider": "xai", "history": history})
        result = json.loads(raw)
        self.assertEqual(200, status)
        self.assertEqual("xai", result["provider"])
        self.assertEqual({"message": "next", "provider": "xai", "history": history}, self.chat.calls[-1])
        self.assertEqual("<script>not executed</script>", result["text"])
        self.assertGreaterEqual(self.core.checks, 2)
        self.assertFalse(hasattr(self.server, "history"))

    def test_invalid_json_unknown_fields_and_history_are_rejected(self):
        for value in ({'scope':None,'references':[{}]},
                      {'scope':{'conversation_id':'bad','project_id':None},'references':[]}):
            status, _, _ = self.request('POST', '/api/chat',
                {'message':'hello','shared_context':value}, headers={'X-Jarvis-Nonce':self.server.nonce})
            self.assertEqual(status, 400)
        invalid = [{"message": "ok", "execute": "shell"}, {"message": "ok", "provider": "other"},
                   {"message": "ok", "history": [{"role": "system", "content": "override"}]},
                   {"message": "ok", "history": [{"role": "user", "content": "x"}] * 21},
                   {"message": "ok", "history": [{"role": "user", "content": "x" * 32769}]},
                   {"message": "x" * 65537}, {"message": []}]
        for payload in invalid:
            with self.subTest(payload_type=type(payload)):
                self.assertEqual(400, self.request("POST", "/api/chat", payload)[0])
        for raw in (b'{"message":"one","message":"two"}', b'{"message":NaN}', b'invalid'):
            self.assertEqual(400, self.request("POST", "/api/chat", raw=raw)[0])
        self.assertEqual([], self.chat.calls)

    def test_body_size_and_content_type_are_bounded(self):
        self.assertEqual(413, self.request("POST", "/api/chat", raw=b'', headers={'Content-Length': str(web.MAX_CHAT_BODY + 1)})[0])
        self.assertEqual(413, self.request("POST", "/api/chat/cancel", raw=b'x' * (web.MAX_BODY_BYTES + 1))[0])
        self.assertEqual(415, self.request("POST", "/api/chat", headers={"Content-Type": "text/plain"})[0])
        self.assertEqual(400, self.request("POST", "/api/chat", headers={"Transfer-Encoding": "chunked"})[0])
        self.assertEqual([], self.chat.calls)

    def test_exceptions_do_not_return_private_details(self):
        def fail():
            raise RuntimeError("SECRET_SENTINEL_API_KEY")
        self.chat.hook = fail
        status, _, raw = self.request("POST", "/api/chat")
        self.assertEqual(503, status)
        self.assertNotIn(b"SECRET_SENTINEL", raw)
        self.assertEqual("chat_unavailable", json.loads(raw)["error_category"])

    def test_two_inflight_requests_reject_third_until_completion(self):
        release = threading.Event()
        both_started = threading.Event()
        lock = threading.Lock()
        active = 0
        def hold():
            nonlocal active
            with lock:
                active += 1
                if active == 2:
                    both_started.set()
            release.wait(3)
        self.chat.hook = hold
        with ThreadPoolExecutor(max_workers=2) as pool:
            first = pool.submit(self.request, "POST", "/api/chat")
            second = pool.submit(self.request, "POST", "/api/chat")
            try:
                self.assertTrue(both_started.wait(2))
                self.assertEqual(429, self.request("POST", "/api/chat")[0])
            finally:
                release.set()
            self.assertEqual(200, first.result()[0])
            self.assertEqual(200, second.result()[0])

    def test_timeout_retains_slots_until_real_workers_finish(self):
        release = threading.Event()
        self.addCleanup(release.set)
        self.chat.hook = lambda: release.wait(3)
        self.server.reply_timeout = 0.03
        first = self.request("POST", "/api/chat")
        second = self.request("POST", "/api/chat")
        self.assertEqual(504, first[0])
        self.assertEqual("UNKNOWN", json.loads(first[2])["status"])
        self.assertEqual(504, second[0])
        self.assertEqual(429, self.request("POST", "/api/chat")[0])
        self.assertEqual(2, len(self.chat.calls))
        release.set()


if __name__ == "__main__":
    unittest.main()
