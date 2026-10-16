"""Local connection configuration. Immutable credential versions live only in DPAPI."""
from __future__ import annotations

from contextlib import closing
from copy import deepcopy
from datetime import datetime, timezone
import json
from pathlib import Path
import sqlite3
import uuid
from functools import lru_cache
from jsonschema import Draft202012Validator

from . import vault
from .catalog import PARAMETERS, REASONING_VALUES, REASONING_PARAMETERS, profiles
from .gateway import validate_config, read_config, ModelError, BAILIAN_HOSTS
from .billing import validate_price

LABELS = {"vertex": "Google Vertex", "openai": "OpenAI", "bailian": "阿里云百炼", "xai": "xAI", "local": "本机 Qwen",
          "eachlabs": "Eachlabs", "anthropic": "Anthropic 官方", "gemini": "Google AI Studio", "compatible": "自定义中转"}
ENDPOINTS = {"vertex": "https://aiplatform.googleapis.com/v1", "openai": "https://api.openai.com/v1",
             "bailian": "https://dashscope.aliyuncs.com/compatible-mode/v1", "xai": "https://api.x.ai/v1",
             "eachlabs": "https://api.eachlabs.ai/v1", "anthropic": "https://api.anthropic.com/v1",
             "gemini": "https://generativelanguage.googleapis.com/v1beta", "local": "http://127.0.0.1:18180/v1"}


@lru_cache(maxsize=1)
def command_validator():
    path = Path(__file__).resolve().parents[4] / "contracts/schemas/model-admin.schema.json"
    return Draft202012Validator(json.loads(path.read_text(encoding="utf-8")))


def claude_models(relay=True):
    result = {}
    for name, tier, rates in (("sonnet", "balanced", (2, 10, .1, 2.5)), ("opus", "advanced", (4, 20, .2, 5)), ("haiku", "economy", (.1, .5, .01, .125))):
        mid = f"anthropic/claude-{name}-5.5" if relay else f"claude-{name}-5-5"
        result[mid] = {"label": f"Claude {name.title()} 5.5", "tier": tier,
                       "parameters": {"reasoning_effort": "low", "max_output_tokens": 8192},
                       "reasoning_levels": ["low", "medium", "high"],
                       "price": dict(zip(("input", "output", "cache_read", "cache_write"), rates), currency="USD",
                                     fee_percent=5.5 if relay else 0, checked_at="2026-10-16", max_input_tokens=100000 if name == "haiku" else 1000000,
                                     source="https://docs.eachlabs.ai/llm-router/models" if relay else "https://platform.claude.com/docs/en/about-claude/pricing")}
    return result


def template(adapter, seed):
    if adapter in seed["providers"]:
        item = deepcopy(seed["providers"][adapter])
    elif adapter in {"eachlabs", "anthropic"}:
        entries = claude_models(adapter == "eachlabs")
        item = {"model": next(iter(entries)), "models": entries}
    elif adapter == "gemini":
        item = deepcopy(seed["providers"]["vertex"])
        # Gemini Developer API and Vertex prices are configured independently.
        for entry in item["models"].values():
            entry.pop("price", None)
    elif adapter == "compatible":
        item = {"model": "configure-model", "models": {"configure-model": {"label": "填写模型 ID", "parameters": {"max_output_tokens": 4096}}}}
    else:
        raise ValueError("未知接入模板。")
    item.update(adapter=adapter, label=LABELS[adapter], enabled=True, keys={})
    return item


def effective_config(seed_path, data_dir):
    path = Path(data_dir) / "model-admin.db"
    if path.exists():
        with closing(sqlite3.connect(path.absolute().as_uri() + "?mode=ro", uri=True, timeout=5)) as db:
            row = db.execute("SELECT config FROM settings WHERE id=1").fetchone()
            if row:
                return validate_config(json.loads(row[0]))
    return read_config(seed_path)


