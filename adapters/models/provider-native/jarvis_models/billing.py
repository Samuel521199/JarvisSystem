"""Request-time, reproducible text-token estimates. Never claims invoice settlement."""
from __future__ import annotations

from contextlib import closing
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
import json
import math
from pathlib import Path
import sqlite3

LOCAL_ZONE = timezone(timedelta(hours=8))
RATES = {"input", "output", "cache_read", "cache_write", "fee_percent"}


def validate_price(price):
    if price is None:
        return
    if not isinstance(price, dict) or set(price) - RATES - {"currency", "source", "checked_at", "max_input_tokens", "valid_until"}:
        raise ValueError("invalid_price")
    if price.get("currency") not in {"USD", "CNY"}:
        raise ValueError("invalid_currency")
    for key in RATES:
        value = price.get(key)
        if value is not None and (type(value) not in (int, float) or not math.isfinite(value) or not 0 <= value <= 1000000):
            raise ValueError("invalid_rate")
    for key in ("source", "checked_at"):
        if key in price and (not isinstance(price[key], str) or len(price[key]) > 500):
            raise ValueError("invalid_price_source")
    if "max_input_tokens" in price and (type(price["max_input_tokens"]) is not int or not 1 <= price["max_input_tokens"] <= 10000000):
        raise ValueError("invalid_price_tier")
    if price.get("valid_until"):
        date.fromisoformat(price["valid_until"])


def clean_usage(raw):
    """Flatten only documented numeric fields; no arbitrary upstream strings."""
    if not isinstance(raw, dict):
        return {}
    names = {"promptTokenCount", "candidatesTokenCount", "totalTokenCount", "cachedContentTokenCount",
             "thoughtsTokenCount", "prompt_tokens", "completion_tokens", "total_tokens", "input_tokens",
             "output_tokens", "num_sources_used", "cost_in_usd_ticks", "cache_read_input_tokens",
             "cache_creation_input_tokens"}
    good = lambda value: type(value) in (int, float) and math.isfinite(value) and 0 <= value <= 1e15
    result = {k: v for k, v in raw.items() if k in names and good(v)}
    for field in ("prompt_tokens_details", "input_tokens_details", "completion_tokens_details", "output_tokens_details"):
        child = raw.get(field)
        if isinstance(child, dict):
            for key in ("cached_tokens", "cache_write_tokens", "reasoning_tokens"):
                if good(child.get(key)):
                    result[key] = child[key]
    details = raw.get("cost_details")
    if isinstance(details, dict) and good(details.get("upstream_inference_cost")):
        result["upstream_inference_cost"] = details["upstream_inference_cost"]
    return result


def tokens(adapter, usage):
    read = usage.get("cached_tokens", usage.get("cachedContentTokenCount", usage.get("cache_read_input_tokens", 0)))
    write = usage.get("cache_write_tokens", usage.get("cache_creation_input_tokens", 0))
    inp = usage.get("input_tokens", usage.get("prompt_tokens", usage.get("promptTokenCount")))
    out = usage.get("output_tokens", usage.get("completion_tokens", usage.get("candidatesTokenCount")))
    if inp is None or out is None:
        return None
    # Anthropic input_tokens excludes the two cache buckets. Other adapters include them.
    total_in = inp + read + write if adapter == "anthropic" else inp
    if adapter in {"vertex", "gemini"}:
        out += usage.get("thoughtsTokenCount", 0)
    if read + write > total_in:
        return None
    return {"input": total_in, "output": out, "cache_read": read, "cache_write": write,
            "total": total_in + out, "reasoning": usage.get("reasoning_tokens", usage.get("thoughtsTokenCount", 0))}


def estimate(adapter, usage, price, *, dispatched=True):
    normalized = tokens(adapter, usage)
    result = {"basis": "unknown", "amount": None, "currency": (price or {}).get("currency", "USD"),
              "tokens": normalized, "price": price, "reason": "missing_usage_or_price"}
    if adapter == "local" or not dispatched:
        return {**result, "basis": "no_api_charge", "amount": 0, "reason": "local" if adapter == "local" else "not_dispatched"}
    if not price or normalized is None:
        return result
    if price.get("valid_until") and datetime.now(LOCAL_ZONE).date() > date.fromisoformat(price["valid_until"]):
        return {**result, "reason": "price_expired"}
    if normalized["input"] > price.get("max_input_tokens", 10000000):
        return {**result, "reason": "outside_price_tier"}
    counts = {"input": normalized["input"] - normalized["cache_read"] - normalized["cache_write"],
              "output": normalized["output"], "cache_read": normalized["cache_read"], "cache_write": normalized["cache_write"]}
    if any(count and price.get(key) is None for key, count in counts.items()):
        return {**result, "reason": "missing_token_rate"}
    subtotal = sum(Decimal(str(count)) * Decimal(str(price.get(key) or 0)) for key, count in counts.items()) / Decimal(1000000)
    amount = subtotal * (1 + Decimal(str(price.get("fee_percent") or 0)) / 100)
    return {**result, "basis": "estimated", "amount": float(amount), "reason": "token_rates"}


