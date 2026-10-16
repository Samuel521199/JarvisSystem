"""Versioned, data-driven text model profiles; credentials and URLs stay in adapters."""
from __future__ import annotations

from copy import deepcopy
import re

MODEL_ID = re.compile(r"[a-zA-Z0-9._:-]{1,128}")
PARAMETERS = {
    "openai": {"reasoning_effort", "max_output_tokens"},
    "vertex": {"thinking_level", "max_output_tokens"},
    "bailian": {"enable_thinking", "max_output_tokens"},
    "xai": {"reasoning_effort", "max_output_tokens"},
    "local": {"max_output_tokens"},
}
REASONING_PARAMETERS = {"openai": "reasoning_effort", "xai": "reasoning_effort",
                        "vertex": "thinking_level", "bailian": "enable_thinking"}
REASONING_VALUES = {
    "openai": {"none", "low", "medium", "high", "xhigh", "max"},
    "xai": {"low", "medium", "high", "xhigh"},
    "vertex": {"minimal", "low", "medium", "high"},
    "bailian": {"off", "on"}, "local": set(),
}


def reasoning_value(provider, parameters):
    value = parameters.get(REASONING_PARAMETERS.get(provider))
    if provider == "bailian" and type(value) is bool:
        return "on" if value else "off"
    return value.lower() if isinstance(value, str) else None


def profiles(settings):
    # Old one-model configuration files remain usable without migration.
    return settings.get("models", {settings["model"]: {"label": settings["model"], "tier": "configured"}})


def validate_catalog(config):
    for provider, settings in config["providers"].items():
        entries = profiles(settings)
        if not isinstance(entries, dict) or not 1 <= len(entries) <= 64 or settings["model"] not in entries:
            raise ValueError("invalid_model_catalog")
        for model, entry in entries.items():
            if not isinstance(model, str) or not MODEL_ID.fullmatch(model) or not isinstance(entry, dict):
                raise ValueError("invalid_model_profile")
            if set(entry) - {"label", "tier", "parameters", "reasoning_levels"}:
                raise ValueError("unsupported_model_profile_field")
            for field in ("label", "tier"):
                if field in entry and (not isinstance(entry[field], str) or not 1 <= len(entry[field]) <= 128):
                    raise ValueError("invalid_model_label")
            params = entry.get("parameters", {})
            if not isinstance(params, dict) or set(params) - PARAMETERS[provider]:
                raise ValueError("unsupported_model_parameter")
            if "max_output_tokens" in params:
                ceiling = 256 if provider == "local" else 32768
                if type(params["max_output_tokens"]) is not int or not 1 <= params["max_output_tokens"] <= ceiling:
                    raise ValueError("invalid_model_output_limit")
            if "reasoning_effort" in params:
                choices = {"low", "medium", "high", "xhigh"} if provider == "xai" else {"none", "low", "medium", "high", "xhigh", "max"}
                if params["reasoning_effort"] not in choices:
                    raise ValueError("invalid_reasoning_effort")
            if "thinking_level" in params and params["thinking_level"] not in {"MINIMAL", "LOW", "MEDIUM", "HIGH"}:
                raise ValueError("invalid_thinking_level")
            if "enable_thinking" in params and type(params["enable_thinking"]) is not bool:
                raise ValueError("invalid_thinking_switch")
            levels = entry.get("reasoning_levels", [])
            if (not isinstance(levels, list) or len(levels) > 6
                    or any(not isinstance(level, str) or level not in REASONING_VALUES[provider] for level in levels)
                    or len(set(levels)) != len(levels)
                    or (levels and reasoning_value(provider, params) not in levels)):
                raise ValueError("invalid_model_reasoning_levels")


def resolve_settings(config, provider, model=None):
    settings = config["providers"][provider]
    chosen = settings["model"] if model is None else model
    if not isinstance(chosen, str) or chosen not in profiles(settings):
        raise ValueError("model_not_registered_for_provider")
    entry = profiles(settings)[chosen]
    return {**{k: v for k, v in settings.items() if k != "models"},
            **entry.get("parameters", {}), "model": chosen}


def select_model(config, provider, model, reasoning=None):
    """Make a request-local choice. Never mutate shared configuration on disk."""
    resolve_settings(config, provider, model)
    selected = deepcopy(config)
    selected["providers"][provider]["model"] = model
    if reasoning is not None:
        entry = profiles(selected["providers"][provider])[model]
        if not isinstance(reasoning, str) or reasoning not in entry.get("reasoning_levels", []):
            raise ValueError("unsupported_model_reasoning_level")
        value = reasoning.upper() if provider == "vertex" else reasoning == "on" if provider == "bailian" else reasoning
        entry.setdefault("parameters", {})[REASONING_PARAMETERS[provider]] = value
    return selected


def public_models(config):
    result = []
    for provider, settings in config["providers"].items():
        for model, entry in profiles(settings).items():
            result.append({"provider": provider, "model": model, "label": entry.get("label", model),
                           "tier": entry.get("tier", "configured"), "is_provider_default": model == settings["model"],
                           "parameters": dict(entry.get("parameters", {})),
                           "reasoning_levels": list(entry.get("reasoning_levels", [])),
                           "reasoning_default": reasoning_value(provider, entry.get("parameters", {}))})
    return result
