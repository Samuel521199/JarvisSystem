"""Finite, receipt-driven growth. Reuses K3 and the existing growth execution lane.

The observer only advances an explicitly requested cycle. It never invents work,
replays UNKNOWN calls, edits source files, or runs generated code in the host.
"""
import copy
import json
import re
import time
import uuid
from .. import policy
from ..coding_demand import CodingDemands
from .catalog import ProjectTools, fail
from .growth_domains import specification, listing
from .growth_policy import read as read_policy, configure, authorize, TERMINAL
from .lifecycle import ToolLifecycle
from .store import now


def key(cycle, name):
    return uuid.uuid5(uuid.UUID(cycle['id']), name).hex


def accounting(receipts):
    usages = [r.get('usage') or {} for r in receipts]
    bills = [r.get('billing') or {} for r in receipts]
    amounts = [b.get('amount') for b in bills]
    currencies = {b.get('currency') for b in bills}
    from jarvis_models.billing import tokens
    normalized = [tokens(r.get('provider', ''), u) for r, u in zip(receipts, usages)]
    total_tokens = [n['total'] if n is not None else None for n in normalized]
    return {'calls': len(receipts),
            'tokens': sum(total_tokens) if all(type(x) in (int, float) for x in total_tokens) else None,
            'amount': sum(amounts) if len(currencies) == 1 and all(type(x) in (int, float) for x in amounts) else None,
            'currency': next(iter(currencies)) if len(currencies) == 1 else None}


