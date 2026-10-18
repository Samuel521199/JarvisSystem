"""Content-addressed tool packages and transactional selection/improvement ledger."""
from contextlib import contextmanager
from datetime import datetime, timezone
import json
from pathlib import Path
import re
import sqlite3
import uuid

from .. import policy
from . import recipes

ACTIVE = ('QUEUED', 'RUNNING', 'OBSERVING')


def now():
    return datetime.now(timezone.utc).isoformat()


def plain_file(path, limit=1024*1024):
    path = policy.safe_path(path, directory=False)
    if path.stat().st_nlink != 1 or path.stat().st_size > limit:
        raise policy.CoreError('evolution_file_invalid', '进化文件不是独立普通文件，或超过大小限制。')
    return path


class EvolutionStore:
    def __init__(self, core, route):
        self.core = core
        self.root = policy.safe_path(Path(core.data_dir) / 'evolution', directory=True, must_exist=False)
        self.root.mkdir(parents=True, exist_ok=True)
        self.packages = policy.safe_path(self.root / 'packages', directory=True, must_exist=False)
        self.packages.mkdir(exist_ok=True)
        self.path = self.root / 'evolution.db'
        with self.connection() as db:
            version = db.execute('PRAGMA user_version').fetchone()[0]
            if version not in (0, 1):
                raise policy.CoreError('evolution_schema_invalid', '进化账本版本不兼容。')
            db.executescript('''
                CREATE TABLE IF NOT EXISTS settings(singleton INTEGER PRIMARY KEY,document TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS selection(singleton INTEGER PRIMARY KEY,active TEXT,previous TEXT,generation INTEGER NOT NULL);
                CREATE TABLE IF NOT EXISTS packages(id TEXT PRIMARY KEY,revision INTEGER NOT NULL,state TEXT NOT NULL,document TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS jobs(id TEXT PRIMARY KEY,request_id TEXT UNIQUE NOT NULL,status TEXT NOT NULL,document TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS incidents(id TEXT PRIMARY KEY,created_at TEXT NOT NULL);
            ''')
            db.execute('INSERT OR IGNORE INTO settings VALUES(1,?)', (policy.canonical_json(
                {'enabled': False, 'route': route, 'target_revision': 1, 'interval_seconds': 300}),))
            db.execute('INSERT OR IGNORE INTO selection VALUES(1,NULL,NULL,0)')
            db.execute('PRAGMA user_version=1')

    @contextmanager
    def connection(self):
        policy.safe_path(self.root, directory=True)
        for suffix in ('', '-wal', '-shm', '-journal'):
            path = policy.safe_path(str(self.path) + suffix, must_exist=False)
            if path.exists(): plain_file(path, 32*1024*1024)
        db = sqlite3.connect(self.path, timeout=3)
        db.row_factory = sqlite3.Row
        try:
            with db:
                yield db
        finally:
            db.close()

    def settings(self):
        with self.connection() as db:
            return json.loads(db.execute('SELECT document FROM settings WHERE singleton=1').fetchone()[0])

    def configure(self, settings):
        with self.core.effect_guard(), self.connection() as db:
            db.execute('UPDATE settings SET document=? WHERE singleton=1', (policy.canonical_json(settings),))

    def selection(self):
        with self.connection() as db:
            return dict(db.execute('SELECT * FROM selection WHERE singleton=1').fetchone())

    def job(self, ident):
        with self.connection() as db:
            row = db.execute('SELECT document FROM jobs WHERE id=?', (ident,)).fetchone()
            if row is None: raise policy.CoreError('not_found', '改进任务不存在。')
            return json.loads(row[0])

    def create_job(self, payload, *, proposal=None):
        with self.core.effect_guard(), self.connection() as db:
            db.execute('BEGIN IMMEDIATE')
            existing = db.execute('SELECT document FROM jobs WHERE request_id=?', (payload['request_id'],)).fetchone()
            if existing:
                value = json.loads(existing[0])
                if value['request'] != payload:
                    raise policy.CoreError('evolution_conflict', '同一请求编号对应了不同内容。')
                return value, False
            if proposal is None and db.execute("SELECT 1 FROM jobs WHERE status IN ('QUEUED','RUNNING','OBSERVING')").fetchone():
                raise policy.CoreError('evolution_busy', '已有一个改进或工具任务正在处理。')
            if db.execute('SELECT COUNT(*) FROM jobs').fetchone()[0] >= 1000:
                raise policy.CoreError('evolution_quota', '改进账本达到保留上限，请整理证据后再继续。')
            value = {'id': uuid.uuid4().hex, 'request': payload, 'status': 'PROPOSED' if proposal is not None else 'QUEUED', 'created_at': now(),
                     'events': [], 'attempts': [], 'result': None, 'error': None}
            if proposal is not None: value['proposal'] = proposal
            db.execute('INSERT INTO jobs VALUES(?,?,?,?)', (value['id'], payload['request_id'], value['status'], policy.canonical_json(value)))
            return value, True

    def queue_proposal(self, ident):
        """One durable admission; recovery never restarts an interrupted job."""
        with self.core.effect_guard(), self.connection() as db:
            db.execute('BEGIN IMMEDIATE')
            row = db.execute('SELECT document FROM jobs WHERE id=?', (ident,)).fetchone()
            if row is None: raise policy.CoreError('not_found', '改进单不存在。')
            value = json.loads(row[0])
            if value['status'] != 'PROPOSED': return value, False
            if db.execute("SELECT 1 FROM jobs WHERE status IN ('QUEUED','RUNNING','OBSERVING')").fetchone():
                raise policy.CoreError('evolution_busy', '已有成长任务，请稍后启动此改进单。')
            value['status'] = 'QUEUED'
            value['events'].append({'at': now(), 'phase': 'OWNER_REQUESTED'})
            self.write_job(db, value)
            return value, True

    @staticmethod
    def write_job(db, value):
        value['updated_at'] = now()
        db.execute('UPDATE jobs SET status=?,document=? WHERE id=?',
                   (value['status'], policy.canonical_json(value), value['id']))

    def update(self, value, phase=None, **fields):
        value.update(fields)
        if phase:
            value['events'].append({'at': now(), 'phase': phase})
        with self.connection() as db:
            self.write_job(db, value)

    def stage(self, candidate, revision, receipt):
        build_id = uuid.uuid4().hex
        files = {'candidate.py': candidate['code'], 'SKILL.md': recipes.reference_skill(revision),
                 'manifest.json': policy.canonical_json({**recipes.metadata(revision), 'build_id': build_id})}
        ident = policy.digest(policy.canonical_json(files).encode())[7:]
        with self.core.effect_guard(), self.connection() as db:
            existing = db.execute('SELECT id FROM packages WHERE id=?', (ident,)).fetchone()
            if existing:
                self.read_package(ident)
                return ident
            if db.execute('SELECT COUNT(*) FROM packages').fetchone()[0] >= 64:
                raise policy.CoreError('evolution_quota', '已保留 64 个候选包，请先审阅退役记录。')
            target = policy.safe_path(self.packages / ident, must_exist=False, directory=True)
            # Never reuse a partial/unregistered directory after an interrupted write.
            if target.exists():
                raise policy.CoreError('evolution_package_orphan', '发现未登记候选目录，请先核对恢复材料。')
            target.mkdir()
            for name, content in files.items():
                with (target / name).open('x', encoding='utf-8', newline='') as stream:
                    stream.write(content)
                    stream.flush()
                    import os
                    os.fsync(stream.fileno())
            value = {'id': ident, 'revision': revision, 'build_id': build_id, 'created_at': now(),
                     'files': {n: policy.digest(v.encode()) for n, v in files.items()},
                     'coding_receipt': receipt, 'notes': candidate.get('notes', ''), 'validation': None}
            db.execute('INSERT INTO packages VALUES(?,?,?,?)', (ident, revision, 'CANDIDATE', policy.canonical_json(value)))
        return ident

    def package(self, ident):
        if not isinstance(ident, str) or not re.fullmatch('[0-9a-f]{64}', ident):
            raise policy.CoreError('evolution_package_invalid', '技能包编号无效。')
        with self.connection() as db:
            row = db.execute('SELECT * FROM packages WHERE id=?', (ident,)).fetchone()
            if row is None: raise policy.CoreError('not_found', '技能包未登记。')
            return {**json.loads(row['document']), 'state': row['state']}

    def read_package(self, ident):
        record = self.package(ident)
        root = policy.safe_path(self.packages / ident, directory=True)
        if {p.name for p in root.iterdir()} != {'candidate.py', 'SKILL.md', 'manifest.json'}:
            raise policy.CoreError('evolution_package_changed', '技能包文件集合发生变化。')
        try:
            files = {name: plain_file(root / name, 32768).read_bytes().decode('utf-8') for name in record['files']}
        except UnicodeError:
            raise policy.CoreError('evolution_package_changed', '技能包编码损坏。') from None
        if (policy.digest(policy.canonical_json(files).encode())[7:] != ident or
                any(policy.digest(v.encode()) != record['files'][n] for n, v in files.items()) or
                files['manifest.json'] != policy.canonical_json({**recipes.metadata(record['revision']), 'build_id': record['build_id']})):
            raise policy.CoreError('evolution_package_changed', '技能包内容或验收契约发生变化。')
        return record, files

    def assess(self, ident, state, evidence):
        with self.connection() as db:
            row = db.execute('SELECT document FROM packages WHERE id=?', (ident,)).fetchone()
            value = json.loads(row[0]); value['validation'] = evidence
            db.execute('UPDATE packages SET state=?,document=? WHERE id=?', (state, policy.canonical_json(value), ident))

    def activate(self, ident, base, job):
        record, _ = self.read_package(ident)
        if record['state'] != 'VERIFIED':
            raise policy.CoreError('evolution_unverified', '候选未通过独立验收。')
        with self.core.effect_guard(), self.connection() as db:
            db.execute('BEGIN IMMEDIATE')
            current = dict(db.execute('SELECT * FROM selection').fetchone())
            if current != base:
                raise policy.CoreError('evolution_conflict', '当前版本已变化，候选没有覆盖新基线。')
            db.execute('UPDATE selection SET active=?,previous=active,generation=generation+1', (ident,))
            job.update(status='OBSERVING', published=ident, activation_confirmed=False)
            job['events'].append({'at': now(), 'phase': 'ACTIVATED'})
            self.write_job(db, job)

    def restore(self, broken, replacement, *, pause_automatic=False):
        if replacement:
            record, _ = self.read_package(replacement)
            if record['state'] != 'VERIFIED':
                raise policy.CoreError('evolution_unverified', '恢复目标不可用。')
        with self.core.effect_guard(), self.connection() as db:
            db.execute('BEGIN IMMEDIATE')
            if db.execute('SELECT active FROM selection').fetchone()[0] != broken:
                raise policy.CoreError('evolution_conflict', '活动版本已经变化，未执行过期回退。')
            db.execute('UPDATE selection SET active=?,previous=NULL,generation=generation+1', (replacement,))
            if pause_automatic:
                settings = json.loads(db.execute('SELECT document FROM settings WHERE singleton=1').fetchone()[0])
                settings['enabled'] = False
                db.execute('UPDATE settings SET document=? WHERE singleton=1', (policy.canonical_json(settings),))
            if broken:
                db.execute("UPDATE packages SET state='QUARANTINED' WHERE id=?", (broken,))

    def recover(self):
        # Called only while holding the cross-process lane lock.
        with self.connection() as db:
            db.execute('BEGIN IMMEDIATE')
            rows = db.execute("SELECT document FROM jobs WHERE status IN ('QUEUED','RUNNING','OBSERVING') OR (json_extract(document,'$.published') IS NOT NULL AND json_extract(document,'$.activation_confirmed')=0)").fetchall()
            for row in rows:
                value = json.loads(row[0])
                active = db.execute('SELECT active FROM selection').fetchone()[0]
                if active and active == value.get('published') and not value.get('activation_confirmed'):
                    # Deactivate until a fresh check; do not trust an unverified fallback on recovery.
                    db.execute('UPDATE selection SET active=NULL,generation=generation+1')
                    db.execute("UPDATE packages SET state='QUARANTINED' WHERE id=?", (active,))
                value.update(status='INTERRUPTED', error='进程中断；未重放模型调用，未确认的启用已停用。')
                self.write_job(db, value)

    def existing_job(self, request_id):
        with self.connection() as db:
            row = db.execute('SELECT document FROM jobs WHERE request_id=?', (request_id,)).fetchone()
            return json.loads(row[0]) if row else None

    def reserve_incident(self, ident):
        with self.connection() as db:
            db.execute('BEGIN IMMEDIATE')
            # Four autonomous incidents per UTC day; each has <=2 coding calls.
            day = now()[:10]
            if db.execute('SELECT COUNT(*) FROM incidents WHERE created_at LIKE ?', (day+'%',)).fetchone()[0] >= 4:
                return False
            return db.execute('INSERT OR IGNORE INTO incidents VALUES(?,?)', (ident, now())).rowcount == 1

    def compact_health_checks(self):
        # Only redundant successful, read-only automatic checks. Never remove
        # changes, model calls, user jobs, failure/UNKNOWN or recovery evidence.
        with self.core.effect_guard(), self.connection() as db:
            rows = db.execute("SELECT id,document FROM jobs WHERE request_id LIKE 'auto-%' AND status='SUCCEEDED' ORDER BY rowid DESC").fetchall()
            healthy = []
            for row in rows:
                value = json.loads(row['document'])
                if (value['request']['action'] == 'check' and not value.get('issue') and not value['attempts']
                        and value.get('result', {}).get('healthy') is True): healthy.append(row['id'])
            db.executemany('DELETE FROM jobs WHERE id=?', [(ident,) for ident in healthy[30:]])

    def snapshot(self):
        with self.connection() as db:
            jobs = [json.loads(r[0]) for r in db.execute('SELECT document FROM jobs ORDER BY rowid DESC LIMIT 30')]
            packages = [{**json.loads(r['document']), 'state': r['state']} for r in
                        db.execute('SELECT * FROM packages ORDER BY rowid DESC LIMIT 64')]
        return {'settings': self.settings(), 'selection': self.selection(), 'packages': packages,
                'jobs': [{k: v for k, v in row.items() if k not in {'attempts', 'events', 'result', 'request'}} |
                         {'action': row['request']['action'], 'event': row['events'][-1]['phase'] if row['events'] else 'QUEUED'}
                         for row in jobs]}
