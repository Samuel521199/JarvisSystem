"""Bounded text-only diagnostics. Model output never executes tools or code."""
from __future__ import annotations

from contextlib import closing, nullcontext
import asyncio
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
import re
import sqlite3
import time
import uuid

import httpx

from .vault import load, VaultError
from .catalog import resolve_settings, validate_catalog, PARAMETERS, MODEL_ID, CONNECTION_ID
from .billing import clean_usage, estimate
from urllib.parse import urlsplit

BAILIAN_HOSTS = {"beijing": "dashscope.aliyuncs.com", "singapore": "dashscope-intl.aliyuncs.com",
                "us": "dashscope-us.aliyuncs.com", "hongkong": "cn-hongkong.dashscope.aliyuncs.com"}


class ModelError(RuntimeError):
    """Only safe diagnostic codes; never embed HTTP bodies or credentials."""


class RequestCancelled(Exception):
    """The caller cancelled this one request, not the whole core."""


class ProbeJournal:
    """Persistent usage journal. History never blocks a new user request."""
    def __init__(self, path: Path):
        self.path = path
        path.parent.mkdir(parents=True, exist_ok=True)
        with closing(self.connect()) as db, db:
            db.execute("CREATE TABLE IF NOT EXISTS probes (id TEXT PRIMARY KEY, provider TEXT, model TEXT, prompt_digest TEXT, created_at TEXT, status TEXT, metadata TEXT)")

    def connect(self):
        return sqlite3.connect(self.path, timeout=5)

    def reserve(self, provider: str, model: str, prompt: str) -> str:
        ident = uuid.uuid4().hex
        with closing(self.connect()) as db, db:
            db.execute("BEGIN IMMEDIATE")
            db.execute("INSERT INTO probes VALUES(?,?,?,?,?,?,?)", (ident, provider, model,
                       hashlib.sha256(prompt.encode()).hexdigest(), datetime.now(timezone.utc).isoformat(),
                       "RESERVED", "{}"))
        return ident

    def finish(self, ident: str, status: str, metadata: dict) -> None:
        with closing(self.connect()) as db, db:
            db.execute("UPDATE probes SET status=?, metadata=? WHERE id=?", (status, json.dumps(metadata), ident))

    def counts(self) -> dict:
        with closing(self.connect()) as db:
            return dict(db.execute("SELECT provider,COUNT(*) FROM probes GROUP BY provider"))


def read_config(path: Path) -> dict:
    config = json.loads(path.read_text(encoding="utf-8"))
    return validate_config(config)


def validate_config(config):
    if config.get("schema_version") != 1 or type(config.get("automatic_fallback")) is not bool:
        raise ModelError("unsupported_probe_config")
    if (type(config.get("max_prompt_bytes")) is not int or not 1 <= config["max_prompt_bytes"] <= 65536
            or type(config.get("max_output_tokens")) is not int or not 1 <= config["max_output_tokens"] <= 4096):
        raise ModelError("unsafe_probe_limits")
    for key, ceiling in [("local_max_prompt_bytes", 4096), ("local_max_output_tokens", 256)]:
        if type(config.get(key, ceiling)) is not int or not 1 <= config.get(key, ceiling) <= ceiling:
            raise ModelError("unsafe_local_limits")
    providers = config.get("providers")
    if not isinstance(providers, dict) or not 1 <= len(providers) <= 64 or config.get("default_provider") not in providers:
        raise ModelError("invalid_provider_config")
    order = config.get("fallback_order", [config["default_provider"]])
    if (not isinstance(order, list) or not order or any(not isinstance(p, str) or p not in providers for p in order)
            or len(order) != len(set(order))):
        raise ModelError("invalid_fallback_order")
    for provider, item in config["providers"].items():
        if not isinstance(provider, str) or not CONNECTION_ID.fullmatch(provider) or not isinstance(item, dict):
            raise ModelError("unsupported_provider")
        adapter = item.get("adapter", provider)
        if adapter not in PARAMETERS or type(item.get("enabled", True)) is not bool:
            raise ModelError("unsupported_adapter")
        if not isinstance(item.get("model"), str) or not MODEL_ID.fullmatch(item["model"]):
            raise ModelError("invalid_model_identifier")
        if adapter == "compatible":
            parsed = urlsplit(item.get("base_url", ""))
            if (parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password
                    or parsed.query or parsed.fragment or len(item["base_url"]) > 500):
                raise ModelError("invalid_compatible_endpoint")
        if adapter == "bailian" and item.get("region") not in {"beijing", "singapore", "us", "hongkong"}:
            raise ModelError("invalid_bailian_region")
        if adapter == "vertex" and item.get("location") != "global":
            raise ModelError("unsupported_vertex_location")
        if adapter == "local" and item.get("endpoint") != "http://127.0.0.1:18180/v1/chat/completions":
            raise ModelError("local_endpoint_must_be_fixed_loopback")
        if not item.get("models", {}).get(item["model"], {}).get("enabled", True):
            raise ModelError("default_model_disabled")
    if not providers[config["default_provider"]].get("enabled", True):
        raise ModelError("default_provider_disabled")
    try:
        validate_catalog(config)
    except (ValueError, KeyError, TypeError):
        raise ModelError("invalid_model_catalog") from None
    return config


