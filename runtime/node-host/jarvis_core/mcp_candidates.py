"""Local validation of model-proposed document drafts. Never dispatches tools."""
import re

from . import policy
from .conversations import ConversationStore
from .workspace import identifier, WorkspaceService


def resolve_scope(core, args):
    """Saved conversation membership wins over caller-supplied project context."""
    context = {key: args[key] for key in ('conversation_id', 'project_id') if key in args}
    for value in context.values():
        identifier(value)
    if context.get('conversation_id'):
        store = ConversationStore(core)
        with store.connection() as db:
            row = db.execute("SELECT deleted,json_extract(document,'$.project_id') AS project_id FROM conversations WHERE id=?",
                             (context['conversation_id'],)).fetchone()
        if row:
            if row['deleted']:
                raise policy.CoreError('conversation_deleted', '该会话已删除，请在当前会话重新准备文档任务。')
            project = row['project_id']
            if 'project_id' in context and context['project_id'] != project:
                raise policy.CoreError('mcp_scope_changed', '会话的项目归属已变化，请刷新后重新准备文档任务。')
            if project:
                context['project_id'] = project
    if context.get('project_id'):
        workspace = WorkspaceService(core)
        with workspace.connection() as db:
            workspace._project(db, context['project_id'])
    return context


def assess_candidate(service, candidate, *, text, conversation_id=None, project_id=None):
    """Ground parameters in this message, then check the current local policy.

    Eligibility permits a reviewable draft only. Intent semantics belong to the
    common intent router; a model response is never execution authorization.
    """
    result = {'kind': 'mcp.documentation', 'eligible': False, 'auto_eligible': False,
              'automatic_execution': False, 'next_action': 'none', 'policy': None}
    try:
        if (not isinstance(candidate, dict) or set(candidate) != {'library', 'query'}
                or not isinstance(text, str) or not text.strip() or len(text.encode('utf-8')) > 16384):
            raise policy.CoreError('invalid_mcp_candidate', '文档候选字段无效；没有准备任务。')
        args = service.validate({'library': candidate['library'], 'prompt': candidate['query']})
        if args['prompt'] not in text or not re.search(r'(?<![A-Za-z0-9_./-])' + re.escape(args['library']) + r'(?![A-Za-z0-9_./-])', text):
            raise policy.CoreError('mcp_candidate_not_grounded', '库名和查询必须取自本条消息，请明确填写文档查询。')
        context = {key: value for key, value in [('conversation_id', conversation_id), ('project_id', project_id)] if value is not None}
        context = resolve_scope(service.core, context)
        item = next(row for row in service.manager.snapshot(context)['entries'] if row['id'] == 'context7')
        result['policy'] = item['policy']
        selected = service.selection({**args, **context})
        return {**result, 'eligible': True, 'auto_eligible': item['policy']['mode'] == 'auto',
                'reason_code': 'review_required', 'reason': '已核对库名、查询来源和选用规则；请检查文档草稿后发送。',
                'next_action': 'review_draft', 'library': args['library'], 'query': args['prompt'],
                'context': context, 'connection': selected,
                'data_scope': '仅发送库名与所示查询；不发送聊天历史、记忆、项目文件或附件。'}
    except policy.CoreError as exc:
        return {**result, 'reason_code': exc.code, 'reason': str(exc)}
