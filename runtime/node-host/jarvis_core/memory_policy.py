"""Small, deterministic fact-use policy. No model, service, index or inference.

Classification is owner-supplied metadata, not a truth/identity verification.
Only owner-facing chat and work views are implemented. Never treat these as an
external-recipient, NPC or raw conversation redaction policy.
"""
from datetime import datetime, timezone

SUBJECTS = {
    'personal_fact': 'owner', 'preference': 'owner', 'episode': 'owner',
    'temporary_state': 'owner', 'project_fact': 'project', 'work_result': 'project',
    'shared_experience': 'owner', 'third_party': 'other', 'fiction': 'character',
}
PURPOSES = ('personal_chat', 'work_assist')


def purpose(request):
    request = request or {}
    return request.get('purpose') or ('work_assist' if request.get('project_id') or request.get('project_ids') else 'personal_chat')


def expiry(value):
    # Contract uses a canonical UTC representation; no machine-local time parsing.
    return datetime.strptime(value, '%Y-%m-%dT%H:%M:%SZ').replace(tzinfo=timezone.utc)


def check(document):
    """Schema validates shape; cross-field meaning is checked before writing."""
    meta = document.get('classification')
    if meta is None:
        return
    if meta['subject'] != SUBJECTS[meta['kind']]:
        raise ValueError('记忆类型与主体不一致。')
    if meta['subject'] == 'project' and not document['project_id']:
        raise ValueError('项目资料和工作结果必须绑定项目。')
    if meta['subject'] in ('other', 'character') and not meta['subject_label'].strip():
        raise ValueError('请填写他人或虚构角色的名称，避免当作主人信息。')
    if meta['subject'] in ('owner', 'project') and meta['subject_label']:
        raise ValueError('主人与项目主体由当前范围确定，不填写他人名称。')
    if meta['kind'] == 'fiction' and meta['uses']:
        raise ValueError('虚构角色资料目前只保存，不进入现实聊天记忆。')
    if meta['kind'] == 'temporary_state' and not meta['expires_at']:
        raise ValueError('临时状态必须填写到期时间。')
    if meta['expires_at']:
        expiry(meta['expires_at'])
    if '\0' in meta['subject_label']:
        raise ValueError('主体名称不能包含空字符。')


def eligible(document, use, *, now=None):
    if use not in PURPOSES:
        return False
    meta = document.get('classification')
    # Preserve old explicit scope/provider semantics. Never infer that old global
    # facts are consent for external recipients or a future purpose.
    if meta is None:
        return True
    try:
        check(document)
        return (meta['kind'] != 'fiction' and use in meta['uses'] and
                (not meta['expires_at'] or expiry(meta['expires_at']) > (now or datetime.now(timezone.utc))))
    except (ValueError, KeyError, TypeError):
        return False


def describe(document):
    meta = document.get('classification')
    if meta is None:
        return {'state': 'legacy', 'kind': 'unclassified'}
    try:
        check(document)
        state = 'expired' if meta['expires_at'] and expiry(meta['expires_at']) <= datetime.now(timezone.utc) else 'active'
        if not meta['uses']: state = 'stored_only'
        return {'state': state, **meta}
    except (ValueError, KeyError, TypeError):
        return {'state': 'invalid', 'kind': 'unclassified'}
