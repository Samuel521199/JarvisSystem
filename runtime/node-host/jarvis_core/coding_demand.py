"""Conversation improvement proposals backed by the existing coding task ledger.

No scheduler or model runs here. Admission links proposal and task in the same
SQLite transaction; execution and recovery remain owned by the shared queue.
"""
import json
import uuid

from . import policy
from .conversation_tasks import conversation_id
from .conversations import ConversationStore, ConversationError
from .project_files import ProjectFiles
from .evolution.store import now


def conflict(message):
    raise policy.CoreError('coding_demand_conflict', message)


def archive(core, ident):
    conversation_id(ident)
    try:
        doc = ConversationStore(core).get(ident)['document']
    except ConversationError:
        raise policy.CoreError('growth_archive_required', '请先保存普通项目会话，再建立编码改进单。') from None
    if not doc['project_id']:
        raise policy.CoreError('growth_project_required', '编码改进单需要当前会话关联一个项目。')
    return doc


def read(db, ident):
    row = db.execute('SELECT document FROM coding_demands WHERE id=?', (ident,)).fetchone()
    if row is None:
        raise policy.CoreError('not_found', '未找到编码改进单。')
    return json.loads(row['document'])


def write(db, job):
    job['updated_at'] = now()
    db.execute('UPDATE coding_demands SET document=? WHERE id=?', (policy.canonical_json(job), job['id']))


def validate_binding(core, args, *, task_id=None):
    """Also called at admission/execution, so bypassing the UI grants nothing."""
    ref = args.get('coding_demand')
    if ref is None:
        return
    if not isinstance(ref, dict) or set(ref) != {'id', 'digest'}:
        conflict('编码改进单绑定无效。')
    conversation_id(ref['id'])
    with core.ledger.connection() as db:
        # Ordinary skills must not require this optional table to exist.
        if not db.execute("SELECT 1 FROM sqlite_master WHERE name='coding_demands' AND type='table'").fetchone():
            conflict('编码改进单尚未登记。')
        job = read(db, ref['id'])
    frozen = job['frozen']
    if (ref['digest'] != job['proposal']['binding'] or
            policy.digest(policy.canonical_json(frozen).encode()) != ref['digest'] or
            {k: v for k, v in args.items() if k != 'coding_demand'} != frozen['arguments']):
        conflict('任务与冻结的需求、文件范围或验收条件不一致。')
    if task_id is not None and job.get('task_id') != task_id:
        conflict('任务不属于此编码改进单。')
    doc = archive(core, args['conversation_id'])
    if doc['project_id'] != args['project_id']:
        conflict('会话所属项目已改变，请重新分析。')
    from .skill_tasks import SkillTaskService
    if SkillTaskService.binding() != frozen['runtime_binding']:
        conflict('编码实现已升级，请按当前版本重新分析。')
    from .coding_workflow import composition
    if composition(SkillTaskService(core), args)[0] != frozen['composition']:
        conflict('冻结后的组合技能规则已改变，请重新分析。')
    files = ProjectFiles(core)
    if str(files.root(args['project_id'])) != frozen['project_root']:
        conflict('项目根目录已变化，请重新分析。')
    for row in frozen['sources']:
        from .coding_files import snapshot
        if snapshot(files, args['project_id'], row['path'], allow_missing=row['digest'] is None)['digest'] != row['digest']:
            conflict('改进单建立后的源文件已变化，请重新分析，未使用新内容替换旧基线。')


def register(db, args, record, request_id):
    """Runs inside Ledger.prepare, including idempotent retries."""
    ref = args.get('coding_demand')
    if ref is None:
        return
    job = read(db, ref['id'])
    if request_id != 'web-' + job['id'] or ref['digest'] != job['proposal']['binding']:
        conflict('编码任务请求编号与改进单不一致。')
    task_id = record['task']['task_id']
    if job.get('task_id') == task_id:
        return
    if job['status'] != 'PROPOSED' or job.get('task_id'):
        conflict('此改进单已取消或已绑定其他任务，不能再次启动。')
    job.update(task_id=task_id, status='QUEUED')
    job['events'].append({'at': now(), 'phase': 'CODING_ADMITTED', 'task_id': task_id})
    write(db, job)


