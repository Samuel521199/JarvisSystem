"""Optional SQLite shared-card state; never opens the personal memory databases."""
from contextlib import closing
import json
import sqlite3
import threading

from . import policy
from . import federation_protocol as p


class FederationStore:
    def __init__(self, core):
        self.core = core
        self.path = core.data_dir / 'federation.db'
        self.lock = threading.RLock()

    def _path(self):
        for suffix in ('', '-journal', '-wal', '-shm'):
            policy.safe_path(str(self.path) + suffix, must_exist=False)
        return self.path

    def _read(self, db, node):
        if db.execute('PRAGMA user_version').fetchone()[0] != 1:
            p.fail('共享资料版本无法识别。', 'federation_storage')
        row = db.execute('SELECT node,state,revision FROM shared_state WHERE id=1').fetchone()
        if not row or row[0] != node:
            p.fail('共享资料与本机身份不匹配。', 'federation_storage')
        return json.loads(row[1]), row[2]

    def _guard_path(self):
        return policy.safe_path(self.core.data_dir/'federation/frontier.dpapi', must_exist=False)

    def _check_frontier(self, node, revision):
        from jarvis_models import vault
        try:
            value = vault.load(self._guard_path())
            if value != {'node': node, 'revision': revision}:
                raise ValueError()
        except Exception:
            p.fail('共享数据库与独立版本标记不一致；请保留恢复材料并检查，未自动重建或继续同步。',
                   'federation_storage')

    def read(self, node):
        with self.lock:
            if not self._path().exists():
                if self._guard_path().exists():
                    p.fail('共享数据库缺失，保留独立版本标记；未自动重建。', 'federation_storage')
                return {'spaces': {}}
            with closing(sqlite3.connect(self.path.as_uri() + '?mode=ro', uri=True, timeout=2)) as db:
                state, revision = self._read(db, node)
                self._check_frontier(node, revision)
                return state

    def change(self, node, update):
        from jarvis_models import vault
        with self.lock, self.core.effect_guard(), closing(sqlite3.connect(self._path(), timeout=2)) as db, db:
            db.execute('PRAGMA secure_delete=ON')
            db.execute('BEGIN IMMEDIATE')
            if db.execute('PRAGMA user_version').fetchone()[0] == 0:
                if self._guard_path().exists():
                    p.fail('共享数据库缺失或版本倒退，未重新初始化。', 'federation_storage')
                db.execute('CREATE TABLE shared_state(id INTEGER PRIMARY KEY CHECK(id=1),node TEXT NOT NULL,state TEXT NOT NULL,revision INTEGER NOT NULL)')
                db.execute('PRAGMA user_version=1')
                db.execute('INSERT INTO shared_state VALUES(1,?,?,0)', (node, '{"spaces":{}}'))
                state, revision = self._read(db, node)
            else:
                state, revision = self._read(db, node)
                self._check_frontier(node, revision)
            result = update(state)
            if len(state['spaces']) > p.MAX_SPACES or len(p.encode(state)) > 5 * 1024 * 1024:
                p.fail('共享空间容量已满。')
            # Reserve before commit. A crash in between fails closed on restart rather
            # than reusing an old sequence. Whole-directory clones need a future anchor.
            vault.save({'node': node, 'revision': revision + 1}, self._guard_path())
            db.execute('UPDATE shared_state SET state=?,revision=? WHERE id=1',
                       (p.encode(state).decode('utf-8'), revision + 1))
            return result
