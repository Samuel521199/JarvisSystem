"""Report control receipts and replacement checks in the existing ledger transaction."""
import json

from . import policy


def revision(record):
    action = record['action']
    return policy.digest(policy.canonical_json({key: action[key] for key in
        ('action_id', 'arguments_digest', 'owner_epoch', 'enforcement_policy_version')}).encode())


def bound(ledger, db, task_id, conversation_id, expected):
    row = db.execute('SELECT action_id FROM actions WHERE task_id=?', (task_id,)).fetchone()
    record = ledger._record(db, row['action_id']) if row else None
    if (not record or record['action']['capability_id'] != 'sample.report.v1'
            or record['action']['arguments'].get('conversation_id') != conversation_id):
        raise policy.CoreError('report_target_not_found', '当前会话没有此样例报告；请使用本会话任务中的完整编号。')
    if not expected or revision(record) != expected:
        raise policy.CoreError('report_target_changed', '目标任务版本无法确认，未修改或取消任务；请核对后重新提出。')
    return record


def register_origin(ledger, db, record, origin, replacement):
    db.execute('CREATE TABLE IF NOT EXISTS report_admissions(task_id TEXT PRIMARY KEY REFERENCES tasks(task_id),document TEXT NOT NULL)')
    value = policy.canonical_json({'origin': origin, 'replacement': replacement})
    old = db.execute('SELECT document FROM report_admissions WHERE task_id=?', (record['task']['task_id'],)).fetchone()
    if old:
        if old['document'] != value:
            raise policy.CoreError('idempotency_conflict', '同一报告编号不能更换来源或替换对象。')
        return False
    if replacement:
        previous = bound(ledger, db, replacement['task_id'], record['action']['arguments']['conversation_id'], replacement['revision'])
        if previous['action']['status'] != 'PREPARED' or previous['cancel_requested']:
            raise policy.CoreError('report_already_started', '报告已经开始或结束，未改写原任务；可取消运行中的报告后明确创建新报告。')
        ledger._cancel_record(db, previous)
        previous['action']['error'] = {'code': 'replaced', 'message': 'Replaced by '+record['task']['task_id']}
        ledger._save(db, previous)
    db.execute('INSERT INTO report_admissions VALUES(?,?)', (record['task']['task_id'], value))
    return True


def cancel_report(core, *, request_id, conversation_id, task_id, expected, origin):
    ledger = core.ledger
    args = policy.canonical_json({'conversation_id': conversation_id, 'task_id': task_id, 'revision': expected, 'origin': origin})
    with ledger.transaction() as db:
        ledger._control(db)
        db.execute('CREATE TABLE IF NOT EXISTS report_controls(request_id TEXT PRIMARY KEY,arguments TEXT NOT NULL,result TEXT NOT NULL)')
        old = db.execute('SELECT * FROM report_controls WHERE request_id=?', (request_id,)).fetchone()
        if old:
            if old['arguments'] != args: raise policy.CoreError('idempotency_conflict', '控制请求编号已用于其他对象。')
            return json.loads(old['result'])
        record = bound(ledger, db, task_id, conversation_id, expected)
        active = record['action']['status'] in {'PREPARED', 'DISPATCHING'}
        if active: ledger._cancel_record(db, record)
        result = {'task_id': task_id, 'request_id': request_id, 'task_status': record['task']['status'],
                  'status': 'controlled', 'reason': '已请求取消这一项报告，最终状态以任务记录为准。' if active else '这项报告已经结束，保留已有结果；没有撤销产物或取消其他任务。'}
        db.execute('INSERT INTO report_controls VALUES(?,?,?)', (request_id, args, policy.canonical_json(result)))
        return result
