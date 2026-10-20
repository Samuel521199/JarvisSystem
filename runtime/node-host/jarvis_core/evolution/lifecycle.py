"""Explicit admission, bounded real-input canaries, evidence and reversible retirement.

One small projection in the existing growth DB; all commands and trials retain
their original jobs. No timers, models, filesystem cleanup or new task lane.
"""
import copy
import json
import time
from .. import policy
from .catalog import encoded, fail, runtime_binding, FAULTS
from .store import now

OPERATIONS = {'publish', 'trial', 'promote', 'pause', 'resume', 'discard', 'retire', 'restore', 'retire-version','archive-version','load-version'}


def checked_note(value):
    if not isinstance(value, str) or len(value.strip()) < 5 or len(value) > 1000 or '\0' in value:
        fail('请说明本次审阅、用途或退役依据（5—1000 字符）。')


class ToolLifecycle:
    def __init__(self, tools):
        self.tools, self.store, self.core = tools, tools.store, tools.core

    def state(self, project, tool):
        with self.store.connection() as db:
            row = db.execute('SELECT document FROM tool_lifecycle WHERE project_id=? AND tool_id=?', (project, tool)).fetchone()
        return json.loads(row[0]) if row else {'revision': 0, 'phase': 'LEGACY', 'candidate': None}

    def validate(self, payload):
        op = payload['operation']
        extra = {'publish': {'reviewed', 'review_note', 'minimum_verified', 'maximum_trials', 'maximum_seconds'},
                 'trial': {'expected', 'useful', 'benefit_note'},
                 'retire-version': {'version', 'reviewed', 'review_note'}}
        if op in {'archive-version','load-version'}:extra[op]={'version','reviewed','review_note'}
        common = {'operation', 'request_id', 'tool_id', 'generation', 'lifecycle_revision'}
        if op == 'publish': common |= {'task_id', 'name', 'when_to_use', 'when_not_to_use'}
        if op == 'trial': common |= {'input'}
        required = common | extra.get(op, {'reviewed', 'review_note'})
        if set(payload) != required: fail('工具生命周期请求字段不完整；请刷新后按审阅/灰度入口提交。')
        if type(payload['lifecycle_revision']) is not int or payload['lifecycle_revision'] < 0:
            fail('生命周期修订无效。')
        if op == 'trial':
            encoded(payload['input'])
            if not isinstance(payload['expected'], str) or len(payload['expected'].encode()) > 16384:
                fail('灰度试用需要本次独立预期，最多 16 KiB，可为空字符串。')
            if type(payload['useful']) is not bool: fail('请明确本次用途反馈。')
            checked_note(payload['benefit_note'])
        else:
            if payload['reviewed'] is not True: fail('请先明确核对本次操作。')
            checked_note(payload['review_note'])
        if op == 'publish':
            for key, lo, hi in (('minimum_verified', 2, 10), ('maximum_trials', 2, 30), ('maximum_seconds', 1, 30)):
                if type(payload[key]) is not int or not lo <= payload[key] <= hi: fail('灰度门槛超出限定范围。')
            if payload['maximum_trials'] < payload['minimum_verified']: fail('试用上限不能小于核验数量。')
        if op in {'retire-version','archive-version','load-version'} and (not isinstance(payload['version'], str) or len(payload['version']) != 64
                                      or any(c not in '0123456789abcdef' for c in payload['version'])):
            fail('旧版本标识无效。')

    def fresh(self, job):
        self.tools.checkpoint(job)
        req = job['request']; base = req['base']
        if self.tools.selected(base['project_id'], base['tool_id']) != base:
            fail('稳定工具代际变化，请重新核对。', 'evolution_conflict')
        current = self.state(base['project_id'], base['tool_id'])
        if current != req['lifecycle']: fail('灰度或退役状态已变化，请刷新原记录。', 'evolution_conflict')
        return current

    def write(self, job, value, *, quarantine=None, retire_version=None, confirm=False, selection=None, version_update=None):
        self.tools.checkpoint(job)
        req = job['request']; base = req['base']
        with self.core.effect_guard(), self.store.connection() as db:
            db.execute('BEGIN IMMEDIATE')
            row = db.execute('SELECT document FROM tool_lifecycle WHERE project_id=? AND tool_id=?', (base['project_id'], base['tool_id'])).fetchone()
            current = json.loads(row[0]) if row else {'revision': 0, 'phase': 'LEGACY', 'candidate': None}
            if current != req['lifecycle']: fail('生命周期修订冲突。', 'evolution_conflict')
            selected = db.execute('SELECT * FROM project_tools WHERE project_id=? AND tool_id=?', (base['project_id'], base['tool_id'])).fetchone()
            selected = dict(selected) if selected else base
            expected = job.get('tool_activation')
            if expected:
                if selected['generation'] != expected['generation'] or selected['active'] != expected['version']:
                    fail('启用观察基线变化。', 'evolution_conflict')
            elif selected != base: fail('工具代际冲突。', 'evolution_conflict')
            if version_update:
                ident,old_state,old_raw,target,new_raw=version_update
                if db.execute('UPDATE tool_versions SET state=?,document=? WHERE id=? AND state=? AND document=?',
                              (target,new_raw,ident,old_state,old_raw)).rowcount!=1:fail('版本存储修订冲突。','evolution_conflict')
            if row is None and not db.execute('SELECT 1 FROM project_tools WHERE project_id=? AND tool_id=?',(base['project_id'],base['tool_id'])).fetchone():
                from .maintenance import directory_count
                if directory_count(db)>=32: fail('工具目录达到上限。')
                if db.execute('SELECT COUNT(*) FROM project_tools').fetchone()[0]>=288: fail('目录身份总索引达到 288 项上限。')
                db.execute('INSERT INTO project_tools VALUES(?,?,?,?,?)',(base['project_id'],base['tool_id'],base['active'],base['previous'],base['generation']))
            if selection is not None:
                db.execute('UPDATE project_tools SET active=?,previous=?,generation=generation+1 WHERE project_id=? AND tool_id=?',
                           (*selection,base['project_id'],base['tool_id']))
                job['tool_activation']={'project_id':base['project_id'],'tool_id':base['tool_id'],
                                        'version':selection[0],'generation':base['generation']+1}
                job['tool_activation_confirmed']=True
            value = {**copy.deepcopy(value), 'revision': current['revision']+1, 'updated_at': now(), 'last_job': job['id']}
            db.execute('INSERT INTO tool_lifecycle VALUES(?,?,?) ON CONFLICT(project_id,tool_id) DO UPDATE SET document=excluded.document',
                       (base['project_id'], base['tool_id'], policy.canonical_json(value)))
            if quarantine: db.execute("UPDATE tool_versions SET state='QUARANTINED' WHERE id=?", (quarantine,))
            if retire_version: db.execute("UPDATE tool_versions SET state='RETIRED' WHERE id=?", (retire_version,))
            if confirm: job['tool_activation_confirmed'] = True
            job['lifecycle_transition'] = {'phase': value['phase'], 'revision': value['revision']}
            self.store.write_job(db, job)
        return value

    def assessment(self, project, tool, value=None, jobs=None):
        value = value or self.state(project, tool)
        if jobs is None:
            with self.store.connection() as db:
                jobs = [self.store.hydrate(r[0]) for r in db.execute("SELECT document FROM jobs WHERE json_extract(document,'$.request.action')='project-tool' AND json_extract(document,'$.request.scope.project_id')=? AND json_extract(document,'$.request.submission.tool_id')=? ORDER BY rowid", (project, tool))]
        trials = [j for j in jobs if j['request']['submission']['operation'] == 'trial' and j['request'].get('lifecycle', {}).get('admission_id') == value.get('admission_id')]
        eligible = {}; paired = []
        for j in sorted(trials,key=lambda j:j['created_at']):
            e = (j.get('result') or {}).get('trial')
            if j['status'] == 'SUCCEEDED' and e and e['passed'] and e['novel']:
                eligible[e['input_digest']] = e
        paired = [{'candidate_seconds':e['candidate_seconds'], 'baseline_seconds':e['baseline']['elapsed_seconds'],
                   'baseline_correct':e['baseline']['correct'],'baseline_error':e['baseline'].get('error'),
                   'candidate_peak_process_memory_bytes':e.get('peak_process_memory_bytes'),
                   'baseline_peak_process_memory_bytes':e['baseline'].get('peak_process_memory_bytes')}
                  for e in eligible.values() if e.get('baseline')]
        useful = sum(e['useful'] for e in eligible.values())
        failures = sum(j['status'] == 'FAILED' for j in trials)
        limits = value.get('limits', {'minimum_verified':2, 'maximum_trials':10, 'maximum_seconds':15})
        fresh = value.get('runtime_binding') == runtime_binding()
        selected = self.tools.selected(project, tool)
        stable_matches = value.get('baseline') == selected if value['phase'] in {'CANARY','PAUSED'} else True
        ready = value['phase'] == 'CANARY' and fresh and stable_matches and len(eligible) >= limits['minimum_verified'] and useful > 0 and failures == 0
        return {'phase':value['phase'], 'trials':len(trials), 'verified_novel_inputs':len(eligible), 'useful_inputs':useful,
                'failed_trials':failures, 'eligible_to_promote':ready, 'runtime_current':fresh, 'stable_current':stable_matches,
                'paired_observations':paired, 'limits':limits, 'model_calls':0,
                'paired_quality_improvements':sum(e['baseline_correct'] is False for e in paired),
                'benefit_basis':'独立预期核验和本地调用者用途声明；延迟配对含进程启动噪声，不能据此宣称通用净收益或 token 节省。',
                'recommendation':'可核对后正式启用' if ready else '继续观察或保持暂停；证据不足不宣称有效进步'}

    def execute(self, job):
        req = job['request']; p = req['submission']; base = req['base']; op = p['operation']
        value = self.fresh(job); check = lambda: self.fresh(job)
        if op in {'archive-version','load-version'}:
            from .tool_archive import ToolArchive
            return ToolArchive(self).execute(job,value)
        if op == 'publish':
            if value['phase'] in {'CANARY', 'PAUSED', 'RETIRED'}: fail('请先处理原灰度或退役记录，不能覆盖在途候选。')
            doc = req['package']; proof = self.tools.evaluate(doc, check)
            ident = policy.digest(policy.canonical_json(doc).encode())[7:]
            if ident == base['active']: fail('候选已经是稳定版本，无须再次准入。')
            with self.store.connection() as db:
                if not db.execute('SELECT 1 FROM tool_versions WHERE id=?',(ident,)).fetchone() and db.execute("SELECT COUNT(*) FROM tool_versions WHERE state!='ARCHIVED'").fetchone()[0] >= 64: fail('在线版本保留达到上限；请审阅退役归档。')
                db.execute('INSERT OR IGNORE INTO tool_versions VALUES(?,?,?)', (ident, 'VERIFIED', policy.canonical_json(doc)))
                if db.execute('SELECT state FROM tool_versions WHERE id=?',(ident,)).fetchone()[0] != 'VERIFIED': fail('该版本已隔离或退役。')
            self.write(job, {'phase':'CANARY','candidate':ident,'admission_id':job['id'], 'runtime_binding':req['runtime_binding'],
                             'baseline':base,'limits':{k:p[k] for k in ('minimum_verified','maximum_trials','maximum_seconds')},
                             'contract_quality':req['contract_quality'],
                             'review':{'note':p['review_note'],'source':'explicit_local_review','semantic_truth_verified':False}})
            return {'version':ident,'staged':True,'stable_unchanged':True,'validation':proof,'model_calls':0}
        if op == 'trial':
            if value['phase'] != 'CANARY' or value['baseline'] != base or value['runtime_binding'] != req['runtime_binding']:
                fail('候选未在有效灰度期，或基线/执行器变化，请核对原记录。')
            assessment = self.assessment(base['project_id'],base['tool_id'],value)
            if assessment['trials'] > value['limits']['maximum_trials']: fail('灰度试用次数已用完。')
            try:
                doc,state = self.tools.package(value['candidate'],base)
                if state != 'VERIFIED': fail('灰度包未验证。','tool_package_changed')
                proof = self.tools.evaluate(doc,check)
                tick = time.monotonic(); outputs,evidence = self.tools.manager.runner.run_build(doc['build'],[p['input']],check)
                elapsed = time.monotonic()-tick
                if len(outputs)!=1 or outputs[0] != p['expected']: fail('灰度结果不符合独立预期；稳定工具未切换。','tool_result_mismatch')
                if elapsed > value['limits']['maximum_seconds']: fail('候选超过本次冻结延迟门槛。','tool_trial_slow')
                baseline = None
                if base['active']:
                    try:
                        old,state = self.tools.package(base['active'],base)
                        if state != 'VERIFIED': fail('旧稳定包不适合配对。','tool_package_changed')
                        self.tools.evaluate(old,check); tick=time.monotonic()
                        other,old_evidence=self.tools.manager.runner.run_build(old['build'],[p['input']],check)
                        baseline={'elapsed_seconds':round(time.monotonic()-tick,4),'correct':other==[p['expected']],
                                  'peak_process_memory_bytes':old_evidence.get('peak_process_memory_bytes')}
                    except policy.CoreError as exc:
                        if exc.code not in FAULTS: raise
                        baseline={'correct':False,'error':exc.code,'elapsed_seconds':None}
                trial={'passed':True,'version':value['candidate'],'input_digest':policy.digest(encoded(p['input'])),
                       'novel':all(encoded(c['input'])!=encoded(p['input']) for c in doc['cases']),
                       'useful':p['useful'],'usefulness_source':'explicit_local_review','benefit_note':p['benefit_note'],
                       'candidate_seconds':round(elapsed,4),'peak_process_memory_bytes':evidence.get('peak_process_memory_bytes'),'baseline':baseline}
                check(); self.tools.package(value['candidate'],base)
                return {'trial':trial,'text':outputs[0],'result_verified':True,'regression':proof,'isolation':evidence,'model_calls':0}
            except policy.CoreError as exc:
                if exc.code in FAULTS|{'tool_trial_slow'}:
                    self.write(job,{**value,'phase':'REJECTED','reason':exc.code},quarantine=value['candidate'])
                raise
        if op == 'promote':
            if not self.assessment(base['project_id'],base['tool_id'],value)['eligible_to_promote']:
                fail('真实新输入、用途反馈或灰度基线尚未达到准入条件。')
            try:
                doc,state=self.tools.package(value['candidate'],base)
                if state!='VERIFIED': fail('候选不可启用。','tool_package_changed')
                proof=self.tools.evaluate(doc,check)
            except policy.CoreError as exc:
                if exc.code in FAULTS:self.write(job,{**value,'phase':'REJECTED','reason':exc.code},quarantine=value['candidate'])
                raise
            # Previous stable is frozen for recovery; input is never replayed.
            job['tool_recovery_previous']=base['active']
            previous=base['active'] or (base['previous'] if base['previous']!=value['candidate'] else None)
            self.tools.select(job,value['candidate'],previous,observing=True)
            self.tools.evaluate(doc,lambda:self.tools.checkpoint(job))
            self.write(job,{**value,'phase':'ACTIVE','promotion_review':p['review_note']},confirm=True)
            return {'version':value['candidate'],'promoted':True,'validation':proof,'model_calls':0}
        if op == 'pause':
            if value['phase']!='CANARY': fail('只有灰度候选可以暂停。')
            self.write(job,{**value,'phase':'PAUSED','reason':p['review_note']})
        elif op == 'resume':
            if value['phase']!='PAUSED' or value['baseline']!=base or value['runtime_binding']!=req['runtime_binding']:
                fail('灰度基线变化，不能沿用旧准入；请重新审阅候选。')
            doc,state=self.tools.package(value['candidate'],base)
            if state!='VERIFIED': fail('候选已隔离或退役。')
            self.tools.evaluate(doc,check);self.write(job,{**value,'phase':'CANARY','reason':p['review_note']})
        elif op == 'discard':
            if value['phase'] not in {'CANARY','PAUSED','REJECTED'}:fail('没有待放弃的灰度候选。')
            self.write(job,{**value,'phase':'ABANDONED','candidate':None,'reason':p['review_note']})
        elif op == 'retire':
            if value['phase']=='RETIRED': fail('此工具已经退役，请核对原记录。')
            self.write(job,{**value,'phase':'RETIRED','candidate':None,'retired_version':base['active'] or base['previous'] or value.get('candidate'),
                            'retired_candidate':value.get('candidate'),'reason':p['review_note']},
                       selection=(None,base['active'] or base['previous']))
        elif op == 'restore':
            if value['phase']!='RETIRED' or not value.get('retired_version'): fail('没有可重新准入的退役版本。')
            doc,state=self.tools.package(value['retired_version'],base)
            if state!='VERIFIED': fail('旧包已隔离或损坏，不能恢复。')
            self.tools.evaluate(doc,check)
            self.write(job,{**value,'phase':'CANARY','candidate':value['retired_version'],'baseline':base,
                            'admission_id':job['id'],'runtime_binding':req['runtime_binding'],
                            'review':{'note':p['review_note'],'source':'explicit_local_review','semantic_truth_verified':False},
                            'limits':value.get('limits',{'minimum_verified':2,'maximum_trials':10,'maximum_seconds':15}),
                            'reason':p['review_note']})
        elif op == 'retire-version':
            ident=p['version'];self.tools.package(ident,base)
            if ident in {base['active'],base['previous'],value.get('candidate'),value.get('retired_version'),value.get('retired_candidate')}:
                fail('该版本仍被稳定/灰度/恢复引用，不能退役。')
            self.write(job,value,retire_version=ident)
        return {'operation':op,'lifecycle':job['lifecycle_transition'],'model_calls':0,'files_deleted':0}
