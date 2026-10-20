"""Durable ranking selection. Data lives in the existing growth SQLite ledger."""
from contextlib import closing
import json
from pathlib import Path
import sqlite3
import threading
import time

from . import policy
from .ranking_program import Program


def document(row):
    if row is None or len(row[0]) > 100000:
        raise ValueError('ranking record')
    return json.loads(row[0])


def read_version(db, ident):
    value = document(db.execute('SELECT document FROM ranking_versions WHERE id=?', (ident,)).fetchone())
    if policy.digest(policy.canonical_json(value).encode())[7:] != ident:
        raise ValueError('ranking digest')
    from .ranking_evaluation import binding
    if value['binding'] != binding() or not value['evaluation']['passed']:
        raise ValueError('ranking incompatible')
    program = Program(value['source'], ident)
    if list(program.keys) != value['keys']:
        raise ValueError('ranking plan')
    return value, program


def select_row(db):
    return document(db.execute('SELECT document FROM ranking_selection WHERE singleton=1').fetchone())


def save(db, value):
    db.execute('UPDATE ranking_selection SET document=? WHERE singleton=1', (policy.canonical_json(value),))


def restore(db, current, reason):
    previous = current['previous']
    if previous:
        try: read_version(db, previous)
        except (ValueError, TypeError, KeyError, SyntaxError): previous = None
    current.update(active=previous, previous=None, trial=False, samples=[], generation=current['generation']+1,
                   last_event=reason)
    save(db, current)
    return current


class StoredRanking:
    """Read fresh selection per request; only trial counters write, no content cache."""
    protocol = 1
    requested_id = 'stored-ranking'

    def __init__(self, core):
        self.core = core
        self.path = Path(core.data_dir) / 'evolution/evolution.db'
        self.local = threading.local()

    @property
    def module_id(self):
        return getattr(self.local, 'module_id', 'lexical-v1')

    @module_id.setter
    def module_id(self, value):
        self.local.module_id = value

    def order(self, rows, words):
        from .retrieval_ranking import LexicalV1
        self.module_id = 'lexical-v1'
        if not self.path.exists():
            return LexicalV1.order(rows, words)
        selected = None
        try:
            policy.safe_path(self.path, directory=False)
            with closing(sqlite3.connect(self.path.as_uri()+'?mode=ro', uri=True, timeout=.1)) as db:
                schema = db.execute('PRAGMA user_version').fetchone()[0]
                if schema < 8:
                    return LexicalV1.order(rows, words)
                if schema not in (8, 9):
                    raise ValueError('unsupported ranking store schema')
                selected = select_row(db)
                if not selected['active']:
                    return LexicalV1.order(rows, words)
                _, program = read_version(db, selected['active'])
            started = time.perf_counter()
            result = program.order(rows, words)
            elapsed = time.perf_counter()-started
            self.module_id = program.module_id
            # Empty/no-match requests are not observation samples.
            if selected['trial'] and rows and words:
                sample = policy.digest(policy.canonical_json(list(words)).encode())
                self._observe(selected, sample, elapsed)
            return result
        except Exception:
            # A damaged selection must never take down knowledge or chat.
            if selected is not None:
                try: self._reject(selected)
                except Exception: pass
            self.module_id = 'lexical-v1'
            raise

    def _observe(self, selected, sample, elapsed):
        with self.core.effect_guard(), closing(sqlite3.connect(self.path, timeout=.1)) as db, db:
            db.execute('BEGIN IMMEDIATE')
            current = select_row(db)
            if current['generation'] != selected['generation'] or not current['trial']:
                return
            if elapsed > .05:
                restore(db, current, 'trial_latency_rollback')
                raise ValueError('ranking trial latency')
            if sample not in current['samples'] and len(current['samples']) < 12:
                current['samples'].append(sample)
                current['maximum_ms'] = max(current.get('maximum_ms', 0), round(elapsed*1000, 3))
                save(db, current)

    def _reject(self, selected):
        with self.core.effect_guard(), closing(sqlite3.connect(self.path, timeout=.1)) as db, db:
            db.execute('BEGIN IMMEDIATE')
            current = select_row(db)
            if current['generation'] == selected['generation']:
                restore(db, current, 'invalid_or_failed_module_rollback')
