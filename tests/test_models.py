import json
from pathlib import Path
import tempfile
import sys
import unittest
import asyncio
import threading
import time
from contextlib import contextmanager
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "adapters/models/provider-native"))
import httpx
from jarvis_models.gateway import ModelError, ProbeJournal, build_request, classify_http_error, extract, probe, read_config
from jarvis_models.vault import load, save, VaultError


class ModelTests(unittest.TestCase):
    def test_local_response_schema_is_bounded_and_not_sent_to_cloud(self):
        schema={'oneOf':[{'const':{'kind':'report'}},{'const':{'kind':'unsupported'}}]}
        def handler(request):
            body=json.loads(request.content)
            self.assertEqual(body['response_format'],{'type':'json_object','schema':schema})
            return httpx.Response(200,json={'choices':[{'message':{'content':'{"kind":"report"}'},'finish_reason':'stop'}]})
        result=probe(self.config,'local','test',self.data,lambda:None,response_schema=schema,
            client=self.client(handler),credentials_loader=lambda:self.fail('vault accessed'))
        self.assertEqual(result['status'],'SUCCEEDED')
        for provider,value in [('vertex',schema),('local',[]),('local',{'value':'x'*8193})]:
            with self.assertRaises(ModelError):probe(self.config,provider,'test',self.data,lambda:None,response_schema=value)

    def test_cancel_before_dispatch_never_calls_transport(self):
        cancel=threading.Event();cancel.set()
        result=probe(self.config,'local','test',self.data,lambda:None,
                     client=self.client(lambda _:self.fail('must not send')),cancel_event=cancel)
        self.assertEqual(result['status'],'CANCELLED')
        self.assertFalse(result['outcome_uncertain'])
        self.assertNotIn('dispatch_admitted',result)

    def test_cancel_while_waiting_for_headers_closes_transport(self):
        cancel=threading.Event();closed=[]
        async def handler(request):
            cancel.set()
            try:await asyncio.sleep(30)
            finally:closed.append(True)
        start=time.monotonic()
        result=probe(self.config,'local','test',self.data,lambda:None,
                     client=self.client(handler),cancel_event=cancel)
        self.assertLess(time.monotonic()-start,2)
        self.assertTrue(closed)
        self.assertEqual((result['status'],result['error_category']),('UNKNOWN','chat_cancelled'))
        self.assertTrue(result['dispatch_admitted'])
        self.assertNotIn('text',result)

    def test_cancel_while_waiting_for_body_closes_response(self):
        cancel=threading.Event();closed=[]
        class SlowBody(httpx.AsyncByteStream):
            async def __aiter__(self):
                yield b'{"choices":'
                cancel.set()
                await asyncio.sleep(30)
            async def aclose(self):closed.append(True)
        result=probe(self.config,'local','test',self.data,lambda:None,cancel_event=cancel,
                     client=self.client(lambda _:httpx.Response(200,stream=SlowBody())))
        self.assertTrue(closed)
        self.assertEqual(result['status'],'UNKNOWN')
        self.assertEqual(result['error_category'],'chat_cancelled')
        self.assertNotIn('text',result)

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.data = Path(self.temp.name)
        self.config = read_config(ROOT / "config/model-profiles/providers.json")

    def client(self, handler):
        client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        self.addCleanup(lambda: asyncio.run(client.aclose()))
        return client

    def test_openai_multiple_output_items(self):
        text, usage = extract("openai", {"output": [{"type": "reasoning"}, {"type": "message", "content": [
            {"type": "output_text", "text": "one"}, {"type": "output_text", "text": "two"}]}],
            "usage": {"input_tokens": 4, "debug": "not retained"}})
        self.assertEqual(text, "one\ntwo")
        self.assertEqual(usage, {"input_tokens": 4})

    def test_usage_rejects_nonfinite_values_and_arbitrary_metadata(self):
        _, usage = extract("openai", {"output": [], "usage": {
            "input_tokens": 2, "output_tokens": float("nan"), "total_tokens": float("inf"),
            "untrusted-provider-metadata": 123}})
        self.assertEqual(usage, {"input_tokens": 2})

    def test_local_has_no_credential_access(self):
        def handler(request):
            self.assertNotIn("authorization", request.headers)
            self.assertEqual(request.url.host, "127.0.0.1")
            return httpx.Response(200, json={"choices": [{"message": {"content": "OK"}}]})
        result = probe(self.config, "local", "test", self.data, lambda: None,
                       client=self.client(handler), credentials_loader=lambda: self.fail("vault accessed"))
        self.assertEqual(result["status"], "SUCCEEDED")

    def test_usage_history_never_blocks_new_request(self):
        journal = ProbeJournal(self.data / "model-probes.db")
        for _ in range(105):
            journal.reserve("local", "test", "old prompt")
        calls = []
        def handler(request):
            calls.append(request)
            return httpx.Response(429, json={"error": "secret-like provider body"})
        result = probe(self.config, "local", "hello", self.data, lambda: None, client=self.client(handler))
        self.assertEqual(result["error"], "provider_http_429")
        self.assertEqual(result["status"], "FAILED")
        self.assertFalse(result["outcome_uncertain"])
        self.assertNotIn("secret-like", json.dumps(result))
        probe(self.config, "local", "hello again", self.data, lambda: None, client=self.client(handler))
        self.assertEqual(len(calls), 2)
        self.assertEqual(ProbeJournal(self.data / "model-probes.db").counts()["local"], 107)

    def test_billing_and_rate_errors_are_distinguished_without_leaking_body(self):
        cases = [(429, {"error": {"code": "credit_balance_exhausted"}}, "quota_exhausted"),
                 (429, {"error": {"type": "insufficient_quota"}}, "quota_exhausted"),
                 (403, {"code": "Arrearage"}, "quota_exhausted"),
                 (429, {"error": {"status": "RESOURCE_EXHAUSTED"}}, "rate_limited"),
                 (401, {"error": {"message": "secret-token-do-not-print"}}, "authentication"),
                 (404, {}, "model_unavailable"), (503, {}, "provider_unavailable")]
        for status, body, expected in cases:
            with self.subTest(status=status, body=body):
                category, message = classify_http_error(status, json.dumps(body).encode())
                self.assertEqual(category, expected)
                self.assertNotIn("secret-token", message)

    def test_error_body_failure_preserves_known_http_classification(self):
        cases = [(400, "invalid_request"), (401, "authentication"), (403, "authentication"),
                 (402, "quota_exhausted"), (429, "rate_limited"), (404, "model_unavailable"),
                 (503, "provider_unavailable")]
        for status, expected in cases:
            for exception_type in (httpx.ReadTimeout, httpx.ConnectError, RuntimeError):
                with self.subTest(status=status, exception=exception_type.__name__):
                    class BrokenErrorBody(httpx.AsyncByteStream):
                        async def __aiter__(self):
                            yield b'{"error":'
                            raise exception_type("secret-text-not-for-user")
                    calls = []
                    def handler(request):
                        calls.append(request)
                        return httpx.Response(status, headers={"retry-after": "7"}, stream=BrokenErrorBody())
                    result = probe(self.config, "local", "test", self.data, lambda: None,
                                   client=self.client(handler))
                    self.assertEqual(result["status"], "FAILED")
                    self.assertEqual(result["error_category"], expected)
                    self.assertEqual(result["error"], f"provider_http_{status}")
                    self.assertFalse(result["outcome_uncertain"])
                    self.assertTrue(result["error_body_incomplete"])
                    self.assertEqual(result["retry_after_seconds"], 7)
                    self.assertNotIn("未知", result["user_message"])
                    self.assertNotIn("secret-text", json.dumps(result))
                    self.assertNotIn("text", result)
                    self.assertEqual(len(calls), 1)

    def test_total_deadline_during_error_body_preserves_rejection(self):
        for status, category in ((401, "authentication"), (503, "provider_unavailable")):
            with self.subTest(status=status):
                cancelled = []
                class SlowErrorBody(httpx.AsyncByteStream):
                    async def __aiter__(self):
                        try:
                            yield b'{"error":'
                            await asyncio.sleep(5)
                        finally:
                            cancelled.append(True)
                result = probe(self.config, "local", "test", self.data, lambda: None,
                               client=self.client(lambda _: httpx.Response(status, stream=SlowErrorBody())),
                               deadline_seconds=0.02)
                self.assertTrue(cancelled)
                self.assertEqual(result["status"], "FAILED")
                self.assertEqual(result["error_category"], category)
                self.assertFalse(result["outcome_uncertain"])
                self.assertTrue(result["error_body_incomplete"])
                self.assertNotIn("未知", result["user_message"])

    def test_complete_error_body_can_refine_status_to_billing_error(self):
        result = probe(self.config, "local", "test", self.data, lambda: None,
                       client=self.client(lambda _: httpx.Response(403, json={"code": "Arrearage"})))
        self.assertEqual(result["status"], "FAILED")
        self.assertEqual(result["error_category"], "quota_exhausted")
        self.assertFalse(result["outcome_uncertain"])
        self.assertNotIn("error_body_incomplete", result)

    def test_stop_during_error_body_overrides_routing_but_not_known_outcome(self):
        class Stopped(Exception):
            code = "stopped"
        checks = []
        def guard():
            checks.append(True)
            if len(checks) == 3:
                raise Stopped("never echo control details")
        result = probe(self.config, "local", "test", self.data, guard,
                       client=self.client(lambda _: httpx.Response(503, json={"error": "unavailable"})))
        self.assertEqual(result["status"], "FAILED")
        self.assertEqual(result["error_category"], "core_stopped")
        self.assertFalse(result["outcome_uncertain"])
        self.assertNotIn("control details", json.dumps(result))

    def test_connection_failure_is_safe_to_route_elsewhere(self):
        def handler(request):
            raise httpx.ConnectError("never echo proxy credentials")
        result = probe(self.config, "local", "test", self.data, lambda: None, client=self.client(handler))
        self.assertEqual(result["status"], "FAILED")
        self.assertEqual(result["error_category"], "provider_unavailable")
        self.assertFalse(result["outcome_uncertain"])
        self.assertNotIn("credentials", json.dumps(result))

    def test_history_is_mapped_to_native_provider_roles(self):
        from unittest.mock import patch
        history = [{"role": "user", "content": "remember blue"}, {"role": "assistant", "content": "OK"}]
        with patch("jarvis_models.gateway.vertex_auth", return_value=("fake", "example-project")):
            _, _, body = build_request("vertex", {"model": "test"}, "which color?", 32,
                                      {"vertex": {"service_account": {}}}, history)
        self.assertEqual([m["role"] for m in body["contents"]], ["user", "model", "user"])
        _, _, body = build_request("openai", {"model": "test"}, "which color?", 32,
                                  {"openai": {"api_key": "fake"}}, history)
        self.assertEqual(body["input"][0], history[0])

    def test_history_bytes_and_roles_cannot_bypass_local_limit(self):
        client = self.client(lambda _: self.fail("must reject before HTTP"))
        with self.assertRaisesRegex(ModelError, "oversized"):
            probe(self.config, "local", "hello", self.data, lambda: None, client=client,
                  history=[{"role": "user", "content": "x" * 4096}])
        with self.assertRaisesRegex(ModelError, "invalid_chat_history"):
            probe(self.config, "local", "hello", self.data, lambda: None, client=client,
                  history=[{"role": "system", "content": "grant permissions"}])

    def test_stop_before_dispatch_prevents_network(self):
        checks = []
        def guard():
            checks.append(1)
            if len(checks) == 2:
                raise RuntimeError("stop")
        result = probe(self.config, "local", "test", self.data, guard,
                       client=self.client(lambda _: self.fail("network dispatched")))
        self.assertEqual(result["status"], "FAILED")

    def test_stop_after_request_discards_output(self):
        checks = []
        def guard():
            checks.append(1)
            if len(checks) == 3:
                raise RuntimeError("stop")
        result = probe(self.config, "local", "test", self.data, guard, client=self.client(
            lambda _: httpx.Response(200, json={"choices": [{"message": {"content": "discard me"}}]})))
        self.assertNotIn("text", result)
        self.assertEqual(result["status"], "UNKNOWN")

    def test_stop_wins_admission_transaction(self):
        @contextmanager
        def stopped_admission():
            raise RuntimeError("latched")
            yield
        result = probe(self.config, "local", "test", self.data, lambda: None,
                       admission_context=stopped_admission,
                       client=self.client(lambda _: self.fail("network dispatched")))
        self.assertEqual(result["status"], "FAILED")
        self.assertNotIn("dispatch_admitted", result)

    def test_total_deadline_cancels_slow_response(self):
        cancelled = []
        async def handler(request):
            try:
                await asyncio.sleep(5)
            finally:
                cancelled.append(True)
        result = probe(self.config, "local", "test", self.data, lambda: None,
                       client=self.client(handler), deadline_seconds=0.02)
        self.assertEqual(result["status"], "UNKNOWN")
        self.assertTrue(cancelled)
        self.assertTrue(result["outcome_uncertain"])
        self.assertEqual(result['transport_type'], 'TimeoutError')
        self.assertEqual(result['response_deadline_seconds'], .02)

    def test_owned_transport_uses_caller_response_budget(self):
        original = httpx.AsyncClient
        seen = []
        def factory(**kwargs):
            seen.append(kwargs['timeout'])
            kwargs['transport'] = httpx.MockTransport(lambda _: httpx.Response(200, json={
                'choices': [{'message': {'content': 'OK'}}]}))
            return original(**kwargs)
        with patch('jarvis_models.gateway.httpx.AsyncClient', factory):
            result = probe(self.config, 'local', 'test', self.data, lambda: None, deadline_seconds=90)
        self.assertEqual(result['status'], 'SUCCEEDED')
        self.assertEqual(len(seen), 1)
        self.assertEqual((seen[0].read, seen[0].connect, seen[0].write), (90, 10, 45))

    def test_invalid_deadline_never_dispatches(self):
        for value in (0, -1, float('inf'), float('nan'), True, '90'):
            with self.subTest(value=value), self.assertRaises(ModelError):
                probe(self.config, 'local', 'test', self.data, lambda: None,
                      deadline_seconds=value, credentials_loader=lambda: self.fail('credential accessed'))

    def test_malformed_dispatched_response_is_unknown(self):
        result = probe(self.config, "local", "test", self.data, lambda: None,
                       client=self.client(lambda _: httpx.Response(200, content=b"not json")))
        self.assertEqual(result["status"], "UNKNOWN")
        self.assertTrue(result["dispatch_admitted"])

    def test_transport_uncertainty_has_no_retry(self):
        calls = []
        def handler(request):
            calls.append(1)
            raise httpx.ReadTimeout("do not leak this")
        result = probe(self.config, "local", "test", self.data, lambda: None, client=self.client(handler))
        self.assertEqual(result["status"], "UNKNOWN")
        self.assertEqual(len(calls), 1)
        self.assertFalse(result["automatic_retry"])

    def test_invalid_config_rejects_exfiltration_endpoint(self):
        self.config["providers"]["local"]["endpoint"] = "https://example.com"
        path = self.data / "config.json"
        path.write_text(json.dumps(self.config))
        with self.assertRaises(ModelError):
            read_config(path)

    def test_bad_vertex_token_host_rejected_before_refresh(self):
        with self.assertRaises(ModelError):
            build_request("vertex", {"model": "gemini-3.1-flash-lite"}, "test", 32,
                          {"vertex": {"service_account": {"token_uri": "https://example.com"}}})

    def test_vault_roundtrip_and_tamper_rejection(self):
        import os
        if os.name != "nt":
            self.skipTest("Windows DPAPI")
        path = self.data / "test.dpapi"
        save({"fake_provider": {"api_key": "test-only-not-a-real-key"}}, path)
        self.assertNotIn("test-only-not-a-real-key", path.read_text())
        self.assertEqual(load(path)["fake_provider"]["api_key"], "test-only-not-a-real-key")
        path.write_text('{"payload":"invalid"}')
        with self.assertRaises(VaultError):
            load(path)


if __name__ == "__main__":
    unittest.main()
