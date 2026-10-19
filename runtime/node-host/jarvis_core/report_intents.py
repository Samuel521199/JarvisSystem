"""Ground one bounded report operation in the current input, without a model call."""
import re

from .intent import ENGINE

RULE = 'mixed-sample-report-v1'
TASK = r'task_[a-f0-9]{32}'
PATH = r'(?:\.|[\w-]+(?:/[\w.-]+)*)'
LEAD = r'(?:(?:请帮我|帮我|请你|请|顺便|也|然后|再)\s*)*'
CREATE = [
    re.compile(LEAD + r'(?:生成|导出|保存|整理|统计)(?:一份|一下)?\s*(?:样例目录|样例)(?:统计)?报告(?:\s*目录[：:]\s*(?P<path>' + PATH + r'))?', re.I),
    re.compile(LEAD + r'把(?:样例目录|样例)(?:统计)?报告(?:生成|导出|保存)(?:一下)?', re.I),
    re.compile(r'(?:(?:please|also|and)\s+)*(?:generate|export|save)\s+(?:a\s+|the\s+)?sample\s+(?:directory\s+)?report(?:\s+for\s+(?P<path>' + PATH + r'))?', re.I),
]
CANCEL = re.compile(LEAD + r'(?:只)?(?:取消|停止)(?:报告|任务)?\s*(?P<target>' + TASK + r')|(?:please\s+)?cancel\s+(?:report\s+)?(?P<english>' + TASK + r')', re.I)
REVISE = re.compile(LEAD + r'(?:把)?(?:报告|任务)?\s*(?P<target>' + TASK + r')\s*(?:的)?目录(?:改为|改成)[：:]?\s*(?P<path>' + PATH + r')|(?:please\s+)?change\s+(?P<english>' + TASK + r')\s+directory\s+to\s+(?P<english_path>' + PATH + r')', re.I)
# A semantic candidate alone cannot remove a negation, quote or condition.
BLOCKED = re.compile(r'不要|不用|无需|禁止|别做|别生成|别导出|别取消|别停|先不|如果|假[如设装]|以后|将来|原文|引述|例句|模拟|翻译|等我|暂不|暂停|["\'`“”‘’《》<>\n\r]|\b(?:if|unless|never|not|without|hypothetical|quote|translate|pretend|later|wait|stop)\b', re.I)
TRIM = ' \t，,。.!！?？;；'
GAP = re.compile(r'(?:(?:顺便|也|然后|再|请帮我|请你|帮我|请)|(?:also|and|please)\b|[\s，,。.!！?？;；])*', re.I)


def operation(text):
    """Accept complete clauses; paths stay inside the preconfigured sample root."""
    if '?' in text or '？' in text: return None
    # Try a literal final dot first: it may be the requested root directory.
    for source in dict.fromkeys((text.strip(TRIM.replace('.', '')), text.strip(TRIM))):
        for pattern in CREATE:
            match = pattern.fullmatch(source)
            if match:
                return {'operation': 'create', 'relative_path': match.groupdict().get('path') or '.'}
        match = CANCEL.fullmatch(source)
        if match:
            return {'operation': 'cancel', 'target': match['target'] or match['english']}
        match = REVISE.fullmatch(source)
        if match:
            return {'operation': 'revise', 'target': match['target'] or match['english'],
                    'relative_path': match['path'] or match['english_path']}
    return None


def select_report(message, decision):
    if (not isinstance(message, str) or len(message.encode('utf-8')) > 4096 or BLOCKED.search(message)
            or not isinstance(decision, dict) or decision.get('state') != 'recognized' or decision.get('engine') != ENGINE):
        return None
    items = decision.get('intents', [])
    if not isinstance(items, list) or not 1 <= len(items) <= 8:
        return None
    candidates, spans = [], []
    for index, item in enumerate(items):
        if not isinstance(item, dict): return None
        quote = item.get('quote')
        if not isinstance(quote, str) or not quote or message.count(quote) != 1: return None
        start = message.index(quote); end = start + len(quote)
        if item.get('source_span') != {'start': start, 'end': end}: return None
        spans.append((start, end))
        if item.get('kind') in {'action', 'control'}:
            choice = operation(quote)
            if re.match(r'\s*[?？]', message[end:]): return None
            if (not choice or item.get('disposition') != 'requested' or item.get('missing_fields') != []
                    or item.get('capability') is not None or item.get('arguments') != {}):
                return None
            if choice['operation'] == 'create' and item['kind'] != 'action': return None
            candidates.append({**choice, 'index': index, 'quote': quote})
        elif item.get('kind') not in {'chat', 'emotion', 'question'} or item.get('disposition') not in {'requested', 'discussed'}:
            return None
    # Do not let a cropped quote hide a condition or second requested action.
    cursor = 0
    for start, end in sorted(spans):
        if start < cursor or not GAP.fullmatch(message[cursor:start]): return None
        cursor = end
    if message[cursor:].strip(TRIM) or len(candidates) != 1: return None
    return candidates[0]


def explicit_target(message):
    """Capture only an exact current-input task identifier, never a recent-task guess."""
    if not isinstance(message, str) or BLOCKED.search(message): return None
    matches = re.findall(TASK, message)
    return matches[0] if len(matches) == 1 else None
