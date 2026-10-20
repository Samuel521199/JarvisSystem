"""Revocable project grants for finite growth cycles on the existing ledger."""
import copy
import json
import re
import time
import sqlite3
from contextlib import closing
from pathlib import Path
from .. import policy
from .catalog import fail, runtime_binding
from .growth_domains import DOMAINS

TERMINAL = {'COMPLETE', 'PAUSED', 'CANCELLED', 'INTERRUPTED'}


def read(db, project):
    row = db.execute('SELECT document FROM growth_policies WHERE project_id=?', (project,)).fetchone()
    return json.loads(row[0]) if row else {
        'revision': 0, 'enabled': False, 'domains': list(DOMAINS),
        'model': '', 'expires_at': 0, 'maximum_cycles': 3,
        'window_seconds': 30, 'maximum_seconds': 15, 'maximum_cycle_seconds': 1800,
        'maximum_model_calls': 8, 'minimum_calls_saved': 1,
        'maximum_memory_bytes': 192 * 1024 * 1024,
    }


def configure(tools, cid, payload):
    project = tools.scope(cid)['project_id']
    fields = {'revision', 'enabled', 'domains', 'model', 'expires_at', 'maximum_cycles',
              'window_seconds', 'maximum_seconds', 'maximum_cycle_seconds',
              'maximum_model_calls', 'minimum_calls_saved', 'maximum_memory_bytes'}
    if not isinstance(payload, dict) or set(payload) != fields | {'reviewed', 'review_note'}:
        fail('成长策略字段不完整。')
    if payload['reviewed'] is not True or not isinstance(payload['review_note'], str) or not 5 <= len(payload['review_note']) <= 500:
        fail('请核对任务范围、观察与调用预算。')
    limits = {'revision': (0, 1000000), 'maximum_cycles': (1, 10), 'window_seconds': (30, 3600),
              'maximum_seconds': (1, 30), 'maximum_cycle_seconds': (300, 86400),
              'maximum_model_calls': (8, 8), 'minimum_calls_saved': (1, 4),
              'maximum_memory_bytes': (16*1024*1024, 192*1024*1024)}
    if any(type(payload[k]) is not int or not lo <= payload[k] <= hi for k, (lo, hi) in limits.items()):
        fail('策略预算超出支持范围。')
    if type(payload['enabled']) is not bool or not isinstance(payload['domains'], list) or not payload['domains'] or any(not isinstance(x, str) or x not in DOMAINS for x in payload['domains']):
        fail('请选择明确的任务域。')
    if type(payload['expires_at']) not in (int, float) or not time.time() < payload['expires_at'] <= time.time()+31*86400:
        fail('授权有效期须在未来 31 天内。')
    if payload['window_seconds']*2+120 >= payload['maximum_cycle_seconds']: fail('总时限不足以覆盖两段观察窗口。')
    tools.manager.provider.configuration(payload['model'])
    value = {k: copy.deepcopy(payload[k]) for k in fields}
    value.update(revision=value['revision']+1, review_note=payload['review_note'], runtime_binding=runtime_binding())
    with tools.manager.lock, tools.core.effect_guard(), tools.store.connection() as db:
        db.execute('BEGIN IMMEDIATE')
        if read(db, project)['revision'] != payload['revision']: fail('策略已变化，请刷新。', 'evolution_conflict')
        if not db.execute('SELECT 1 FROM growth_policies WHERE project_id=?', (project,)).fetchone() and db.execute('SELECT count(*) FROM growth_policies').fetchone()[0] >= 32:
            fail('成长策略达到 32 个项目上限。')
        db.execute('INSERT INTO growth_policies VALUES(?,?) ON CONFLICT(project_id) DO UPDATE SET document=excluded.document',
                   (project, policy.canonical_json(value)))
    return value


def check_core(core, request):
    """Read-only bridge from K3 checkpoints; never opens another execution lane."""
    path = policy.safe_path(Path(core.data_dir)/'evolution/evolution.db', directory=False)
    with closing(sqlite3.connect(path.as_uri()+'?mode=ro', uri=True, timeout=3)) as db:
        authorize(db, request)


def authorize(db, request):
    """Called again *inside* selection/lifecycle transactions to close revoke races."""
    ref = request.get('growth_authorization')
    if ref is None: return
    if not isinstance(ref, dict) or set(ref) != {'cycle_id', 'revision'} or not re.fullmatch('[a-f0-9]{32}', ref['cycle_id']):
        fail('成长授权绑定无效。', 'growth_authorization_changed')
    row = db.execute('SELECT document FROM growth_cycles WHERE id=?', (ref['cycle_id'],)).fetchone()
    if row is None: fail('成长记录不存在。', 'growth_authorization_changed')
    cycle = json.loads(row[0]); current = read(db, cycle['scope']['project_id'])
    if (cycle['status'] in TERMINAL | {'STOPPING'} or cycle['policy']['revision'] != ref['revision']
            or current != cycle['policy'] or not current['enabled'] or current['expires_at'] <= time.time()
            or time.time()-cycle['started_epoch'] > current['maximum_cycle_seconds']
            or current['runtime_binding'] != runtime_binding()
            or cycle['domain']['id'] not in current['domains']
            or request.get('scope', cycle['scope']) != cycle['scope']):
        fail('授权已撤销、过期、超预算或执行版本变化；没有继续自动准入。', 'growth_authorization_changed')
