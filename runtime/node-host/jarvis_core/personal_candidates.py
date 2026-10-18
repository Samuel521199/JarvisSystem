"""Bounded local suggestions; only explicit confirmation writes existing stores.

No extraction model, background scan, candidate database or task scheduler.
The source is one current, archived owner message, never an assistant answer.
"""
import hashlib
import json
import re
import uuid

from .conversations import ConversationStore, ConversationError
from .continuity import ContinuityStore, validate_source
from .memory import MemoryStore, MemoryError, validate
from .memory_sources import candidate_id

ENGINE = 'personal-candidates-v1'
REJECT = re.compile(r'假如|假设|例如|比如|示例|角色扮演|NPC|他说|她说|不要记|别记|不保存|忘记|不必记|```|["“”<>]|sk-[A-Za-z0-9]|PRIVATE KEY|密码|密钥|验证码', re.I)
TRANSIENT = re.compile(r'这一次|这次|本次|今天|今晚|此刻|暂时|这份报告')
QUESTION = re.compile(r'[?？]|(?:吗|么|呢)[!！。]?$')


def identity_candidates_v1(text):
    """Frozen v1 identity grammar, also used by semantic source revocation.

    Tighten current eligibility in extract(), not here: changing an old ID could
    let a model paraphrase resurrect a corrected or forgotten source candidate.
    """
    if not isinstance(text, str) or not 1 <= len(text) <= 800 or REJECT.search(text): return []
    result = []
    for part in re.split(r'[。；;\n]', text):
        part = part.strip()
        if not part or len(part) > 240: continue
        match = re.fullmatch(r'(?:请记住[，,：:]?|记住[，,：:]?)?(我(?:平时|通常|一直|比较|更)?(?:喜欢|不喜欢|习惯|偏好|希望你).+|以后(?:请)?叫我.+)', part)
        if match:
            content = match[1]
            title = '称呼偏好' if content.startswith('以后') else '交流偏好' if '希望你' in content else '个人偏好'
            result.append({'kind': 'fact', 'title': title, 'content': content, 'next_step': ''})
        else:
            match = re.fullmatch(r'((?:(?:我们)?(?:下次|明天|之后|以后)(?:我们)?(?:继续|再).+)|(?:我(?:还有|还没|尚未).+))', part)
            if match:
                result.append({'kind': 'continuity', 'title': part[:60], 'content': '主人提出的未结事项：'+part, 'next_step': part})
        if len(result) == 3: break
    return result


def extract(text):
    items = identity_candidates_v1(text)
    # Conservative eligibility only; mixed stable/one-off clauses go to review
    # through the semantic path instead of dropping an exception by guesswork.
    return [item for item in items if item['kind'] != 'fact' or
            not (TRANSIENT.search(item['content']) or QUESTION.search(item['content']))]


