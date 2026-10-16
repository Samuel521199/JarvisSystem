"""Text-only chat with explicit routing and bounded, caller-owned conversation history.

No workspace retrieval, tool execution or persistent conversation store is used.
The 90-second routing budget is cooperative; provider authentication may add its
own bounded wait outside the asynchronous response deadline.
"""
from __future__ import annotations

from contextlib import closing
from pathlib import Path
import sqlite3
import sys
import time

from .policy import safe_path

ROOT = Path(__file__).resolve().parents[3]
ADAPTER_PATH = str(ROOT / "adapters" / "models" / "provider-native")
if ADAPTER_PATH not in sys.path:
    sys.path.insert(0, ADAPTER_PATH)
from jarvis_models import gateway
from jarvis_models.catalog import public_models, select_model, reasoning_value, resolve_settings

PROVIDERS = ("vertex", "bailian", "openai", "xai", "local")
MAX_HISTORY_MESSAGES = 20
MAX_HISTORY_BYTES = 32768
MAX_MESSAGE_BYTES = 65536
ROUTE_BUDGET_SECONDS = 90.0
ATTEMPT_DEADLINE_SECONDS = 60.0
FALLBACK_CATEGORIES = {"quota_exhausted", "rate_limited", "provider_unavailable", "model_unavailable"}
RESULT_FIELDS = {"status", "text", "provider", "model", "usage", "error", "error_category", "user_message",
                 "outcome_uncertain", "dispatch_admitted", "request_id", "elapsed_seconds", "http_status",
                 "retry_after_seconds", "automatic_retry"}
RESULT_FIELDS.add("cancel_requested")


def bounded_history(history, *, max_bytes=MAX_HISTORY_BYTES):
    """Return recent complete context; never reinterpret a history role as tools/system."""
    if history is None:
        history = []
    if not isinstance(history, list) or len(history) > 1000:
        raise ValueError("历史必须是有界的消息列表。")
    result = []
    total_input = 0
    for item in history:
        if (not isinstance(item, dict) or set(item) != {"role", "content"}
                or item["role"] not in {"user", "assistant"} or not isinstance(item["content"], str)):
            raise ValueError("历史只接受 user/assistant 的纯文本消息。")
        total_input += len(item["content"].encode("utf-8"))
        if total_input > 262144:
            raise ValueError("传入历史过大，请清空或缩短会话。")
        result.append({"role": item["role"], "content": item["content"]})
    original = len(result)
    result = result[-MAX_HISTORY_MESSAGES:]
    size = sum(len(item["content"].encode("utf-8")) for item in result)
    while result and size > max(0, min(max_bytes, MAX_HISTORY_BYTES)):
        size -= len(result.pop(0)["content"].encode("utf-8"))
    # Avoid leaving the assistant half of an older turn at the beginning.
    while result and result[0]["role"] == "assistant":
        size -= len(result.pop(0)["content"].encode("utf-8"))
    return result, {"input_messages": original, "kept_messages": len(result),
                    "dropped_messages": original - len(result), "truncated": original != len(result),
                    "kept_bytes": size, "max_messages": MAX_HISTORY_MESSAGES,
                    "max_bytes": max(0, min(max_bytes, MAX_HISTORY_BYTES))}


