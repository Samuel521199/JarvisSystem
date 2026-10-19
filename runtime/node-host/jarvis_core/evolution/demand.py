"""Conversation demand adapter for the existing evolution lane and ledger.

Only an existing, verified inventory report can be transformed. Preview is
local and model-free; candidate prompts never include owner paths or chats.
"""
import json
import re

from .. import policy
from ..conversations import ConversationStore, ConversationError
from ..conversation_tasks import conversation_id
from . import recipes


def output_format(prompt):
    if not isinstance(prompt, str) or len(prompt.encode()) > 1024:
        raise policy.CoreError('growth_request_invalid', '需求最多 1,024 UTF-8 字节。')
    match = re.fullmatch(r'(?:请)?(?:把|将)?(?:本会话)?(?:最近的?|已完成的?)?(?:目录报告|文件清单|清单)?\s*(?:导出|转换|转)(?:成|为)?\s*(CSV|TSV|Markdown)(?:格式|表格)?[。！!]?|(?:CSV|TSV|Markdown)', prompt.strip(), re.I)
    if not match:
        raise policy.CoreError('growth_unsupported', '当前成长入口支持把已完成目录报告导出为 CSV、TSV 或 Markdown；其他需求尚无独立验收配方，未生成或执行代码。')
    return (match[1] or match[0]).lower()


def validate_fulfillment(payload):
    if not isinstance(payload, dict) or set(payload) != {'action','request_id','target_revision','input','origin'} or payload['action'] != 'fulfill':
        raise policy.CoreError('growth_request_invalid', '改进单字段无效。')
    origin = payload['origin']
    required = {'conversation_id','project_id','goal','source_task','source_digest'}
    if not isinstance(origin, dict) or not required <= set(origin) or set(origin)-required-{'previous_job'}:
        raise policy.CoreError('growth_request_invalid', '改进单来源字段无效。')
    if 'previous_job' in origin: conversation_id(origin['previous_job'])
    conversation_id(origin['conversation_id'])
    if origin['project_id'] is not None: conversation_id(origin['project_id'])
    if not isinstance(payload['request_id'], str) or not re.fullmatch('growth-'+origin['conversation_id']+'-[a-f0-9]{32}', payload['request_id']):
        raise policy.CoreError('growth_request_invalid', '改进请求编号无效。')
    if (not isinstance(origin['source_task'], str) or not re.fullmatch('task_[a-f0-9]{32}', origin['source_task'])
            or not isinstance(origin['source_digest'], str) or not re.fullmatch('sha256:[a-f0-9]{64}', origin['source_digest'])):
        raise policy.CoreError('growth_request_invalid', '改进单来源标识无效。')
    fmt = output_format(origin['goal'])
    revision = 2 if fmt == 'tsv' else 1
    recipes.specification(payload['target_revision'])
    recipes.validate_input(payload['input'], revision)
    if payload['target_revision'] != revision or payload['input']['format'] != fmt:
        raise policy.CoreError('growth_request_invalid', '需求、输入格式与验收版本不一致。')


