"""Lazy SQLite settings for an optional, on-demand coding executor."""
from contextlib import closing
import json
import re
import sqlite3
from . import policy


class CodingSettings:
    def __init__(self,core): self.core=core
    def path(self):
        path=self.core.data_dir/'coding-settings.db'
        for suffix in ('','-wal','-shm','-journal'): policy.safe_path(str(path)+suffix,must_exist=False)
        return path
    def read(self):
        path=self.path()
        if not path.exists(): return {'revision':0,'enabled':False,'model':'gpt-6.1-sol','reasoning':'medium'}
        try:
            with closing(sqlite3.connect(path.as_uri()+'?mode=ro',uri=True,timeout=.1)) as db:
                if db.execute('PRAGMA user_version').fetchone()[0]!=1: raise ValueError()
                row=db.execute('SELECT revision,value FROM settings WHERE singleton=1').fetchone()
                value=json.loads(row[1]); self.validate(value)
                if value['revision']!=row[0]: raise ValueError()
                return value
        except (sqlite3.Error,TypeError,ValueError): raise policy.CoreError('coding_settings_unavailable','编码协作设置不可读；外部执行保持停用。') from None
    @staticmethod
    def validate(value):
        if (not isinstance(value,dict) or set(value)!={'revision','enabled','model','reasoning'}
                or type(value['revision']) is not int or value['revision']<0 or type(value['enabled']) is not bool
                or not isinstance(value['model'],str) or not re.fullmatch(r'[a-zA-Z0-9][a-zA-Z0-9._-]{0,79}',value['model'])
                or value['reasoning'] not in {'low','medium','high','xhigh'}):
            raise policy.CoreError('coding_settings_invalid','编码设置、模型名称或推理档位无效。')
    def write(self,value):
        self.validate(value);self.core.assert_running()
        self.read()  # Reject unknown/corrupt schema before any mutation.
        with closing(sqlite3.connect(self.path(),timeout=.1)) as db:
            with db:
                db.execute('BEGIN IMMEDIATE')
                db.execute('CREATE TABLE IF NOT EXISTS settings(singleton INTEGER PRIMARY KEY,revision INTEGER,value TEXT)')
                row=db.execute('SELECT revision FROM settings WHERE singleton=1').fetchone()
                if (row[0] if row else 0)!=value['revision']: raise policy.CoreError('coding_settings_conflict','设置已变化，请刷新。')
                updated={**value,'revision':value['revision']+1}
                db.execute('INSERT OR REPLACE INTO settings VALUES(1,?,?)',(updated['revision'],policy.canonical_json(updated)))
                db.execute('PRAGMA user_version=1')
        return self.read()