def vertex_auth(info: dict) -> tuple[str, str]:
    if (info.get("type") != "service_account" or info.get("token_uri") != "https://oauth2.googleapis.com/token"
            or info.get("universe_domain", "googleapis.com") != "googleapis.com"
            or not re.fullmatch(r"[a-z][a-z0-9-]{4,61}[a-z0-9]", info.get("project_id", ""))):
        raise ModelError("invalid_vertex_credential_metadata")
    from google.oauth2 import service_account
    from google.auth.transport.requests import Request
    credentials = service_account.Credentials.from_service_account_info(
        info, scopes=["https://www.googleapis.com/auth/cloud-platform"])
    transport = Request()

    attempts = 0

    def limited_request(*args, **kwargs):
        nonlocal attempts
        attempts += 1
        if attempts > 1:
            raise ModelError("vertex_auth_retry_disabled")
        kwargs["timeout"] = 15
        return transport(*args, **kwargs)

    try:
        credentials.refresh(limited_request)
    except Exception:
        raise ModelError("vertex_authentication_failed") from None
    return credentials.token, info["project_id"]


def build_request(provider: str, settings: dict, prompt: str, max_output: int, credentials: dict,
                  history=None, attachments=None, instructions="", response_schema=None) -> tuple[str, dict, dict]:
    if "models" in settings:
        settings = resolve_settings({"providers": {provider: settings}}, provider)
    model = settings["model"]
    connection = provider
    provider = settings.get("adapter", provider)
    if provider != "local":
        key_id = settings.get("credential_id")
        if key_id:
            stored = credentials.get("_managed", {}).get(key_id, {})
            if stored.get("connection") != connection:
                raise VaultError("credential_connection_mismatch")
            credential = stored["credential"]
        else:
            credential = credentials.get(connection, {})
        credentials = {provider: credential}
    from .attachments import validate_message, wire_messages, image_capable, image_budget
    source = [validate_message(m) for m in list(history or []) + [{"role": "user", "content": prompt, "attachments": attachments}]]
    if image_budget(source)[1] and not image_capable(provider, model):
        raise ModelError('model_does_not_support_images')
    messages = wire_messages(source, provider)
    if provider in {"vertex", "gemini"}:
        if provider == "vertex":
            token, project = vertex_auth(credentials["vertex"]["service_account"])
            url = f"https://aiplatform.googleapis.com/v1/projects/{project}/locations/global/publishers/google/models/{model}:generateContent"
            headers = {"Authorization": "Bearer " + token}
        else:
            url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
            headers = {"x-goog-api-key": credentials[provider]["api_key"]}
        return url, headers, {
            "contents": messages,
            **({"systemInstruction": {"parts": [{"text": instructions}]}} if instructions else {}),
            "generationConfig": {"maxOutputTokens": max_output,
                                 "thinkingConfig": {"thinkingLevel": settings.get("thinking_level", "MINIMAL")}}}
    if provider == "openai":
        return "https://api.openai.com/v1/responses", {"Authorization": "Bearer " + credentials[provider]["api_key"]}, {
            "model": model, "input": messages, "max_output_tokens": max_output, "store": False,
            **({"instructions": instructions} if instructions else {}),
            "reasoning": {"effort": settings.get("reasoning_effort", "none")}}
    if provider == "local":
        return settings["endpoint"], {}, {"model": model, "messages": ([{"role": "system", "content": instructions}] if instructions else []) + messages,
            "max_tokens": max_output, "stream": False, "temperature": 0,
            **({'response_format':{'type':'json_object','schema':response_schema}} if response_schema is not None else {}),
            "chat_template_kwargs": {"enable_thinking": False}}
    if provider == "anthropic":
        return "https://api.anthropic.com/v1/messages", {"x-api-key": credentials[provider]["api_key"], "anthropic-version": "2023-06-01"}, {
            "model": model, "messages": messages, "max_tokens": max_output,
            **({"system": instructions} if instructions else {}),
            **({"thinking": {"type": "adaptive"}, "output_config": {"effort": settings["reasoning_effort"]}} if settings.get("reasoning_effort") else {})}
    if provider == "bailian":
        host = BAILIAN_HOSTS[settings["region"]]
        url = f"https://{host}/compatible-mode/v1/chat/completions"
    elif provider == "eachlabs":
        url = "https://api.eachlabs.ai/v1/chat/completions"
    elif provider == "compatible":
        url = settings["base_url"].rstrip("/") + "/chat/completions"
    else:
        url = "https://api.x.ai/v1/chat/completions"
    body = {"model": model, "messages": ([{"role": "system", "content": instructions}] if instructions else []) + messages, "max_tokens": max_output, "stream": False}
    if provider == "bailian":
        body["enable_thinking"] = settings.get("enable_thinking", False)
    if provider in {"xai", "eachlabs", "compatible"} and "reasoning_effort" in settings:
        body["reasoning_effort"] = settings["reasoning_effort"]
    return url, {"Authorization": "Bearer " + credentials[provider]["api_key"]}, body