class ConversationGrowth:
    def __init__(self, core, manager, tasks):
        self.core, self.manager, self.tasks = core, manager, tasks
        self.archives = ConversationStore(core)
        from ..coding_demand import CodingDemands
        self.coding = CodingDemands(core, tasks)

    def is_coding(self, job_id):
        with self.core.ledger.connection() as db:
            return db.execute('SELECT 1 FROM coding_demands WHERE id=?', (job_id,)).fetchone() is not None

    def archive(self, ident):
        conversation_id(ident)
        try: return self.archives.get(ident)['document']
        except ConversationError:
            raise policy.CoreError('growth_archive_required', '请先确认当前普通会话已保存；临时会话不建立持久改进单。') from None

    def bound(self, ident, job_id):
        if self.is_coding(job_id): return self.coding.bound(ident, job_id)
        archive = self.archive(ident); conversation_id(job_id)
        job = self.manager.store.job(job_id)
        origin = job['request'].get('origin', {})
        if job['request'].get('action') != 'fulfill' or origin.get('conversation_id') != ident or origin.get('project_id') != archive['project_id']:
            raise policy.CoreError('not_found', '未找到当前会话范围的改进单。')
        return job

    def lookup(self, ident, request_id):
        conversation_id(ident); conversation_id(request_id)
        job = self.manager.store.existing_job('growth-'+ident+'-'+request_id)
        if job is None: return self.coding.lookup(ident, request_id)
        return self.bound(ident, job['id'])

    def list(self, ident):
        archive = self.archive(ident)
        with self.manager.store.connection() as db:
            rows = db.execute("SELECT id FROM jobs WHERE json_extract(document,'$.request.origin.conversation_id')=? AND json_extract(document,'$.request.origin.project_id') IS ? ORDER BY status IN ('QUEUED','RUNNING','OBSERVING','PROPOSED') DESC,rowid DESC LIMIT 30", (ident, archive['project_id'])).fetchall()
        coding = self.coding.list(ident) if archive['project_id'] else []
        jobs = [self.bound(ident, row['id']) for row in rows] + coding
        jobs.sort(key=lambda job: (job['status'] in {'PROPOSED','QUEUED','RUNNING','OBSERVING'}, job['created_at']), reverse=True)
        return {'jobs': jobs[:30], 'conversation_id': ident}

    def source(self, ident, task_id):
        raw = self.tasks.artifact(ident, task_id)
        try: doc = json.loads(raw)
        except ValueError: raise policy.CoreError('growth_source_invalid', '来源产物不是有效目录报告。') from None
        if doc.get('kind') != 'jarvis.sample-report' or doc.get('verified') is not True:
            raise policy.CoreError('growth_source_invalid', '当前只支持已核验的目录报告。')
        try: entries = [{'path': row['path'], 'size': row['size_bytes']} for row in doc['files']]
        except (KeyError, TypeError): raise policy.CoreError('growth_source_invalid', '目录报告字段无效。') from None
        return entries, policy.digest(raw)

    def propose(self, ident, payload, *, previous_job=None):
        if isinstance(payload, dict) and 'coding' in payload:
            if self.manager.store.existing_job('growth-'+ident+'-'+str(payload.get('request_id', ''))):
                raise policy.CoreError('evolution_conflict', '请求编号已用于报告改进，不能改为编码任务。')
            return self.coding.propose(ident, payload, previous_job=previous_job)
        archive = self.archive(ident)
        if not isinstance(payload, dict) or set(payload) != {'request_id','prompt'}:
            raise policy.CoreError('growth_request_invalid', '需求分析只接受请求编号与本轮要求。')
        conversation_id(payload['request_id']); fmt = output_format(payload['prompt'])
        with self.core.ledger.connection() as db:
            if db.execute('SELECT 1 FROM coding_demands WHERE conversation_id=? AND request_id=?', (ident, payload['request_id'])).fetchone():
                raise policy.CoreError('evolution_conflict', '请求编号已用于编码改进，不能改为报告任务。')
        request_id = 'growth-'+ident+'-'+payload['request_id']
        existing = self.manager.store.existing_job(request_id)
        if existing:
            if existing['request']['origin']['goal'] != payload['prompt'] or existing['request']['origin'].get('previous_job') != previous_job:
                raise policy.CoreError('evolution_conflict', '该请求编号已用于另一条需求。')
            return self.bound(ident, existing['id'])
        # Use only a successful report from this conversation, never a workspace scan.
        with self.core.ledger.connection() as db:
            row = db.execute("SELECT tasks.task_id FROM tasks JOIN actions USING(task_id) WHERE json_extract(actions.document,'$.status')='CONFIRMED' AND json_extract(actions.document,'$.capability_id')='sample.report.v1' AND json_extract(actions.document,'$.arguments.conversation_id')=? ORDER BY tasks.rowid DESC LIMIT 1", (ident,)).fetchone()
        if row is None:
            raise policy.CoreError('growth_source_missing', '本会话还没有完成的目录报告。先用 /任务 列出样例目录文件并保存报告，再提出导出需求。')
        entries, digest = self.source(ident, row['task_id'])
        request = {'action': 'fulfill', 'request_id': request_id, 'target_revision': 2 if fmt=='tsv' else 1,
            'input': {'format': fmt, 'entries': entries}, 'origin': {'conversation_id': ident,
            'project_id': archive['project_id'], 'goal': payload['prompt'], 'source_task': row['task_id'], 'source_digest': digest}}
        if previous_job is not None: request['origin']['previous_job'] = previous_job
        return self.manager.propose(request)

    def reanalyse(self, ident, job_id, payload):
        if self.is_coding(job_id): return self.coding.reanalyse(ident, job_id, payload)
        if not isinstance(payload, dict) or set(payload) != {'request_id'}:
            raise policy.CoreError('growth_request_invalid', '重新分析只接受新的请求编号。')
        old = self.bound(ident, job_id)
        if old['status'] not in {'FAILED', 'INTERRUPTED', 'UNKNOWN', 'CANCELLED'}:
            raise policy.CoreError('evolution_conflict', '当前记录尚未结束，无需重新分析；请先核对原单状态。')
        return self.propose(ident, {'request_id': payload['request_id'], 'prompt': old['request']['origin']['goal']}, previous_job=job_id)

    def start(self, ident, job_id, payload):
        if self.is_coding(job_id): return self.coding.start(ident, job_id, payload)
        if payload != {}: raise policy.CoreError('growth_request_invalid', '启动只接受已保存改进单，不接受替换参数。')
        job = self.bound(ident, job_id)
        if job['status'] == 'PROPOSED':
            entries, digest = self.source(ident, job['request']['origin']['source_task'])
            if digest != job['request']['origin']['source_digest'] or entries != job['request']['input']['entries']:
                raise policy.CoreError('evolution_conflict', '来源报告已变化，请重新分析需求。')
        return self.manager.start_proposal(job_id)

    def cancel(self, ident, job_id, payload):
        if self.is_coding(job_id): return self.coding.cancel(ident, job_id, payload)
        if payload != {}: raise policy.CoreError('growth_request_invalid', '取消只接受空对象。')
        self.bound(ident, job_id)
        return self.manager.cancel(job_id)

    def artifact(self, ident, job_id):
        if self.is_coding(job_id):
            job = self.coding.bound(ident, job_id)
            if job['status'] != 'SUCCEEDED':
                raise policy.CoreError('growth_result_unavailable', '编码改进尚未通过验收。')
            return self.tasks.artifact(ident, job['task_id']), 'json'
        job = self.bound(ident, job_id); result = job.get('result') or {}
        text = result.get('text')
        if (job['status'] != 'SUCCEEDED' or not isinstance(text, str)
                or policy.digest(text.encode()) != result.get('result_digest')
                or text != recipes.expected(job['request']['input'])):
            raise policy.CoreError('growth_result_unavailable', '尚无核验成功的导出结果。')
        return text.encode('utf-8'), job['request']['input']['format']
