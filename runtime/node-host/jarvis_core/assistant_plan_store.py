"""Bounded personal plans. Task effects remain exclusively in the task ledger."""
from contextlib import contextmanager
import json
from pathlib import Path
import sqlite3

from . import policy

NAME = 'assistant-plans.db'
MAX_BYTES = 24 * 1024 * 1024


def path_for(core):
    return policy.safe_path(Path(core.data_dir) / NAME, must_exist=False)


@contextmanager
def connection(data_dir, *, write=False):
    path = policy.safe_path(Path(data_dir) / NAME, must_exist=False)
    for suffix in ('', '-wal', '-shm', '-journal'):
        item = policy.safe_path(str(path) + suffix, must_exist=False)
        if item.exists() and (item.stat().st_size > MAX_BYTES or item.stat().st_nlink != 1):
            raise policy.CoreError('plan_storage', '个人计划存储达到上限或路径异常。')
    if not write and not path.exists():
        yield None
        return
    db = sqlite3.connect(path if write else path.absolute().as_uri() + '?mode=ro',
                         uri=not write, timeout=2)
    db.row_factory = sqlite3.Row
    try:
        if write:
            db.execute('BEGIN IMMEDIATE')
            if db.execute('PRAGMA user_version').fetchone()[0] not in (0,1):
                raise policy.CoreError('plan_storage', '个人计划数据版本不兼容，未修改。')
            db.execute('CREATE TABLE IF NOT EXISTS plans(id TEXT PRIMARY KEY, document TEXT NOT NULL)')
            db.execute('CREATE TABLE IF NOT EXISTS plan_runtime(singleton INTEGER PRIMARY KEY CHECK(singleton=1), owner TEXT NOT NULL)')
            db.execute('CREATE TABLE IF NOT EXISTS plan_budget('
                       'plan_id TEXT PRIMARY KEY, max_calls INTEGER NOT NULL, usd REAL NOT NULL, cny REAL NOT NULL)')
            db.execute('CREATE TABLE IF NOT EXISTS plan_calls('
                       'request_id TEXT PRIMARY KEY, plan_id TEXT NOT NULL, currency TEXT NOT NULL, '
                       'reserved REAL NOT NULL, document TEXT NOT NULL)')
            db.execute('CREATE TABLE IF NOT EXISTS plan_fact_sources('
                       'fact_id TEXT PRIMARY KEY, plan_id TEXT NOT NULL, candidate_revision INTEGER NOT NULL)')
            db.execute('PRAGMA user_version=1')
        elif db.execute('PRAGMA user_version').fetchone()[0] != 1:
            raise policy.CoreError('plan_storage', '个人计划数据版本不兼容。')
        yield db
        if write: db.commit()
    finally:
        db.close()


def read(db, ident):
    row = db.execute('SELECT document FROM plans WHERE id=?', (ident,)).fetchone() if db else None
    if row is None: raise policy.CoreError('not_found', '未找到个人计划。')
    return json.loads(row['document'])


def save(db, row):
    raw = policy.canonical_json(row)
    if len(raw.encode()) > 128 * 1024:
        raise policy.CoreError('plan_capacity', '单个计划内容超过 128 KiB，未覆盖原记录。')
    db.execute('INSERT INTO plans VALUES(?,?) ON CONFLICT(id) DO UPDATE SET document=excluded.document',
               (row['id'], raw))


def annotate_facts(core, rows):
    """A withdrawn/corrected result cannot leak through old memory or history views."""
    try:
        with connection(core.data_dir) as db:
            if db is None: return rows
            sources = {r['fact_id']: dict(r) for r in db.execute('SELECT * FROM plan_fact_sources')}
            cache = {}
            for row in rows:
                source = sources.get(row['id'])
                if not source: continue
                ident = source['plan_id']
                if ident not in cache:
                    plan = read(db, ident)
                    from .conversations import ConversationStore
                    try:
                        scope = ConversationStore(core).get(plan['conversation_id'])['document']['project_id']
                        valid_scope = scope == plan['project_id']
                        if plan.get('continuity_source'):
                            from .continuity import ContinuityStore
                            store=ContinuityStore(core);ref=plan['continuity_source']
                            note=next((n for n in store.list(scope)['records'] if n['id']==ref['id']),None)
                            valid_scope=valid_scope and bool(note and note['revision']==ref['revision']
                                and note['document']['state']=='open' and store.source_current(note['document'],{}))
                        for evidence in (plan.get('candidate') or {}).get('evidence',[]):
                            record=core.ledger.record(task_id=evidence['task_id'])
                            if record['action']['status']!='CONFIRMED':valid_scope=False;break
                            core._verify_artifact(record['artifact'])
                    except (ValueError, policy.CoreError): valid_scope = False
                    cache[ident] = plan, valid_scope
                plan, valid_scope = cache[ident]
                candidate = plan.get('candidate') or {}
                valid = (valid_scope and candidate.get('state') == 'accepted'
                         and candidate.get('revision') == source['candidate_revision'])
                row['source'] = 'owner_confirmed_plan_result'
                row['provenance'] = {'kind': row['source'], 'state': 'current' if valid else 'source_changed_or_missing',
                                     'source_ref': {'plan_id': ident, 'revision': source['candidate_revision']}}
    except (OSError, ValueError, sqlite3.Error, policy.CoreError):
        # If provenance cannot be checked, do not guess which facts are safe.
        for row in rows:
            row['provenance'] = {'kind': 'plan_source_unavailable', 'state': 'unchecked'}
    return rows