def extract(provider: str, response: dict) -> tuple[str, dict]:
    if provider in {"vertex", "gemini"}:
        texts = [part["text"] for item in response.get("candidates", [])
                 for part in item.get("content", {}).get("parts", []) if isinstance(part.get("text"), str) and not part.get("thought")]
        usage = response.get("usageMetadata", {})
    elif provider == "openai":
        texts = [part["text"] for item in response.get("output", []) if item.get("type") == "message"
                 for part in item.get("content", []) if part.get("type") == "output_text" and isinstance(part.get("text"), str)]
        usage = response.get("usage", {})
    elif provider == "anthropic":
        texts = [part["text"] for part in response.get("content", []) if part.get("type") == "text" and isinstance(part.get("text"), str)]
        usage = response.get("usage", {})
    else:
        texts = [choice["message"]["content"] for choice in response.get("choices", [])
                 if isinstance(choice.get("message", {}).get("content"), str)]
        usage = response.get("usage", {})
    # Only numerical accounting metadata is persisted, never raw provider responses.
    allowed = {"promptTokenCount", "candidatesTokenCount", "totalTokenCount", "cachedContentTokenCount",
               "thoughtsTokenCount", "prompt_tokens", "completion_tokens", "total_tokens", "input_tokens",
               "output_tokens", "num_sources_used", "cost_in_usd_ticks"}
    if not isinstance(usage, dict):
        usage = {}
    return "\n".join(texts), clean_usage(usage)