class ChatService:
    def __init__(self, core, config_path=None):
        self.core = core
        self.config_path = ROOT / "config" / "model-profiles" / "providers.json" if config_path is None else Path(config_path)

    def models(self):
        """Configuration and historical counts only; never reads the credential vault."""
        config = gateway.read_config(self.config_path)
        counts, count_status, observations = {}, "available", {}
        path = Path(self.core.data_dir) / "model-probes.db"
        if path.exists():
            try:
                safe_path(path, directory=False)
                with closing(sqlite3.connect(path.absolute().as_uri() + "?mode=ro", uri=True, timeout=2)) as connection:
                    counts = dict(connection.execute("SELECT provider,COUNT(*) FROM probes GROUP BY provider"))
                    for entry in public_models(config):
                        row = connection.execute("SELECT status,created_at FROM probes WHERE provider=? AND model=? ORDER BY rowid DESC LIMIT 1",
                                                 (entry["provider"], entry["model"])).fetchone()
                        if row:
                            observations[(entry["provider"], entry["model"])] = {"last_probe_status": row[0], "last_probe_at": row[1]}
            except Exception:
                count_status = "unavailable"
                observations = {}
        return {"default_provider": config["default_provider"], "automatic_fallback": config["automatic_fallback"],
                "fallback_order": list(config.get("fallback_order", [])),
                "providers": [{"provider": provider, "model": settings["model"],
                               "is_default": provider == config["default_provider"],
                               "historical_requests": counts.get(provider, 0) if count_status == "available" else None,
                               "credential_status": "not_checked"}
                              for provider, settings in config["providers"].items()],
                "history_count_status": count_status, "balance_status": "not_queried",
                "models": [{**entry, **observations.get((entry["provider"], entry["model"]), {"last_probe_status": "NOT_TESTED" if count_status == "available" else "UNAVAILABLE"})}
                           for entry in public_models(config)],
                "catalog_checked_at": config.get("catalog_checked_at"),
                "cumulative_call_limit": None,
                "notice": ["历史请求数仅用于诊断，不限制累计使用；账户余额未查询。"]}

    @staticmethod
    def _failure(category, code, message, provider=None, model=None, status="FAILED"):
        return {"status": status, "provider": provider, "model": model, "error": code,
                "error_category": category, "user_message": message,
                "outcome_uncertain": status == "UNKNOWN"}

    @staticmethod
    def _package(result, attempts, notice, history_info):
        return {**result, "attempts": attempts, "notice": notice, "history_info": history_info}

    def _guard_error(self):
        try:
            self.core.assert_running()
        except Exception:
            return self._failure("core_stopped", "core_unavailable", "核心尚未初始化、已停止或控制状态不可用；未继续请求模型。")
        return None

    @staticmethod
    def _cancel_result(previous=None):
        previous = previous or {}
        uncertain = previous.get("outcome_uncertain", False) or previous.get("status") == "UNKNOWN"
        return {**{key: previous[key] for key in ("provider", "model", "request_id", "dispatch_admitted", "usage") if key in previous},
                "status": "UNKNOWN" if uncertain else "CANCELLED", "error_category": "chat_cancelled",
                "cancel_requested": True, "outcome_uncertain": uncertain,
                "user_message": "已停止本次生成，后续输出不再采用；已接收的远端请求可能仍有用量。"}

    def reply(self, message, provider="auto", history=None, model=None, reasoning=None, cancel_event=None):
        attempts, notice = [], []
        info = {"input_messages": 0, "kept_messages": 0, "dropped_messages": 0, "truncated": False}
        if cancel_event is not None and cancel_event.is_set():
            return self._package(self._cancel_result(), attempts, notice, info)
        blocked = self._guard_error()
        if blocked:
            return self._package(blocked, attempts, notice, info)
        try:
            config = gateway.read_config(self.config_path)
            if not isinstance(message, str) or not message.strip():
                raise ValueError("请输入非空文本。")
            message_bytes = len(message.encode("utf-8"))
            if message_bytes > min(config["max_prompt_bytes"], MAX_MESSAGE_BYTES):
                raise ValueError("消息超过输入字节上限，请缩短内容。")
            if provider != "auto" and provider not in config["providers"]:
                raise ValueError("未知模型提供商，请先查看 models。")
            if model is not None or reasoning is not None:
                if provider == "auto":
                    raise ValueError("指定模型时同时指定提供商。")
                model = model if model is not None else config["providers"][provider]["model"]
                config = select_model(config, provider, model, reasoning)
            base_history, base_info = bounded_history(history)
            info = base_info
            if provider == "auto":
                candidates = [config["default_provider"]]
                if config["automatic_fallback"]:
                    candidates.extend(config.get("fallback_order", []))
                routes = list(dict.fromkeys(item for item in candidates if item in config["providers"] and item in PROVIDERS))
            else:
                routes = [provider]
            if not routes:
                raise ValueError("没有可用的模型路由配置。")
        except (ValueError, OSError, KeyError, TypeError, gateway.ModelError):
            result = self._failure("invalid_request", "invalid_chat_input_or_configuration",
                                   "消息、历史、模型选择或配置无效；请检查长度与可用模型。")
            return self._package(result, attempts, notice, info)

        started = time.monotonic()
        result = self._failure("provider_unavailable", "no_model_attempt", "本次未调用模型。")
        for index, selected in enumerate(routes):
            if cancel_event is not None and cancel_event.is_set():
                return self._package(self._cancel_result(result), attempts, notice, info)
            blocked = self._guard_error()
            if blocked:
                return self._package(blocked, attempts, notice, info)
            remaining = ROUTE_BUDGET_SECONDS - (time.monotonic() - started)
            if remaining <= 0:
                notice.append("本轮自动路由等待预算已用完，未继续尝试其他模型。")
                return self._package(result, attempts, notice, info)
            limit = config.get("local_max_prompt_bytes", 4096) if selected == "local" else config["max_prompt_bytes"]
            model = config["providers"][selected]["model"]
            if message_bytes > limit:
                result = self._failure("invalid_request", "selected_model_input_limit",
                                       "当前消息超过所选模型的输入上限；未发送，请缩短消息或选择其他模型。", selected, model)
                return self._package(result, attempts, notice, info)
            selected_history, selected_info = bounded_history(base_history, max_bytes=limit - message_bytes)
            info = {**selected_info, "input_messages": base_info["input_messages"],
                    "dropped_messages": base_info["input_messages"] - len(selected_history),
                    "truncated": base_info["input_messages"] != len(selected_history)}
            if info["truncated"]:
                notice.append(f"{selected} 本次仅发送最近 {info['kept_messages']} 条历史，已截断 {info['dropped_messages']} 条旧消息。")
            try:
                response = gateway.probe(config, selected, message, Path(self.core.data_dir), self.core.assert_running,
                                         admission_context=self.core.effect_guard,
                                         deadline_seconds=min(ATTEMPT_DEADLINE_SECONDS, remaining), history=selected_history,
                                         **({"cancel_event": cancel_event} if cancel_event is not None else {}))
                if not isinstance(response, dict) or response.get("status") not in {"SUCCEEDED", "FAILED", "UNKNOWN", "CANCELLED"}:
                    raise ValueError("Invalid gateway result")
                result = {key: value for key, value in response.items() if key in RESULT_FIELDS}
                result.setdefault("provider", selected)
                result.setdefault("model", model)
                if result["status"] == "SUCCEEDED" and (not isinstance(result.get("text"), str) or not result["text"].strip()):
                    raise ValueError("Missing text")
            except Exception:
                result = self._failure("transport_unknown", "gateway_result_unknown",
                                       "模型请求结果无法确定，本轮不会自动重发。", selected, model, "UNKNOWN")
            if result["status"] != "SUCCEEDED":
                result.pop("text", None)
            result["reasoning"] = reasoning_value(selected, resolve_settings(config, selected))
            if cancel_event is not None and cancel_event.is_set():
                result = self._cancel_result(result)
            blocked = self._guard_error()
            if blocked:
                # Preserve uncertainty/usage while withholding generated output.
                uncertain = result.get("outcome_uncertain", False) or result["status"] == "UNKNOWN"
                preserved = {key: result[key] for key in ("dispatch_admitted", "request_id", "usage") if key in result}
                result = {**blocked, **preserved, "provider": selected, "model": model,
                          "status": "UNKNOWN" if uncertain else "FAILED", "outcome_uncertain": uncertain}
                result["user_message"] = "核心已停止，本次模型输出未采用；已经发生的请求无法撤回。"
            attempt = {key: result[key] for key in ("provider", "model", "status", "error_category", "user_message",
                       "outcome_uncertain", "dispatch_admitted", "request_id", "usage", "elapsed_seconds") if key in result}
            attempts.append(attempt)
            if result["status"] == "SUCCEEDED":
                return self._package(result, attempts, notice, info)
            category = result.get("error_category")
            if category in {"core_stopped", "chat_cancelled"}:
                notice.append("停止已生效，本轮未继续切换模型。")
                return self._package(result, attempts, notice, info)
            if result["status"] == "UNKNOWN" or result.get("outcome_uncertain") is not False:
                notice.append("请求结果不确定，未自动尝试其他模型，避免重复请求。")
                return self._package(result, attempts, notice, info)
            local_not_sent = (selected == "local" and not result.get("dispatch_admitted", False)
                              and category == "transport_unknown")
            eligible = category in FALLBACK_CATEGORIES or local_not_sent
            if provider != "auto" or not config["automatic_fallback"] or not eligible or index + 1 >= len(routes):
                return self._package(result, attempts, notice, info)
            explanation = result.get("user_message", "所选模型不可用。")
            notice.append(f"{selected} / {model}：{explanation} 下一候选模型：{routes[index + 1]}。")
        return self._package(result, attempts, notice, info)
