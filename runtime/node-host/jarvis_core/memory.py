"""Explicit owner facts: bounded SQLite, revisions, scopes and route-aware views.

No extraction model, background worker, vector index or network client. Corrected
body text is replaced; revision receipts contain metadata only. Forget clears
the current body and keeps an ID tombstone so delayed writes cannot revive it.
"""
from contextlib import contextmanager
from datetime import datetime, timezone
from functools import lru_cache
import hashlib
import json
import re
from pathlib import Path
import sqlite3
import unicodedata
import uuid

from jsonschema import Draft202012Validator

from .policy import safe_path
from . import memory_policy

ROOT = Path(__file__).resolve().parents[3]
MAX_FACTS = 1000
MAX_IDENTITIES = 10000
MAX_RECEIPTS = 20000
MAX_VIEW_BYTES = 6144
MAX_VIEW_FACTS = 20


class MemoryError(ValueError):
    def __init__(self, code, message):
        self.code = code
        super().__init__(message)


def fail(code, message):
    raise MemoryError(code, message)


@lru_cache(maxsize=8)
def validator(kind):
    schema = json.loads((ROOT / 'contracts/schemas/memory-fact.schema.json').read_text(encoding='utf-8'))
    schema['$ref'] = '#/$defs/' + kind
    return Draft202012Validator(schema)


def validate(kind, value):
    if not validator(kind).is_valid(value):
        fail('invalid_memory', '记忆字段、范围或版本无效，请检查后重试。')
    return value


def timestamp():
    return datetime.now(timezone.utc).isoformat()


def normalized(value):
    return unicodedata.normalize('NFKC', value).casefold()


def validate_history_references(value, history):
    if value is None:
        return [[] for _ in (history or [])]
    validate('history', value)
    if len(value) != len(history or []):
        fail('invalid_memory', '历史消息与记忆来源数量不匹配。')
    return value


