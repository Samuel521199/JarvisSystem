"""Dormant MCP/skill registrations. This module never starts or downloads code."""
from contextlib import contextmanager
import json
from pathlib import Path
import re
import sqlite3
from urllib.parse import urlsplit

from .policy import safe_path, CoreError
from .workspace import WorkspaceService, fields, identifier, fail, timestamp
from .project_files import read_text


class ExtensionCatalog:
    def __init__(self, core):
        self.core = core
        self.path = Path(core.data_dir) / 'extensions.db'

    @contextmanager
    def connection(self):
        safe_path(self.path.parent, directory=True)
        for suffix in ('', '-journal', '-wal', '-shm'):
            safe_path(str(self.path) + suffix, must_exist=False)
        db = sqlite3.connect(self.path, timeout=3)
        db.row_factory = sqlite3.Row
        try:
            version = db.execute('PRAGMA user_version').fetchone()[0]
            if version not in (0, 1):
                fail('extensions_unavailable', '扩展目录数据版本不兼容。')
            db.execute('PRAGMA secure_delete=ON')
            db.execute('CREATE TABLE IF NOT EXISTS entries(id TEXT PRIMARY KEY, revision INTEGER NOT NULL, kind TEXT NOT NULL, document TEXT NOT NULL, updated_at TEXT NOT NULL, deleted INTEGER NOT NULL DEFAULT 0)')
            db.execute('PRAGMA user_version=1')
            db.commit()
            yield db
            db.commit()
        finally:
            db.close()

    @staticmethod
    def public(row):
        return {'id': row['id'], 'revision': row['revision'], 'kind': row['kind'],
                'document': json.loads(row['document']), 'updated_at': row['updated_at'],
                'status': 'registered', 'runtime_available': False}

    def list(self):
        with self.core.effect_guard(), self.connection() as db:
            return {'entries': [self.public(row) for row in db.execute('SELECT * FROM entries WHERE deleted=0 ORDER BY updated_at DESC')],
                    'runtime_available': False}

    def skill(self, path):
        if not isinstance(path, str) or len(path) > 4096 or not Path(path).is_absolute():
            fail('invalid_extension', '请输入含 SKILL.md 的本地技能文件夹完整路径。')
        folder = safe_path(path, directory=True)
        WorkspaceService(self.core)._allowed_destination(folder)
        result = read_text(folder / 'SKILL.md')
        if result['size_bytes'] > 128 * 1024 or not result['content'].strip():
            fail('invalid_extension', 'SKILL.md 必须为非空 UTF-8 文本，且不超过 128 KiB。')
        return result

    def validate(self, document):
        fields(document, {'kind', 'name', 'config'}, {'catalog_id'})
        if 'catalog_id' in document:
            from .mcp_catalog import catalog
            if document['kind'] != 'mcp' or not isinstance(document['catalog_id'], str) or document['catalog_id'] not in {x['id'] for x in catalog()[0]['servers']}:
                fail('invalid_extension', '目录归属必须是有效的 MCP 来源标识。')
        name = document['name']
        if not isinstance(name, str) or not name.strip() or len(name) > 80 or any(ord(c) < 32 for c in name):
            fail('invalid_extension', '扩展名称应为 1—80 个可见字符。')
        config = document['config']
        if document['kind'] == 'skill':
            fields(config, {'path'}, {'digest'})
            result = self.skill(config['path'])
            return {**document, 'config': {'path': str(Path(config['path']).absolute()), 'digest': result['digest']}}
        if document['kind'] != 'mcp':
            fail('invalid_extension', '扩展类型只能是 mcp 或 skill。')
        fields(config, {'transport'}, {'command', 'args', 'url', 'credential_ref'})
        reference = config.get('credential_ref', '')
        if not isinstance(reference, str) or (reference and not re.fullmatch(r'[a-zA-Z0-9_.-]{1,80}', reference)):
            fail('invalid_extension', '这里只保存凭据引用名称，不接收 Key 或请求头。')
        if config['transport'] == 'stdio':
            if set(config) - {'transport', 'command', 'args', 'credential_ref'} or not isinstance(config.get('command'), str) or not config['command'].strip() or len(config['command']) > 1024 or any(ord(c) < 32 for c in config['command']):
                fail('invalid_extension', 'stdio 需要程序路径或命令名；参数另填 JSON 数组。')
            args = config.get('args', [])
            if not isinstance(args, list) or len(args) > 32 or any(not isinstance(a, str) or len(a) > 1024 or '\x00' in a for a in args):
                fail('invalid_extension', '参数应为最多 32 项的文本数组。')
        elif config['transport'] == 'streamable-http':
            if set(config) - {'transport', 'url', 'credential_ref'} or not isinstance(config.get('url'), str) or len(config['url']) > 2048:
                fail('invalid_extension', 'HTTP 连接需要 MCP 端点 URL。')
            parsed = urlsplit(config['url'])
            try:
                port = parsed.port
            except ValueError:
                fail('invalid_extension', '端点端口无效。')
            if not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment or any(c.isspace() for c in config['url']) or not (parsed.scheme == 'https' or parsed.scheme == 'http' and parsed.hostname in {'127.0.0.1', 'localhost', '::1'}):
                fail('invalid_extension', '使用 HTTPS 或本机 HTTP 端点；凭据不要写在 URL 中。')
        else:
            fail('invalid_extension', '当前登记支持 stdio 与 Streamable HTTP。')
        return document

    def put(self, entry_id, payload):
        identifier(entry_id)
        fields(payload, {'revision', 'document'})
        revision = payload['revision']
        if type(revision) is not int or not 0 <= revision < 2**53:
            fail('invalid_extension', '修订号无效。')
        with self.core.effect_guard(), self.connection() as db:
            doc = self.validate(payload['document'])
            encoded = json.dumps(doc, ensure_ascii=False, sort_keys=True)
            db.execute('BEGIN IMMEDIATE')
            old = db.execute('SELECT * FROM entries WHERE id=?', (entry_id,)).fetchone()
            if old and not old['deleted'] and old['document'] == encoded and revision in {old['revision'], old['revision'] - 1}:
                return self.public(old)
            if (old['revision'] if old else 0) != revision or old and (old['deleted'] or old['kind'] != doc['kind']):
                fail('extension_conflict', '扩展配置已经变化，请刷新列表后重新编辑；当前输入保留。')
            if not old and db.execute('SELECT COUNT(*) FROM entries').fetchone()[0] >= 1000:
                fail('extension_limit', '扩展目录累计标识已达 1000 项上限。')
            db.execute('INSERT INTO entries VALUES (?,?,?,?,?,0) ON CONFLICT(id) DO UPDATE SET revision=excluded.revision,document=excluded.document,updated_at=excluded.updated_at',
                       (entry_id, revision + 1, doc['kind'], encoded, timestamp()))
            return self.public(db.execute('SELECT * FROM entries WHERE id=?', (entry_id,)).fetchone())

    def delete(self, entry_id, payload):
        identifier(entry_id); fields(payload, {'revision'})
        if type(payload['revision']) is not int:
            fail('invalid_extension', '修订号无效。')
        with self.core.effect_guard(), self.connection() as db:
            db.execute('BEGIN IMMEDIATE')
            row = db.execute('SELECT * FROM entries WHERE id=?', (entry_id,)).fetchone()
            if not row or row['revision'] != payload['revision']:
                fail('extension_conflict', '登记已变化，请刷新后重试。')
            db.execute("UPDATE entries SET deleted=1,document='{}',revision=revision+1 WHERE id=?", (entry_id,))
            return {'deleted': True}

    def inspect(self, entry_id, payload):
        identifier(entry_id); fields(payload, set())
        with self.core.effect_guard(), self.connection() as db:
            row = db.execute('SELECT * FROM entries WHERE id=? AND deleted=0', (entry_id,)).fetchone()
            if not row: fail('not_found', '扩展登记不存在。')
            doc = json.loads(row['document'])
            if row['kind'] == 'skill':
                result = self.skill(doc['config']['path'])
                return {'status': 'unchanged' if result['digest'] == doc['config']['digest'] else 'changed',
                        'content': result['content'], 'digest': result['digest'], 'runtime_available': False}
            self.validate(doc)
            return {'status': 'configuration_valid', 'runtime_available': False,
                    'message': '配置格式有效。尚未连接服务器、下载依赖或发现工具。'}