class GrowthCycles:
    def __init__(self, manager, tasks, *, recover=True):
        self.manager, self.store, self.core = manager, manager.store, manager.core
        self.tools = ProjectTools(manager, tasks)
        self.demands = CodingDemands(self.core, tasks)
        if recover:
            with self.store.connection() as db:
                for raw in db.execute('SELECT document FROM growth_cycles').fetchall():
                    c = json.loads(raw[0])
                    if c['status'] not in TERMINAL:
                        c.update(status='STOPPING', stop_reason='restart_requires_reanalysis', final_status='INTERRUPTED')
                        self.write(db, c)

    @staticmethod
    def write(db, c):
        c['updated_at'] = now()
        raw = policy.canonical_json(c)
        if len(raw.encode()) > 192*1024: fail('成长记录达到单轮容量上限。')
        db.execute('UPDATE growth_cycles SET document=? WHERE id=?', (raw, c['id']))

    def save(self, c):
        with self.core.effect_guard(), self.store.connection() as db: self.write(db, c)

    def stored(self, cid, ident):
        scope = self.tools.scope(cid)
        with self.store.connection() as db:
            row = db.execute('SELECT document FROM growth_cycles WHERE id=?', (ident,)).fetchone()
        if not row: fail('未找到成长记录。', 'not_found')
        c = json.loads(row[0])
        if c['scope'] != scope: fail('成长记录不属于当前会话。', 'not_found')
        return c

    def snapshot(self, cid):
        scope = self.tools.scope(cid)
        with self.store.connection() as db:
            rows = db.execute("SELECT document FROM growth_cycles WHERE project_id=? ORDER BY rowid DESC LIMIT 30", (scope['project_id'],)).fetchall()
            p = read_policy(db, scope['project_id'])
        return {'policy': p, 'domains': listing(), 'cycles': [json.loads(r[0]) for r in rows],
                'defaults': {'window_seconds': 30, 'maximum_model_calls': 8, 'samples': 6},
                'note': '每轮 2 次以内编码调用 + 6 次正常模型对照；无在途成长时不调用模型。收益主指标是重复模型调用减少，费用和 token 单独列示。'}

    def configure(self, cid, payload):
        return configure(self.tools, cid, payload)

    def start(self, cid, payload):
        if not isinstance(payload, dict) or set(payload) != {'request_id', 'goal', 'domain', 'policy_revision'}:
            fail('成长请求需要原始需求、明确契约及策略修订。')
        if not isinstance(payload['request_id'], str) or not re.fullmatch('[a-f0-9]{32}', payload['request_id']):
            fail('成长请求编号无效。')
        if not isinstance(payload['goal'], str) or not 5 <= len(payload['goal']) <= 2000: fail('请保留原始需求。')
        from ..coding_secrets import ensure
        ensure(payload['goal'])
        spec = specification(payload['domain'])
        scope = self.tools.scope(cid)
        with self.manager.lock, self.core.effect_guard(), self.store.connection() as db:
            db.execute('BEGIN IMMEDIATE')
            row = db.execute('SELECT document FROM growth_cycles WHERE id=?', (payload['request_id'],)).fetchone()
            if row:
                old = json.loads(row[0])
                if old['submission'] != payload or old['scope'] != scope: fail('请求编号用于其他内容。')
                return old
            p = read_policy(db, scope['project_id'])
            if not p['enabled'] or p['revision'] != payload['policy_revision'] or spec['id'] not in p['domains'] or p['expires_at'] <= time.time():
                fail('此项目尚无适用且有效的成长策略。')
            rows = [json.loads(r[0]) for r in db.execute('SELECT document FROM growth_cycles')]
            if len(rows) >= 128: fail('成长记录达到 128 轮保留上限，请维护后再继续。')
            used = db.execute('PRAGMA page_count').fetchone()[0]*db.execute('PRAGMA page_size').fetchone()[0]
            if used + 2*1024*1024 > 28*1024*1024: fail('成长账本接近容量门槛，保留恢复空间后停止新轮次。')
            if any(c['status'] not in TERMINAL for c in rows): fail('已有一轮成长在处理。', 'evolution_busy')
            for old in rows:
                if old['scope']['project_id'] == scope['project_id'] and old['domain']['digest'] == spec['digest'] and old['status'] == 'COMPLETE':
                    active = db.execute('SELECT active FROM project_tools WHERE project_id=? AND tool_id=?',
                                        (scope['project_id'], old['tool_id'])).fetchone()
                    if active and active[0] == old['candidate_version']:
                        fail('已有此契约的已验证工具，请在项目工具库复用：'+old['tool_id'], 'growth_reuse_available')
            if sum(c['scope']['project_id'] == scope['project_id'] and c['policy']['revision'] == p['revision'] for c in rows) >= p['maximum_cycles']:
                fail('当前策略的轮次预算已用完，请核对记录后修订。')
            c = {'id': payload['request_id'], 'scope': scope, 'submission': copy.deepcopy(payload), 'policy': p,
                 'domain': spec, 'status': 'CODING', 'started_epoch': time.time(), 'created_at': now(),
                 'tool_id': 'growth-'+spec['id']+'-'+payload['request_id'][:8], 'pending': None,
                 'baseline': [], 'trials': [], 'uses': [], 'coding_receipts': [],
                 'events': [{'phase': 'CONTRACT_FROZEN', 'at': now(), 'domain_digest': spec['digest']}],
                 'feedback': {'source': 'not_provided', 'useful': None},
                 'reserved_model_calls': 8, 'candidate_version': None}
            # Insert then validate against the same transaction before committing.
            db.execute('INSERT INTO growth_cycles VALUES(?,?,?)', (c['id'], scope['project_id'], policy.canonical_json(c)))
            authorize(db, self.binding(c))
        return c

    @staticmethod
    def binding(c):
        return {'scope': c['scope'], 'growth_authorization': {'cycle_id': c['id'], 'revision': c['policy']['revision']}}

    def check(self, c):
        if self.tools.scope(c['scope']['conversation_id']) != c['scope']: fail('项目范围已改变。', 'growth_scope_changed')
        with self.store.connection() as db: authorize(db, self.binding(c))
        if c['domain'] != specification(c['domain']['id']): fail('独立验证器已变化。', 'growth_validator_changed')

    def stop(self, c, reason, final='PAUSED'):
        c.update(status='STOPPING', stop_reason=reason, final_status=final)
        self.save(c)
        pending = c.get('pending')
        if pending and pending['kind'] == 'coding':
            try:
                d = self.demands.lookup(c['scope']['conversation_id'], pending['payload']['request_id'])
                self.demands.cancel(c['scope']['conversation_id'], d['id'], {})
            except policy.CoreError as exc:
                if exc.code != 'not_found': raise
        elif pending:
            job = self.store.existing_job(pending['request_id'])
            if job and job['status'] in {'QUEUED', 'RUNNING', 'OBSERVING'}: self.manager.cancel(job['id'])

    def cancel(self, cid, ident):
        with self.manager.lock:
            c = self.stored(cid, ident)
            if c['status'] not in TERMINAL: self.stop(c, 'owner_cancelled', 'CANCELLED')
            return c

    def tick(self):
        """One bounded advancement per existing observer tick; reads idle once."""
        with self.manager.lock:
            if self.manager.closed.is_set(): return
            with self.store.connection() as db:
                row = db.execute("SELECT document FROM growth_cycles WHERE json_extract(document,'$.status') NOT IN ('COMPLETE','PAUSED','CANCELLED','INTERRUPTED') ORDER BY rowid LIMIT 1").fetchone()
            if not row: return
            c = json.loads(row[0])
            try:
                if c['status'] == 'STOPPING':
                    self.cleanup(c); return
                self.check(c)
                if c['pending']:
                    result = self.dispatch(c)
                    if result is None: return
                    self.consume(c, result)
                    return
                self.advance(c)
            except policy.CoreError as exc:
                if exc.code not in {'evolution_busy', 'queue_busy'}: self.stop(c, exc.code)
            except Exception as exc:
                c['internal_error_type'] = type(exc).__name__
                self.stop(c, 'growth_internal_error')

    def plan(self, c, kind, name, payload):
        c['pending'] = {'kind': kind, 'name': name, 'payload': payload,
                        'request_id': ('project-tool-' if kind == 'tool' else 'growth-baseline-')+key(c, name)}
        self.save(c)  # Durable intent before any external dispatch.

    def dispatch(self, c):
        p = c['pending']; cid = c['scope']['conversation_id']
        if p['kind'] == 'coding':
            d = self.demands.propose(cid, p['payload'], growth_request=self.binding(c))
            if d['status'] == 'PROPOSED':
                self.check(c); d = self.demands.start(cid, d['id'], {})
            if d['status'] in {'PROPOSED', 'QUEUED', 'RUNNING'}: return None
            if d['status'] != 'SUCCEEDED': fail('编码未确认成功；停止且不重发。', 'growth_coding_'+d['status'].lower())
            return d
        if p['kind'] == 'tool':
            j = self.tools.submit(cid, p['payload'], authorization=self.binding(c)['growth_authorization'])
        else:
            j = self.manager._enqueue({**self.binding(c), 'action': 'growth-baseline',
                                       'request_id': p['request_id'], 'input': p['payload'],
                                       'contract': c['domain']['contract'], 'model': c['policy']['model']})
        if j['status'] in {'QUEUED', 'RUNNING', 'OBSERVING'}: return None
        if j['status'] != 'SUCCEEDED': fail('子任务失败或结果未知，没有重发。', 'growth_child_'+j['status'].lower())
        return j

    def consume(self, c, result):
        step = c['pending']['name']; c['pending'] = None
        c['events'].append({'phase': step, 'at': now(), 'receipt': result['id']})
        if step == 'coding':
            c['task_id'] = result['task_id']
            report = json.loads(self.tools.tasks.artifact(c['scope']['conversation_id'], result['task_id']))['coding']
            c['coding_receipts'] = [a['model'] for a in report['attempts']]
            c['status'] = 'BASELINE'
        elif step.startswith('baseline-'):
            index = len(c['baseline']); r = result['result']
            c['baseline'].append({'job_id': result['id'], **r,
                                  'correct': r['text'] == c['domain']['samples'][index]['expected']})
            if not c['baseline'][-1]['correct']:
                self.stop(c, 'working_baseline_not_verified'); return
            if len(c['baseline']) == 6: c['status'] = 'STAGING'
        elif step == 'publish':
            c.update(status='CANARY', candidate_version=result['result']['version'], canary_epoch=time.time())
        elif step.startswith('trial-'):
            c['trials'].append({'job_id': result['id'], **result['result']['trial']})
        elif step == 'promote':
            c.update(status='OBSERVING', observation_epoch=time.time())
        elif step.startswith('use-'):
            c['uses'].append({'job_id': result['id'], **result['result']})
        self.save(c)

    def tool_plan(self, c, op, step, **extra):
        selected = self.tools.selected(c['scope']['project_id'], c['tool_id'])
        life = ToolLifecycle(self.tools).state(c['scope']['project_id'], c['tool_id'])
        p = {'operation': op, 'request_id': key(c, step), 'tool_id': c['tool_id'], 'generation': selected['generation'], **extra}
        if op in {'publish', 'trial', 'promote'}: p['lifecycle_revision'] = life['revision']
        if op in {'publish', 'promote'}: p.update(reviewed=True, review_note='预先审阅的限定成长策略 #'+str(c['policy']['revision']))
        self.plan(c, 'tool', step, p)

    def advance(self, c):
        s = c['status']; spec = c['domain']; p = c['policy']
        if s == 'CODING':
            path = 'jarvis_growth_'+c['id'][:12]+'.py'
            self.plan(c, 'coding', 'coding', {'request_id': key(c, 'coding'),
                'prompt': c['submission']['goal']+'\n本轮用户选择的唯一验收范围：'+spec['contract']+'\n只生成此接口；范围外保持未实现。',
                'coding': {'paths': [path], 'new_paths': [path], 'entrypoint': path,
                           'cases': spec['public'], 'heldout_cases': spec['heldout'],
                           'model': p['model'], 'coding_provider': 'gateway', 'build_recipe': 'python-package-v1'}})
        elif s == 'BASELINE':
            i = len(c['baseline'])
            self.plan(c, 'baseline', 'baseline-'+str(i), spec['samples'][i]['input'])
        elif s == 'STAGING':
            self.tool_plan(c, 'publish', 'publish', task_id=c['task_id'], name=spec['name'],
                           when_to_use=spec['contract'][:150], when_not_to_use='仅此冻结契约；其他含义、文件和网络操作均不适用。',
                           minimum_verified=3, maximum_trials=3, maximum_seconds=p['maximum_seconds'])
        elif s == 'CANARY':
            i = len(c['trials'])
            if i < 3:
                self.tool_plan(c, 'trial', 'trial-'+str(i), **spec['samples'][i], useful=True,
                               benefit_note='适用性依据用户选定契约；非主人体验反馈。')
            elif time.time()-c['canary_epoch'] >= p['window_seconds']:
                if any(x.get('peak_process_memory_bytes') is None or x['peak_process_memory_bytes'] > p['maximum_memory_bytes'] for x in c['trials']):
                    self.stop(c, 'memory_evidence_missing_or_over_budget'); return
                self.tool_plan(c, 'promote', 'promote')
        elif s == 'OBSERVING':
            i = len(c['uses'])
            if i < 3:
                self.tool_plan(c, 'run', 'use-'+str(i), **spec['samples'][i+3])
            elif time.time()-c['observation_epoch'] >= p['window_seconds']:
                c['assessment'] = self.assess(c)
                if c['assessment']['accepted']: c.update(status='COMPLETE'); self.save(c)
                else: self.stop(c, 'benefit_not_established')

    @staticmethod
    def assess(c):
        coding = accounting(c['coding_receipts'])
        baseline = accounting([x['receipt'] for x in c['baseline']])
        times = [x['candidate_seconds'] for x in c['trials']]+[x['elapsed_seconds'] for x in c['uses']]
        memory = [x.get('peak_process_memory_bytes') for x in c['trials']]+[x.get('isolation', {}).get('peak_process_memory_bytes') for x in c['uses']]
        saved = 6-coding['calls']
        verified = len(c['trials']) == 3 and len(c['uses']) == 3 and all(x['result_verified'] for x in c['uses'])
        return {'accepted': verified and saved >= c['policy']['minimum_calls_saved']
                and max(times, default=999) <= c['policy']['maximum_seconds']
                and all(type(m) is int and m <= c['policy']['maximum_memory_bytes'] for m in memory),
                'criterion': 'six independently verified uses, fewer repeated model calls after coding, bounded latency and memory',
                'samples': 6, 'verified': verified, 'calls_saved': saved, 'coding': coding,
                'working_model_baseline': baseline, 'experiment_model_calls': coding['calls']+baseline['calls'],
                'token_delta_baseline_minus_coding': baseline['tokens']-coding['tokens'] if baseline['tokens'] is not None and coding['tokens'] is not None else None,
                'amount_delta_baseline_minus_coding': baseline['amount']-coding['amount'] if baseline['amount'] is not None and coding['amount'] is not None and baseline['currency'] == coding['currency'] else None,
                'maximum_tool_seconds': max(times, default=None), 'maximum_worker_memory_bytes': max([m for m in memory if type(m) is int], default=None),
                'interventions': 0, 'user_feedback': c['feedback'],
                'limits': '短窗口、限定任务域；不证明长期稳定或总费用降低。对照调用计入实验支出，不计为实际节省。'}

    def cleanup(self, c):
        if self.manager.busy: return
        selected = self.tools.selected(c['scope']['project_id'], c['tool_id'])
        if c.get('candidate_version') and selected['active'] == c['candidate_version']:
            # Revocation forbids new capability admission, never prevents stopping
            # this cycle's own exact active version. Existing stable versions untouched.
            p = c.get('cleanup_payload') or {'operation': 'disable', 'request_id': key(c, 'cleanup'),
                                           'tool_id': c['tool_id'], 'generation': selected['generation']}
            c['cleanup_payload'] = p; self.save(c)
            j = self.tools.submit(c['scope']['conversation_id'], p)
            if j['status'] in {'QUEUED', 'RUNNING', 'OBSERVING'}: return
            if j['status'] != 'SUCCEEDED': fail('停用未确认，请核对工具库。', 'growth_cleanup_pending')
            c['cleanup_job'] = j['id']
        c.update(status=c.get('final_status', 'PAUSED'))
        c['events'].append({'phase': c['status'], 'at': now(), 'reason': c['stop_reason']})
        self.save(c)


