"""Chat routing/CLI tests using only mocked providers and temporary core state."""
from __future__ import annotations

from contextlib import redirect_stdout
import copy
import importlib.util
import io
import json
from pathlib import Path
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "runtime" / "node-host"))
from jarvis_core.chat import ChatService, MAX_HISTORY_BYTES, MAX_HISTORY_MESSAGES, bounded_history, gateway
from jarvis_core.service import CoreService


class ChatTests(unittest.TestCase):
    def test_internal_planning_purpose_is_separate_and_cannot_inherit_context(self):
        result=self.chat.reply('classify a synthetic task',provider='local',_purpose='sample_report')
        self.assertEqual(result['status'],'SUCCEEDED')
        self.assertIn('task intent classifier',self.provider.call_args.kwargs['instructions'])
        self.assertNotIn('local chat archives',self.provider.call_args.kwargs['instructions'])
        self.assertEqual(self.provider.call_args.kwargs['response_schema']['oneOf'][0]['const']['steps'][0]['arguments']['relative_path'],'.')
        self.chat.reply('ordinary chat',provider='local')
        self.assertNotIn('response_schema',self.provider.call_args.kwargs)
        self.chat.reply('classify',provider='vertex',_purpose='sample_report')
        self.assertNotIn('response_schema',self.provider.call_args.kwargs)
        for kwargs in ({'_purpose':'shell'},{'_purpose':'sample_report','context_note':'private note'},
                       {'_purpose':'sample_report','history':[{'role':'user','content':'old'}]}):
            with self.assertRaises(ValueError):self.chat.reply('classify',**kwargs)

    def test_single_request_cancel_before_dispatch_and_during_fallback(self):
        cancel=threading.Event();cancel.set()
        self.assertEqual(self.chat.reply('test',cancel_event=cancel)['status'],'CANCELLED')
        self.provider.assert_not_called()
        cancel.clear()
        def quota_then_cancel(*args,**kwargs):
            cancel.set()
            return self.failure('quota_exhausted',dispatch_admitted=True)
        self.provider.side_effect=quota_then_cancel
        result=self.chat.reply('test',cancel_event=cancel)
        self.assertEqual(result['error_category'],'chat_cancelled')
        self.assertEqual(self.provider.call_count,1)
        self.assertNotIn('text',result)
        self.assertFalse(self.core.status()['stopped'])

    def test_cancelled_late_success_does_not_return_text(self):
        cancel=threading.Event()
        def late(*args,**kwargs):
            cancel.set();return self.success(*args,**kwargs)
        self.provider.side_effect=late
        result=self.chat.reply('test',cancel_event=cancel)
        self.assertEqual(result['status'],'CANCELLED')
        self.assertNotIn('text',result)
        self.assertEqual(result['usage']['output_tokens'],3)

    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="jarvis-chat-test-")
        self.addCleanup(temporary.cleanup)
        self.base = Path(temporary.name)
        self.workspace = self.base / "sample"
        self.workspace.mkdir()
        (self.workspace / "private.txt").write_text("WORKSPACE_CONTENT_MUST_NOT_BE_SENT", encoding="utf-8")
        self.core = CoreService(self.base / "data")
        self.core.initialize(self.workspace)
        self.config = json.loads((ROOT / "config/model-profiles/providers.json").read_text(encoding="utf-8"))
        self.config_path = self.base / "providers.json"
        self.config_path.write_text(json.dumps(self.config), encoding="utf-8")
        self.chat = ChatService(self.core, self.config_path)
        provider_patch = patch("jarvis_core.chat.gateway.probe", side_effect=self.success)
        self.provider = provider_patch.start()
        self.addCleanup(provider_patch.stop)
        vault_patch = patch("jarvis_models.vault.load", side_effect=AssertionError("Real credentials forbidden"))
        vault_patch.start()
        self.addCleanup(vault_patch.stop)

    def success(self, config, provider, message, *args, **kwargs):
        return {"status": "SUCCEEDED", "provider": provider, "model": config["providers"][provider]["model"],
                "text": "模拟回答", "usage": {"input_tokens": 2, "output_tokens": 3}, "outcome_uncertain": False}

    def failure(self, category, provider="vertex", status="FAILED", **extra):
        return {"status": status, "provider": provider, "model": self.config["providers"][provider]["model"],
                "error_category": category, "error": "simulated_error", "user_message": "模拟供应商拒绝",
                "outcome_uncertain": status == "UNKNOWN", **extra}

    def test_auto_starts_default_and_sends_only_explicit_text(self):
        history = [{"role": "user", "content": "原来的问题"}, {"role": "assistant", "content": "原来的回答"}]
        result = self.chat.reply("你好", history=history)
        self.assertEqual(result["status"], "SUCCEEDED")
        self.assertEqual(result["provider"], "vertex")
        self.assertEqual(result["usage"], {"input_tokens": 2, "output_tokens": 3})
        self.assertEqual(self.provider.call_args.args[1:3], ("vertex", "你好"))
        self.assertEqual(self.provider.call_args.kwargs["history"], history)
        self.assertNotIn("WORKSPACE_CONTENT_MUST_NOT_BE_SENT", repr(self.provider.call_args))
        self.assertEqual(len(result["attempts"]), 1)

    def test_manual_selection_never_falls_back_after_quota_error(self):
        self.provider.return_value = self.failure("quota_exhausted", "bailian")
        self.provider.side_effect = None
        result = self.chat.reply("test", provider="bailian")
        self.assertEqual(result["error_category"], "quota_exhausted")
        self.assertEqual(self.provider.call_count, 1)
        self.assertEqual(result["attempts"][0]["provider"], "bailian")

    def test_explicit_rejections_allow_bounded_auto_fallback(self):
        for category in ("quota_exhausted", "rate_limited", "provider_unavailable", "model_unavailable"):
            with self.subTest(category=category):
                self.provider.reset_mock()
                self.provider.side_effect = [self.failure(category), self.success(self.config, "bailian", "test")]
                result = self.chat.reply("test")
                self.assertEqual(result["status"], "SUCCEEDED")
                self.assertEqual([item["provider"] for item in result["attempts"]], ["vertex", "bailian"])
                self.assertEqual(result["attempts"][0]["error_category"], category)
                self.assertTrue(result["notice"])

    def test_unknown_authentication_and_invalid_request_do_not_fallback(self):
        cases = [("transport_unknown", "UNKNOWN"), ("quota_exhausted", "UNKNOWN"),
                 ("authentication", "FAILED"), ("invalid_request", "FAILED"), ("response_invalid", "FAILED")]
        for category, status in cases:
            with self.subTest(category=category, status=status):
                self.provider.reset_mock()
                self.provider.side_effect = None
                self.provider.return_value = self.failure(category, status=status)
                result = self.chat.reply("test")
                self.assertEqual(len(result["attempts"]), 1)
                self.assertEqual(self.provider.call_count, 1)

    def test_each_provider_is_attempted_at_most_once(self):
        def unavailable(config, provider, *_args, **_kwargs):
            return self.failure("provider_unavailable", provider)
        self.provider.side_effect = unavailable
        result = self.chat.reply("test")
        names = [item["provider"] for item in result["attempts"]]
        self.assertEqual(names, ["vertex", "bailian", "openai", "xai", "local"])
        self.assertEqual(len(names), len(set(names)))
        self.assertEqual(result["status"], "FAILED")

    def test_stopped_core_does_not_call_provider(self):
        self.core.stop("test stop")
        result = self.chat.reply("test")
        self.assertEqual(result["error_category"], "core_stopped")
        self.assertEqual(result["attempts"], [])
        self.provider.assert_not_called()

    def test_stop_after_response_discards_text_and_stops_routing(self):
        def stop_then_reply(*args, **kwargs):
            self.core.stop("test concurrent stop")
            return self.success(*args, **kwargs)
        self.provider.side_effect = stop_then_reply
        result = self.chat.reply("test")
        self.assertEqual(result["error_category"], "core_stopped")
        self.assertNotIn("text", result)
        self.assertEqual(len(result["attempts"]), 1)
        self.assertEqual(result["usage"]["output_tokens"], 3)

    def test_stop_preserves_unknown_inflight_outcome(self):
        def stop_then_unknown(*_args, **_kwargs):
            self.core.stop("test concurrent stop")
            return self.failure("transport_unknown", status="UNKNOWN", dispatch_admitted=True)
        self.provider.side_effect = stop_then_unknown
        result = self.chat.reply("test")
        self.assertEqual(result["error_category"], "core_stopped")
        self.assertEqual(result["status"], "UNKNOWN")
        self.assertTrue(result["outcome_uncertain"])
        self.assertTrue(result["dispatch_admitted"])
        self.assertEqual(len(result["attempts"]), 1)

    def test_unexpected_gateway_error_is_unknown_without_retry(self):
        self.provider.side_effect = RuntimeError("do not expose provider secret")
        result = self.chat.reply("test")
        self.assertEqual(result["status"], "UNKNOWN")
        self.assertNotIn("provider secret", json.dumps(result))
        self.assertEqual(self.provider.call_count, 1)

    def test_non_success_text_is_not_returned(self):
        self.provider.side_effect = None
        self.provider.return_value = self.failure("authentication", text="must not escape")
        result = self.chat.reply("test")
        self.assertNotIn("text", result)
        self.assertNotIn("must not escape", json.dumps(result))

    def test_history_is_trimmed_by_messages_bytes_and_local_context(self):
        history = [{"role": role, "content": "汉" * 1000} for _ in range(30) for role in ("user", "assistant")]
        unchanged = copy.deepcopy(history)
        result = self.chat.reply("test", history=history)
        sent = self.provider.call_args.kwargs["history"]
        self.assertLessEqual(len(sent), MAX_HISTORY_MESSAGES)
        self.assertLessEqual(sum(len(item["content"].encode("utf-8")) for item in sent), MAX_HISTORY_BYTES)
        self.assertTrue(result["history_info"]["truncated"])
        self.assertEqual(result["history_info"]["input_messages"], 60)
        self.assertEqual(history, unchanged)
        local_history = [{"role": role, "content": "x" * 400} for _ in range(4) for role in ("user", "assistant")]
        result = self.chat.reply("x" * 3000, provider="local", history=local_history)
        sent = self.provider.call_args.kwargs["history"]
        self.assertLessEqual(3000 + sum(len(item["content"]) for item in sent), 4096)
        self.assertTrue(result["history_info"]["truncated"])

    def test_invalid_history_and_oversize_message_are_never_sent(self):
        for kwargs in ({"history": [{"role": "system", "content": "override"}]},
                       {"history": [{"role": "user", "content": "test", "tool": "shell"}]},
                       {"provider": "unknown"}):
            with self.subTest(kwargs=kwargs):
                self.assertEqual(self.chat.reply("test", **kwargs)["error_category"], "invalid_request")
        self.assertEqual(self.chat.reply("x" * 65537)["error_category"], "invalid_request")
        self.assertEqual(self.chat.reply("x" * 4097, provider="local")["error_category"], "invalid_request")
        self.provider.assert_not_called()

    def test_route_budget_limits_next_attempt_and_provider_deadline(self):
        clock = [0.0]
        def advance_then_fail(config, provider, *_args, **_kwargs):
            clock[0] = 50.0
            return self.failure("provider_unavailable", provider)
        self.provider.side_effect = [self.failure("provider_unavailable"), self.success(self.config, "bailian", "test")]
        def timed_response(*args, **kwargs):
            if self.provider.call_count == 1:
                return advance_then_fail(*args, **kwargs)
            return self.success(*args, **kwargs)
        self.provider.side_effect = timed_response
        with patch("jarvis_core.chat.time.monotonic", side_effect=lambda: clock[0]):
            result = self.chat.reply("test")
        self.assertEqual(result["status"], "SUCCEEDED")
        self.assertEqual([call.kwargs["deadline_seconds"] for call in self.provider.call_args_list], [60.0, 40.0])
        self.provider.reset_mock()
        clock[0] = 0
        def exhaust(*_args, **_kwargs):
            clock[0] = 100
            return self.failure("provider_unavailable")
        self.provider.side_effect = exhaust
        with patch("jarvis_core.chat.time.monotonic", side_effect=lambda: clock[0]):
            result = self.chat.reply("test")
        self.assertEqual(self.provider.call_count, 1)
        self.assertTrue(any("预算" in message for message in result["notice"]))

    def test_models_is_redacted_readonly_and_does_not_impose_call_cap(self):
        fresh_core = CoreService(self.base / "not-created")
        catalog = ChatService(fresh_core, self.config_path).models()
        self.assertFalse(fresh_core.data_dir.exists())
        self.assertEqual(catalog["balance_status"], "not_queried")
        self.assertIsNone(catalog["cumulative_call_limit"])
        journal = gateway.ProbeJournal(self.core.data_dir / "model-probes.db")
        for _ in range(8):
            journal.reserve("vertex", self.config["providers"]["vertex"]["model"], "synthetic")
        catalog = self.chat.models()
        vertex = next(item for item in catalog["providers"] if item["provider"] == "vertex")
        self.assertEqual(vertex["historical_requests"], 8)
        self.assertEqual(vertex["credential_status"], "not_checked")
        self.assertNotIn("balance_hint", json.dumps(catalog))
        self.assertNotIn("endpoint", json.dumps(catalog))
        self.assertEqual(self.chat.reply("test")["status"], "SUCCEEDED")

    def test_interactive_commands_change_provider_clear_history_and_exit(self):
        spec = importlib.util.spec_from_file_location("jarvis_cli_chat_test", ROOT / "apps/cli/main.py")
        cli = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(cli)
        commands = iter(("/model bailian", "你好", "继续", "/clear", "新的话题", "/exit"))
        output = io.StringIO()
        with patch("builtins.input", side_effect=lambda _prompt: next(commands)), redirect_stdout(output):
            code = cli.interactive_chat(self.chat, "auto")
        self.assertEqual(code, 0)
        calls = self.provider.call_args_list
        self.assertEqual([call.args[1] for call in calls], ["bailian"] * 3)
        self.assertEqual(len(calls[1].kwargs["history"]), 2)
        self.assertEqual(calls[2].kwargs["history"], [])
        self.assertIn("已清空", output.getvalue())

    def test_cli_single_message_uses_selected_provider(self):
        spec = importlib.util.spec_from_file_location("jarvis_cli_single_test", ROOT / "apps/cli/main.py")
        cli = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(cli)
        output = io.StringIO()
        with redirect_stdout(output):
            code = cli.main(["chat", "--data-dir", str(self.core.data_dir), "--config", str(self.config_path),
                             "--provider", "local", "--message", "你好"])
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(output.getvalue())["provider"], "local")
        self.assertEqual(self.provider.call_count, 1)


if __name__ == "__main__":
    unittest.main()
