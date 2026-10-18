"""Local chat archives, separate from task receipts and curated long-term memory.

Stores bounded plain text snapshots, never DOM, attachment payloads or drafts.
Optimistic revisions prevent stale tabs overwriting newer work. Tombstones stop
delayed autosaves resurrecting a deleted chat. No model or network dependency.
"""
from contextlib import contextmanager
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import sqlite3

from .policy import safe_path

MAX_DOCUMENT_BYTES = 2 * 1024 * 1024
MAX_STORE_BYTES = 64 * 1024 * 1024
MAX_CONVERSATIONS = 500
MAX_MESSAGES = 500


class ConversationError(ValueError):
    def __init__(self, code, message):
        self.code = code
        super().__init__(message)


def fail(code, message):
    raise ConversationError(code, message)


def identifier(value):
    if not isinstance(value, str) or not re.fullmatch(r'[a-f0-9]{32}', value):
        fail('invalid_conversation', '会话标识无效。')
    return value


def revision(value):
    if type(value) is not int or value < 0 or value > 2**53 - 1:
        fail('invalid_conversation', '会话版本无效。')
    return value


def bounded_text(value, maximum):
    if not isinstance(value, str) or '\0' in value or len(value.encode('utf-8')) > maximum:
        fail('invalid_conversation', '会话文本格式无效或超过保存上限。')
    return value


def validate_document(value):
    if not isinstance(value, dict) or not {'title', 'project_id', 'messages', 'context_note'} <= set(value) or set(value)-{'title','project_id','messages','context_note','continuity_ids'}:
        fail('invalid_conversation', '会话字段无效。')
    if 'continuity_ids' in value:
        from .continuity import validate_context
        try:validate_context({'enabled': True, 'ids': value['continuity_ids']})
        except (ValueError, TypeError):fail('invalid_conversation', '接续选择无效。')
    bounded_text(value['title'], 256)
    bounded_text(value['context_note'], 8192)
    if value['project_id'] is not None:
        identifier(value['project_id'])
    messages = value['messages']
    if not isinstance(messages, list) or not 1 <= len(messages) <= MAX_MESSAGES:
        fail('conversation_limit', '每个会话最多保存 500 条消息；请开启新会话，当前页面内容仍保留。')
    for row in messages:
        required = {'role', 'content', 'meta', 'short_meta', 'attachments_omitted', 'incomplete'}
        if not isinstance(row, dict) or not required <= set(row) or set(row) - required - {'memory_refs','knowledge_refs','knowledge_citations','task_control','task_ref','task_request_id','personal_control','continuity_refs','growth_ref','growth_request_id','reply_ref'}:
            fail('invalid_conversation', '消息字段无效；附件与 HTML 不属于会话归档格式。')
        if 'reply_ref' in row:identifier(row['reply_ref'])
        for key in ('growth_ref','growth_request_id'):
            if key in row:
                if row.get('personal_control') is not True: fail('invalid_conversation', '成长引用需要控制消息标志。')
                identifier(row[key])
        if 'task_control' in row and type(row['task_control']) is not bool:
            fail('invalid_conversation','任务控制标志无效。')
        if 'personal_control' in row and type(row['personal_control']) is not bool:
            fail('invalid_conversation','个人指令标志无效。')
        for field,pattern in [('task_ref',r'task_[a-f0-9]{32}'),('task_request_id',r'web-[a-f0-9]{32}')]:
            if field in row and (row.get('task_control') is not True or not isinstance(row[field],str) or not re.fullmatch(pattern,row[field])):
                fail('invalid_conversation','任务引用无效；引用本身不授予任务读取或取消权限。')
        if 'memory_refs' in row:
            from .memory import validate, MemoryError
            try:validate('references', row['memory_refs'])
            except MemoryError:fail('invalid_conversation', '记忆来源标识无效。')
        if 'continuity_refs' in row:
            from .continuity import validate_history_references
            from .memory import MemoryError
            try:validate_history_references([row['continuity_refs']],[{}])
            except MemoryError:fail('invalid_conversation', '接续来源标识无效。')
        from .knowledge import validate as validate_knowledge, KnowledgeError
        for field, kind in [('knowledge_refs','references'),('knowledge_citations','citations')]:
            if field in row:
                try:validate_knowledge(kind,row[field])
                except KnowledgeError:fail('invalid_conversation', '项目资料来源标识无效。')
        if row['role'] not in ('user', 'assistant', 'error', 'stopped'):
            fail('invalid_conversation', '消息角色无效。')
        bounded_text(row['content'], 1024 * 1024)
        bounded_text(row['meta'], 8192)
        bounded_text(row['short_meta'], 1024)
        if type(row['attachments_omitted']) is not bool or type(row['incomplete']) is not bool:
            fail('invalid_conversation', '消息状态无效。')
    encoded = json.dumps(value, ensure_ascii=False, separators=(',', ':'), sort_keys=True)
    size = len(encoded.encode('utf-8'))
    if size > MAX_DOCUMENT_BYTES:
        fail('conversation_limit', '当前会话超过 2 MiB 保存上限，请开启新会话；原记录未被截断。')
    return encoded, size, hashlib.sha256(encoded.encode('utf-8')).hexdigest()


