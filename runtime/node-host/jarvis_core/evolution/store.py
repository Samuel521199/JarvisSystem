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
from .settings import migrate, purpose

ACTIVE = ('QUEUED', 'RUNNING', 'OBSERVING')


def now():
    return datetime.now(timezone.utc).isoformat()


def plain_file(path, limit=1024*1024):
    path = policy.safe_path(path, directory=False)
    if path.stat().st_nlink != 1 or path.stat().st_size > limit:
        raise policy.CoreError('evolution_file_invalid', '进化文件不是独立普通文件，或超过大小限制。')
    return path


def tool_fallback(db, job):
    """Restore only the recorded prior stable package; never execute on recovery."""
    ident=job.get('tool_recovery_previous');base=job['request'].get('base',{})
    if not ident or ident!=base.get('active'):return None
    try:
        row=db.execute('SELECT state,document FROM tool_versions WHERE id=?',(ident,)).fetchone()
        if not row or row['state']!='VERIFIED':return None
        doc=json.loads(row['document'])
        if policy.digest(policy.canonical_json(doc).encode())[7:]!=ident or any(doc.get(k)!=base.get(k) for k in ('project_id','tool_id')):return None
        from ..coding_build import bytes_from
        bytes_from(doc['build'])
        return ident
    except (ValueError,KeyError,TypeError,policy.CoreError):return None


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
            if version not in (0, 1, 2, 3, 4, 5, 6, 7, 8, 9):
                raise policy.CoreError('evolution_schema_invalid', '进化账本版本不兼容。')
            db.executescript('''
                CREATE TABLE IF NOT EXISTS settings(singleton INTEGER PRIMARY KEY,document TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS selection(singleton INTEGER PRIMARY KEY,active TEXT,previous TEXT,generation INTEGER NOT NULL);
                CREATE TABLE IF NOT EXISTS packages(id TEXT PRIMARY KEY,revision INTEGER NOT NULL,state TEXT NOT NULL,document TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS jobs(id TEXT PRIMARY KEY,request_id TEXT UNIQUE NOT NULL,status TEXT NOT NULL,document TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS incidents(id TEXT PRIMARY KEY,created_at TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS project_tools(project_id TEXT NOT NULL,tool_id TEXT NOT NULL,active TEXT,previous TEXT,generation INTEGER NOT NULL,PRIMARY KEY(project_id,tool_id));
                CREATE TABLE IF NOT EXISTS tool_versions(id TEXT PRIMARY KEY,state TEXT NOT NULL,document TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS tool_lifecycle(project_id TEXT NOT NULL,tool_id TEXT NOT NULL,document TEXT NOT NULL,PRIMARY KEY(project_id,tool_id));
                CREATE TABLE IF NOT EXISTS maintenance_receipts(id TEXT PRIMARY KEY,binding TEXT NOT NULL,document TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS growth_policies(project_id TEXT PRIMARY KEY,document TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS growth_cycles(id TEXT PRIMARY KEY,project_id TEXT NOT NULL,document TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS ranking_versions(id TEXT PRIMARY KEY,document TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS ranking_selection(singleton INTEGER PRIMARY KEY,document TEXT NOT NULL);
            ''')
            db.execute('INSERT OR IGNORE INTO settings VALUES(1,?)', (policy.canonical_json(
                {'enabled': False, 'route': route, 'target_revision': 1, 'interval_seconds': 1800}),))
            db.execute('INSERT OR IGNORE INTO selection VALUES(1,NULL,NULL,0)')
            settings = migrate(json.loads(db.execute('SELECT document FROM settings WHERE singleton=1').fetchone()[0]))
            db.execute('UPDATE settings SET document=? WHERE singleton=1', (policy.canonical_json(settings),))
            db.execute('INSERT OR IGNORE INTO ranking_selection VALUES(1,?)', (policy.canonical_json(
                {'active':None,'previous':None,'generation':0,'trial':False,'samples':[],'last_event':'initial'}),))
            db.execute('PRAGMA user_version='+str(max(8,version)))

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
            db.execute('BEGIN IMMEDIATE')
            current = json.loads(db.execute('SELECT document FROM settings WHERE singleton=1').fetchone()[0])
            if settings['revision'] != current['revision']:
                raise policy.CoreError('evolution_conflict', '成长设置已被其他页面修改，请重新载入后再保存。')
            settings = {**settings, 'revision': current['revision'] + 1}
            db.execute('UPDATE settings SET document=? WHERE singleton=1', (policy.canonical_json(settings),))

    def selection(self):
        with self.connection() as db:
            return dict(db.execute('SELECT * FROM selection WHERE singleton=1').fetchone())

    def job(self, ident):
        with self.connection() as db:
            row = db.execute('SELECT document FROM jobs WHERE id=?', (ident,)).fetchone()
            if row is None: raise policy.CoreError('not_found', '改进任务不存在。')
            return self.hydrate(row[0])

    def hydrate(self, raw):
        from .maintenance import LedgerMaintenance
        return LedgerMaintenance.read(self, json.loads(raw))

    def create_job(self, payload, *, proposal=None):
        with self.core.effect_guard(), self.connection() as db:
            db.execute('BEGIN IMMEDIATE')
            existing = db.execute('SELECT document FROM jobs WHERE request_id=?', (payload['request_id'],)).fetchone()
            if existing:
                value = self.hydrate(existing[0])
                if value['request'] != payload:
                    raise policy.CoreError('evolution_conflict', '同一请求编号对应了不同内容。')
                return value, False
            if proposal is None and db.execute("SELECT 1 FROM jobs WHERE status IN ('QUEUED','RUNNING','OBSERVING')").fetchone():
                raise policy.CoreError('evolution_busy', '已有一个改进或工具任务正在处理。')
            if db.execute("SELECT COUNT(*) FROM jobs WHERE json_extract(document,'$.receipt_archive') IS NULL").fetchone()[0] >= 1000:
                raise policy.CoreError('evolution_quota', '改进账本达到保留上限，请整理证据后再继续。')
            if db.execute('SELECT COUNT(*) FROM jobs').fetchone()[0] >= 5096:
                raise policy.CoreError('evolution_quota', '回执总索引达到上限，原任务编号继续保留。')
            if payload.get('action') in {'project-tool','project-tool-plan','tool-contract','ranking-improve'}:
                # Leave room for the immutable package, escaped output, recovery
                # receipt and SQLite page growth; never fill the 32 MiB ledger.
                used = (db.execute('PRAGMA page_count').fetchone()[0]-db.execute('PRAGMA freelist_count').fetchone()[0]) * db.execute('PRAGMA page_size').fetchone()[0]
                reserve = 6 * len(policy.canonical_json(payload).encode()) + 2 * 1024 * 1024
                archiving=payload.get('action')=='project-tool' and payload.get('submission',{}).get('operation')=='archive-version'
                if archiving:reserve=256*1024  # Small immutable digest request; preserve maintenance headroom.
                if used + reserve > (30 if archiving else 28) * 1024 * 1024:
                    raise policy.CoreError('evolution_quota', '工具账本空间不足；已保留恢复空间，请先整理版本与证据。')
            value = {'id': uuid.uuid4().hex, 'request': payload, 'status': 'PROPOSED' if proposal is not None else 'QUEUED', 'created_at': now(),
                     'events': [], 'attempts': [], 'result': None, 'error': None}
            settings = json.loads(db.execute('SELECT document FROM settings WHERE singleton=1').fetchone()[0])
            value.update(purpose=purpose(payload['action']), policy_revision=settings['revision'], policy=settings)
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
        row = db.execute("SELECT json_extract(document,'$.receipt_archive') FROM jobs WHERE id=?", (value['id'],)).fetchone()
        if row and row[0] is not None:
            raise policy.CoreError('evolution_conflict', '已归档的终态回执不可改写或重新执行。')
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
                settings['auto_heal'] = False
                settings['revision'] += 1
                db.execute('UPDATE settings SET document=? WHERE singleton=1', (policy.canonical_json(settings),))
            if broken:
                db.execute("UPDATE packages SET state='QUARANTINED' WHERE id=?", (broken,))

    def recover(self):
        # Called only while holding the cross-process lane lock.
        with self.connection() as db:
            db.execute('BEGIN IMMEDIATE')
            rows = db.execute("SELECT document FROM jobs WHERE status IN ('QUEUED','RUNNING','OBSERVING') OR (json_extract(document,'$.published') IS NOT NULL AND json_extract(document,'$.activation_confirmed')=0) OR (json_extract(document,'$.tool_activation.version') IS NOT NULL AND json_extract(document,'$.tool_activation_confirmed')=0)").fetchall()
            for row in rows:
                value = json.loads(row[0])
                pending=value.get('tool_activation')
                if pending and not value.get('tool_activation_confirmed'):
                    fallback=tool_fallback(db,value)
                    db.execute('UPDATE project_tools SET active=?,previous=NULL,generation=generation+1 WHERE project_id=? AND tool_id=? AND active=? AND generation=?',
                               (fallback,pending['project_id'],pending['tool_id'],pending['version'],pending['generation']))
                    db.execute("UPDATE tool_versions SET state='QUARANTINED' WHERE id=?",(pending['version'],))
                    state=db.execute('SELECT document FROM tool_lifecycle WHERE project_id=? AND tool_id=?',(pending['project_id'],pending['tool_id'])).fetchone()
                    if state:
                        state=json.loads(state[0]);state.update(phase='REJECTED',reason='promotion_interrupted',revision=state['revision']+1)
                        db.execute('UPDATE tool_lifecycle SET document=? WHERE project_id=? AND tool_id=?',(policy.canonical_json(state),pending['project_id'],pending['tool_id']))
                active = db.execute('SELECT active FROM selection').fetchone()[0]
                if active and active == value.get('published') and not value.get('activation_confirmed'):
                    # Deactivate until a fresh check; do not trust an unverified fallback on recovery.
                    db.execute('UPDATE selection SET active=NULL,generation=generation+1')
                    db.execute("UPDATE packages SET state='QUARANTINED' WHERE id=?", (active,))
                value.update(status='INTERRUPTED', error='进程中断；未重放模型调用，未确认的启用已停用。')
                self.write_job(db, value)

        with self.connection() as db:
            for row in db.execute('SELECT project_id,tool_id,document FROM tool_lifecycle').fetchall():
                value=json.loads(row['document'])
                if value['phase']=='CANARY':
                    value.update(phase='PAUSED',revision=value['revision']+1,reason='restart_review',updated_at=now())
                    db.execute('UPDATE tool_lifecycle SET document=? WHERE project_id=? AND tool_id=?',(policy.canonical_json(value),row['project_id'],row['tool_id']))

    def existing_job(self, request_id):
        with self.connection() as db:
            row = db.execute('SELECT document FROM jobs WHERE request_id=?', (request_id,)).fetchone()
            return self.hydrate(row[0]) if row else None

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
            rows = db.execute("SELECT id,document FROM jobs WHERE request_id LIKE 'auto-%' AND status='SUCCEEDED' AND json_extract(document,'$.receipt_archive') IS NULL ORDER BY rowid DESC").fetchall()
            healthy = []
            for row in rows:
                value = json.loads(row['document'])
                if (value['request']['action'] == 'check' and not value.get('issue') and not value['attempts']
                        and (value.get('result', {}).get('healthy') is True
                             or value.get('result', {}).get('classification') == 'missing_optional')): healthy.append(row['id'])
            db.executemany('DELETE FROM jobs WHERE id=?', [(ident,) for ident in healthy[30:]])

    def snapshot(self):
        with self.connection() as db:
            # Routine inspections must not push the last healing/evolution work
            # out of their tabs. Legacy jobs keep their original mixed semantics.
            jobs = []
            for lane in ('inspect', 'heal', 'evolve'):
                rows = db.execute('''SELECT document FROM jobs WHERE COALESCE(json_extract(document,'$.purpose'),
                    CASE json_extract(document,'$.request.action') WHEN 'check' THEN 'inspect'
                    WHEN 'rollback' THEN 'heal' ELSE 'evolve' END)=? ORDER BY rowid DESC LIMIT 30''', (lane,))
                jobs.extend(json.loads(r[0]) for r in rows)
            jobs.sort(key=lambda row: row['created_at'], reverse=True)
            packages = [{**json.loads(r['document']), 'state': r['state']} for r in
                        db.execute('SELECT * FROM packages ORDER BY rowid DESC LIMIT 64')]
        return {'settings': self.settings(), 'selection': self.selection(), 'packages': packages,
                'jobs': [{k: v for k, v in row.items() if k not in {'attempts', 'events', 'result', 'request'}} |
                         {'action': row['request']['action'], 'event': row['events'][-1]['phase'] if row['events'] else 'QUEUED'}
                         for row in jobs]}