class Registry:
    def __init__(self, data_dir, seed_path, *, loader=vault.load, saver=vault.save, vault_exists=None):
        self.path = Path(data_dir) / "model-admin.db"
        self.seed_path = Path(seed_path)
        self.loader, self.saver = loader, saver
        self.vault_exists = vault_exists if vault_exists is not None else vault.default_path().exists
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with closing(self.connect()) as db, db:
            db.execute("CREATE TABLE IF NOT EXISTS settings(id INTEGER PRIMARY KEY CHECK(id=1), revision INTEGER NOT NULL, config TEXT NOT NULL)")
            db.execute("BEGIN IMMEDIATE")
            if db.execute("SELECT id FROM settings WHERE id=1").fetchone():
                return
            config = read_config(self.seed_path)
            config["providers"].setdefault("eachlabs", template("eachlabs", config))
            for name, item in config["providers"].items():
                item.setdefault("adapter", name)
                item.setdefault("label", LABELS.get(name, name))
                item.setdefault("keys", {})
            validate_config(config)
            db.execute("INSERT INTO settings VALUES(1,1,?)", (json.dumps(config, ensure_ascii=False),))

    def import_legacy(self):
        """Explicit one-time inventory import; constructing test instances never touches a vault."""
        with closing(self.connect()) as db, db:
            db.execute("BEGIN IMMEDIATE")
            revision, raw = db.execute("SELECT revision,config FROM settings WHERE id=1").fetchone()
            config = json.loads(raw)
            credentials = self.credentials()
            changed = False
            for name, item in config["providers"].items():
                legacy = credentials.get(name)
                if legacy and name != "local" and not item.get("keys"):
                    kid, metadata = self.new_key(credentials, name, "原有凭据 · v1", legacy)
                    item.setdefault("keys", {})[kid] = metadata
                    item["credential_id"] = kid
                    changed = True
            if changed:
                self.saver(credentials)
                db.execute("UPDATE settings SET revision=?,config=? WHERE id=1", (revision+1,json.dumps(config,ensure_ascii=False)))
        return self.snapshot()

    def connect(self):
        return sqlite3.connect(self.path, timeout=5)

    def credentials(self):
        if not self.vault_exists():
            return {}
        return self.loader()  # Never replace an existing vault that cannot be decrypted.

    @staticmethod
    def new_key(credentials, connection, label, credential):
        kid = "key_" + uuid.uuid4().hex
        credentials.setdefault("_managed", {})[kid] = {"connection": connection, "credential": credential}
        secret = credential.get("api_key", "")
        return kid, {"label": label, "masked": "•••• " + secret[-4:] if secret else "服务账户 JSON",
                     "created_at": datetime.now(timezone.utc).isoformat(), "enabled": True}

    def snapshot(self):
        with closing(self.connect()) as db:
            revision, raw = db.execute("SELECT revision,config FROM settings WHERE id=1").fetchone()
        config = json.loads(raw)
        connections = []
        for name, item in config["providers"].items():
            adapter = item.get("adapter", name)
            endpoint = item.get("base_url", ENDPOINTS.get(adapter, ""))
            if adapter == "bailian":
                endpoint = "https://" + BAILIAN_HOSTS[item["region"]] + "/compatible-mode/v1"
            connections.append({"id": name, "label": item.get("label", name), "adapter": adapter,
                                "base_url": endpoint, "region": item.get("region"),
                                "enabled": item.get("enabled", True), "model": item["model"],
                                "credential_id": item.get("credential_id"), "keys": item.get("keys", {}),
                                "models": profiles(item), "is_default": config["default_provider"] == name})
        return {"revision": revision, "connections": connections, "default_provider": config["default_provider"],
                "automatic_fallback": config["automatic_fallback"], "fallback_order": config.get("fallback_order", []),
                "templates": [{"id": adapter, "label": label} for adapter, label in LABELS.items() if adapter != "local"]}

    def mutate(self, payload):
        if not command_validator().is_valid(payload):
            raise ValueError("配置字段或类型无效，请检查表单后重试。")
        if not isinstance(payload, dict) or type(payload.get("revision")) is not int:
            raise ValueError("配置版本无效，请刷新后重试。")
        action = payload.get("action")
        with closing(self.connect()) as db, db:
            db.execute("BEGIN IMMEDIATE")
            revision, raw = db.execute("SELECT revision,config FROM settings WHERE id=1").fetchone()
            if revision != payload["revision"]:
                raise ValueError("配置已在其他页面修改，请刷新后重新操作。")
            config = json.loads(raw)
            connection = payload.get("connection")
            item = config["providers"].get(connection)
            credentials = None
            if action == "add_connection":
                self.fields(payload, {"template", "label", "base_url", "region"})
                adapter = payload.get("template")
                item = template(adapter, read_config(self.seed_path))
                connection = "conn_" + uuid.uuid4().hex
                item["label"] = self.label(payload.get("label"))
                if adapter == "compatible":
                    item["base_url"] = payload.get("base_url", "").strip().rstrip("/")
                if adapter == "bailian":
                    region = payload.get("region", "beijing")
                    if region != item.get("region"):
                        for entry in item["models"].values():
                            entry.pop("price", None)
                    item["region"] = region
                config["providers"][connection] = item
            elif not item:
                raise ValueError("接入方不存在。")
            elif action == "connection":
                self.fields(payload, {"label", "enabled", "default"})
                if "label" in payload:
                    item["label"] = self.label(payload["label"])
                if "enabled" in payload:
                    item["enabled"] = payload["enabled"]
                if payload.get("default") is True:
                    config["default_provider"] = connection
            elif action == "add_key":
                self.fields(payload, {"label", "secret", "replace_key"})
                adapter = item.get("adapter", connection)
                if adapter == "local":
                    raise ValueError("本地模型不需要 Key。")
                secret = payload.get("secret")
                if not isinstance(secret, str) or not 8 <= len(secret.strip()) <= 20000:
                    raise ValueError("请填写完整 API Key 或服务账户 JSON。")
                if adapter == "vertex":
                    try:
                        account = json.loads(secret)
                        if account.get("type") != "service_account" or not account.get("private_key") or not account.get("client_email") or account.get("token_uri") != "https://oauth2.googleapis.com/token":
                            raise ValueError()
                    except (ValueError, AttributeError):
                        raise ValueError("服务账户 JSON 格式不正确。") from None
                    credential = {"service_account": account}
                else:
                    if any(c.isspace() for c in secret.strip()):
                        raise ValueError("API Key 不能含空白字符。")
                    credential = {"api_key": secret.strip()}
                credentials = self.credentials()
                keys = item.setdefault("keys", {})
                if len(keys) >= 100:
                    raise ValueError("该接入方已登记 100 个 Key 版本。")
                previous = payload.get("replace_key")
                if previous:
                    if previous not in keys:
                        raise ValueError("原 Key 不存在，请刷新。")
                    keys[previous]["enabled"] = False
                kid, metadata = self.new_key(credentials, connection, self.label(payload.get("label")), credential)
                keys[kid] = metadata
                item["credential_id"] = kid
            elif action == "key":
                self.fields(payload, {"key_id", "enabled", "active"})
                kid = payload.get("key_id")
                key = item.get("keys", {}).get(kid)
                if not key:
                    raise ValueError("Key 不存在。")
                if "enabled" in payload:
                    if type(payload["enabled"]) is not bool:
                        raise ValueError("Key 状态无效。")
                    key["enabled"] = payload["enabled"]
                if payload.get("active") is True:
                    if not key["enabled"]:
                        raise ValueError("请先启用此 Key。")
                    item["credential_id"] = kid
                if item.get("credential_id") == kid and not key["enabled"]:
                    raise ValueError("请先切换到其他 Key，或用替换操作登记新 Key。")
            elif action == "model":
                self.fields(payload, {"model", "label", "enabled", "default", "max_output_tokens", "reasoning_levels", "reasoning_default", "price"})
                mid = payload.get("model")
                if not isinstance(mid, str):
                    raise ValueError("请填写模型 ID。")
                entry = item.setdefault("models", {}).setdefault(mid, {"parameters": {}})
                if mid != "configure-model" and item["model"] == "configure-model":
                    item["models"].pop("configure-model", None)
                    item["model"] = mid
                if "label" in payload:
                    entry["label"] = self.label(payload["label"])
                if "enabled" in payload:
                    entry["enabled"] = payload["enabled"]
                if payload.get("default") is True:
                    item["model"] = mid
                params = entry.setdefault("parameters", {})
                if "max_output_tokens" in payload:
                    params["max_output_tokens"] = payload["max_output_tokens"]
                if "reasoning_levels" in payload:
                    adapter = item.get("adapter", connection)
                    levels = payload["reasoning_levels"]
                    entry["reasoning_levels"] = levels
                    parameter = REASONING_PARAMETERS.get(adapter)
                    value = payload.get("reasoning_default")
                    if levels:
                        if value not in levels:
                            raise ValueError("默认推理级别必须在可选级别中。")
                        params[parameter] = value.upper() if adapter in {"vertex", "gemini"} else value == "on" if adapter == "bailian" else value
                    elif parameter:
                        params.pop(parameter, None)
                if "price" in payload:
                    validate_price(payload["price"])
                    entry["price"] = payload["price"]
            else:
                raise ValueError("不支持此配置操作。")
            try:
                validate_config(config)
            except (ValueError, ModelError, KeyError, TypeError):
                raise ValueError("配置无效：请检查模型 ID、参数、价格及默认模型；停用默认接入方前请先更换默认接入方。") from None
            # Write immutable encrypted material first. Failed config commits can only leave an unused key.
            if credentials is not None:
                self.saver(credentials)
            db.execute("UPDATE settings SET revision=?,config=? WHERE id=1", (revision + 1, json.dumps(config, ensure_ascii=False)))
        return self.snapshot()

    @staticmethod
    def fields(payload, allowed):
        if set(payload) - allowed - {"revision", "action", "connection"}:
            raise ValueError("请求包含不支持的配置字段。")

    @staticmethod
    def label(value):
        if not isinstance(value, str) or not 1 <= len(value.strip()) <= 80 or any(ord(c) < 32 for c in value):
            raise ValueError("名称须为 1–80 个字符。")
        return value.strip()

    def balance(self, connection):
        """Explicit read, no retries or polling. Account balance is not per-key usage."""
        import httpx
        config = effective_config(self.seed_path, self.path.parent)
        item = config["providers"].get(connection, {})
        if item.get("adapter", connection) != "eachlabs":
            raise ValueError("此接入方没有接入统一余额接口，请以供应商账户账单为准。")
        kid = item.get("credential_id")
        credentials = self.credentials()
        key = credentials.get("_managed", {}).get(kid, {})
        if key.get("connection") != connection:
            raise ValueError("请先登记可用 Key。")
        try:
            with httpx.Client(timeout=15, follow_redirects=False) as client:
                response = client.get("https://api.eachlabs.ai/v1/billing/balance", headers={"Authorization": "Bearer " + key["credential"]["api_key"]})
                response.raise_for_status()
                balance = response.json()["balance_usd"]
                import math
                if type(balance) not in (int, float) or not math.isfinite(balance):
                    raise ValueError()
        except Exception:
            raise ValueError("余额查询失败，请检查 Key、网络或 Eachlabs 账户。未自动重试。") from None
        return {"connection": connection, "balance": balance, "currency": "USD", "checked_at": datetime.now(timezone.utc).isoformat(),
                "notice": "Eachlabs 账户余额，可能延迟更新；多个 Key 可能共享同一余额，不能相加。"}