def baseline(manager, job):
    """Normal working LLM workflow, never a deliberately broken comparison."""
    from .provider import gateway
    req = job['request']
    def check():
        manager._checkpoint()
        with manager.store.connection() as db: authorize(db, req)
    check(); manager._resources()
    config, provider = manager.provider.configuration(req['model'])
    response = gateway.probe(config, provider, policy.canonical_json(req['input']), manager.core.data_dir, check,
        admission_context=manager.core.effect_guard, cancel_event=manager.cancel_event, deadline_seconds=90,
        instructions='严格按以下契约转换输入，返回 JSON 对象且只有 text 字符串字段，不附解释或 Markdown。契约：'+req['contract'])
    receipt = manager.provider.receipt(response, config, provider)
    manager.store.update(job, baseline_receipt=receipt, model_outcome=response.get('status'))
    check()
    if response.get('status') != 'SUCCEEDED' or response.get('output_incomplete'): fail('对照调用未确认，未重发。', 'growth_baseline_failed')
    try:
        value = json.loads(response.get('text', ''))
        if not isinstance(value, dict) or set(value) != {'text'} or not isinstance(value['text'], str) or len(value['text'].encode()) > 8192: raise ValueError()
    except (ValueError, TypeError): fail('对照结果格式无效。', 'growth_baseline_invalid')
    return {'text': value['text'], 'receipt': receipt}
