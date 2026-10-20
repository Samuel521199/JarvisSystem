"""Explicit bounded ledger maintenance, independent of a full work queue.

Only terminal receipts move to verified local files. Original IDs and searchable
projections remain; no command, model, user file deletion or task replay occurs.
"""
import copy
from contextlib import closing
import json
import os
import re

from .. import policy
from ..worker_recovery import locked
from .store import plain_file, now

TERMINAL = {'SUCCEEDED', 'FAILED', 'CANCELLED', 'INTERRUPTED'}
LIMIT = 4 * 1024 * 1024
ARCHIVE_COUNT = 4096
ARCHIVE_BYTES = 128 * 1024 * 1024
MAINTENANCE_LIMIT = 256


def fail(message, code='maintenance_invalid'):
    raise policy.CoreError(code, message)


def strings(value):
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for child in value.values(): yield from strings(child)
    elif isinstance(value, list):
        for child in value: yield from strings(child)


def directory_count(db):
    return db.execute("""SELECT COUNT(*) FROM project_tools p WHERE NOT EXISTS
        (SELECT 1 FROM tool_lifecycle l WHERE l.project_id=p.project_id AND l.tool_id=p.tool_id
         AND json_extract(l.document,'$.phase')='STORED')""").fetchone()[0]


class LedgerMaintenance:
    def __init__(self, manager):
        self.manager, self.store, self.core = manager, manager.store, manager.core

    def archive_path(self, ident):
        if not isinstance(ident, str) or not re.fullmatch('[a-f0-9]{64}', ident): fail('归档标识无效。')
        root = policy.safe_path(self.store.root / 'receipt-archives', directory=True, must_exist=False)
        return root, policy.safe_path(root / (ident+'.json'), directory=False, must_exist=False)

    def archive_usage(self):
        root = policy.safe_path(self.store.root / 'receipt-archives', directory=True, must_exist=False)
        count = size = 0
        if root.exists():
            for entry in root.iterdir():
                if not re.fullmatch('[a-f0-9]{64}\\.json', entry.name): fail('回执归档区存在未识别材料。')
                size += plain_file(entry, LIMIT).stat().st_size
                count += 1
                if count > ARCHIVE_COUNT or size > ARCHIVE_BYTES: fail('回执归档区超过容量预算。')
        return {'files': count, 'bytes': size, 'file_limit': ARCHIVE_COUNT, 'byte_limit': ARCHIVE_BYTES}

    def save(self, doc):
        raw = policy.canonical_json({'schema': 1, 'job': doc}).encode()
        if len(raw) > LIMIT: fail('单份回执归档超过 4 MiB。')
        digest = policy.digest(raw); root, path = self.archive_path(digest[7:])
        usage = self.archive_usage()
        if not path.exists() and (usage['files'] >= ARCHIVE_COUNT or usage['bytes']+len(raw) > ARCHIVE_BYTES):
            fail('回执归档达到 4096 份或 128 MiB 上限，请维护归档存储。')
        root.mkdir(exist_ok=True)
        if not path.exists():
            with path.open('xb') as stream:
                stream.write(raw); stream.flush(); os.fsync(stream.fileno())
        if plain_file(path, LIMIT).read_bytes() != raw: fail('已有归档不完整或不一致，未覆盖材料。')
        return {'sha256': digest, 'bytes': len(raw)}

    @staticmethod
    def read(store, projection):
        proof = projection.get('receipt_archive')
        if not proof: return projection
        digest = proof.get('sha256', '')
        if not re.fullmatch('sha256:[a-f0-9]{64}', digest): fail('回执归档摘要无效。')
        root = policy.safe_path(store.root/'receipt-archives', directory=True)
        path = policy.safe_path(root/(digest[7:]+'.json'), directory=False)
        raw = plain_file(path, LIMIT).read_bytes()
        if len(raw) != proof.get('bytes') or policy.digest(raw) != digest: fail('回执归档损坏；没有重新执行原任务。')
        try:
            payload = json.loads(raw); value = payload['job']
            if set(payload) != {'schema', 'job'} or payload['schema'] != 1 or not isinstance(value, dict): raise ValueError()
            if any(value[k] != projection[k] for k in ('id', 'status', 'created_at')): raise ValueError()
            if value['request']['request_id'] != projection['request']['request_id']: raise ValueError()
            if value['status'] not in TERMINAL: raise ValueError()
        except (ValueError, KeyError, TypeError): fail('回执归档结构或身份不一致。')
        return value

    def references(self, db):
        """Conservative references, never infer terminality from age."""
        refs = {}
        def add(value, source):
            for item in strings(value):
                if re.fullmatch('[a-f0-9]{32}', item): refs.setdefault(item, set()).add(source)
        for row in db.execute('SELECT id,document FROM jobs'):
            doc = json.loads(row['document'])
            if doc.get('receipt_archive'): continue
            # Self identity is not a reference; nested parent/review IDs are.
            add({k:v for k,v in doc.items() if k not in {'id','request','result','events','attempts'}}, '任务关联')
            add({k:v for k,v in doc.get('request',{}).items() if k not in {'request_id','submission','package','input'}}, '任务来源或冻结状态')
            if doc['status'] not in TERMINAL: add(doc.get('result'), '在途结果')
        for table in ('tool_lifecycle', 'packages'):
            for row in db.execute('SELECT document FROM '+table): add(json.loads(row[0]), '生命周期或恢复材料')
        # Read only: do not initialize/mutate the conversation database here.
        from ..conversations import ConversationStore
        path = policy.safe_path(ConversationStore(self.core).path, directory=False, must_exist=False)
        if path.exists():
            import sqlite3
            with closing(sqlite3.connect(path.as_uri()+'?mode=ro', uri=True, timeout=2)) as chats:
                for row in chats.execute("SELECT document FROM conversations WHERE deleted=0 AND document IS NOT NULL"):
                    doc = json.loads(row[0])
                    for message in doc.get('messages', []):
                        if message.get('growth_ref'): add(message['growth_ref'], '会话回执链接')
        return refs

    @staticmethod
    def projection(doc, proof):
        value = {k:v for k,v in doc.items() if k in {'id','status','created_at','updated_at','purpose','error'}}
        request = doc['request']
        value.update(request={k:v for k,v in request.items() if k in {'action','request_id','scope','origin','plan_id'}},
                     events=[{'at':now(),'phase':'RECEIPT_ARCHIVED'}], attempts=[], result=None, receipt_archive=proof)
        if 'submission' in request:
            value['request']['submission']={k:v for k,v in request['submission'].items() if k in {'tool_id','operation'}}
        return value

    def _preview(self, db):
        refs = self.references(db); jobs = []; online = archived = 0
        for row in db.execute('SELECT id,document FROM jobs ORDER BY rowid DESC'):
            doc = json.loads(row['document'])
            if doc.get('receipt_archive'): archived += 1; continue
            online += 1; reasons = sorted(refs.get(row['id'], set()))
            if doc['status'] not in TERMINAL: reasons.append('非确定终态（含待开始、未知与在途）')
            if doc['request']['action'] == 'tool-contract': reasons.append('契约草案仍可审阅，不整理')
            if (doc.get('published') and not doc.get('activation_confirmed')) or (doc.get('tool_activation') and not doc.get('tool_activation_confirmed')):
                reasons.append('启用结果尚未确认')
            jobs.append({'id': row['id'], 'status': doc['status'], 'action': doc['request']['action'],
                         'created_at': doc['created_at'], 'bytes': len(row['document'].encode()),
                         'binding': policy.digest(row['document'].encode()), 'eligible': not reasons, 'reasons': reasons})
        directories = []
        active_scope = set()
        for row in db.execute("SELECT document FROM jobs WHERE status IN ('PROPOSED','QUEUED','RUNNING','OBSERVING','UNKNOWN')"):
            doc = json.loads(row[0]); scope = doc['request'].get('scope', {})
            if scope.get('project_id'): active_scope.add(scope['project_id'])
        for row in db.execute('SELECT * FROM project_tools ORDER BY project_id,tool_id'):
            selected = dict(row)
            record = db.execute('SELECT document FROM tool_lifecycle WHERE project_id=? AND tool_id=?', (row['project_id'],row['tool_id'])).fetchone()
            life = json.loads(record[0]) if record else {'phase':'LEGACY','revision':0}
            stored = life['phase'] == 'STORED'; reasons = []
            if not stored and (life['phase'] != 'RETIRED' or row['active']): reasons.append('需先明确退役且停止活动选择')
            if row['project_id'] in active_scope: reasons.append('本项目有待开始、未知或在途任务')
            directories.append({'project_id': row['project_id'], 'tool_id': row['tool_id'], 'phase':life['phase'],
                                'generation':row['generation'], 'eligible':not reasons, 'reasons': reasons,
                                'binding':policy.digest(policy.canonical_json([selected,life]).encode())})
        page = db.execute('PRAGMA page_size').fetchone()[0]
        return {'jobs':jobs, 'directories':directories, 'capacity':{
            'online_jobs':online, 'archived_jobs':archived, 'online_limit':1000, 'index_limit':1000+ARCHIVE_COUNT,
            'online_directories':directory_count(db), 'directory_limit':32,
            'maintenance_receipts':db.execute('SELECT COUNT(*) FROM maintenance_receipts').fetchone()[0],
            'maintenance_limit':MAINTENANCE_LIMIT,
            'ledger_allocated_bytes':db.execute('PRAGMA page_count').fetchone()[0]*page,
            'ledger_reusable_bytes':db.execute('PRAGMA freelist_count').fetchone()[0]*page},
            'archive':self.archive_usage(), 'model_calls':0,
            'recent_maintenance':[json.loads(r[0]) for r in db.execute('SELECT document FROM maintenance_receipts ORDER BY rowid DESC LIMIT 20')],
            'note':'只读预览；归档保留原 ID 和完整材料，释放在线名额，不等于释放磁盘。目录收存保留恢复版本，不启用代码。'}

    def preview(self):
        self.core.assert_running()
        with self.manager.lock, self.store.connection() as db: return self._preview(db)

    def apply(self, payload):
        fields = {'request_id','operation','targets','reviewed','review_note'}
        if not isinstance(payload, dict) or set(payload) != fields: fail('整理请求字段不完整。')
        if not isinstance(payload['request_id'],str) or not re.fullmatch('[a-f0-9]{32}',payload['request_id']): fail('整理请求编号无效。')
        if not isinstance(payload['operation'],str) or payload['operation'] not in {'archive-receipts','store-directory','restore-directory'}: fail('整理动作无效。')
        from .lifecycle import checked_note
        if payload['reviewed'] is not True: fail('请先核对预览及恢复范围。')
        checked_note(payload['review_note'])
        targets = payload['targets']
        if not isinstance(targets,list) or not 1 <= len(targets) <= 20: fail('每次整理 1—20 项。')
        directory = payload['operation'] != 'archive-receipts'
        if directory and len(targets) != 1: fail('每次只整理一个目录身份。')
        for target in targets:
            needed = {'project_id','tool_id','binding'} if directory else {'id','binding'}
            if not isinstance(target,dict) or set(target) != needed or any(not isinstance(v,str) for v in target.values()): fail('目标字段无效。')
        if len({policy.canonical_json(t) for t in targets}) != len(targets): fail('整理目标不能重复。')
        binding = policy.digest(policy.canonical_json(payload).encode())
        with self.manager.lock, self.core.effect_guard(), self.store.connection() as db:
            db.execute('BEGIN IMMEDIATE')
            prior = db.execute('SELECT binding,document FROM maintenance_receipts WHERE id=?',(payload['request_id'],)).fetchone()
            if prior:
                if prior['binding'] != binding: fail('整理编号已用于其他内容。','evolution_conflict')
                return json.loads(prior['document'])
            if self.manager.busy: fail('成长任务进行中，请结束后整理。','evolution_busy')
            with locked(self.store.root/'.lane.lock'):
                current = self._preview(db)
                if current['capacity']['maintenance_receipts'] >= MAINTENANCE_LIMIT: fail('整理审计达到 256 条上限；未删除审计。')
                used = current['capacity']['ledger_allocated_bytes']-current['capacity']['ledger_reusable_bytes']
                if used+65536 > 31*1024*1024: fail('账本维护余量不足；未改动记录。')
                collection = current['directories'] if directory else current['jobs']
                for target in targets:
                    found = next((x for x in collection if all(x.get(k)==v for k,v in target.items())),None)
                    if not found: fail('原预览已变化，请重新核对。','evolution_conflict')
                    if not found['eligible']: fail('仍有引用或状态不满足整理条件。','evolution_conflict')
                    if directory and (found['phase']=='STORED') != (payload['operation']=='restore-directory'): fail('目录状态与操作不符。')
                result = {'id':payload['request_id'], 'operation':payload['operation'], 'at':now(), 'targets':copy.deepcopy(targets),
                          'review_note':payload['review_note'], 'online_slots_released':0, 'model_calls':0,
                          'user_files_deleted':0, 'disk_space_freed_claimed':False}
                if directory:
                    self._directory(db, targets[0], payload['operation'], result)
                else:
                    for target in targets:
                        raw = db.execute('SELECT document FROM jobs WHERE id=?',(target['id'],)).fetchone()[0]
                        doc = json.loads(raw); proof = self.save(doc)
                        projection = self.projection(doc, proof)
                        encoded = policy.canonical_json(projection)
                        db.execute('UPDATE jobs SET document=? WHERE id=? AND document=?',(encoded,target['id'],raw))
                        result['online_slots_released'] += 1
                db.execute('INSERT INTO maintenance_receipts VALUES(?,?,?)',(payload['request_id'],binding,policy.canonical_json(result)))
                return result

    def _directory(self, db, target, operation, result):
        key = (target['project_id'],target['tool_id'])
        life = json.loads(db.execute('SELECT document FROM tool_lifecycle WHERE project_id=? AND tool_id=?',key).fetchone()[0])
        if operation == 'store-directory':
            life = {'phase':'STORED','revision':life['revision']+1,'candidate':None,'stored_lifecycle':life,'stored_at':now()}
            result['online_slots_released'] = 1
        else:
            if directory_count(db) >= 32: fail('在线目录名额已满，未恢复。')
            life = {**life['stored_lifecycle'],'phase':'RETIRED','revision':life['revision']+1,'updated_at':now()}
        # Leave previous/recovery packages intact. A stored identity is never
        # reused at generation zero; restore still requires original canary flow.
        db.execute('UPDATE project_tools SET generation=generation+1 WHERE project_id=? AND tool_id=?',key)
        db.execute('UPDATE tool_lifecycle SET document=? WHERE project_id=? AND tool_id=?',(policy.canonical_json(life),*key))
        result['phase'] = life['phase']
