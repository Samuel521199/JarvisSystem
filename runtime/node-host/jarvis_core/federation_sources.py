"""Read selected facts without replicating databases, raw chats or local paths."""
from contextlib import closing
import json
import sqlite3

from . import federation_protocol as p
from .memory import MemoryStore
from .memory_policy import eligible
from .memory_sources import matches
from .policy import safe_path


def projects(core):
    from .workspace import WorkspaceService
    path=safe_path(core.data_dir/'workspace.db',must_exist=False)
    if not path.exists():return []
    with closing(sqlite3.connect(path.as_uri()+'?mode=ro',uri=True,timeout=2)) as db:
        db.row_factory=sqlite3.Row
        if db.execute('PRAGMA user_version').fetchone()[0]!=1:p.fail('项目库版本不支持。')
        rows=[WorkspaceService._public_project(r) for r in db.execute('SELECT * FROM projects')]
    return [{'id':row['id'],'name':row['name']} for row in rows if row['available']]


def current_origin(core, origin, cache):
    if not origin or origin['detached']:return True
    ref=json.loads(origin['source_json'])
    chat=ref['conversation_id']
    if chat not in cache:
        if len(cache)>=32:return False
        path=safe_path(core.data_dir/'conversations.db',must_exist=False)
        if not path.exists():return False
        with closing(sqlite3.connect(path.as_uri()+'?mode=ro',uri=True,timeout=2)) as db:
            row=db.execute('SELECT document FROM conversations WHERE id=? AND deleted=0',(chat,)).fetchone()
        if row is None or len(row[0].encode('utf-8'))>256*1024:cache[chat]=None
        else:cache[chat]=json.loads(row[0])
    doc=cache[chat]
    try:return doc is not None and matches(ref,doc,doc['messages'][ref['message_index']])
    except (KeyError,IndexError,TypeError):return False


def facts(core, project_id=None):
    """Read-only, exact domain. Unlike the normal view, no global/project union."""
    memory = MemoryStore(core)
    if project_id is not None and project_id not in {r['id'] for r in projects(core)}:
        p.fail('目标项目未登记或当前不可用。', 'federation_scope')
    path = safe_path(memory.path, must_exist=False)
    if not path.exists():
        return []
    with closing(sqlite3.connect(path.as_uri()+'?mode=ro', uri=True, timeout=2)) as db:
        db.row_factory = sqlite3.Row
        if db.execute('PRAGMA user_version').fetchone()[0] != 3:
            p.fail('请先在记忆面板升级并检查旧记忆库；共享入口不自动迁移。')
        db.execute('BEGIN')
        rows = db.execute('SELECT * FROM facts WHERE deleted=0 AND project_id IS ? ORDER BY id',
                          (project_id,)).fetchall()
        origins = memory._origins(db)
        cache={}
        result = [memory._public(row) for row in rows if current_origin(core,origins.get(row['id']),cache)]
    return [row for row in result if eligible(
        row['document'], 'work_assist' if project_id else 'personal_chat')]


def sources(service, space, kind, project_id=None):
    if kind == 'card':
        if project_id is not None:
            p.fail()
        return [{'id': item, 'title': heads[0]['body']['title'],
                 'expected': p.heads_token(heads)}
                for item, heads in space['items'].items()
                if len(heads) == 1 and not heads[0]['body']['deleted']]
    if kind != 'memory':
        p.fail()
    return [{'id': row['id'], 'title': row['document']['title'],
             'expected': p.digest({'revision': row['revision'], 'document': row['document']})}
            for row in facts(service.core, project_id)]


def read(service, space, selection, cache=None):
    """Current source only. Deletion, scope or provenance changes withdraw it."""
    from .federation_access import destination
    kind, item, project = (selection[k] for k in ('kind', 'source', 'source_project'))
    cache={} if cache is None else cache
    if 'config' not in cache:cache['config']=service.access.config()
    config = cache['config']
    if kind == 'card':
        heads = space['items'].get(item, [])
        if len(heads) != 1 or heads[0]['body']['deleted']:
            return None
        body = heads[0]['body']
        policy = space.get('model_access', {})
        # A generic card is received in the personal domain; a source project-only
        # model grant cannot silently become a personal grant on another device.
        providers = policy.get('providers', {}) if item in policy.get('cards', []) and policy.get('project_id') is None else {}
        providers = {provider: expected for provider, expected in providers.items()
                     if provider in config['providers'] and destination(config,provider)==expected}
        return dict(title=body['title'], text=body['text'], source_revision=p.heads_token(heads),
                    model_targets=providers, expires_at=None, classification='shared_card')
    if project not in cache:cache[project]=facts(service.core,project)
    row = next((r for r in cache[project] if r['id'] == item), None)
    if row is None:
        return None
    doc = row['document']; meta = doc.get('classification', {})
    targets = {provider: destination(config, provider)
               for provider in ['local', *doc['providers']] if provider in config['providers']}
    return dict(title=doc['title'], text=doc['content'],
                source_revision=p.digest({'revision': row['revision'], 'document': doc}),
                model_targets=targets, expires_at=meta.get('expires_at'),
                classification=meta.get('kind', 'unclassified'))
