"""Host admission for one explicit document query, never a general tool loop."""
import hashlib
import json
import re

from . import policy
from .conversations import ConversationStore
from .intent import ENGINE
from .mcp_candidates import resolve_scope
from .mcp_client import LIBRARY_ID
from .workspace import identifier

SETTINGS = policy.REPOSITORY_ROOT/'config/mcp/automation.json'
RULE = 'single-documentation-v1'
BLOCKED = re.compile(r"不要|不用|无需|禁止|别|如果|假[如设装]|以后|将来|先不|原文|引述|例句|模拟|忽略|翻译|不查|[\"'`“”‘’《》<>\n\r;；,，]|\b(?:if|unless|never|not|without|hypothetical|quote|translate|pretend|ignore|instead|wait|later)\b", re.I)
LIB = r'(?:Electron|'+LIBRARY_ID+r')'
PATTERNS = [re.compile(r'(?:请帮我|请你|请|帮我|麻烦)?\s*(?:查询|查阅|查找|查)\s*(?P<library>'+LIB+r')\s*(?:的)?(?:官方)?文档(?:中的|里的|关于|的|：|:)?\s*(?P<query>.+)', re.I),
            re.compile(r'(?:please\s+)?(?:look up|check|search)\s+(?P<library>'+LIB+r')\s+documentation\s+(?:for|on|about)\s+(?P<query>.+)', re.I)]


def settings():
    raw = policy.safe_path(SETTINGS, directory=False).read_bytes()
    if len(raw) > 4096:
        raise policy.CoreError('documentation_config_invalid', '自动文档查询设置无效。')
    value = json.loads(raw)
    if (not isinstance(value, dict) or set(value) != {'schema_version', 'enabled', 'routes', 'rule'}
            or value['schema_version'] != 1 or type(value['enabled']) is not bool or value['rule'] != RULE
            or not isinstance(value['routes'], list) or any(r != 'vertex::gemini-3.8-flash' for r in value['routes'])):
        raise policy.CoreError('documentation_config_invalid', '自动文档查询设置无效。')
    return value


def select_documentation(message, decision):
    """Require whole-message grammar AND a grounded, single semantic request.

    Mixed, quoted, uncertain and unsupported-language requests remain drafts.
    Electron's fixed ID was verified in the existing real Context7 evaluation;
    all other IDs must be written explicitly by the user.
    """
    if not isinstance(message, str) or len(message.encode('utf-8')) > 2048 or BLOCKED.search(message):
        return None
    source = message.strip().rstrip('.。!?！？').strip()
    if any(ord(c) < 32 for c in source) or re.search(r'[。!?！？]|https?://|[A-Za-z]:[\\/]|\.\./|\\|(?:password|api[_-]?key|token)\s*[:=]', source, re.I):
        return None
    match = next((p.fullmatch(source) for p in PATTERNS if p.fullmatch(source)), None)
    if not match or not isinstance(decision, dict) or decision.get('state') != 'recognized' or decision.get('engine') != ENGINE:
        return None
    items = decision.get('intents', [])
    if not isinstance(items, list) or len(items) != 1 or not isinstance(items[0], dict):
        return None
    item = items[0]
    if (item.get('kind') != 'action' or item.get('disposition') != 'requested'
            or item.get('capability') != 'mcp.documentation' or item.get('missing_fields') != []):
        return None
    args = item.get('arguments', {})
    library, query = match['library'], match['query'].strip()
    quote = item.get('quote', '')
    if (not isinstance(args, dict) or set(args) != {'library', 'query'} or args['library'] != library or not isinstance(args['query'], str)
            or len(query) < 2 or not args['query'].strip() or args['query'].strip().rstrip('.。') not in query
            or not isinstance(quote, str) or not quote or message.count(quote) != 1
            or args['library'] not in quote or args['query'] not in quote):
        return None
    return {'library': '/electron/electron' if library.lower() == 'electron' else library,
            'prompt': query, 'source_library': library, 'source_query': args['query']}


class DocumentationAdmission:
    def __init__(self, core, tasks):
        self.core, self.tasks = core, tasks

    def capture(self, conversation_id):
        # Missing/deleted archives and unavailable projects fail closed.
        ConversationStore(self.core).get(conversation_id)
        return resolve_scope(self.core, {'conversation_id': conversation_id})

    def admit(self, row, payload, result):
        if result.get('status') != 'SUCCEEDED' or result.get('output_incomplete'):
            return result
        decision = result.get('intent_decision', {})
        choice = select_documentation(payload.get('message', ''), decision)
        if choice is None:
            return result
        outcome = {'status': 'not_submitted', 'capability': 'mcp.documentation.v1', 'automatic': False}
        result = {**result, 'work_admission': outcome}
        try:
            config = settings()
            if not config['enabled'] or decision.get('provider', '')+'::'+decision.get('model', '') not in config['routes']:
                outcome.update(reason_code='route_not_enabled', reason='该模型尚未开放自动文档查询，可使用文档草稿。')
                return result
            if not row.get('durable') or payload.get('attachments') or payload.get('context_note'):
                outcome.update(reason_code='explicit_review_required', reason='临时会话、附件或附加要求请使用文档草稿核对。')
                return result
            identifier(row['request_id']); identifier(row['conversation_id'])
            expected_id = hashlib.sha256((ENGINE+':'+row['request_id']).encode()).hexdigest()[:32]
            if decision.get('turn_id') != row['request_id'] or decision.get('decision_id') != expected_id:
                raise policy.CoreError('documentation_binding_invalid', '识别来源不匹配，未自动提交。')
            scope = self.capture(row['conversation_id'])
            if scope != row.get('work_scope'):
                raise policy.CoreError('mcp_scope_changed', '会话项目已变化，请重新核对文档查询。')
            if row['event'].is_set():
                raise policy.CoreError('cancelled', '回复已停止，未自动提交文档查询。')
            check = self.tasks.mcp.assess_candidate({'library': choice['source_library'], 'query': choice['source_query']}, text=payload['message'], **scope)
            if not check['eligible'] or not check['auto_eligible']:
                outcome.update(reason_code=check.get('reason_code') if not check['eligible'] else 'manual_policy',
                               reason=check.get('reason') if not check['eligible'] else '当前规则仅允许明确手动使用，请核对草稿后发送。')
                return result
            origin = {'kind': 'dialogue', 'turn_id': row['request_id'], 'decision_id': expected_id,
                      'text_digest': policy.digest(payload['message'].encode()), 'rule': RULE}
            key = 'web-'+hashlib.sha256(('documentation:'+row['conversation_id']+':'+row['request_id']).encode()).hexdigest()[:32]
            accepted = self.tasks.queue.enqueue_mcp(request_id=key,
                payload={'library': choice['library'], 'prompt': choice['prompt'], **scope}, automatic=origin)
            outcome.update(status='submitted', automatic=True, **accepted,
                           reason='已按当前规则受理一项只读文档查询，结果以任务回执为准。')
            decision = {**decision, 'mode': 'bounded_documentation', 'automatic_execution': True,
                        'intents': [{**decision['intents'][0], 'execution': 'submitted', 'task_id': accepted['task_id']}]}
            result['intent_decision'] = decision
        except Exception as exc:
            outcome.update(reason_code=getattr(exc, 'code', 'admission_unavailable'),
                           reason=str(exc) if isinstance(exc, policy.CoreError) else '文档受理结果未确认，请查看本会话任务；没有自动重试。')
        return result
