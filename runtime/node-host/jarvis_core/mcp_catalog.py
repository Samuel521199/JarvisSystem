"""Curated MCP discovery and preferences; registrations confer no execution rights."""
import json

from . import policy
from .extensions import ExtensionCatalog
from .workspace import fields, identifier, timestamp

CATALOG = policy.REPOSITORY_ROOT / 'config/mcp/catalog.json'
MODES = {'auto', 'manual', 'disabled'}
SCOPES = {'global', 'project', 'conversation'}


def catalog():
    raw = policy.safe_path(CATALOG, directory=False).read_bytes()
    if len(raw) > 128 * 1024:
        raise policy.CoreError('mcp_catalog_invalid', 'MCP 目录超过大小限制。')
    data = json.loads(raw)
    from jsonschema import Draft202012Validator
    schema = json.loads((policy.REPOSITORY_ROOT / 'contracts/schemas/mcp-catalog.schema.json').read_text(encoding='utf-8'))
    if not Draft202012Validator(schema).is_valid(data):
        raise policy.CoreError('mcp_catalog_invalid', 'MCP 目录未通过契约检查。')
    ids = [s['id'] for s in data['servers']]
    if len(ids) != len(set(ids)):
        raise policy.CoreError('mcp_catalog_invalid', 'MCP 标识重复。')
    return data, policy.digest(raw)