def report(data_dir, *, start=None, end=None, provider=None, model=None, key_id=None, offset=0):
    """All aggregates share one filter and one SQLite read snapshot; pages are bounded."""
    today = datetime.now(LOCAL_ZONE).date()
    end_day = date.fromisoformat(end) if end else today
    start_day = date.fromisoformat(start) if start else end_day - timedelta(days=6)
    if not 0 <= (end_day - start_day).days <= 365 or type(offset) is not int or offset < 0:
        raise ValueError("invalid_report_range")
    begin = datetime.combine(start_day, datetime.min.time(), LOCAL_ZONE).astimezone(timezone.utc).isoformat()
    until = datetime.combine(end_day + timedelta(days=1), datetime.min.time(), LOCAL_ZONE).astimezone(timezone.utc).isoformat()
    def blank():
        return {"requests": 0, "succeeded": 0, "tokens": 0, "usage_missing": 0, "unpriced": 0,
                "uncertain": 0, "estimated": {"USD": 0, "CNY": 0}}
    total, daily, providers, models, keys, entries = blank(), {}, {}, {}, {}, []
    for i in range((end_day - start_day).days + 1):
        daily[(start_day + timedelta(days=i)).isoformat()] = blank()
    path = Path(data_dir) / "model-probes.db"
    if path.exists():
        with closing(sqlite3.connect(path.absolute().as_uri() + "?mode=ro", uri=True, timeout=5)) as db:
            cursor = db.execute("SELECT id,provider,model,created_at,status,metadata FROM probes WHERE created_at>=? AND created_at<? ORDER BY created_at DESC,rowid DESC", (begin, until))
            for ident, route, mid, timestamp, status, serialized in cursor:
                metadata = json.loads(serialized)
                identity = metadata.get("billing_identity", {})
                kid = identity.get("key_id") or "legacy"
                if (provider and route != provider) or (model and mid != model) or (key_id and kid != key_id):
                    continue
                bill = metadata.get("billing") or {"basis": "unknown", "amount": None, "tokens": tokens(identity.get("adapter", route), metadata.get("usage", {})), "reason": "historical_no_price_snapshot"}
                stamp = datetime.fromisoformat(timestamp).astimezone(LOCAL_ZONE)
                if stamp.date().isoformat() not in daily:
                    continue
                row = {"id": ident, "provider": route, "model": mid, "created_at": stamp.isoformat(), "status": status,
                       "connection_label": identity.get("label", route), "key_id": kid, "key_label": identity.get("key_label", "历史未归属"),
                       "billing": bill, "elapsed_seconds": metadata.get("elapsed_seconds"), "error_category": metadata.get("error_category")}
                p = providers.setdefault(route, {**blank(), "id": route, "label": row["connection_label"]})
                m = models.setdefault((route, mid), {**blank(), "provider": route, "model": mid})
                k = keys.setdefault((route, kid), {**blank(), "provider": route, "key_id": kid, "label": row["key_label"]})
                for target in (total, daily[stamp.date().isoformat()], p, m, k):
                    target["requests"] += 1
                    target["succeeded"] += status == "SUCCEEDED"
                    target["uncertain"] += status in {"UNKNOWN", "RESERVED", "DISPATCHING"}
                    target["usage_missing"] += bill.get("tokens") is None
                    target["tokens"] += (bill.get("tokens") or {}).get("total", 0)
                    target["unpriced"] += bill.get("amount") is None
                    if bill.get("basis") == "estimated" and bill.get("currency") in target["estimated"]:
                        currency = bill["currency"]
                        target["estimated"][currency] = float(Decimal(str(target["estimated"][currency])) + Decimal(str(bill["amount"])))
                if offset <= total["requests"] - 1 < offset + 50:
                    entries.append(row)
    return {"timezone": "Asia/Shanghai", "start": str(start_day), "end": str(end_day), "total": total,
            "daily": [{"date": day, **values} for day, values in daily.items()], "providers": list(providers.values()),
            "models": list(models.values()), "keys": list(keys.values()), "entries": entries, "offset": offset,
            "has_more": total["requests"] > offset + 50,
            "scope": "仅此 Jarvis 实例记录的调用；金额为请求时单价估算，不是供应商已结算账单。历史无价格快照的调用不补算。"}