def completion_metadata(provider: str, response: dict) -> dict:
    """Normalize only known completion markers, never persist arbitrary provider text."""
    if provider == "openai":
        state = response.get("status")
        detail = response.get("incomplete_details") or {}
        reason = detail.get("reason") if isinstance(detail, dict) else None
        if state in {"incomplete", "failed", "cancelled", "queued", "in_progress"}:
            return {"output_incomplete": True, "completion_reason":
                    "length" if reason == "max_output_tokens" else "provider_incomplete"}
        reasons = [state] if state else []
        complete = {"completed"}
    elif provider in {"vertex", "gemini"}:
        reasons = [c.get("finishReason") for c in response.get("candidates", []) if c.get("finishReason")]
        if response.get("promptFeedback", {}).get("blockReason"):
            return {"output_incomplete": True, "completion_reason": "provider_incomplete"}
        complete = {"STOP"}
    elif provider == "anthropic":
        reasons = [response["stop_reason"]] if response.get("stop_reason") else []
        complete = {"end_turn", "stop_sequence"}
    else:
        reasons = [c.get("finish_reason") for c in response.get("choices", []) if c.get("finish_reason")]
        complete = {"stop"}
    if any(r not in complete for r in reasons):
        return {"output_incomplete": True, "completion_reason":
                "length" if any(r in {"length", "MAX_TOKENS", "max_tokens"} for r in reasons) else "provider_incomplete"}
    # Older compatible endpoints omit finish reasons. Do not fabricate a provider receipt.
    return {"output_incomplete": False, "completion_reason": "complete" if reasons else "unspecified"}


def classify_http_error(status: int, body: bytes) -> tuple[str, str]:
    """Inspect only bounded structured codes; never echo provider messages or headers."""
    try:
        payload = json.loads(body)
        error = payload.get("error", payload)
        error = error if isinstance(error, dict) else {}
        codes = {str(error.get(key, "")).lower() for key in ("code", "type", "status")}
    except (ValueError, AttributeError, TypeError):
        codes = set()
    quota_codes = {"insufficient_quota", "credit_balance_exhausted", "organization_spend_limit_exceeded",
                   "project_spend_limit_exceeded", "organization_usage_limit_exceeded", "arrearage",
                   "insufficientbalance", "allocationquota.freetieronly", "prepaidbilloverdue"}
    if status == 402 or codes & quota_codes:
        return "quota_exhausted", "供应商报告余额、账单或用量额度受限，请检查该账户额度。"
    if status == 429:
        return "rate_limited", "供应商暂时限流或配额受限；仅凭此响应不能判断余额是否耗尽。"
    if status in {401, 403}:
        return "authentication", "供应商拒绝认证或访问，请检查凭据、权限与区域。"
    if status == 404:
        return "model_unavailable", "所选模型或接口当前不可用，请检查模型权限。"
    if status >= 500:
        return "provider_unavailable", "供应商服务暂时不可用。"
    return "invalid_request", "供应商拒绝本次请求，请检查模型参数或输入。"


