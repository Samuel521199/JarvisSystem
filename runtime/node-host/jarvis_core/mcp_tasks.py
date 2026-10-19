"""Explicit read-only documentation tasks in the shared durable ledger/FIFO."""
import asyncio
import json
import os
import re
import time

from . import policy
from .ledger import TERMINAL_ACTIONS
from .mcp_catalog import McpManager
from .mcp_client import Context7Client, ENDPOINT, LIBRARY_ID
from .mcp_candidates import assess_candidate, resolve_scope
from .workspace import fields, identifier

CAPABILITY = 'mcp.documentation.v1'
TIMEOUT_SECONDS = 90
SOURCE_PATHS = ('runtime/node-host/jarvis_core/mcp_tasks.py', 'runtime/node-host/jarvis_core/mcp_client.py',
                'runtime/node-host/jarvis_core/mcp_candidates.py',
                'runtime/node-host/jarvis_core/documentation_admission.py', 'config/mcp/automation.json',
                'runtime/node-host/jarvis_core/mcp_catalog.py', 'config/mcp/catalog.json')


def configured(rows):
    return [r for r in rows if r['document']['config'] == {'transport': 'streamable-http', 'url': ENDPOINT}]


class McpTaskService:
    def __init__(self, core, *, client_factory=Context7Client):
        self.core, self.client_factory = core, client_factory
        self.manager = McpManager(core)

    @staticmethod
    def binding():
        return policy.digest(policy.canonical_json({p: policy.digest((policy.REPOSITORY_ROOT/p).read_bytes()) for p in SOURCE_PATHS}).encode())

    @staticmethod
    def validate(payload):
        fields(payload, {'prompt', 'library'}, {'project_id', 'conversation_id'})
        for key in ('prompt', 'library'):
            value = payload[key]
            if not isinstance(value, str) or not value.strip() or len(value.encode('utf-8')) > (2048 if key == 'prompt' else 160) or any(ord(c) < 32 for c in value):
                raise policy.CoreError('invalid_mcp_request', '请填写库名称或库 ID，以及单个文档问题（最多 2,048 UTF-8 字节）。')
        library = payload['library'].strip()
        if library.startswith('/') and not re.fullmatch(LIBRARY_ID, library):
            raise policy.CoreError('invalid_mcp_request', '库 ID 应为 /组织/项目 或 /组织/项目/版本。')
        for key in ('project_id', 'conversation_id'):
            if key in payload:
                identifier(payload[key])
        return {**payload, 'library': library, 'prompt': payload['prompt'].strip()}

    def selection(self, args, *, automatic=False):
        context = resolve_scope(self.core, args)
        item = next(r for r in self.manager.snapshot(context)['entries'] if r['id'] == 'context7')
        if item['policy']['mode'] == 'disabled':
            raise policy.CoreError('mcp_disabled', '当前作用域已停用 Context7。')
        if automatic:
            from .documentation_admission import settings
            automation = settings()
            if not automation['enabled'] or item['policy']['mode'] != 'auto':
                raise policy.CoreError('mcp_auto_disabled', '自动文档查询已关闭或当前规则仅允许手动使用。')
        rows = configured(item['registrations'])
        if len(rows) != 1 or len(item['registrations']) != 1:
            raise policy.CoreError('mcp_not_configured', '请在 MCP 工具页保留一个 Context7 官方 HTTP 连接；首期支持无凭据连接。')
        return {'registration_id': rows[0]['id'], 'revision': rows[0]['revision'],
                'policy': item['policy'], 'scope': context, 'selection': 'validated_dialogue_documentation' if automatic else 'explicit_documentation_task',
                **({'automation_digest': policy.digest(policy.canonical_json(automation).encode())} if automatic else {})}

    def assess_candidate(self, candidate, *, text, conversation_id=None, project_id=None):
        return assess_candidate(self, candidate, text=text, conversation_id=conversation_id, project_id=project_id)

    def admit(self, payload, *, automatic=None):
        args = self.validate(payload)
        args.update(resolve_scope(self.core, args))
        if automatic is not None:
            from .documentation_admission import RULE
            fields(automatic, {'kind','turn_id','decision_id','text_digest','rule'})
            identifier(automatic['turn_id']); identifier(automatic['decision_id'])
            if automatic['kind'] != 'dialogue' or automatic['rule'] != RULE or not re.fullmatch(r'sha256:[a-f0-9]{64}', automatic['text_digest']):
                raise policy.CoreError('invalid_mcp_origin', '自动文档查询来源无效。')
        return {**args, '_connection': self.selection(args, automatic=automatic is not None),
                **({'_origin': automatic} if automatic is not None else {})}

    def binding_for(self, args):
        # Only source IO here: the queue may call this under its ledger write lock.
        # The immutable arguments carry the connection/policy admission snapshot.
        return self.binding()

    def run(self, action_id, *, _before_dispatch=None):
        with self.core.ledger.worker_lock():
            self.core.ledger.recover_orphans()
            record = self.core.ledger.record(action_id)
            if record['action']['capability_id'] != CAPABILITY:
                raise policy.CoreError('wrong_executor', '此任务需要文档 MCP 执行器。')
            if record['action']['status'] in TERMINAL_ACTIONS:
                if record['artifact']:
                    self.core._verify_artifact(record['artifact'])
                return record
            record = self.core.ledger.begin_dispatch(action_id, self.core.host_instance_id, _admission=_before_dispatch)
            task_id, attempted_write, client = record['task']['task_id'], False, None
            deadline = time.monotonic() + TIMEOUT_SECONDS
            try:
                arguments = record['action']['arguments']
                args = self.validate({k: v for k, v in arguments.items() if k not in {'_connection','_origin'}})
                selected = arguments['_connection']
                from .network_policy import NetworkPolicy
                network = NetworkPolicy(self.core.data_dir)
                network_revision = network.require_online()
                def checkpoint():
                    network.require_online(network_revision)
                    self.core.assert_running()
                    self.core.ledger.assert_admitted(task_id)
                    if time.monotonic() > deadline:
                        raise policy.CoreError('mcp_timeout', 'MCP 任务等待预算用完；未自动重试。')
                    if self.selection(args, automatic='_origin' in arguments) != selected:
                        raise policy.CoreError('mcp_policy_changed', '连接配置或选用规则已改变，停止此任务。')
                checkpoint()
                client = self.client_factory(checkpoint)
                client.network_checkpoint = lambda: network.require_online(network_revision)
                report = asyncio.run(client.query(args['library'], args['prompt']))
                checkpoint()
                report['selection'] = selected
                if '_origin' in arguments: report['origin'] = arguments['_origin']
                raw = (policy.canonical_json(report) + '\n').encode('utf-8')
                if len(raw) > policy.MAX_OUTPUT_BYTES:
                    raise policy.CoreError('mcp_output_limit', 'MCP 回执过大。')
                filename = action_id + '.json'
                artifact = {'schema_version': '1.0.0', 'artifact_id': 'artifact_' + action_id[4:], 'task_id': task_id,
                            'action_id': action_id, 'path': filename, 'digest': policy.digest(raw),
                            'media_type': 'application/json', 'size_bytes': len(raw)}
                with self.core.ledger.effect_guard(task_id, expected_epoch=self.core._security_epoch) as db:
                    attempted_write = True
                    destination = policy.safe_path(self.core.ledger.artifact_dir/filename, must_exist=False)
                    with destination.open('xb') as stream:
                        stream.write(raw); stream.flush(); os.fsync(stream.fileno())
                    self.core._verify_artifact(artifact)
                    self.core.ledger.complete(db, action_id, artifact)
            except Exception as exc:
                code = getattr(exc, 'code', 'mcp_network_error')
                uncertain = code in {'mcp_timeout', 'mcp_network_error', 'mcp_incomplete', 'mcp_http_error', 'network_offline', 'network_policy_changed'} and client is not None and client.dispatched
                status = 'UNKNOWN' if attempted_write or uncertain else 'CANCELLED' if code in {'cancelled', 'stopped'} else 'FAILED'
                self.core.ledger.finish_without_receipt(action_id, status, {'code': code,
                    'message': str(exc) if isinstance(exc, policy.CoreError) else 'MCP 网络请求未完成；没有自动重试。'})
            return self.core.ledger.record(action_id)
