"""K5 bounded source generation, independent evaluation and reviewed selection."""
import json
import re

from .. import policy
from ..ranking_evaluation import binding, evaluate
from ..ranking_program import FEATURES, compile_source, source_for
from ..ranking_registry import read_version, restore, save, select_row
from .store import now


class RankingModules:
    def __init__(self, manager, model_calls=None):
        self.manager = manager
        self.core, self.store = manager.core, manager.store
        self.model_calls = model_calls

    def recover(self):
        """Called once by the owning server, never by a disposable chat worker."""
        with self.store.connection() as db:
            db.execute('BEGIN IMMEDIATE')
            selected = select_row(db)
            if selected['trial']:
                restore(db, selected, 'unconfirmed_trial_restart_rollback')
            elif selected['active']:
                try: read_version(db, selected['active'])
                except (ValueError, TypeError, KeyError, SyntaxError):
                    restore(db, selected, 'startup_incompatible_rollback')

    def snapshot(self):
        self.core.assert_running()
        with self.store.connection() as db:
            selected = select_row(db)
            versions = []
            for row in db.execute('SELECT id,document FROM ranking_versions ORDER BY rowid DESC LIMIT 32'):
                value = json.loads(row['document'])
                versions.append(dict(id=row['id'], **value))
        jobs = [self.store.job(j['id']) for j in self.store.snapshot()['jobs'] if j['action'] == 'ranking-improve']
        return dict(selection=selected, versions=versions, jobs=jobs, busy=self.manager.busy,
                    binding=binding(), default_model=self.store.settings()['route'],
                    scope='仅检索排序；来源权限、原文、记忆、引用与上下文预算由宿主管理。',
                    limits=dict(versions=32, calls_per_request=1, automatic_activation=False))

    def submit(self, payload):
        if (not isinstance(payload, dict) or set(payload) != {'request_id', 'model'}
                or not isinstance(payload['request_id'], str)
                or not re.fullmatch('[a-f0-9]{32}', payload['request_id'])):
            raise policy.CoreError('evolution_request_invalid', '需要请求编号和明确的编码模型。')
        self.manager.provider.configuration(payload['model'])
        return self.manager._enqueue(dict(action='ranking-improve', **payload, binding=binding()))

    def execute(self, job):
        manager = self.manager
        manager._checkpoint(); manager._resources()
        if job['request']['binding'] != binding():
            raise policy.CoreError('evolution_conflict', '检索契约已变化，请创建新的改进请求。')
        with self.store.connection() as db:
            if db.execute('SELECT count(*) FROM ranking_versions').fetchone()[0] >= 32:
                raise policy.CoreError('evolution_capacity', '候选版本已达到 32 个，未请求模型。')
        # Public contract only. No project text, personal memory or heldout data.
        prompt = policy.canonical_json({
            'task':'Improve lexical retrieval source ranking. Favor documents covering all query concepts over repeated single concepts. Preserve strong title matches and deterministic ties.',
            'interface':'transform(data) takes a list of precomputed feature dictionaries and returns comma-separated sorted indices.',
            'features':{'coverage':'count of distinct query terms found in text OR heading',
                        'text_coverage':'distinct terms found in text',
                        'heading_coverage':'distinct terms found in heading',
                        'score':'legacy term frequency plus heading score',
                        'path':'stable path string', 'start_line':'stable line integer'},
            'grammar':'Use EXACT skeleton below. Only change the tuple in the key lambda: choose 1 to 4 different negative numeric feature accesses, MUST include score, followed by data[i]["path"], data[i]["start_line"]. No additional statements, comments with directives, imports, helper functions or other expressions.',
            'skeleton':source_for(('score', 'path', 'start_line')),
            'allowed_numeric_features':FEATURES})
        config, provider = manager.provider.configuration(job['request']['model'])
        if self.model_calls is None:
            raise policy.CoreError('evolution_unavailable', '隔离模型调用服务不可用。')
        self.store.update(job, 'GENERATING', model_outcome='UNKNOWN')
        def guard():
            manager._checkpoint()
            return self.core.assert_running()
        response = self.model_calls.probe(config, provider, prompt, self.core.data_dir, guard,
            admission_context=self.core.effect_guard, cancel_event=manager.cancel_event, deadline_seconds=70,
            instructions='Return only a JSON object {"code":"complete Python source","notes":"short explanation"}. Follow the exact bounded source grammar. No Markdown.')
        receipt = manager.provider.receipt(response, config, provider)
        self.store.update(job, 'MODEL_RETURNED', model_outcome=response.get('status', 'UNKNOWN'), model_receipt=receipt)
        manager._checkpoint()
        if response.get('status') != 'SUCCEEDED' or response.get('output_incomplete'):
            raise policy.CoreError('evolution_model_failed', '模型未返回完整候选；未自动重发。')
        try:
            raw = response.get('text', '')
            if len(raw.encode()) > 12000: raise ValueError('size')
            candidate = json.loads(raw)
            if (set(candidate) != {'code', 'notes'} or not isinstance(candidate['notes'], str)
                    or len(candidate['notes']) > 2000): raise ValueError('fields')
            keys = compile_source(candidate['code'])
        except (ValueError, TypeError, SyntaxError, KeyError):
            raise policy.CoreError('candidate_invalid', '候选不属于可证明有界的排序代码，保留当前模块。') from None
        self.store.update(job, 'EVALUATING')
        evaluation = evaluate(candidate['code'], manager.runner, manager._checkpoint)
        value = dict(source=candidate['code'], keys=list(keys), notes=candidate['notes'],
                     binding=job['request']['binding'], evaluation=evaluation, model_receipt=receipt,
                     created_at=now(), job_id=job['id'])
        ident = policy.digest(policy.canonical_json(value).encode())[7:]
        manager._checkpoint()
        with self.core.effect_guard(), self.store.connection() as db:
            db.execute('BEGIN IMMEDIATE')
            if value['binding'] != binding():
                raise policy.CoreError('evolution_conflict', '评估期间契约发生变化，未发布候选。')
            db.execute('INSERT INTO ranking_versions VALUES(?,?)', (ident, policy.canonical_json(value)))
        return dict(candidate_id=ident, eligible=evaluation['passed'], evaluation=evaluation,
                    activated=False, message='候选与对照已保存；启用仍需审阅。')

    def transition(self, payload):
        if (not isinstance(payload, dict) or set(payload) != {'action', 'generation', 'version', 'review'}
                or payload['action'] not in {'trial', 'confirm', 'rollback', 'baseline'}
                or type(payload['generation']) is not int or not isinstance(payload['review'], str)
                or not 8 <= len(payload['review']) <= 1000
                or not (payload['version'] is None or isinstance(payload['version'], str) and re.fullmatch('[a-f0-9]{64}', payload['version']))):
            raise policy.CoreError('evolution_request_invalid', '需要操作、当前版本/代次以及审阅依据。')
        with self.manager.lock, self.core.effect_guard(), self.store.connection() as db:
            db.execute('BEGIN IMMEDIATE')
            current = select_row(db)
            # Read-only idempotent return after an interrupted HTTP reply.
            if current.get('last_request') == payload: return current
            if current['generation'] != payload['generation']:
                raise policy.CoreError('evolution_conflict', '选择已变化，请刷新后核对。')
            action = payload['action']
            if action == 'trial':
                if current['trial'] or current['active'] == payload['version']:
                    raise policy.CoreError('evolution_conflict', '已有试用或该版本已经启用。')
                try: read_version(db, payload['version'])
                except (ValueError, TypeError, KeyError, SyntaxError):
                    raise policy.CoreError('candidate_invalid', '候选未通过当前独立验收或已不兼容。') from None
                current.update(previous=current['active'], active=payload['version'], trial=True,
                               samples=[], maximum_ms=0, last_event='reviewed_trial')
            else:
                if current['active'] != payload['version']:
                    raise policy.CoreError('evolution_conflict', '操作目标与当前模块不匹配。')
                if action == 'confirm':
                    if not current['trial'] or len(current['samples']) < 3:
                        raise policy.CoreError('evolution_conflict', '至少观察 3 个不同的有效查询后才能保留。')
                    read_version(db, current['active'])
                    current.update(trial=False, last_event='reviewed_confirmation')
                elif action == 'baseline':
                    current.update(active=None, previous=None, trial=False, samples=[], last_event='owner_baseline')
                else:
                    current = restore(db, current, 'reviewed_rollback')
            current.update(generation=payload['generation']+1, last_request=payload)
            save(db, current)
            return current
