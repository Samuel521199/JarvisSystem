"""Bounded, caller-supplied attachments. No path reads, uploads or retained content."""
from __future__ import annotations

import base64
import binascii
import re

MAX_ATTACHMENTS = 8
MAX_IMAGE_BYTES = 4 * 1024 * 1024
MAX_IMAGES_BYTES = 8 * 1024 * 1024
MAX_TEXT_BYTES = 48 * 1024
MAX_CHAT_BODY = 12 * 1024 * 1024


def image_capable(adapter, model):
    """Conservative family allowlist; an upstream account can still reject a model."""
    model = model.lower().split('/')[-1]
    if adapter in {'vertex', 'gemini'}:
        return model.startswith('gemini-')
    if adapter == 'anthropic':
        return model.startswith('claude-')
    if adapter in {'openai', 'eachlabs', 'compatible', 'xai'}:
        return model.startswith(('gpt-4o', 'gpt-4.1', 'gpt-5', 'gpt-6', 'o3', 'o4', 'claude-', 'gemini-', 'grok-4')) or 'vision' in model
    if adapter == 'bailian':
        return model.startswith(('qwen-vl', 'qwen3-vl', 'qwen3.5', 'qwen3.6'))
    return False


def validate_attachments(value):
    if value is None:
        return []
    if not isinstance(value, list) or len(value) > MAX_ATTACHMENTS:
        raise ValueError('附件每条最多 8 个。')
    result = []
    for item in value:
        if not isinstance(item, dict):
            raise ValueError('附件格式无效。')
        name, kind = item.get('name'), item.get('kind')
        if not isinstance(name, str) or not 1 <= len(name) <= 180 or re.search(r'[\x00-\x1f\x7f/\\]', name):
            raise ValueError('附件名称无效。')
        if kind == 'text' and set(item) == {'name', 'kind', 'text'}:
            content = item['text']
            if not isinstance(content, str) or len(content.encode('utf-8')) > MAX_TEXT_BYTES or re.search(r'[\x00-\x08\x0b\x0c\x0e-\x1f]', content):
                raise ValueError('文本附件应为可读文本，单个不超过 48 KiB。')
        elif kind == 'image' and set(item) == {'name', 'kind', 'media_type', 'data'}:
            mime, data = item['media_type'], item['data']
            if mime not in {'image/png', 'image/jpeg', 'image/webp'} or not isinstance(data, str) or len(data) > 4 * ((MAX_IMAGE_BYTES + 2) // 3):
                raise ValueError('图片须为 PNG、JPEG 或 WebP，单张不超过 4 MiB。')
            try:
                raw = base64.b64decode(data, validate=True)
            except (ValueError, binascii.Error):
                raise ValueError('图片编码无效。') from None
            matches = {'image/png': raw.startswith(b'\x89PNG\r\n\x1a\n'),
                       'image/jpeg': raw.startswith(b'\xff\xd8\xff'),
                       'image/webp': raw.startswith(b'RIFF') and raw[8:12] == b'WEBP'}
            if not 12 <= len(raw) <= MAX_IMAGE_BYTES or not matches[mime] or base64.b64encode(raw).decode('ascii') != data:
                raise ValueError('图片内容与格式不符。')
        else:
            raise ValueError('暂不支持此附件格式。')
        result.append(dict(item))
    if image_budget([{'attachments': result}])[0] > MAX_IMAGES_BYTES:
        raise ValueError('图片合计不能超过 8 MiB。')
    return result


def validate_message(item):
    if (not isinstance(item, dict) or set(item) - {'role', 'content', 'attachments'}
            or item.get('role') not in {'user', 'assistant'} or not isinstance(item.get('content'), str)):
        raise ValueError('历史消息格式无效。')
    attachments = validate_attachments(item.get('attachments'))
    if attachments and item['role'] != 'user':
        raise ValueError('只有用户消息可以包含附件。')
    return {'role': item['role'], 'content': item['content'], **({'attachments': attachments} if attachments else {})}


def message_text(item):
    text = item['content']
    for attachment in item.get('attachments', []):
        if attachment['kind'] == 'text':
            text += '\n\n[附件资料：' + attachment['name'] + ']\n' + attachment['text'] + '\n[附件结束]'
        else:
            text += '\n[图片附件：' + attachment['name'] + ']'
    return text


def text_size(item):
    return len(message_text(item).encode('utf-8'))


def image_budget(messages):
    images = [a for m in messages for a in m.get('attachments', []) if a['kind'] == 'image']
    return sum(len(a['data']) // 4 * 3 - len(a['data']) + len(a['data'].rstrip('=')) for a in images), len(images)


def wire_messages(messages, adapter):
    """Translate validated attachment content into the native provider schema."""
    result = []
    for item in messages:
        text = message_text(item)
        images = [a for a in item.get('attachments', []) if a['kind'] == 'image']
        if adapter in {'vertex', 'gemini'}:
            parts = [{'text': text}] + [{'inlineData': {'mimeType': a['media_type'], 'data': a['data']}} for a in images]
            result.append({'role': 'model' if item['role'] == 'assistant' else 'user', 'parts': parts})
            continue
        content = text
        if images:
            if adapter == 'anthropic':
                content = [{'type': 'text', 'text': text}] + [{'type': 'image', 'source': {'type': 'base64', 'media_type': a['media_type'], 'data': a['data']}} for a in images]
            else:
                content = [{'type': 'input_text' if adapter == 'openai' else 'text', 'text': text}]
                for a in images:
                    url = 'data:' + a['media_type'] + ';base64,' + a['data']
                    content.append({'type': 'input_image', 'image_url': url} if adapter == 'openai' else {'type': 'image_url', 'image_url': {'url': url}})
        result.append({'role': item['role'], 'content': content})
    return result