class PersonalCandidates:
    def __init__(self, core):
        self.core = core
        self.archives = ConversationStore(core)

    def source(self, source, project_id):
        validate_source(source)
        if project_id is not None: validate('id', project_id)
        try:
            archive = self.archives.get(source['conversation_id'])['document']
            row = archive['messages'][source['message_index']]
        except (ConversationError, IndexError):
            raise MemoryError('candidate_source_missing', '来源消息已删除或尚未保存，请先核对会话。') from None
        if (archive['project_id'] != project_id or row['role'] != 'user' or row.get('personal_control')
                or row.get('task_control') or row.get('attachments_omitted') or row.get('incomplete')):
            raise MemoryError('candidate_source_invalid', '候选只整理当前范围内已保存的本人文字；临时会话、控制消息与附件不参与。')
        text = row['content']
        return text, hashlib.sha256(text.encode()).hexdigest()

    def suggest(self, payload):
        if not isinstance(payload, dict) or set(payload) != {'source', 'project_id'}:
            raise MemoryError('invalid_candidate', '候选查询字段无效。')
        text, digest = self.source(payload['source'], payload['project_id'])
        return {'engine': ENGINE, **payload, 'source_digest': digest, 'source_text': text[:800],
                'candidates': [{**item, 'candidate_id': candidate_id(item)} for item in extract(text)], 'model_used': False, 'committed': False}

    def confirm(self, payload):
        if not isinstance(payload, dict) or set(payload) != {'source', 'project_id', 'source_digest', 'candidate', 'scope'}:
            raise MemoryError('invalid_candidate', '候选确认字段无效。')
        text, digest = self.source(payload['source'], payload['project_id'])
        if digest != payload['source_digest'] or not extract(text):
            raise MemoryError('candidate_source_changed', '来源已变化或不适用于本机候选规则，请重新整理。')
        item = payload['candidate']
        if not isinstance(item, dict) or not {'kind', 'title', 'content', 'next_step'} <= set(item) or set(item)-{'kind', 'title', 'content', 'next_step', 'candidate_id'} or not isinstance(item['kind'], str) or item['kind'] not in {'fact', 'continuity'}:
            raise MemoryError('invalid_candidate', '候选类型或字段无效。')
        if item['kind'] not in {r['kind'] for r in extract(text)}:
            raise MemoryError('invalid_candidate', '候选类型与来源不一致。')
        originals = [r for r in extract(text) if r['kind'] == item['kind']]
        if 'candidate_id' in item:
            originals = [r for r in originals if candidate_id(r) == item['candidate_id']]
        elif len(originals) > 1:
            originals = [r for r in originals if r == item]
        if len({candidate_id(r) for r in originals}) != 1:
            raise MemoryError('invalid_candidate', '无法确定原始候选，请刷新页面后重新整理。')
        original_id = candidate_id(originals[0])
        for key, maximum in (('title', 60), ('content', 1024), ('next_step', 512)):
            value = item[key]
            if not isinstance(value, str) or len(value) > maximum or '\0' in value or (key != 'next_step' and not value.strip()):
                raise MemoryError('invalid_candidate', '请填写有效标题和内容，并遵守长度限制。')
        if not isinstance(payload['scope'], str) or payload['scope'] not in {'current', 'global'}:
            raise MemoryError('invalid_candidate', '记忆范围无效。')
        if item['kind'] == 'continuity' and (payload['scope'] != 'current' or not item['next_step'].strip()):
            raise MemoryError('invalid_candidate', '未结事项必须留在来源会话范围，并填写下一步。')
        if item['kind'] == 'fact' and item['next_step']:
            raise MemoryError('invalid_candidate', '事实记忆不包含执行下一步。')
        scope = None if payload['scope'] == 'global' else payload['project_id']
        MemoryStore(self.core)._project(scope)
        # Stable across reload/lost responses: replay cannot resurrect a forgotten item.
        # Keep v1 exact retry IDs; source identity separately fences edited retries.
        legacy = {**payload, 'candidate': {k:v for k,v in item.items() if k != 'candidate_id'}}
        key = uuid.uuid5(uuid.NAMESPACE_URL, ENGINE+json.dumps(legacy, ensure_ascii=False, sort_keys=True)).hex
        if item['kind'] == 'fact':
            archive = self.archives.get(payload['source']['conversation_id'])
            origin = {**payload['source'], 'project_id':payload['project_id'], 'sha256':digest,
                      'candidate_id':original_id, 'archive_revision':archive['revision']}
            receipt = MemoryStore(self.core).command('remember', item['title'].strip(), item['content'].strip(), project_id=scope, request_id=key, candidate_source=origin)
        else:
            receipt = ContinuityStore(self.core).change('save', target=item['title'].strip(), progress=item['content'].strip(),
                next_step=item['next_step'].strip(), project_id=scope, source=payload['source'], message=text,
                candidate_source=True, request_id=key)
        return {'receipt': receipt, 'text': '此确认已处理；请在记忆面板核对当前记录。' if receipt['replayed'] else
                ('已保存事实记忆。' if item['kind'] == 'fact' else '已保存未结事项，可在接续中继续话题。')+' 默认仅本地使用，没有启动任务或提醒。'}