class McpManager:
    def __init__(self, core):
        self.core = core
        self.extensions = ExtensionCatalog(core)

    @staticmethod
    def _tables(db):
        db.execute('CREATE TABLE IF NOT EXISTS mcp_policies(scope TEXT NOT NULL,scope_id TEXT NOT NULL,mcp_id TEXT NOT NULL,revision INTEGER NOT NULL,mode TEXT NOT NULL,updated_at TEXT NOT NULL,PRIMARY KEY(scope,scope_id,mcp_id))')

    @staticmethod
    def _context(context):
        context = {} if context is None else context
        fields(context, set(), {'project_id', 'conversation_id'})
        for value in context.values():
            identifier(value)
        return context

    @staticmethod
    def _policy(db, ident, context):
        mode, source = 'auto', 'package_default'
        overrides = [dict(r) for r in db.execute('SELECT scope,scope_id,mode,revision FROM mcp_policies WHERE mcp_id=?', (ident,))]
        for scope, target in [('global', ''), ('project', context.get('project_id')), ('conversation', context.get('conversation_id'))]:
            row = next((r for r in overrides if r['scope'] == scope and r['scope_id'] == target), None)
            if row and row['mode'] != 'inherit':
                mode, source = row['mode'], scope
        return {'mode': mode, 'source': source}, overrides

    def snapshot(self, context=None):
        context = self._context(context)
        data, digest = catalog()
        entries = self.extensions.list()['entries']
        registrations = [r for r in entries if r['kind'] == 'mcp']
        from .documentation_admission import settings
        try:
            automation = settings()
            auto_enabled = automation['enabled'] and 'vertex::gemini-3.8-flash' in automation['routes']
        except Exception:
            auto_enabled = False
        known = {x['id'] for x in data['servers']}
        result = []
        with self.core.ledger.connection() as ledger:
            latest = ledger.execute("SELECT t.document AS task,a.document AS action FROM tasks t JOIN actions a USING(task_id) WHERE json_extract(a.document,'$.capability_id')='mcp.documentation.v1' ORDER BY t.rowid DESC LIMIT 1").fetchone()
        validation = None
        if latest:
            task, action = json.loads(latest['task']), json.loads(latest['action'])
            validation = {'task_id': task['task_id'], 'status': action['status'], 'at': task['updated_at'],
                          'connection': action['arguments'].get('_connection'), 'error': action.get('error')}
        with self.core.effect_guard(), self.extensions.connection() as db:
            self._tables(db)
            for item in data['servers']:
                attached = [r for r in registrations if r['document'].get('catalog_id') == item['id']]
                pref, overrides = self._policy(db, item['id'], context)
                from .mcp_client import ENDPOINT
                ready = item['id'] == 'context7' and len(attached) == 1 and attached[0]['document']['config'] == {'transport': 'streamable-http', 'url': ENDPOINT}
                result.append({**item, 'registrations': attached, 'policy': pref, 'overrides': overrides,
                    'runtime_available': ready, 'callable': ready and pref['mode'] != 'disabled',
                    'automatic_available': ready and pref['mode'] == 'auto' and auto_enabled,
                    'last_validation': validation if item['id'] == 'context7' else None,
                    'status': 'available' if ready else 'registered' if attached else 'recommended',
                    'reason': ('已开放 Google Flash 的单项文档查询：例如“查询 Electron 文档中的 ipcMain.handle 示例”。需普通已保存会话、无附件且选用规则为“条件满足时选用”；其他请求可用文档草稿。' if auto_enabled and pref['mode']=='auto' else '只读文档适配器已接入；从聊天选择“文档工具”发起查询，每次重新握手；历史成功不代表当前额度。') if ready else
                              'Context7 首期需要唯一的官方 HTTP 连接，不填写凭据引用。' if item['id'] == 'context7' and attached else
                              '已保存配置；此 MCP 的运行适配、凭据绑定与工具调用尚未接入。' if attached else '来源与用途已核对；尚未添加连接配置。'})
            for row in registrations:
                if row['document'].get('catalog_id') in known:
                    continue
                ident = 'custom.' + row['id']
                pref, overrides = self._policy(db, ident, context)
                result.append({'id': ident, 'name': row['document']['name'], 'category': 'custom', 'icon': 'plug',
                    'publisher': '自定义', 'source_type': 'custom', 'summary': '由你添加的 MCP 连接配置。',
                    'use_when': '明确需要此服务器的工具，并已核对工具、目标和授权范围。',
                    'do_not_use_when': '来源、工具用途或目标范围不明确；依赖与验证未完成。',
                    'requirements': ['核对维护者与工具说明', '运行适配器和调用验收'], 'cost': '取决于服务器和接入服务。',
                    'skills': [], 'alternative_group': '', 'registrations': [row], 'policy': pref, 'overrides': overrides,
                    'runtime_available': False, 'callable': False, 'status': 'registered',
                    'reason': '自定义配置仅登记；来源、协议和实际调用尚未验证。'})
        return {'schema_version': 1, 'bundle_digest': digest, 'reviewed_at': data['reviewed_at'],
                'entries': result, 'combinations': data['combinations'], 'excluded': data['excluded'],
                'runtime_available': any(r['runtime_available'] for r in result),
                'selection_method': 'bounded_documentation_and_explicit' if auto_enabled else 'explicit_documentation_task', 'scope': context}

    def put_policy(self, payload):
        fields(payload, {'mcp_id', 'scope', 'revision'}, {'scope_id', 'mode'})
        ident, scope = payload['mcp_id'], payload['scope']
        if not isinstance(ident, str) or ident not in {r['id'] for r in self.snapshot()['entries']}:
            raise policy.CoreError('invalid_mcp_policy', 'MCP 标识不在当前目录中。')
        target = payload.get('scope_id', '')
        if not isinstance(scope, str) or scope not in SCOPES or (scope == 'global' and target):
            raise policy.CoreError('invalid_mcp_policy', 'MCP 设置作用域无效。')
        if scope != 'global':
            identifier(target)
        mode = payload.get('mode')
        if type(payload['revision']) is not int or not 0 <= payload['revision'] < 2**53 or (mode is not None and (not isinstance(mode, str) or mode not in MODES)):
            raise policy.CoreError('invalid_mcp_policy', 'MCP 模式或修订号无效。')
        with self.core.effect_guard(), self.extensions.connection() as db:
            self._tables(db)
            db.execute('BEGIN IMMEDIATE')
            key = (scope, target, ident)
            row = db.execute('SELECT revision FROM mcp_policies WHERE scope=? AND scope_id=? AND mcp_id=?', key).fetchone()
            previous = row['revision'] if row else 0
            if previous != payload['revision']:
                raise policy.CoreError('mcp_policy_conflict', 'MCP 规则已经变化，请刷新后重试；当前输入保留。')
            db.execute('INSERT INTO mcp_policies VALUES(?,?,?,?,?,?) ON CONFLICT(scope,scope_id,mcp_id) DO UPDATE SET revision=excluded.revision,mode=excluded.mode,updated_at=excluded.updated_at',
                       (*key, previous + 1, mode or 'inherit', timestamp()))
        return {'saved': True, 'revision': previous + 1, 'mode': mode, 'runtime_available': False}
