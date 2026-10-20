"""Detect -> generate -> isolated evaluate -> atomic activate -> observe/repair."""
import copy
import re
import threading
import time
import uuid

from .. import policy
from ..worker_recovery import locked
from . import recipes
from .provider import ModelCodingProvider, default_route
from .runner import IsolatedRunner, validate_code
from .store import EvolutionStore, now
from .settings import validate as validate_settings, can_fallback

CANDIDATE_FAULTS = {'evolution_package_changed', 'evolution_package_invalid', 'evolution_file_invalid',
                    'evolution_unverified', 'evolution_regression', 'candidate_invalid',
                    'candidate_execution_failed', 'candidate_reply_invalid', 'worker_timeout',
                    'worker_cpu_limit', 'worker_output_limit', 'path_missing', 'path_denied', 'not_found'}


class EvolutionManager:
    def __init__(self, core, *, config_path=None, provider=None, runner=None, monitor=True):
        self.core = core
        self.provider = provider or ModelCodingProvider(core, config_path)
        self.runner = runner or IsolatedRunner()
        self.store = EvolutionStore(core, default_route())
        self.lock = threading.RLock()
        self.cancel_event = threading.Event()
        self.closed = threading.Event()
        self.busy = False
        self.thread = None
        self.observer = None
        self.growth = None
        self.last_check = None
        self.monitor_error = None
        self.schedule_changed = threading.Event()
        with locked(self.store.root / '.lane.lock'):
            self.store.recover()
        if monitor:
            self.observer = threading.Thread(target=self._monitor, name='jarvis-evolution-observer', daemon=True)
            self.observer.start()

    def close(self):
        self.closed.set()
        self.cancel_event.set()
        if self.observer: self.observer.join(timeout=2)
        if self.thread: self.thread.join(timeout=2)

    def snapshot(self):
        self.core.assert_running()
        return {**self.store.snapshot(), 'busy': self.busy, 'last_check': self.last_check,
                'monitor_error': self.monitor_error, 'feature': 'growth-purposes-v2',
                'scope': '文件清单导出技能的代码生成、隔离执行、升级与自愈；宿主与任意第三方组件仍不自动改写。',
                'limits': {'attempts_per_job': 2, 'automatic_incidents_per_day': 4,
                           'worker_memory_mb': 192, 'worker_cpu_seconds': 3, 'max_packages': 64},
                'recipes': [recipes.metadata(1), recipes.metadata(2)]}

    def configure(self, payload):
        with self.lock:
            if self.busy:
                raise policy.CoreError('evolution_busy', '任务结束后才能改变编码模型和自动维护设置。')
            self.store.configure(validate_settings(payload, self.store.settings(), self.provider))
            self.schedule_changed.set()
        return self.snapshot()

    def submit(self, payload, *, background=False, cause=None):
        if not isinstance(payload, dict) or set(payload) - {'action', 'request_id', 'target_revision', 'input'}:
            raise policy.CoreError('evolution_request_invalid', '进化请求字段无效。')
        action = payload.get('action')
        if action not in {'ensure', 'check', 'analyze', 'heal', 'execute', 'rollback'} or not isinstance(payload.get('request_id'), str) or not re.fullmatch('[a-zA-Z0-9_-]{8,80}', payload['request_id']):
            raise policy.CoreError('evolution_request_invalid', '动作或请求编号无效。')
        if set(payload) != {'action', 'request_id'} | ({'target_revision'} if action == 'ensure' else {'input'} if action == 'execute' else set()):
            raise policy.CoreError('evolution_request_invalid', '动作参数不匹配。')
        if action == 'ensure': recipes.specification(payload['target_revision'])
        if action == 'execute': recipes.validate_input(payload['input'], 2)
        return self._enqueue(payload, background=background, cause=cause)

    def _enqueue(self, payload, *, background=False, cause=None):
        """Shared bounded growth lane; adapters validate before entering here."""
        payload = copy.deepcopy(payload)
        with self.lock:
            if self.closed.is_set(): raise policy.CoreError('evolution_closed', '维护服务已关闭。')
            # Idempotent request lookup remains possible while the lane is busy.
            existing = self.store.existing_job(payload['request_id'])
            if existing:
                if existing['request'] != payload:
                    raise policy.CoreError('evolution_conflict', '请求编号已经用于其他内容。')
                return existing
            if self.busy:
                raise policy.CoreError('evolution_busy', '已有一个改进或工具任务正在处理。')
            job, created = self.store.create_job(payload)
            if not created: return job
            if cause: self.store.update(job, cause=cause)
            self.busy = True
            self.cancel_event.clear()
            self.thread = threading.Thread(target=self._work, args=(job, background), name='jarvis-evolution-worker', daemon=True)
            self.thread.start()
        return job

    def cancel(self, ident):
        if not isinstance(ident, str) or not re.fullmatch('[a-f0-9]{32}', ident):
            raise policy.CoreError('evolution_request_invalid', '任务编号无效。')
        with self.lock:
            job = self.store.job(ident)
            if job['status'] == 'PROPOSED':
                with self.core.effect_guard(): self.store.update(job, 'CANCELLED', status='CANCELLED')
            if job['status'] in {'QUEUED', 'RUNNING', 'OBSERVING'}:
                self.cancel_event.set()
        return self.store.job(ident)

    def propose(self, payload):
        from .demand import validate_fulfillment
        validate_fulfillment(payload)
        with self.lock:
            if self.closed.is_set(): raise policy.CoreError('evolution_closed', '成长服务已关闭。')
            selection = self.store.selection()
            revision, issue = 0, None
            if selection['active']:
                try:
                    record, _ = self.store.read_package(selection['active'])
                    if record['state'] == 'VERIFIED': revision = record['revision']
                    else: issue = 'evolution_unverified'
                except policy.CoreError as exc:
                    if exc.code not in CANDIDATE_FAULTS: raise
                    issue = exc.code
            settings = self.store.settings()
            proposal = {'selection': selection, 'route': settings['route'], 'policy_revision': settings['revision'],
                'baseline_revision': revision, 'issue': issue,
                'decision': 'reuse' if revision >= payload['target_revision'] else 'repair' if issue else 'upgrade' if revision else 'create',
                'max_coding_attempts': 2, 'acceptance_digest': recipes.binding(payload['target_revision']),
                'input_digest': policy.digest(policy.canonical_json(payload['input']).encode())}
            return self.store.create_job(copy.deepcopy(payload), proposal=proposal)[0]

    def start_proposal(self, ident):
        with self.lock:
            if self.closed.is_set(): raise policy.CoreError('evolution_closed', '成长服务已关闭。')
            job = self.store.job(ident)
            if job['request'].get('action') != 'fulfill':
                raise policy.CoreError('evolution_request_invalid', '不是需求改进单。')
            if job['status'] != 'PROPOSED': return job
            if self.busy: raise policy.CoreError('evolution_busy', '已有成长任务，请稍后启动。')
            expected = job['proposal']
            settings = self.store.settings()
            if (self.store.selection() != expected['selection'] or settings['route'] != expected['route']
                    or expected.get('policy_revision') != settings['revision']):
                raise policy.CoreError('evolution_conflict', '能力基线或编码模型已变化，请重新分析需求，未启动旧改进单。')
            if (recipes.binding(job['request']['target_revision']) != expected['acceptance_digest']
                    or policy.digest(policy.canonical_json(job['request']['input']).encode()) != expected['input_digest']):
                raise policy.CoreError('evolution_conflict', '验收条件或输入已变化，请重新分析需求，未启动旧改进单。')
            job, created = self.store.queue_proposal(ident)
            if created:
                self.busy = True; self.cancel_event.clear()
                self.thread = threading.Thread(target=self._work, args=(job, False), name='jarvis-evolution-worker', daemon=True)
                self.thread.start()
            return job

    def _checkpoint(self):
        if self.closed.is_set() or self.cancel_event.is_set():
            raise policy.CoreError('evolution_cancelled', '改进已停止；已发出的模型调用可能仍有用量。')
        self.core.assert_running()

    def _resources(self):
        from ..resources import memory_snapshot, load_profile, MIB
        sample = memory_snapshot()
        required = (load_profile()['foreground_reserve_mib'] + 192) * MIB
        if min(sample['available_bytes'], sample['commit_available_bytes']) < required:
            raise policy.CoreError('evolution_memory_pressure', '本机内存不足，成长任务已让出资源；聊天继续可用。')

    def _evaluate(self, source, revision):
        self._resources()
        validate_code(source)
        # Actual outputs are evaluated in Host; candidate cannot edit expected values.
        inputs = recipes.cases(revision, heldout=True)
        outputs, isolation = self.runner.run(source, inputs, self._checkpoint)
        mismatches = [i for i, (x, y) in enumerate(zip(inputs, outputs)) if y != recipes.expected(x)]
        if len(outputs) != len(inputs): mismatches.append(-1)
        return {'passed': not mismatches, 'cases': len(inputs), 'failed_indices': mismatches,
                'acceptance_digest': recipes.binding(revision), 'isolation': isolation}

    def _health(self, ident):
        record, files = self.store.read_package(ident)
        if record['state'] != 'VERIFIED':
            raise policy.CoreError('evolution_unverified', '当前技能包未处于已验证状态。')
        result = self._evaluate(files['candidate.py'], record['revision'])
        if not result['passed']:
            raise policy.CoreError('evolution_regression', '当前技能未通过冻结回归样例。')
        return result

    def _rollback(self, job, selection, *, automatic):
        replacement = selection['previous']
        if replacement:
            try: self._health(replacement)
            except policy.CoreError as exc:
                if exc.code not in CANDIDATE_FAULTS: raise
                replacement = None
        self._checkpoint()
        self.store.restore(selection['active'], replacement, pause_automatic=not automatic)
        self.store.update(job, 'ROLLED_BACK' if replacement else 'DEACTIVATED',
                          rollback={'from': selection['active'], 'to': replacement, 'automatic': automatic})
        return replacement

    def _ensure(self, job, revision, *, lane='evolve'):
        base = self.store.selection()
        previous = ''
        if base['active']:
            try:
                record, files = self.store.read_package(base['active'])
                self._health(base['active'])
                previous = files['candidate.py']
                if record['revision'] >= revision:
                    return {'package': base['active'], 'revision': record['revision'], 'changed': False}
            except policy.CoreError as exc:
                if exc.code not in CANDIDATE_FAULTS: raise
                self._rollback(job, base, automatic=True)
                base = self.store.selection()
                if base['active']:
                    _, files = self.store.read_package(base['active']); previous = files['candidate.py']
        model_policy = job['policy']['models'][lane]
        selected_model = model_policy['primary']
        used_fallback = False
        if hasattr(self.runner, 'preflight'): self.runner.preflight()
        feedback = ''
        for attempt in range(len(job['attempts']) + 1, 3):
            self._checkpoint()
            self._resources()
            self.store.update(job, 'GENERATING', target_revision=revision, base=base)
            try:
                candidate, receipt = self.provider.generate(revision, selected_model['route'], previous, feedback,
                    self.cancel_event, self._checkpoint, reasoning=selected_model['reasoning'])
            except policy.CoreError as exc:
                if exc.code != 'evolution_route_invalid': raise
                candidate, receipt = None, {'status': 'FAILED', 'error_category': 'model_unavailable', 'dispatched': False}
            receipt = {**receipt, 'selection': copy.deepcopy(selected_model), 'purpose': lane, 'fallback': used_fallback}
            item = {'attempt': attempt, 'coding': receipt}
            job['attempts'].append(item)
            self.store.update(job)
            self._checkpoint()
            if not candidate:
                if receipt.get('validation_error'):
                    feedback = 'Return the exact JSON schema and permitted pure Python implementation.'
                    continue
                if not used_fallback and model_policy['fallback'] and can_fallback(receipt) and attempt < 2:
                    selected_model = model_policy['fallback']
                    used_fallback = True
                    self.store.update(job, 'MODEL_FALLBACK', fallback_reason=receipt.get('error_category'))
                    continue
                # Unknown, cancelled and partial calls never trigger a fallback.
                job['model_outcome'] = receipt.get('status')
                raise policy.CoreError('evolution_model_unavailable', '编码模型未返回完整候选；本轮已停止，请查看实际调用记录。')
            ident = self.store.stage(candidate, revision, receipt)
            item['package'] = ident
            self.store.update(job, 'VALIDATING')
            try:
                evidence = self._evaluate(candidate['code'], revision)
            except policy.CoreError as exc:
                if exc.code not in CANDIDATE_FAULTS: raise
                evidence = {'passed': False, 'error': exc.code}
            item['validation'] = evidence
            self.store.assess(ident, 'VERIFIED' if evidence['passed'] else 'REJECTED', evidence)
            self.store.update(job)
            if not evidence['passed']:
                previous = candidate['code']
                feedback = 'Independent evaluation failed: ' + policy.canonical_json(
                    {k: v for k, v in evidence.items() if k != 'isolation'})
                continue
            self._checkpoint()
            self.store.activate(ident, base, job)
            try:
                observation = self._health(ident)
            except Exception:
                # Cancellation after activation also removes the unobserved candidate.
                selected = self.store.selection()
                if selected['active'] == ident:
                    self.store.restore(ident, base['active'])
                    self.store.update(job, 'ROLLED_BACK', rollback={'from': ident, 'to': base['active'], 'automatic': True})
                raise
            # Commit successful observation separately from the caller's task:
            # a failed original invocation can repair a tool yet still report
            # failure for that invocation. Recovery must retain the tested repair.
            with self.core.effect_guard():
                self.store.update(job, 'OBSERVED', activation_confirmed=True)
            return {'package': ident, 'revision': revision, 'changed': True, 'observation': observation}
        raise policy.CoreError('evolution_candidates_rejected', '两次候选均未通过验收；原可用版本保留，本轮停止。')

    def _observation(self, settings):
        """Read package integrity only: no worker, model, rollback or publication."""
        selected = self.store.selection()
        result = {'checked_at': now(), 'scope': 'active_tool_package_integrity', 'selection': selected,
                  'target_revision': settings['target_revision'], 'model_calls': 0,
                  'functional_retest': False, 'healthy': False, 'classification': 'missing_optional',
                  'package': selected['active'], 'actual_revision': None, 'fault': None}
        if selected['active']:
            try:
                record, _ = self.store.read_package(selected['active'])
                result['actual_revision'] = record['revision']
                if record['state'] != 'VERIFIED':
                    raise policy.CoreError('evolution_unverified', '活动技能未验证。')
                result.update(healthy=True, classification='healthy' if record['revision'] >= settings['target_revision'] else 'capability_gap')
            except policy.CoreError as exc:
                if exc.code not in CANDIDATE_FAULTS: raise
                result.update(classification='fault', fault=exc.code)
        return result

    def _check(self, job, automatic=False):
        return self._observation(job['policy'])

    def _analyze(self, job):
        observation = self._check(job)
        model_policy = job['policy']['models']['inspect']
        for selected in (model_policy['primary'], model_policy['fallback']):
            if selected is None: break
            self._checkpoint(); self._resources()
            self.store.update(job, 'ANALYZING')
            try:
                advice, receipt = self.provider.analyze(observation, selected['route'], self.cancel_event,
                    self._checkpoint, reasoning=selected['reasoning'])
            except policy.CoreError as exc:
                if exc.code != 'evolution_route_invalid': raise
                advice, receipt = None, {'status': 'FAILED', 'error_category': 'model_unavailable', 'dispatched': False}
            receipt = {**receipt, 'selection': copy.deepcopy(selected), 'purpose': 'inspect', 'fallback': bool(job['attempts'])}
            job['attempts'].append({'attempt': len(job['attempts']) + 1, 'coding': receipt})
            self.store.update(job)
            self._checkpoint()
            if advice:
                return {'observation': observation, 'advice': advice, 'advisory_only': True}
            job['model_outcome'] = receipt.get('status')
            if not can_fallback(receipt): break
        raise policy.CoreError('evolution_model_unavailable', '诊断模型未返回完整解释，本轮已停止；未执行任何建议。')

    def _heal(self, job):
        observation = self._check(job)
        if observation['classification'] != 'fault':
            return {'changed': False, 'observation': observation, 'message': '没有已确认的包故障；缺失的可选能力和版本差距由进化处理。'}
        selected = observation['selection']
        # Restore the damaged contract, never the (possibly newer) growth target.
        revision = self.store.package(selected['active'])['revision']
        self.store.update(job, 'FAULT_CONFIRMED', fault=observation)
        self._rollback(job, selected, automatic=True)
        repair = self._ensure(job, revision, lane='heal')
        return {'changed': True, 'restored_revision': revision, 'repair': repair, 'original_fault': observation['fault']}

    def _queue_automatic_heal(self, check_job):
        observation = check_job.get('result') or {}
        with self.lock:
            settings = self.store.settings()
            if (self.closed.is_set() or self.cancel_event.is_set() or self.busy or not settings['auto_heal']
                    or check_job['status'] != 'SUCCEEDED' or observation.get('classification') != 'fault'
                    or observation['selection'] != self.store.selection()): return
            incident = policy.digest(policy.canonical_json({'selection': observation['selection'], 'fault': observation['fault']}).encode())
            if self.store.reserve_incident(incident):
                self.submit({'action': 'heal', 'request_id': 'auto-heal-' + uuid.uuid4().hex},
                            cause={'inspection_job': check_job['id'], 'incident': incident})

    def _execute(self, job):
        selected = self.store.selection()
        if not selected['active']:
            raise policy.CoreError('evolution_missing', '请先生成并启用报告技能。')
        try:
            record, files = self.store.read_package(selected['active'])
            value = recipes.validate_input(job['request']['input'], record['revision'])
            if record['state'] != 'VERIFIED':
                raise policy.CoreError('evolution_unverified', '技能包未验证。')
            self._resources()
            outputs, isolation = self.runner.run(files['candidate.py'], [value], self._checkpoint)
            if outputs != [recipes.expected(value)]:
                raise policy.CoreError('evolution_regression', '真实输入结果没有通过独立检查。')
            return {'package': selected['active'], 'text': outputs[0], 'isolation': isolation,
                    'result_digest': policy.digest(outputs[0].encode())}
        except policy.CoreError as exc:
            if exc.code not in CANDIDATE_FAULTS: raise
            damaged_revision = self.store.package(selected['active'])['revision']
            self._rollback(job, selected, automatic=True)
            settings = job['policy']
            incident = 'runtime-' + str(selected['active'])
            if settings['auto_heal'] and self.store.reserve_incident(incident):
                self._ensure(job, damaged_revision, lane='heal')
            # Input is pure, but don't silently pretend the original failed invocation succeeded.
            raise policy.CoreError('evolution_execution_recovered', '执行失败已触发回退/修复；请查看记录后重新调用。') from None

    def _work(self, job, background):
        try:
            with locked(self.store.root / '.lane.lock'):
                self._checkpoint()
                self.store.update(job, 'STARTED', status='RUNNING')
                action = job['request']['action']
                if action == 'project-tool':
                    from .catalog import ProjectTools
                    result = ProjectTools(self).execute(job)
                elif action == 'growth-baseline':
                    from .growth_cycle import baseline
                    result = baseline(self,job)
                elif action == 'tool-contract':
                    from .catalog import ProjectTools
                    from .tool_contract import ToolContracts
                    result = ToolContracts(ProjectTools(self)).execute(job)
                elif action == 'ensure': result = self._ensure(job, job['request']['target_revision'])
                elif action == 'check': result = self._check(job, background)
                elif action == 'analyze': result = self._analyze(job)
                elif action == 'heal': result = self._heal(job)
                elif action == 'execute': result = self._execute(job)
                elif action == 'fulfill':
                    from .demand import validate_fulfillment
                    validate_fulfillment(job['request'])
                    growth = self._ensure(job, job['request']['target_revision'])
                    self.store.update(job, 'APPLYING', growth=growth)
                    result = {**self._execute(job), 'growth': growth,
                              'benefit': {'format': job['request']['input']['format'],
                                  'entries': len(job['request']['input']['entries']),
                                  'source_digest': job['request']['origin']['source_digest'],
                                  'verified_on_user_input': True}}
                else:
                    selected = self.store.selection()
                    if not selected['active']:
                        raise policy.CoreError('evolution_missing', '没有活动版本可以回退。')
                    result = {'restored': self._rollback(job, selected, automatic=False)}
                    # A deliberate rollback is an owner override. Do not let
                    # the next periodic target check immediately upgrade again.
                    result['automatic_maintenance_paused'] = True
                self._checkpoint()
                with self.core.effect_guard():
                    self.store.update(job, 'FINISHED', status='SUCCEEDED', result=result,
                                      **({'activation_confirmed': True} if job.get('published') else {}))
                if background and action == 'check' and not job.get('issue') and not job['attempts']:
                    self.store.compact_health_checks()
        except Exception as exc:
            if job['request']['action']=='project-tool':
                from .catalog import ProjectTools
                ProjectTools(self).abort(job)
            code = exc.code if isinstance(exc, policy.CoreError) else 'evolution_internal_error'
            status = 'CANCELLED' if code == 'evolution_cancelled' else 'UNKNOWN' if job.get('model_outcome') == 'UNKNOWN' else 'FAILED'
            self.store.update(job, 'STOPPED', status=status, error=code)
        finally:
            with self.lock: self.busy = False
        if background and job['request']['action'] == 'check':
            try: self._queue_automatic_heal(job)
            except Exception: self.monitor_error = '自检已记录；自动自愈未启动，请查看成长中心。'

    def _monitor(self):
        # One sleeping thread; no model process or model request while healthy.
        next_check = time.monotonic() + 15
        while not self.closed.wait(1):
            if self.growth is not None:
                try: self.growth.tick()
                except Exception: self.monitor_error = '成长推进暂停，请核对原记录；未重发模型请求。'
            if self.schedule_changed.is_set():
                self.schedule_changed.clear()
                next_check = time.monotonic() + 15
            if time.monotonic() < next_check: continue
            try:
                settings = self.store.settings()
                next_check = time.monotonic() + settings['interval_seconds']
                if settings['enabled'] and not self.busy:
                    self.submit({'action': 'check', 'request_id': 'auto-' + uuid.uuid4().hex}, background=True)
                    self.last_check = now()
                    self.monitor_error = None
            except Exception:
                next_check = time.monotonic() + 300
                self.monitor_error = '自动检查暂不可用；没有停止聊天或重发模型请求。'