class MemoryStore:
    def __init__(self, core):
        self.core = core
        self.directory = Path(core.data_dir)
        self.path = self.directory / 'memory.db'

    @contextmanager
    def connection(self):
        safe_path(self.directory, directory=True)
        for suffix in ('', '-journal', '-wal', '-shm'):
            safe_path(str(self.path) + suffix, must_exist=False)
        db = sqlite3.connect(self.path, timeout=2, isolation_level=None)
        db.row_factory = sqlite3.Row
        try:
            db.execute('PRAGMA synchronous=FULL')
            db.execute('PRAGMA secure_delete=ON')
            version = db.execute('PRAGMA user_version').fetchone()[0]
            if version not in (0, 1, 2, 3):
                fail('memory_unavailable', '记忆库版本不兼容；未读取或改写。')
            db.execute('BEGIN IMMEDIATE')
            db.execute('CREATE TABLE IF NOT EXISTS facts (id TEXT PRIMARY KEY, revision INTEGER NOT NULL, document TEXT, digest TEXT, search_text TEXT, project_id TEXT, created_at TEXT NOT NULL, updated_at TEXT NOT NULL, deleted INTEGER NOT NULL DEFAULT 0)')
            db.execute('CREATE TABLE IF NOT EXISTS receipts (fact_id TEXT NOT NULL, revision INTEGER NOT NULL, operation TEXT NOT NULL, source TEXT NOT NULL, at TEXT NOT NULL, PRIMARY KEY(fact_id,revision))')
            db.execute('CREATE TABLE IF NOT EXISTS fact_origins (fact_id TEXT PRIMARY KEY, source_json TEXT, detached INTEGER NOT NULL DEFAULT 0)')
            db.execute('CREATE TABLE IF NOT EXISTS candidate_bindings (source_key TEXT NOT NULL, scope_key TEXT NOT NULL, fact_id TEXT NOT NULL, fingerprint TEXT NOT NULL, suppressed INTEGER NOT NULL DEFAULT 0, PRIMARY KEY(source_key,scope_key))')
            db.execute('CREATE INDEX IF NOT EXISTS candidate_binding_fact ON candidate_bindings(fact_id)')
            # v3 adds restricted classification inside the existing document.
            # Bump even on read so older binaries cannot silently ignore policy.
            # Old rows, revisions, hashes, receipts and tombstones stay unchanged.
            db.execute('PRAGMA user_version=3')
            db.commit()
            yield db
        finally:
            db.close()

    def _project(self, project_id):
        if project_id is None:
            return
        validate('id', project_id)
        from .workspace import WorkspaceService
        projects = WorkspaceService(self.core).projects()['projects']
        if not any(p['id'] == project_id for p in projects):
            fail('invalid_memory', '请选择已经打开登记的项目。')

    @staticmethod
    def _public(row):
        document = json.loads(row['document'])
        return {'id': row['id'], 'revision': row['revision'],
                'document': document, 'created_at': row['created_at'],
                'updated_at': row['updated_at'], 'source': 'owner_explicit',
                'usage': memory_policy.describe(document)}

    def list(self, *, project_id=None, query=''):
        self._project(project_id)
        if not isinstance(query, str) or len(query) > 128 or '\0' in query:
            fail('invalid_memory', '搜索内容最多 128 个字符。')
        with self.connection() as db:
            rows = db.execute('SELECT * FROM facts WHERE deleted=0 AND (project_id IS NULL OR project_id=?) AND instr(search_text,?)>0 ORDER BY updated_at DESC,id',
                              (project_id, normalized(query.strip()))).fetchall()
            origins = self._origins(db)
        from .memory_sources import annotate
        return {'facts': annotate(self.core, [self._public(row) for row in rows], origins), 'max_facts': MAX_FACTS,
                'schema_version': 3, 'capabilities': ['fact_classification', 'owner_facing_purpose']}

    @staticmethod
    def _origins(db):
        return {row['fact_id']: dict(row) for row in db.execute('SELECT * FROM fact_origins WHERE source_json IS NOT NULL')}

    @staticmethod
    def _suppress_sources(db, fact_id):
        db.execute('UPDATE candidate_bindings SET suppressed=1 WHERE fact_id=?', (fact_id,))

    @staticmethod
    def _review_revision(db):
        # Receipts are append-only and bounded. New facts do not invalidate other
        # cards in the same preview; corrections, permission edits and forgetting do.
        return db.execute("SELECT count(*) FROM receipts WHERE operation IN ('correct','forget')").fetchone()[0]

    def review_revision(self):
        """Read only revision metadata, without creating a database for a preview."""
        safe_path(self.directory, directory=True)
        for suffix in ('', '-journal', '-wal', '-shm'):
            safe_path(str(self.path) + suffix, must_exist=False)
        if not self.path.exists():
            return 0
        db = None
        try:
            db = sqlite3.connect(self.path.resolve().as_uri() + '?mode=ro', uri=True, timeout=2)
            if db.execute('PRAGMA user_version').fetchone()[0] not in (1, 2, 3):
                fail('memory_unavailable', '记忆库版本不兼容；未读取或改写。')
            return self._review_revision(db)
        except sqlite3.Error:
            fail('memory_unavailable', '无法核对记忆修订；未采用旧候选，请检查本机记忆库后重试。')
        finally:
            if db is not None:
                db.close()

    def put(self, fact_id, payload):
        validate('id', fact_id)
        validate('write', payload)
        document = payload['document']
        if any(not document[k].strip() or '\0' in document[k] for k in ('title', 'content')):
            fail('invalid_memory', '记忆名称和内容不能为空或包含空字符。')
        self._project(document['project_id'])
        document = {**document, 'title': document['title'].strip(), 'content': document['content'].strip(),
                    'providers': sorted(document['providers'])}
        expected = payload['revision']
        with self.core.effect_guard(), self.connection() as db:
            db.execute('BEGIN IMMEDIATE')
            old = db.execute('SELECT document FROM facts WHERE id=? AND deleted=0', (fact_id,)).fetchone()
            # Stale/older clients cannot erase policy by simply omitting the field.
            old_document = json.loads(old['document']) if old else {}
            if 'classification' not in document and 'classification' in old_document:
                document = {**document, 'classification': old_document['classification']}
            self._check_policy(document)
            encoded = json.dumps(document, ensure_ascii=False, sort_keys=True, separators=(',', ':'))
            digest = hashlib.sha256(encoded.encode()).hexdigest()
            result = self._put(db, fact_id, document, encoded, digest, expected,
                               reaffirm=payload.get('reaffirm_source', False))
            db.commit()
            return result

    @staticmethod
    def _check_policy(document):
        validate('document', document)
        try:
            memory_policy.check(document)
        except ValueError as error:
            fail('invalid_memory', str(error))

    def _put(self, db, fact_id, document, encoded, digest, expected, *, reaffirm=False, candidate=False):
        row = db.execute('SELECT * FROM facts WHERE id=?', (fact_id,)).fetchone()
        if row and row['deleted']:
            fail('memory_deleted', '这条记忆已忘记，旧页面不能重新保存它。')
        current = row['revision'] if row else 0
        origin = db.execute('SELECT detached FROM fact_origins WHERE fact_id=?', (fact_id,)).fetchone()
        corrected = bool(row and not candidate and
                         (reaffirm or any(json.loads(row['document'])[k] != document[k] for k in ('title', 'content', 'project_id'))))
        policy_changed = bool(row and not candidate and json.loads(row['document']).get('classification') != document.get('classification'))
        detach = bool(origin and not origin['detached'] and corrected)
        if reaffirm and not row:
            fail('invalid_memory', '只能确认保留已经存在的记忆。')
        if row and row['digest'] == digest and expected in (current, current - 1) and not detach:
            return self._public(row)
        if current != expected:
            fail('memory_conflict', '记忆已在其他页面更新；请重新读取后核对，当前输入仍保留。')
        count, total = db.execute('SELECT coalesce(sum(deleted=0),0),count(*) FROM facts').fetchone()
        if (not row and (count >= MAX_FACTS or total >= MAX_IDENTITIES)) or db.execute('SELECT count(*) FROM receipts').fetchone()[0] >= MAX_RECEIPTS:
            fail('memory_limit', '记忆或修订记录达到本版上限，未自动清除旧数据。仍可忘记已有记忆。')
        now = timestamp()
        if corrected or policy_changed:
            self._suppress_sources(db, fact_id)
        if detach:
            db.execute('UPDATE fact_origins SET detached=1 WHERE fact_id=?', (fact_id,))
        db.execute('INSERT INTO facts VALUES (?,?,?,?,?,?,?,?,0) ON CONFLICT(id) DO UPDATE SET revision=excluded.revision,document=excluded.document,digest=excluded.digest,search_text=excluded.search_text,project_id=excluded.project_id,updated_at=excluded.updated_at',
                   (fact_id, current + 1, encoded, digest, normalized(document['title']+'\n'+document['content']), document['project_id'], now, now))
        db.execute('INSERT INTO receipts VALUES (?,?,?,?,?)', (fact_id, current+1, 'correct' if row else 'remember', 'owner_explicit', now))
        result = self._public(db.execute('SELECT * FROM facts WHERE id=?', (fact_id,)).fetchone())
        return result

    def delete(self, fact_id, payload):
        validate('id', fact_id)
        validate('delete', payload)
        expected = payload['revision']
        with self.core.effect_guard(), self.connection() as db:
            db.execute('BEGIN IMMEDIATE')
            result = self._delete(db, fact_id, expected)
            db.commit()
            return result

    def _delete(self, db, fact_id, expected):
        row = db.execute('SELECT * FROM facts WHERE id=?', (fact_id,)).fetchone()
        if row and row['deleted']:
            return {'id': fact_id, 'status': 'forgotten'}
        if not row:
            fail('memory_not_found', '记忆不存在。')
        if expected != row['revision']:
            fail('memory_conflict', '记忆已更新，请重新读取后忘记。')
        now = timestamp()
        self._suppress_sources(db, fact_id)
        db.execute('UPDATE fact_origins SET source_json=NULL,detached=1 WHERE fact_id=?', (fact_id,))
        db.execute('UPDATE facts SET revision=revision+1,document=NULL,digest=NULL,search_text=NULL,project_id=NULL,updated_at=?,deleted=1 WHERE id=?', (now, fact_id))
        db.execute('INSERT INTO receipts VALUES (?,?,?,?,?)', (fact_id, expected+1, 'forget', 'owner_explicit', now))
        return {'id': fact_id, 'status': 'forgotten'}

    def command(self, action, title, content, *, project_id=None, request_id, cancel_event=None, candidate_source=None, classification=None, candidate_review_revision=None, candidate_target=None, candidate_deduplicate=False, candidate_review_required=False):
        """An explicit chat edit and its retry receipt commit in one transaction.

        Matching is exact within one scope. Receipts retain no fact body. They
        are additive to v1: older panel readers still see the same facts.
        """
        validate('id', request_id)
        if candidate_target is not None:
            if (not isinstance(candidate_target, dict) or set(candidate_target) != {'id', 'revision', 'digest', 'mode'} or
                    candidate_target['mode'] not in ('keep', 'replace') or type(candidate_target['revision']) is not int or
                    candidate_target['revision'] < 1 or candidate_review_revision is None):
                fail('invalid_memory', '候选目标无效。')
            validate('id', candidate_target['id'])
            if not isinstance(candidate_target['digest'], str) or not re.fullmatch('[a-f0-9]{64}', candidate_target['digest']):
                fail('invalid_memory', '候选目标摘要无效。')
        if candidate_review_revision is not None:
            if (type(candidate_review_revision) is not int or candidate_review_revision < 0
                    or candidate_source is None or action != 'remember'):
                fail('invalid_memory', '候选修订检查需要有效的来源和修订编号。')
        if candidate_source is not None:
            validate('candidate_source', candidate_source)
            if action != 'remember':
                fail('invalid_memory', '候选来源只用于确认新记忆。')
        if classification is not None:
            if candidate_source is None or action != 'remember':
                fail('invalid_memory', '候选分类必须同时提供经核对的来源。')
            self._check_policy({'title': title, 'content': content, 'project_id': project_id,
                                'providers': [], 'classification': classification})
        self._project(project_id)
        if action not in ('remember', 'correct', 'forget') or not isinstance(title, str) or not 1 <= len(title) <= 2048 or '\0' in title:
            fail('invalid_memory', '请指定完整记忆名称或标识。')
        if action != 'forget':
            validate('document', {'title': title, 'content': content, 'project_id': project_id, 'providers': []})
            if not content.strip() or '\0' in content:
                fail('invalid_memory', '记忆内容不能为空或包含空字符。')
        identity = [action, title, content, project_id]
        if classification is not None: identity.append(classification)
        if candidate_target is not None: identity.append(candidate_target)
        fingerprint = hashlib.sha256(json.dumps(identity, ensure_ascii=False, sort_keys=classification is not None).encode()).hexdigest()
        with self.core.effect_guard(), self.connection() as db:
            db.execute('BEGIN IMMEDIATE')
            db.execute('CREATE TABLE IF NOT EXISTS chat_commands (id TEXT PRIMARY KEY, fingerprint TEXT NOT NULL, receipt TEXT NOT NULL)')
            previous = db.execute('SELECT * FROM chat_commands WHERE id=?', (request_id,)).fetchone()
            if previous:
                if previous['fingerprint'] != fingerprint:
                    fail('memory_conflict', '同一请求标识不能用于不同的记忆操作。')
                return {**json.loads(previous['receipt']), 'replayed': True}
            if candidate_review_required and candidate_review_revision is None:
                fail('candidate_review_required', '旧规则预览不能新增事实，请重新整理本机候选并核对；已完成回执仍可查询。')
            binding_key = None
            if candidate_source is not None:
                from .memory_sources import read_source, source_key
                archive = read_source(self.core, candidate_source)
                candidate_source = {**candidate_source, 'archive_revision': archive['revision']}
                binding_key = source_key(candidate_source)
                if db.execute('SELECT 1 FROM candidate_bindings WHERE source_key=? AND suppressed=1', (binding_key,)).fetchone():
                    fail('candidate_suppressed', '这条来源候选已被纠正或忘记，不会通过改名或切换范围重新保存。需要重新记住时，请使用明确记忆指令。')
                binding = db.execute('SELECT * FROM candidate_bindings WHERE source_key=? AND scope_key=?', (binding_key, project_id or '')).fetchone()
                if binding:
                    fail('memory_conflict', '此来源候选已经保存；请在记忆面板修改已有记忆，不会另建副本。')
                if db.execute('SELECT count(*) FROM candidate_bindings').fetchone()[0] >= MAX_RECEIPTS:
                    fail('memory_limit', '候选来源记录达到上限，未自动删除撤销记录。')
            # Inside the same write transaction as the candidate commit. Exact
            # receipt replays above remain safe and must not become new writes.
            if candidate_review_revision is not None and self._review_revision(db) != candidate_review_revision:
                fail('candidate_review_changed', '整理后记忆已被修改或忘记；旧预览未保存，请重新整理并核对。')
            if cancel_event is not None and cancel_event.is_set():
                fail('personal_cancelled', '已取消；本次没有修改记忆。')
            if db.execute('SELECT count(*) FROM chat_commands').fetchone()[0] >= MAX_RECEIPTS:
                fail('memory_limit', '聊天记忆回执达到上限；请在记忆面板管理，未重复执行。')
            rows = db.execute('SELECT * FROM facts WHERE deleted=0 AND project_id IS ? ORDER BY id', (project_id,)).fetchall()
            from .memory_comparison import duplicate, same_subject
            proposed = {'title': title, 'content': content, 'project_id': project_id, 'classification': classification}
            if candidate_target is not None:
                targets = [r for r in rows if r['id'] == candidate_target['id']]
                if (len(targets) != 1 or targets[0]['revision'] != candidate_target['revision'] or
                        targets[0]['digest'] != candidate_target['digest']):
                    fail('candidate_target_changed', '目标记忆已变化，请重新核对；没有覆盖旧内容。')
                old_doc = json.loads(targets[0]['document'])
                if candidate_target['mode'] == 'replace' and not same_subject(proposed, old_doc):
                    fail('candidate_target_changed', '只能更新同范围、同类型和主体的记忆；未改变原分类或权限。')
                if candidate_target['mode'] == 'keep' and not (duplicate(proposed, old_doc) or
                        (old_doc.get('classification') is None and content.strip() == old_doc['content'].strip())):
                    fail('candidate_target_changed', '内容不再相同，请重新核对。')
                # Old source validity is checked in the same transaction as the
                # replacement, as well as when producing the review card.
                from .memory_sources import annotate, usable
                if not usable(annotate(self.core, [self._public(targets[0])], self._origins(db))[0]):
                    fail('candidate_target_changed', '旧记忆的来源已失效，请在记忆面板先核对。')
            elif candidate_deduplicate and candidate_source is not None:
                from .memory_sources import annotate, usable
                duplicates = [self._public(r) for r in rows if duplicate(proposed, json.loads(r['document']))]
                if any(usable(r) for r in annotate(self.core, duplicates, self._origins(db))):
                    fail('candidate_duplicate', '已有相同内容，请点击“核对已有记忆”并选择沿用，避免重复保存。')
            matches = [r for r in rows if title == r['id'] or normalized(title) in
                       (normalized(json.loads(r['document'])['title']), normalized(json.loads(r['document'])['content']))]
            if candidate_target is not None: matches = targets
            if len(matches) > 1:
                fail('memory_ambiguous', '找到多条同名记忆，未修改。请在记忆面板核对，或用查看记忆返回的完整标识指定。')
            row = matches[0] if matches else None
            if row and candidate_source is not None and candidate_target is None:
                origin = db.execute('SELECT * FROM fact_origins WHERE fact_id=?', (row['id'],)).fetchone()
                if origin and not origin['detached'] and source_key(json.loads(origin['source_json'])) != binding_key:
                    fail('memory_conflict', '同名记忆已经绑定另一条来源，请在记忆面板核对或修改已有记忆。')
            if action != 'remember' and row is None:
                fail('memory_not_found', '当前范围没有这条记忆；请先查看记忆并使用完整名称或标识。')
            if action == 'remember' and row and candidate_target is None and json.loads(row['document'])['content'] != content:
                fail('memory_conflict', '同名记忆已有不同内容；请使用“修改记忆：名称=新内容”明确纠正。')
            ident, revision = (row['id'], row['revision']) if row else (uuid.uuid4().hex, 0)
            if action == 'forget':
                self._delete(db, ident, revision)
                revision += 1
            else:
                old = json.loads(row['document']) if row else None
                document = {'title': old['title'] if old else title, 'content': content,
                            'project_id': project_id, 'providers': old['providers'] if old else []}
                if old and 'classification' in old:
                    document['classification'] = old['classification']
                if classification is not None:
                    if old and candidate_target is None and old.get('classification') != classification:
                        fail('memory_conflict', '同名记忆的用途或分类不同，请在记忆面板修改已有记录。')
                    document['classification'] = classification
                if candidate_target is not None:
                    document = dict(old)
                    if candidate_target['mode'] == 'replace': document['content'] = content
                self._check_policy(document)
                encoded = json.dumps(document, ensure_ascii=False, sort_keys=True, separators=(',', ':'))
                result = self._put(db, ident, document, encoded, hashlib.sha256(encoded.encode()).hexdigest(), revision,
                                   candidate=candidate_source is not None and candidate_target is None,
                                   reaffirm=action == 'correct' or bool(candidate_target and candidate_target['mode'] == 'replace'))
                revision = result['revision']
            if binding_key is not None:
                # A duplicate of an independently saved fact stays independent.
                if row is None or (candidate_target and candidate_target['mode'] == 'replace'):
                    db.execute('INSERT INTO fact_origins VALUES (?,?,0) ON CONFLICT(fact_id) DO UPDATE SET source_json=excluded.source_json,detached=0',
                               (ident, json.dumps(candidate_source, sort_keys=True)))
                db.execute('INSERT INTO candidate_bindings VALUES (?,?,?,?,0)',
                           (binding_key, project_id or '', ident, fingerprint))
            receipt = {'kind': 'memory', 'action': action, 'id': ident, 'revision': revision,
                       'project_id': project_id, 'committed': True, 'replayed': False}
            db.execute('INSERT INTO chat_commands VALUES (?,?,?)', (request_id, fingerprint, json.dumps(receipt)))
            db.commit()
            return receipt

    def view_facts(self, request, provider):
        from .memory_view import project_scope
        request = request or {'enabled': False, 'project_id': None}
        validate('context', request)
        projects = project_scope(request)
        if not request['enabled']:
            return []
        from .workspace import WorkspaceService
        registered = {p['id']: p['name'] for p in WorkspaceService(self.core).projects()['projects']} if projects else {}
        if any(project not in registered for project in projects):
            fail('invalid_memory', '请选择已经打开登记的项目。')
        placeholders = ','.join('?' for _ in projects) or 'NULL'
        with self.connection() as db:
            rows = db.execute(
                'SELECT * FROM facts WHERE deleted=0 AND (project_id IS NULL OR project_id IN ('+placeholders+')) '
                "AND (?='local' OR EXISTS (SELECT 1 FROM json_each(json_extract(document,'$.providers')) WHERE value=?)) "
                'ORDER BY updated_at DESC,id', (*projects, provider, provider)).fetchall()
            origins = self._origins(db)
        from .memory_sources import annotate, usable
        # Purpose and validity are filtered before source archive reads and ranking.
        # Their scope/provider filters were already applied by SQLite above.
        allowed = [row for row in rows if memory_policy.eligible(json.loads(row['document']), memory_policy.purpose(request))]
        decorated = annotate(self.core, [{**self._public(row), 'project_name': registered.get(row['project_id'], '通用')} for row in allowed], origins)
        return [row for row in decorated if usable(row)]

    def current_facts(self, facts, request, provider):
        if facts is None:
            return self.view_facts(request, provider)
        current = {row['id']: row for row in self.view_facts(request, provider)}
        return [current[row['id']] for row in facts if row['id'] in current and current[row['id']]['revision'] == row['revision']]

    def context(self, request, provider, *, max_bytes=MAX_VIEW_BYTES, facts=None):
        if request is None:
            request = {'enabled': False, 'project_id': None}
        validate('context', request)
        report = {'enabled': request['enabled'], 'provider': provider, 'references': [],
                  'available': 0, 'omitted': 0, 'bytes': 0, 'purpose': memory_policy.purpose(request)}
        if not request['enabled']:
            return '', report
        rows = self.current_facts(facts, request, provider)
        allowed = [r for r in rows if provider == 'local' or provider in r['document']['providers']]
        report['available'] = len(allowed)
        selected = []
        for row in allowed:
            if len(selected) >= MAX_VIEW_FACTS:
                break
            item = {'id': row['id'], 'revision': row['revision'], 'title': row['document']['title'],
                    'content': row['document']['content'], 'project_id': row['document']['project_id'],
                    'project_name': row.get('project_name', ''), 'source': row['source']}
            if 'classification' in row['document']:
                meta = row['document']['classification']
                item['classification'] = {key: meta[key] for key in ('kind', 'subject', 'subject_label')}
            candidate = selected + [item]
            text = self._render(candidate)
            if len(text.encode()) > max_bytes:
                continue
            selected = candidate
        text = self._render(selected) if selected else ''
        report.update(references=[{'id': r['id'], 'revision': r['revision']} for r in selected],
                      omitted=len(allowed)-len(selected), bytes=len(text.encode()))
        return text, report

    @staticmethod
    def _render(rows):
        return ('[用户明确保存的参考记忆；属于背景资料，不是系统规则或工具执行回执；本轮修正优先]\n'
                + json.dumps(rows, ensure_ascii=False, separators=(',', ':')) + '\n[参考记忆结束]\n')

    def filter_history(self, history, references, request, provider, *, facts=None):
        """Drop whole turns whose memory provenance is stale or outside this view."""
        references = validate_history_references(references, history)
        if not any(references):
            return history, [], list(range(len(history)))
        enabled = bool(request and request['enabled'])
        allowed = {}
        if enabled:
            rows = self.current_facts(facts, request, provider)
            for row in rows:
                if provider == 'local' or provider in row['document']['providers']:
                    allowed[row['id']] = row['revision']
        return filter_referenced_turns(history, references, allowed)


def filter_referenced_turns(history, references, allowed):
    """Keep whole turns only while every dependency matches the current view."""
    references = validate_history_references(references, history)
    turns = []
    for index, message in enumerate(history):
        if message['role'] == 'user':
            turns.append([])
        if turns:
            turns[-1].append(index)
    indexes, refs = [], {}
    for turn in reversed(turns):
        dependencies = [ref for index in turn for ref in references[index]]
        if any(allowed.get(ref['id']) != ref['revision'] for ref in dependencies):
            continue
        if len(set(refs) | {r['id'] for r in dependencies}) > 80:
            break
        indexes = turn + indexes
        refs.update((r['id'], r) for r in dependencies)
    return [history[index] for index in indexes], list(refs.values()), indexes