class CodingDemands:
    def __init__(self, core, tasks):
        self.core, self.tasks = core, tasks
        self.service = tasks.tasks.skills
        with core.ledger.connection() as db:
            if db.execute("SELECT 1 FROM sqlite_master WHERE name='coding_demands' AND type='table'").fetchone():
                return
        with core.ledger.transaction() as db:
            db.execute('''CREATE TABLE IF NOT EXISTS coding_demands(
                id TEXT PRIMARY KEY, conversation_id TEXT NOT NULL,
                request_id TEXT NOT NULL, document TEXT NOT NULL,
                UNIQUE(conversation_id, request_id))''')

    def stored(self, ident, job_id):
        doc = archive(self.core, ident); conversation_id(job_id)
        with self.core.ledger.connection() as db:
            job = read(db, job_id)
        origin = job['request']['origin']
        if origin['conversation_id'] != ident or origin['project_id'] != doc['project_id']:
            raise policy.CoreError('not_found', '未找到本会话范围内的编码改进单。')
        return job

    def lookup(self, ident, request_id):
        archive(self.core, ident); conversation_id(request_id)
        with self.core.ledger.connection() as db:
            row = db.execute('SELECT id FROM coding_demands WHERE conversation_id=? AND request_id=?', (ident, request_id)).fetchone()
        if row is None:
            raise policy.CoreError('not_found', '未找到编码改进请求，没有自动重发。')
        return self.bound(ident, row['id'])

    def propose(self, ident, payload, *, previous_job=None, expected_source_digest=None):
        doc = archive(self.core, ident)
        if not isinstance(payload, dict) or set(payload) != {'request_id', 'prompt', 'coding'}:
            conflict('编码改进单需要请求编号、目标及编码验收配置。')
        conversation_id(payload['request_id'])
        spec = payload['coding']
        required = {'paths', 'cases', 'heldout_cases', 'model', 'coding_provider', 'build_recipe'}
        if not isinstance(spec, dict) or not required <= set(spec) or set(spec)-required-{'entrypoint','new_paths'}:
            conflict('请选择文件、编码提供者、构建方式，填写公开及独立验收案例。')
        original = {'payload': payload, 'previous_job': previous_job}
        with self.core.ledger.connection() as db:
            row = db.execute('SELECT id,document FROM coding_demands WHERE conversation_id=? AND request_id=?', (ident, payload['request_id'])).fetchone()
        if row:
            if json.loads(row['document'])['submission'] != original:
                conflict('此请求编号已用于另一项改进。')
            return self.bound(ident, row['id'])
        args = self.service.admit({**spec, 'prompt': payload['prompt'], 'project_id': doc['project_id'],
            'conversation_id': ident, 'skill_id': 'matt-pocock.code-review', 'coding': True})
        from .coding_workflow import composition, MAX_ATTEMPTS
        decisions, _ = composition(self.service, args)
        frozen = {'arguments': args, 'sources': self.service._sources(args, lambda: None),
            'project_root': str(ProjectFiles(self.core).root(doc['project_id'])),
            'runtime_binding': self.service.binding(), 'composition': decisions,
            'budget': {'max_model_calls': MAX_ATTEMPTS, 'runtime_seconds': 240}}
        if expected_source_digest is not None and policy.digest(policy.canonical_json(frozen['sources']).encode()) != expected_source_digest:
            conflict('审阅后的源码已经变化，请重新分析，未交接新的文件内容。')
        origin = {'conversation_id': ident, 'project_id': doc['project_id'], 'goal': args['prompt']}
        if previous_job: origin['previous_job'] = previous_job
        job = {'id': uuid.uuid4().hex, 'created_at': now(), 'status': 'PROPOSED',
            'request': {'action': 'coding', 'origin': origin}, 'submission': original, 'frozen': frozen,
            'proposal': {'binding': policy.digest(policy.canonical_json(frozen).encode()),
                'budget': frozen['budget'], 'route': args.get('coding_provider'), 'model': args['model']},
            'task_id': None, 'events': [], 'attempts': [], 'result': None, 'error': None}
        if args['coding_provider'] == 'codex':
            from .coding_settings import CodingSettings
            job['proposal']['executor'] = CodingSettings(self.core).read()
        self.core.assert_running()
        with self.core.ledger.effect_guard(expected_epoch=self.core._security_epoch) as db:
            row = db.execute('SELECT document FROM coding_demands WHERE conversation_id=? AND request_id=?', (ident, payload['request_id'])).fetchone()
            if row:
                old = json.loads(row['document'])
                if old['submission'] != original: conflict('此请求编号已用于另一项改进。')
                job = old
            else:
                if db.execute('SELECT count(*) FROM coding_demands').fetchone()[0] >= 1000:
                    conflict('编码改进单达到 1,000 项保留上限，请先整理记录。')
                db.execute('INSERT INTO coding_demands VALUES(?,?,?,?)', (job['id'], ident, payload['request_id'], policy.canonical_json(job)))
        return self.bound(ident, job['id'])

    def bound(self, ident, job_id):
        job = self.stored(ident, job_id)
        if not job.get('task_id'):
            return self.public(job)
        detail = self.tasks.detail(ident, job['task_id'])
        action = detail['action_status']
        state = {'PREPARED': 'QUEUED', 'DISPATCHING': 'RUNNING', 'CONFIRMED': 'SUCCEEDED'}.get(action, action)
        result = None
        error = detail.get('error')
        if action == 'CONFIRMED':
            # artifact() checks action ownership, receipt digest and bounded bytes.
            report = json.loads(self.tasks.artifact(ident, job['task_id']))
            value = report.get('coding') or {}
            expected = job['frozen']['arguments']
            case_digest = policy.digest(policy.canonical_json({'public': expected['cases'], 'heldout': expected['heldout_cases']}).encode())
            passed = (value.get('passed') is True and value.get('validation', {}).get('independent_checks') is True
                and value.get('cases_digest') == case_digest and value.get('build') is not None
                and (expected['build_recipe'] == 'python-source-v1' or value.get('build_validation', {}).get('passed') is True))
            state = 'SUCCEEDED' if passed else 'FAILED'
            result = {'verified': passed, 'task_id': job['task_id'], 'artifact_digest': detail['artifact']['digest'],
                'cases_digest': case_digest, 'cases': value.get('validation', {}).get('cases', 0),
                'model_calls': len(value.get('attempts', [])), 'build_recipe': value.get('build_recipe'),
                'delivery': 'verified_candidate' if passed else 'diagnostic_only', 'automatically_applied': False}
            if not passed: error = {'code': 'coding_acceptance_failed', 'message': '独立验收未通过，诊断已保存，未应用候选。'}
        if (job['status'], job.get('result'), job.get('error')) != (state, result, error):
            with self.core.ledger.transaction() as db:
                latest = read(db, job_id)
                if latest['status'] not in {'PROPOSED', 'QUEUED', 'RUNNING'} and state in {'QUEUED', 'RUNNING'}:
                    return self.public(latest)
                previous = latest['status']
                latest.update(status=state, result=result, error=error)
                if state != previous:
                    latest['events'].append({'at': now(), 'phase': state})
                write(db, latest)
                job = latest
        return self.public(job)

    @staticmethod
    def public(job):
        # Source content remains local; UI needs paths/digests, not duplicate code.
        return {k: v for k, v in job.items() if k not in {'submission', 'frozen'}} | {
            'coding': {**job['frozen']['arguments'], 'project_root': job['frozen']['project_root'],
                'sources': [{k: v for k, v in row.items() if k != 'content'} for row in job['frozen']['sources']]}}

    def list(self, ident):
        doc = archive(self.core, ident)
        with self.core.ledger.connection() as db:
            rows = db.execute("SELECT id FROM coding_demands WHERE conversation_id=? AND json_extract(document,'$.request.origin.project_id')=? ORDER BY rowid DESC LIMIT 30", (ident, doc['project_id'])).fetchall()
        return [self.bound(ident, row['id']) for row in rows]

    def start(self, ident, job_id, payload):
        if payload != {}: conflict('启动不接受替换冻结参数。')
        job = self.stored(ident, job_id)
        if job['status'] != 'PROPOSED' or job.get('task_id'):
            return self.bound(ident, job_id)
        args = {**job['frozen']['arguments'], 'coding_demand': {'id': job_id, 'digest': job['proposal']['binding']}}
        validate_binding(self.core, args)
        from .coding_workflow import composition
        if composition(self.service, args)[0] != job['frozen']['composition']:
            conflict('技能规则已变化，请重新分析。')
        submitted = {k: v for k, v in args.items() if k != 'conversation_id'}
        self.tasks.submit(ident, {'request_id': 'web-'+job_id, 'mode': 'skill', **submitted})
        return self.bound(ident, job_id)

    def cancel(self, ident, job_id, payload):
        if payload != {}: conflict('取消不接受替换参数。')
        self.stored(ident, job_id)
        with self.core.ledger.transaction() as db:
            job = read(db, job_id)
            if not job.get('task_id') and job['status'] == 'PROPOSED':
                job['status'] = 'CANCELLED'
                job['events'].append({'at': now(), 'phase': 'CANCELLED'})
                write(db, job)
        if job.get('task_id'): self.tasks.cancel(ident, job['task_id'], {})
        return self.bound(ident, job_id)

    def reanalyse(self, ident, job_id, payload):
        if not isinstance(payload, dict) or set(payload) != {'request_id'}:
            conflict('重新分析需要新的请求编号。')
        job = self.bound(ident, job_id)
        if job['status'] not in {'FAILED', 'UNKNOWN', 'INTERRUPTED', 'CANCELLED'}:
            conflict('请先结束或取消原单，再重新分析。')
        original = self.stored(ident, job_id)['submission']['payload']
        return self.propose(ident, {**original, 'request_id': payload['request_id']}, previous_job=job_id)