def probe(config: dict, provider: str, prompt: str, data_dir: Path, guard, *, client=None,
          credentials_loader=load, admission_context=nullcontext, deadline_seconds=60.0, history=None,
          cancel_event=None, attachments=None, instructions="", response_schema=None) -> dict:
    guard()
    if (isinstance(deadline_seconds, bool) or not isinstance(deadline_seconds, (int, float))
            or not math.isfinite(deadline_seconds) or deadline_seconds <= 0):
        raise ModelError('invalid_request_deadline')
    if provider == "auto":
        provider = config["default_provider"]
    if provider not in config["providers"]:
        raise ModelError("unknown_provider")
    from .attachments import validate_message, text_size, image_budget, MAX_IMAGES_BYTES, MAX_ATTACHMENTS
    messages = [] if history is None else history
    if not isinstance(messages, list) or len(messages) > 40:
        raise ModelError("invalid_chat_history")
    try:
        messages = [validate_message(m) for m in messages]
        current = validate_message({'role': 'user', 'content': prompt, 'attachments': attachments})
    except (ValueError, TypeError, UnicodeError) as exc:
        raise ModelError('invalid_chat_history_or_attachments') from exc
    images_size, images_count = image_budget(messages + [current])
    if images_size > MAX_IMAGES_BYTES or images_count > MAX_ATTACHMENTS:
        raise ModelError('attachment_budget_exceeded')
    max_input = config.get("local_max_prompt_bytes", 4096) if provider == "local" else config["max_prompt_bytes"]
    if not isinstance(instructions, str) or len(instructions.encode("utf-8")) > 4096:
        raise ModelError("invalid_host_instructions")
    if (not isinstance(prompt, str) or not prompt.strip()
            or len(instructions.encode("utf-8")) + text_size(current) + sum(text_size(m) for m in messages) > max_input):
        raise ModelError("invalid_or_oversized_prompt")
    item = resolve_settings(config, provider)
    if response_schema is not None:
        try:
            if (item.get('adapter',provider)!='local' or not isinstance(response_schema,dict)
                    or len(json.dumps(response_schema,allow_nan=False).encode('utf-8'))>8192):
                raise ValueError('Invalid local schema')
        except (ValueError,TypeError,RecursionError):raise ModelError('invalid_local_response_schema') from None
    journal = ProbeJournal(data_dir / "model-probes.db")
    ident = journal.reserve(provider, item["model"], json.dumps({"instructions": instructions, "messages": messages + [current],
        **({'response_schema':response_schema} if response_schema is not None else {})}, ensure_ascii=False))
    started = time.monotonic()
    metadata = {"provider": provider, "model": item["model"], "request_id": ident,
                "response_deadline_seconds": deadline_seconds}
    response_text = ""
    status = "FAILED"
    dispatched = False
    rejected = False

    def check_cancel():
        if cancel_event is not None and cancel_event.is_set():
            raise RequestCancelled()

    async def receive(url, headers, payload):
        async def request(active_client):
            nonlocal rejected
            async with active_client.stream("POST", url, headers=headers, json=payload) as response:
                metadata["http_status"] = response.status_code
                if response.status_code != 200:
                    rejected = True
                    category, message = classify_http_error(response.status_code, b"")
                    metadata.update(error="provider_http_" + str(response.status_code),
                                    error_category=category, user_message=message)
                    retry = response.headers.get("retry-after", "")
                    if retry.isdecimal() and len(retry) < 7:
                        metadata["retry_after_seconds"] = min(int(retry), 86400)
                    # The body can refine a known rejection, never erase it.
                    error_body = bytearray()
                    async for chunk in response.aiter_bytes():
                        guard()
                        error_body.extend(chunk[:max(0, 16384-len(error_body))])
                        if len(error_body) >= 16384:
                            break
                    category, message = classify_http_error(response.status_code, bytes(error_body))
                    metadata.update(error_category=category, user_message=message)
                    raise ModelError("provider_http_" + str(response.status_code))
                chunks = bytearray()
                async for chunk in response.aiter_bytes():
                    guard()
                    chunks.extend(chunk)
                    if len(chunks) > 1048576:
                        raise ModelError("provider_response_too_large")
                return json.loads(chunks)
        async def bounded_request():
            if client is not None:
                return await request(client)
            # Non-streaming reasoning can legitimately take more than 45s before
            # its first byte. The caller owns the response budget; wait_for below
            # remains the hard bound even when response bytes trickle in.
            async with httpx.AsyncClient(timeout=httpx.Timeout(deadline_seconds, connect=min(10, deadline_seconds),
                                         write=min(45, deadline_seconds), pool=min(45, deadline_seconds)), follow_redirects=False,
                                         trust_env=provider != "local") as active_client:
                return await request(active_client)
        async def cancellable_request():
            if cancel_event is None:
                return await bounded_request()
            check_cancel()
            pending = asyncio.create_task(bounded_request())
            try:
                while not pending.done():
                    await asyncio.wait({pending}, timeout=0.05)
                    check_cancel()
                return await pending
            finally:
                if not pending.done():
                    pending.cancel()
                # Join transport cleanup before releasing the request slot.
                await asyncio.gather(pending, return_exceptions=True)
        return await asyncio.wait_for(cancellable_request(), timeout=deadline_seconds)

    try:
        check_cancel()
        adapter = item.get("adapter", provider)
        keys = item.get("keys", {})
        selected_key = keys.get(item.get("credential_id"), {})
        metadata["billing_identity"] = {"adapter": adapter, "label": item.get("label", provider),
                                        "key_id": item.get("credential_id"), "key_label": selected_key.get("label", "历史未归属")}
        credentials = {} if adapter == "local" else credentials_loader()
        max_output = config.get("local_max_output_tokens", 256) if adapter == "local" else config["max_output_tokens"]
        max_output = item.get("max_output_tokens", max_output)
        url, headers, payload = build_request(provider, item, prompt, max_output, credentials, history=messages, attachments=attachments, instructions=instructions,response_schema=response_schema)
        # The same short core transaction serializes admission with stop. Once
        # committed this is in-flight, even before socket transmission completes.
        # Never hold that transaction while waiting for a remote response.
        with admission_context():
            guard()
            check_cancel()
            metadata["dispatch_admitted"] = True
            journal.finish(ident, "DISPATCHING", metadata)
            dispatched = True
        parsed = asyncio.run(receive(url, headers, payload))
        response_text, usage = extract(adapter, parsed)
        metadata["usage"] = usage
        metadata.update(completion_metadata(adapter, parsed))
        guard()
        check_cancel()
        if not response_text.strip() and metadata["output_incomplete"]:
            status = "FAILED"
            metadata.update(error="output_incomplete", error_category="response_incomplete",
                            user_message="供应商已结束请求，但未产生完整可用正文；本次仍可能计费，可调整输出长度或思考级别后重新发送。")
        elif not response_text.strip():
            raise ModelError("empty_or_incomplete_response")
        else:
            status = "SUCCEEDED"
    except RequestCancelled:
        status = "UNKNOWN" if dispatched and not rejected else "CANCELLED"
        metadata.update(error="request_cancelled", error_category="chat_cancelled", cancel_requested=True,
                        user_message="已停止本次生成；已接收的远端请求及用量可能仍在结算。" if dispatched else "已停止，本次未发送到模型。")
    except (httpx.ConnectError, httpx.ConnectTimeout, httpx.PoolTimeout) as exc:
        status = "FAILED"
        if rejected:
            metadata.update(error_body_incomplete=True, transport_type=type(exc).__name__)
        else:
            metadata.update(error="connection_unavailable", error_category="provider_unavailable",
                            user_message=("本地模型服务未能连接（127.0.0.1:18180）；请在本机启动 tools/local_llm.py serve 后重试，或切换云模型。"
                                          if item.get("adapter", provider) == "local" else "无法建立模型连接，请检查网络或供应商服务。"))
    except (httpx.TransportError, TimeoutError) as exc:
        status = "FAILED" if rejected else "UNKNOWN"
        metadata["transport_type"] = type(exc).__name__
        if rejected:
            metadata["error_body_incomplete"] = True
        else:
            metadata.update(error="transport_error_no_automatic_retry", error_category="transport_unknown",
                            user_message="连接中断或等待超时，远端结果可能未知；可由你明确重新发送。")
    except VaultError:
        metadata.update(error="credentials_unavailable", error_category="authentication",
                        user_message="当前提供商凭据不可用，请检查本地配置。")
    except ModelError as exc:
        status = "UNKNOWN" if dispatched and not rejected else "FAILED"
        metadata["error"] = str(exc)
        metadata.setdefault("error_category", "response_invalid" if dispatched else "authentication")
        metadata.setdefault("user_message", "模型未返回有效文本。" if dispatched else "模型认证或请求配置不可用。")
    except Exception as exc:
        status = "UNKNOWN" if dispatched and not rejected else "FAILED"
        # Exceptions from authentication, parsing or the core guard are never reflected verbatim.
        stopped = getattr(exc, "code", "") in {"stopped", "core_stopped", "stop_latched", "control_invalid", "control_unavailable", "not_initialized"}
        if stopped:
            metadata.update(error="core_guard_failed", error_category="core_stopped",
                            user_message="核心已停止或控制状态不可用。")
        elif rejected:
            metadata["error_body_incomplete"] = True
        else:
            metadata.update(error="authentication_parsing_or_core_guard_failed", error_category="response_invalid",
                            user_message="响应解析或控制检查失败，本次未采用模型输出。")
    finally:
        metadata["billing"] = estimate(item.get("adapter", provider), metadata.get("usage", {}), item.get("price"), dispatched=dispatched)
        metadata["outcome_uncertain"] = status == "UNKNOWN"
        metadata["elapsed_seconds"] = round(time.monotonic() - started, 3)
        journal.finish(ident, status, metadata)
    result = {**metadata, "status": status, "automatic_retry": False}
    if status == "SUCCEEDED":
        result["text"] = response_text
    return result
