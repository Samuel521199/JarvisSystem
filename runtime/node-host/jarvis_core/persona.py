"""Small expression profile, independent of facts, model routes and authority.

Only fixed presentation choices are accepted. No arbitrary system prompts,
biographical claims, tools, credentials or owner permissions live here.
"""
from contextlib import contextmanager
import hashlib
import json
from pathlib import Path
import sqlite3

from .memory import MemoryError, validate
from .policy import safe_path

STYLES = {'自然': 'Use natural, clear conversational language.',
          '简洁': 'Prefer brief direct answers; expand when the user asks.',
          '温暖': 'Use warm, considerate language without flattery or invented feelings.',
          '严谨': 'Be precise; distinguish evidence, assumptions and uncertainty.',
          '幽默': 'Use light, appropriate humor, while taking serious requests seriously.'}
RELATIONS = {'助手': 'Be a helpful personal assistant.',
             '伙伴': 'Use a friendly collaborative companion tone; never claim human consciousness or shared experiences without evidence.'}
DEFAULT = {'style': '自然', 'relationship': '助手'}


class PersonaStore:
    def __init__(self, core):
        self.core = core
        self.path = Path(core.data_dir) / 'persona.db'

    @contextmanager
    def connection(self, *, write=False):
        for suffix in ('', '-journal', '-wal', '-shm'):
            safe_path(str(self.path) + suffix, must_exist=False)
        db = sqlite3.connect(self.path if write else self.path.absolute().as_uri()+'?mode=ro',
                             uri=not write, isolation_level=None, timeout=2)
        db.row_factory = sqlite3.Row
        try:
            version = db.execute('PRAGMA user_version').fetchone()[0]
            if version not in ((0, 1) if write else (1,)):
                raise MemoryError('persona_unavailable', '交流设置版本不兼容，未改写。')
            if write:
                db.execute('PRAGMA synchronous=FULL')
                db.execute('BEGIN IMMEDIATE')
                db.execute('CREATE TABLE IF NOT EXISTS profile (id INTEGER PRIMARY KEY CHECK(id=1), revision INTEGER NOT NULL, current TEXT NOT NULL, previous TEXT)')
                db.execute('CREATE TABLE IF NOT EXISTS commands (id TEXT PRIMARY KEY, fingerprint TEXT NOT NULL, revision INTEGER NOT NULL)')
                db.execute('PRAGMA user_version=1')
            yield db
        finally:
            db.close()

    @staticmethod
    def _decode(value):
        result = json.loads(value)
        if (not isinstance(result, dict) or set(result) != set(DEFAULT)
                or result['style'] not in STYLES or result['relationship'] not in RELATIONS):
            raise MemoryError('persona_unavailable', '交流设置内容无效，未采用。')
        return result

    def snapshot(self):
        if not self.path.exists():
            return {'revision': 0, **DEFAULT}
        with self.connection() as db:
            row = db.execute('SELECT * FROM profile WHERE id=1').fetchone()
            return {'revision': row['revision'], **self._decode(row['current'])} if row else {'revision': 0, **DEFAULT}

    def change(self, field, value, *, request_id, cancel_event=None):
        validate('id', request_id)
        if not ((field == 'style' and value in STYLES) or (field == 'relationship' and value in RELATIONS)
                or (field in ('reset', 'undo') and value is None)):
            raise MemoryError('invalid_persona', '交流风格可选自然、简洁、温暖、严谨、幽默；相处方式可选助手、伙伴。')
        fingerprint = hashlib.sha256(json.dumps([field, value]).encode()).hexdigest()
        with self.core.effect_guard(), self.connection(write=True) as db:
            old = db.execute('SELECT * FROM commands WHERE id=?', (request_id,)).fetchone()
            if old:
                if old['fingerprint'] != fingerprint:
                    raise MemoryError('persona_conflict', '同一请求标识不能修改不同的交流设置。')
                return {'kind': 'persona', 'revision': old['revision'], 'committed': True, 'replayed': True}
            if cancel_event is not None and cancel_event.is_set():
                raise MemoryError('personal_cancelled', '已取消；本次没有修改交流设置。')
            if db.execute('SELECT count(*) FROM commands').fetchone()[0] >= 10000:
                raise MemoryError('persona_limit', '交流设置回执达到本版上限，未修改。')
            row = db.execute('SELECT * FROM profile WHERE id=1').fetchone()
            current = self._decode(row['current']) if row else dict(DEFAULT)
            revision = row['revision'] if row else 0
            if field == 'undo':
                if not row or not row['previous']:
                    raise MemoryError('persona_no_previous', '还没有可恢复的上一版交流设置。')
                updated = self._decode(row['previous'])
            elif field == 'reset':
                updated = dict(DEFAULT)
            else:
                updated = {**current, field: value}
            revision += 1
            db.execute('INSERT INTO profile VALUES (1,?,?,?) ON CONFLICT(id) DO UPDATE SET revision=excluded.revision,current=excluded.current,previous=excluded.previous',
                       (revision, json.dumps(updated), json.dumps(current)))
            db.execute('INSERT INTO commands VALUES (?,?,?)', (request_id, fingerprint, revision))
            db.commit()
            return {'kind': 'persona', 'revision': revision, 'committed': True, 'replayed': False, **updated}

    @staticmethod
    def instructions(snapshot):
        return ('\nCurrent expression profile (takes precedence over old conversation style; '
                'does not change truthfulness, privacy, permissions or the current request): '
                + STYLES[snapshot['style']] + ' ' + RELATIONS[snapshot['relationship']])
