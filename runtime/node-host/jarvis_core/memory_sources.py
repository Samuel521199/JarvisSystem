"""Bounded source checks for confirmed fact candidates; no model or new database."""
import hashlib
import json

from .conversations import ConversationError, ConversationStore
from .memory import MemoryError, validate

MAX_SOURCE_CHATS = 32
MAX_SOURCE_BYTES = 8 * 1024 * 1024


def candidate_id(item):
    # Independent of extractor version, edited preview and destination scope.
    body = [item['kind'], item['title'], item['content'], item['next_step']]
    return hashlib.sha256(json.dumps(body, ensure_ascii=False, separators=(',', ':')).encode()).hexdigest()


def source_key(source):
    return hashlib.sha256(json.dumps([source['conversation_id'], source['message_index'],
        source['project_id'], source['candidate_id']], separators=(',', ':')).encode()).hexdigest()


def read_source(core, source):
    validate('candidate_source', source)
    try:
        archive = ConversationStore(core).get(source['conversation_id'])
        document = archive['document']
        row = document['messages'][source['message_index']]
    except (ConversationError, IndexError):
        raise MemoryError('candidate_source_changed', '来源消息已变化或删除，请重新整理。') from None
    if not matches(source, document, row):
        raise MemoryError('candidate_source_changed', '来源消息或范围已变化，请重新整理。')
    return archive


def matches(source, document, row):
    return (document['project_id'] == source['project_id'] and row['role'] == 'user'
        and not any(row.get(flag) for flag in ('personal_control', 'task_control', 'attachments_omitted', 'incomplete'))
        and hashlib.sha256(row['content'].encode()).hexdigest() == source['sha256'])


def annotate(core, rows, origins):
    """Read each source chat once, discard full archives, bound the total work.

    Only the owner's local memory panel gets the original excerpt. Model context
    is assembled separately from the fact body, never this provenance object.
    """
    groups = {}
    for row in rows:
        origin = origins.get(row['id'])
        if not origin:
            row['provenance'] = {'kind': 'owner_explicit', 'state': 'independent', 'source_ref': None}
            continue
        source = json.loads(origin['source_json'])
        validate('candidate_source', source)
        detached = bool(origin['detached'])
        row['source'] = 'owner_reaffirmed' if detached else 'owner_confirmed_candidate'
        row['provenance'] = {'kind': row['source'], 'state': 'independent' if detached else 'unchecked',
                             'source_ref': source, 'excerpt': None}
        if not detached:
            groups.setdefault(source['conversation_id'], []).append(row)
    size = 0
    for index, (chat_id, items) in enumerate(groups.items()):
        if index >= MAX_SOURCE_CHATS or size >= MAX_SOURCE_BYTES:
            continue
        try:
            archive = ConversationStore(core).get(chat_id)
        except ConversationError:
            for row in items: row['provenance']['state'] = 'source_changed_or_missing'
            continue
        document = archive['document']
        size += len(json.dumps(document, ensure_ascii=False).encode())
        if size > MAX_SOURCE_BYTES:
            continue
        for row in items:
            source = row['provenance']['source_ref']
            try: message = document['messages'][source['message_index']]
            except IndexError: message = None
            current = message is not None and matches(source, document, message)
            row['provenance']['state'] = 'current' if current else 'source_changed_or_missing'
            if current: row['provenance']['excerpt'] = message['content'][:800]
    from .assistant_plan_store import annotate_facts
    return annotate_facts(core, rows)


def usable(row):
    return row.get('provenance', {}).get('state', 'independent') in {'independent', 'current'}
