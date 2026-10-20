"""Two distinct model contexts, one parent task, durable per-call reservations."""
import json
import os
import time

from . import policy
from .ledger import TERMINAL_ACTIONS, now
from .team_protocol import CAPABILITY, TIMEOUT_SECONDS, ROLES, INSTRUCTIONS, validate, criterion_rows, decode

SOURCE_PATHS = (
    'runtime/node-host/jarvis_core/team_tasks.py',
    'runtime/node-host/jarvis_core/team_protocol.py',
    'runtime/node-host/jarvis_core/evolution/provider.py',
    'runtime/node-host/jarvis_core/dialogue_process.py',
    'runtime/node-host/jarvis_core/dialogue_worker.py',
)


class TeamTaskService:
    def __init__(self, core, *, config_path=None, model_calls=None, provider=None):
        self.core, self.model_calls = core, model_calls
        from .evolution.provider import ModelCodingProvider
        self.provider = provider or ModelCodingProvider(core, config_path)
        with core.ledger.transaction() as db:
            db.execute('CREATE TABLE IF NOT EXISTS team_calls('
                       'task_id TEXT NOT NULL REFERENCES tasks(task_id), ordinal INTEGER NOT NULL, '
                       'document TEXT NOT NULL, PRIMARY KEY(task_id,ordinal))')

    @staticmethod
    def binding():
        return policy.digest(policy.canonical_json({
            p: policy.digest((policy.REPOSITORY_ROOT/p).read_bytes()) for p in SOURCE_PATHS}).encode())

    def configuration(self, args, role):
        config, provider = self.provider.configuration(args[role+'_model'], args.get(role+'_reasoning'))
        from jarvis_models.catalog import resolve_settings
        settings = resolve_settings(config, provider)
        selected = config['providers'][provider]
        model = args[role+'_model'].split('::', 1)[1]
        parameters = selected['models'][model].setdefault('parameters', {}) if 'models' in selected else selected
        parameters['max_output_tokens'] = min(settings.get('max_output_tokens', 2048), 2048)
        return config, provider

    def admit(self, payload):
        args = validate(payload)
        if self.model_calls is None:
            raise policy.CoreError('team_unavailable', '后台模型进程尚未接入。')
        args['_bindings'] = {role: policy.digest(policy.canonical_json(self.configuration(args, role)).encode()) for role in ROLES}
        return args

    def calls(self, task_id):
        record = self.core.ledger.record(task_id=task_id)
        with self.core.ledger.connection() as db:
            rows = [json.loads(r['document']) for r in db.execute(
                'SELECT document FROM team_calls WHERE task_id=? ORDER BY ordinal', (task_id,))]
        # An interrupted reservation never becomes spendable again.
        for row in rows:
            if row['state'] == 'RESERVED' and record['action']['status'] in TERMINAL_ACTIONS:
                row['state'] = 'UNCERTAIN'
        return rows

    def reserve(self, task_id, role):
        ordinal = ROLES.index(role)
        with self.core.ledger.effect_guard(task_id, expected_epoch=self.core._security_epoch) as db:
            action_id = db.execute('SELECT action_id FROM actions WHERE task_id=?', (task_id,)).fetchone()['action_id']
            record = self.core.ledger._record(db, action_id)
            used = db.execute('SELECT ordinal,document FROM team_calls WHERE task_id=? ORDER BY ordinal', (task_id,)).fetchall()
            if record['action']['status'] != 'DISPATCHING' or len(used) != ordinal or len(used) >= min(2, record['task']['budget']['max_cost_units']):
                raise policy.CoreError('team_budget', '角色顺序或父任务预算不允许新的调用。')
            if any(json.loads(r['document'])['state'] != 'SUCCEEDED' for r in used):
                raise policy.CoreError('team_dependency', '前序角色没有有效回执。')
            args = record['action']['arguments']
            row = {'schema_version': 1, 'ordinal': ordinal, 'role': role, 'state': 'RESERVED', 'reserved_calls': 1,
                   'root_task_id': task_id, 'security_epoch': self.core._security_epoch,
                   'model': args[role+'_model'], 'created_at': now()}
            db.execute('INSERT INTO team_calls VALUES(?,?,?)', (task_id, ordinal, policy.canonical_json(row)))
        return row

    def settle(self, row, state, *, receipt=None, output=None, rejected_text=None):
        row = {**row, 'state': state, 'updated_at': now()}
        if receipt is not None: row['receipt'] = receipt
        if output is not None: row['output'] = output
        if rejected_text is not None: row['rejected_text'] = rejected_text
        # Receipt bookkeeping is allowed after cancellation; it grants no effects.
        with self.core.ledger.transaction() as db:
            db.execute('UPDATE team_calls SET document=? WHERE task_id=? AND ordinal=?',
                       (policy.canonical_json(row), row['root_task_id'], row['ordinal']))

    def run(self, action_id, *, _before_dispatch=None):
        with self.core.ledger.worker_lock():
            self.core.ledger.recover_orphans()
            record = self.core.ledger.record(action_id)
            if record['action']['capability_id'] != CAPABILITY:
                raise policy.CoreError('wrong_executor', '此任务需要协作执行器。')
            if record['action']['status'] in TERMINAL_ACTIONS:
                if record['artifact']: self.core._verify_artifact(record['artifact'])
                return record
            record = self.core.ledger.begin_dispatch(action_id, self.core.host_instance_id, _admission=_before_dispatch)
            task_id = record['task']['task_id']
            deadline, attempted_write, pending = time.monotonic()+TIMEOUT_SECONDS, False, None

            def checkpoint():
                control = self.core.assert_running()
                self.core.ledger.assert_admitted(task_id)
                if time.monotonic() >= deadline:
                    raise policy.CoreError('team_timeout', '协作等待预算已用完。')
                return control

            try:
                arguments = record['action']['arguments']
                args = validate({k: v for k, v in arguments.items() if k != '_bindings'})
                proposal = None
                for role in ROLES:
                    checkpoint()
                    config, provider = self.configuration(args, role)
                    if policy.digest(policy.canonical_json((config, provider)).encode()) != arguments['_bindings'][role]:
                        raise policy.CoreError('team_route_changed', '角色模型配置已变化，请核对后重新提交。')
                    prompt = {'goal': args['prompt'], 'criteria': criterion_rows(args)}
                    if proposal is not None: prompt['proposal'] = proposal
                    pending = self.reserve(task_id, role)
                    # No history, personal memory, tools, file access or nested delegation.
                    response = self.model_calls.probe(config, provider, policy.canonical_json(prompt),
                        self.core.data_dir, checkpoint, task_id=task_id, instructions=INSTRUCTIONS[role],
                        deadline_seconds=min(55, max(1, deadline-time.monotonic())))
                    receipt = self.provider.receipt(response, config, provider)
                    if response.get('status') == 'UNKNOWN' or response.get('outcome_uncertain'):
                        self.settle(pending, 'UNCERTAIN', receipt=receipt); pending = None
                        raise policy.CoreError('team_model_unknown', '角色调用结果不明，保留预算占用，未重试或切换模型。')
                    if response.get('status') != 'SUCCEEDED' or response.get('output_incomplete'):
                        self.settle(pending, 'FAILED', receipt=receipt); pending = None
                        checkpoint()
                        raise policy.CoreError('team_model_failed', '角色调用未完成；未启动后续角色。')
                    try:
                        output = decode(response.get('text'), role, args, proposal)
                    except policy.CoreError:
                        raw_text = response.get('text', '')
                        from .team_protocol import MAX_REPLY_BYTES
                        rejected = raw_text.encode()[:MAX_REPLY_BYTES].decode('utf-8', errors='ignore') if isinstance(raw_text, str) else ''
                        self.settle(pending, 'INVALID', receipt=receipt, rejected_text=rejected); pending = None
                        raise
                    self.settle(pending, 'SUCCEEDED', receipt=receipt, output=output); pending = None
                    checkpoint()
                    if role == 'planner': proposal = output
                report = {
                    'schema_version': 1, 'kind': 'jarvis.team-report', 'goal': args['prompt'],
                    'criteria': criterion_rows(args), 'proposal': proposal, 'review': output,
                    'roles': self.calls(task_id), 'decision': output['verdict'],
                    'budget': {'max_model_calls': 2, 'reserved_calls': 2, 'max_runtime_seconds': TIMEOUT_SECONDS,
                               'max_output_tokens_per_call': 2048, 'automatic_retries': 0},
                    'checks': {'structure_valid': True, 'references_valid': True,
                               'separate_model_contexts': True, 'semantic_acceptance_verified': False,
                               'tools_executed': False, 'personal_memory_accessed': False},
                    'limits': '模型审阅意见不等于事实核验或业务验收；没有自动应用方案、执行工具或更新记忆。'
                }
                raw = (policy.canonical_json(report)+'\n').encode()
                if len(raw) > policy.MAX_OUTPUT_BYTES:
                    raise policy.CoreError('team_output_limit', '协作报告超过产物上限。')
                artifact = {'schema_version': '1.0.0', 'artifact_id': 'artifact_'+action_id[4:],
                            'task_id': task_id, 'action_id': action_id, 'path': action_id+'.json',
                            'digest': policy.digest(raw), 'media_type': 'application/json', 'size_bytes': len(raw)}
                checkpoint()
                with self.core.ledger.effect_guard(task_id, expected_epoch=self.core._security_epoch) as db:
                    attempted_write = True
                    destination = policy.safe_path(self.core.ledger.artifact_dir/artifact['path'], must_exist=False)
                    with destination.open('xb') as stream:
                        stream.write(raw); stream.flush(); os.fsync(stream.fileno())
                    self.core._verify_artifact(artifact)
                    self.core.ledger.complete(db, action_id, artifact)
            except Exception as exc:
                if pending is not None:
                    self.settle(pending, 'UNCERTAIN')
                code = getattr(exc, 'code', 'team_internal_error')
                status = 'UNKNOWN' if attempted_write or pending is not None or code == 'team_model_unknown' else 'CANCELLED' if code in {'cancelled', 'stopped'} else 'FAILED'
                self.core.ledger.finish_without_receipt(action_id, status, {'code': code,
                    'message': str(exc) if isinstance(exc, policy.CoreError) else '协作未完成；没有自动重发。'})
            return self.core.ledger.record(action_id)