class ConversationStore:
    def __init__(self, core):
        self.core = core
        self.directory = Path(core.data_dir)
        self.path = self.directory / 'conversations.db'

    @contextmanager
    def connection(self, *, timeout=2):
        safe_path(self.directory, directory=True)
        for suffix in ('', '-journal', '-wal', '-shm'):
            safe_path(str(self.path) + suffix, must_exist=False)
        db = sqlite3.connect(self.path, timeout=timeout, isolation_level=None)
        db.row_factory = sqlite3.Row
        try:
            db.execute('PRAGMA synchronous=FULL')
            db.execute('PRAGMA secure_delete=ON')
            db.execute('CREATE TABLE IF NOT EXISTS conversations (id TEXT PRIMARY KEY, revision INTEGER NOT NULL, document TEXT, digest TEXT, size INTEGER NOT NULL, updated_at TEXT NOT NULL, deleted INTEGER NOT NULL DEFAULT 0)')
            yield db
        finally:
            db.close()

    def list(self):
        with self.connection() as db:
            rows = db.execute("SELECT id,revision,updated_at,json_extract(document,'$.title') AS title,json_extract(document,'$.project_id') AS project_id FROM conversations WHERE deleted=0 ORDER BY updated_at DESC LIMIT ?", (MAX_CONVERSATIONS,)).fetchall()
        return {'conversations': [dict(row) for row in rows]}

    def get(self, chat_id):
        identifier(chat_id)
        with self.connection() as db:
            row = db.execute('SELECT * FROM conversations WHERE id=? AND deleted=0', (chat_id,)).fetchone()
        if row is None:
            fail('conversation_not_found', '该会话不存在或已删除。')
        return {'id': chat_id, 'revision': row['revision'], 'document': json.loads(row['document'])}

    def put(self, chat_id, payload):
        identifier(chat_id)
        if not isinstance(payload, dict) or set(payload) != {'revision', 'document'}:
            fail('invalid_conversation', '会话保存字段无效。')
        expected = revision(payload['revision'])
        document, size, digest = validate_document(payload['document'])
        with self.core.effect_guard(), self.connection() as db:
            db.execute('BEGIN IMMEDIATE')
            row = db.execute('SELECT revision,digest,size,deleted FROM conversations WHERE id=?', (chat_id,)).fetchone()
            if row and row['deleted']:
                fail('conversation_deleted', '该会话已删除，不会由旧页面重新保存。')
            current = row['revision'] if row else 0
            if row and row['digest'] == digest and expected in (current, current - 1):
                db.commit()
                return {'id': chat_id, 'revision': current, 'status': 'saved'}
            if expected != current:
                fail('conversation_conflict', '另一页面已更新此会话；当前内容仍在页面，请刷新核对后继续。')
            usage = db.execute('SELECT count(*) AS count,coalesce(sum(size),0) AS size FROM conversations WHERE deleted=0').fetchone()
            if (not row and usage['count'] >= MAX_CONVERSATIONS) or usage['size'] - (row['size'] if row else 0) + size > MAX_STORE_BYTES:
                fail('conversation_limit', '本机会话归档已达上限，请删除不需要的会话；旧记录不会自动丢弃。')
            now = datetime.now(timezone.utc).isoformat()
            db.execute('INSERT INTO conversations VALUES (?,?,?,?,?,?,0) ON CONFLICT(id) DO UPDATE SET revision=excluded.revision,document=excluded.document,digest=excluded.digest,size=excluded.size,updated_at=excluded.updated_at', (chat_id, current + 1, document, digest, size, now))
            db.commit()
        return {'id': chat_id, 'revision': current + 1, 'status': 'saved'}

    def delete(self, chat_id, payload):
        identifier(chat_id)
        if not isinstance(payload, dict) or set(payload) != {'revision'}:
            fail('invalid_conversation', '会话删除字段无效。')
        expected = revision(payload['revision'])
        with self.core.effect_guard(), self.connection() as db:
            db.execute('BEGIN IMMEDIATE')
            row = db.execute('SELECT revision,deleted FROM conversations WHERE id=?', (chat_id,)).fetchone()
            if row and row['deleted']:
                db.commit()
                return {'id': chat_id, 'status': 'deleted'}
            if expected != (row['revision'] if row else 0):
                fail('conversation_conflict', '另一页面已更新此会话，请刷新核对后删除。')
            db.execute('INSERT INTO conversations VALUES (?,?,NULL,NULL,0,?,1) ON CONFLICT(id) DO UPDATE SET revision=excluded.revision,document=NULL,digest=NULL,size=0,updated_at=excluded.updated_at,deleted=1', (chat_id, expected + 1, datetime.now(timezone.utc).isoformat()))
            if db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='dialogue_receipts'").fetchone():
                db.execute("UPDATE dialogue_receipts SET deleted=1,result=NULL,size=0,status='CANCELLED',cancelled=1,revision=revision+1 WHERE conversation_id=?",(chat_id,))
            db.commit()
        return {'id': chat_id, 'status': 'deleted'}
