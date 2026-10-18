"""Deterministic, request-local context assembly. No storage, tools or model calls.

The host instruction and the current user request/note are required. Older
history is selected in whole user-led turns; no generated summary is trusted.
Byte limits bound text payload, not model tokens or image inference cost.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json

from jarvis_models.attachments import (
    MAX_ATTACHMENTS, MAX_IMAGES_BYTES, image_budget, text_size, validate_message,
)

MAX_HISTORY_MESSAGES = 20
MAX_HISTORY_BYTES = 32768
MAX_NOTE_BYTES = 8192


class ContextBudgetError(ValueError):
    """Required context cannot fit; the caller must not dispatch a model call."""


def validate_note(value):
    if value is None:
        return ""
    if not isinstance(value, str) or len(value.encode("utf-8")) > MAX_NOTE_BYTES or "\0" in value:
        raise ValueError("会话要求须为不超过 8 KiB 的文本。")
    return value.strip()


def validate_history(history):
    if history is None:
        history = []
    if not isinstance(history, list) or len(history) > 1000:
        raise ValueError("历史必须是有界的消息列表。")
    result, total = [], 0
    for item in history:
        item = validate_message(item)
        total += text_size(item)
        if total > 262144:
            raise ValueError("传入历史过大，请清空或缩短会话。")
        result.append(item)
    return result


def _select(messages, max_bytes, max_image_bytes, max_images):
    # An initial orphan assistant message has no originating request. Exclude it.
    turns = []
    for index, item in enumerate(messages):
        if item["role"] == "user":
            turns.append([])
        if turns:
            turns[-1].append((index, item))
    selected, size, images_size, image_count = [], 0, 0, 0
    limit = max(0, min(max_bytes, MAX_HISTORY_BYTES))
    for turn in reversed(turns):
        rows = [item for _, item in turn]
        turn_size = sum(text_size(item) for item in rows)
        turn_images_size, turn_image_count = image_budget(rows)
        if (len(selected) + len(turn) > MAX_HISTORY_MESSAGES or size + turn_size > limit
                or images_size + turn_images_size > max_image_bytes
                or image_count + turn_image_count > max_images):
            break  # Keep a contiguous recent suffix, never silently bridge a gap.
        selected = turn + selected
        size += turn_size
        images_size += turn_images_size
        image_count += turn_image_count
    indexes = [index for index, _ in selected]
    return [item for _, item in selected], {
        "input_messages": len(messages), "kept_messages": len(selected),
        "dropped_messages": len(messages) - len(selected), "truncated": len(selected) != len(messages),
        "kept_bytes": size, "max_messages": MAX_HISTORY_MESSAGES, "max_bytes": limit,
        "kept_indexes": indexes,
    }


def bounded_history(history, *, max_bytes=MAX_HISTORY_BYTES,
                    max_image_bytes=MAX_IMAGES_BYTES, max_images=MAX_ATTACHMENTS):
    return _select(validate_history(history), max_bytes, max_image_bytes, max_images)


@dataclass(frozen=True)
class ContextView:
    message: str
    history: list
    history_info: dict


def assemble_context(*, message, history, attachments, instructions, context_note,
                     provider, model, max_bytes, memory_text=''):
    note = validate_note(context_note)
    prompt = ("[本会话要求：用户填写；如与本轮消息冲突，以本轮修正为准]\n" + note
              + "\n[本轮消息]\n" + message) if note else message
    if memory_text:
        prompt = memory_text + '[当前用户输入]\n' + prompt
    current = {"role": "user", "content": prompt, "attachments": attachments}
    required = text_size(current) + len(instructions.encode("utf-8"))
    if required > max_bytes:
        raise ContextBudgetError("本轮消息、附件与固定会话要求超出所选模型的输入预算；未发送，也未丢弃要求。请缩短内容或切换模型。")
    current_image_bytes, current_images = image_budget([current])
    rows = validate_history(history)
    selected, info = _select(rows, max_bytes - required,
        MAX_IMAGES_BYTES - current_image_bytes, MAX_ATTACHMENTS - current_images)
    # Fingerprint is local to this request/view; it is not a stored session ID.
    revision = hashlib.sha256(json.dumps({"provider": provider, "model": model,
        "instructions": instructions, "message": prompt, "attachments": attachments,
        "history": selected, "max_bytes": max_bytes}, ensure_ascii=False,
        sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()
    report = {"schema_version": "1.0.0", "strategy": "recent-whole-turns-v1",
        "revision": revision, "provider": provider, "model": model,
        "note_applied": bool(note), "note_bytes": len(note.encode("utf-8")),
        "required_bytes": required, "total_text_bytes": required + info["kept_bytes"],
        "max_text_bytes": max_bytes, "token_count": None, "summarized": False,
        "kept_indexes": info["kept_indexes"]}
    return ContextView(prompt, selected, {**info, "context": report})
