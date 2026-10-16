"""Local runtime slots: verify, test, select and roll back without copying data.

Selections affect the next explicit launch. A running managed process holds the
slot lock; no live process is killed or hot-replaced. No credentials required.
"""
from contextlib import contextmanager
from datetime import datetime, timezone
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import sqlite3
import subprocess
import sys
import tempfile
import uuid

from . import policy
from .worker_recovery import locked

SPEC = importlib.util.spec_from_file_location('jarvis_release_bundle', policy.REPOSITORY_ROOT/'tools/release_bundle.py')
bundle = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(bundle)
START_DATA_VERSIONS = frozenset({'0.1.13','0.1.14','0.1.15','0.1.16','0.1.17','0.1.18','0.1.19','0.1.20'})

HEALTH_SCRIPT = r'''
import sys,json
from pathlib import Path
def offline(event,args):
    if event in {'socket.connect','socket.connect_ex','socket.getaddrinfo'}:
        raise RuntimeError('Runtime health check does not use the network')
sys.addaudithook(offline)
root=Path(sys.argv[1]);sys.path.insert(0,str(root/'runtime/node-host'))
from jarvis_core.service import CoreService
from jarvis_core import __version__
if tuple(map(int,__version__.split('.'))) >= (0,1,15):
    from jarvis_core.releases import RuntimeSlots
if tuple(map(int,__version__.split('.'))) >= (0,1,16):
    from jarvis_core.resources import load_profile,memory_snapshot
    load_profile();assert memory_snapshot()['total_bytes'] > 0
import httpx,jsonschema,google.auth,requests
core=CoreService(Path(sys.argv[2]))
core.initialize(root/'tests/fixtures/workspace')
record=core.inventory(request_id='runtime-slot-health')
assert record['action']['status']=='CONFIRMED',record
core._verify_artifact(record['artifact'])
print(json.dumps({'version':__version__,'status':'passed','artifact_digest':record['artifact']['digest'],
                 'task_id':record['task']['task_id'],'network':'Python audit hook denies connect/DNS'}))
'''


def timestamp():
    return datetime.now(timezone.utc).isoformat()


def manifest_digest(value):
    return hashlib.sha256(policy.canonical_json(value).encode()).hexdigest()


def verify_slot(slot, expected_digest):
    slot = policy.safe_path(slot, directory=True)
    meta = policy.safe_path(slot/'release.json', directory=False)
    if meta.stat().st_size > 4*1024*1024:
        raise ValueError('Oversize installed manifest')
    value = json.loads(meta.read_text(encoding='utf-8'))
    if manifest_digest(value) != expected_digest:
        raise ValueError('Installed release manifest changed')
    expected = set(value['files']) | {'release.json'}
    actual = set()
    for path in slot.rglob('*'):
        path = policy.safe_path(path)
        if path.is_file():
            actual.add(path.relative_to(slot).as_posix())
    if actual != expected:
        raise ValueError('Installed release membership changed')
    for name, item in value['files'].items():
        relative = bundle.archive_path(name)
        path = policy.safe_path(slot.joinpath(*relative.parts), directory=False)
        if path.stat().st_size != item['size'] or bundle.sha(path.read_bytes()) != item['sha256']:
            raise ValueError('Installed release content changed: '+name)
    return value


class RuntimeSlots:
    def __init__(self, root):
        self.root = policy.safe_path(root, must_exist=False, directory=True)
        self.root.mkdir(parents=True, exist_ok=True)
        self.slots = policy.safe_path(self.root/'slots', must_exist=False, directory=True)
        self.slots.mkdir(exist_ok=True)
        self.database = policy.safe_path(self.root/'releases.db', must_exist=False)
        with self.connection() as db:
            db.execute('CREATE TABLE IF NOT EXISTS releases(id TEXT PRIMARY KEY,version TEXT NOT NULL,archive_digest TEXT NOT NULL,manifest_digest TEXT NOT NULL,state TEXT NOT NULL,health TEXT,created_at TEXT NOT NULL)')
            db.execute('CREATE TABLE IF NOT EXISTS selection(singleton INTEGER PRIMARY KEY CHECK(singleton=1),active TEXT,previous TEXT,generation INTEGER NOT NULL)')
            db.execute('INSERT OR IGNORE INTO selection VALUES(1,NULL,NULL,0)')
            db.execute('CREATE TABLE IF NOT EXISTS history(sequence INTEGER PRIMARY KEY,operation TEXT NOT NULL,release_id TEXT,created_at TEXT NOT NULL)')
            db.execute('CREATE TABLE IF NOT EXISTS starts(id TEXT PRIMARY KEY,document TEXT NOT NULL)')

    @contextmanager
    def connection(self):
        policy.safe_path(self.database, must_exist=False)
        db = sqlite3.connect(self.database, timeout=5)
        db.row_factory = sqlite3.Row
        try:
            with db:
                yield db
        finally:
            db.close()

    def _lock(self):
        return locked(self.root/'.runtime.lock')

    def _row(self, db, ident):
        if not isinstance(ident,str) or not re.fullmatch(r'release-[0-9a-f]{24}',ident):
            raise ValueError('Invalid release ID')
        row = db.execute('SELECT * FROM releases WHERE id=?',(ident,)).fetchone()
        if row is None:
            raise ValueError('Unknown release')
        return dict(row)

    def _slot(self, ident):
        path = policy.safe_path(self.slots/ident, directory=True)
        if path.parent != self.slots:
            raise ValueError('Release path escaped slot root')
        return path

    def status(self):
        with self.connection() as db:
            selected = dict(db.execute('SELECT active,previous,generation FROM selection').fetchone())
            selected['releases'] = [dict(r) for r in db.execute('SELECT * FROM releases ORDER BY created_at,id')]
            selected['history'] = [dict(r) for r in db.execute('SELECT * FROM history ORDER BY sequence DESC LIMIT 30')]
            selected['starts'] = [json.loads(r['document']) for r in db.execute('SELECT document FROM starts ORDER BY rowid DESC LIMIT 10')]
        for row in selected['releases']:
            row['health'] = json.loads(row['health']) if row['health'] else None
        return selected

    def install(self, archive):
        archive = policy.safe_path(archive, directory=False)
        manifest = bundle.verify(archive)
        archive_digest = bundle.sha(archive.read_bytes())
        ident = 'release-'+archive_digest[:24]
        with self._lock():
            with self.connection() as db:
                existing = db.execute('SELECT * FROM releases WHERE id=?',(ident,)).fetchone()
                if existing:
                    if existing['archive_digest'] != archive_digest:
                        raise ValueError('Release identity collision')
                    verify_slot(self._slot(ident),existing['manifest_digest'])
                    return {'id':ident,'version':existing['version'],'state':existing['state'],'existing':True}
            destination = self.slots/ident
            bundle.extract(archive,destination)
            expected = manifest_digest(manifest)
            verify_slot(destination,expected)
            with self.connection() as db:
                db.execute('INSERT INTO releases VALUES(?,?,?,?,?,?,?)',
                           (ident,manifest['version'],archive_digest,expected,'installed',None,timestamp()))
                db.execute('INSERT INTO history(operation,release_id,created_at) VALUES(?,?,?)',('install',ident,timestamp()))
            return {'id':ident,'version':manifest['version'],'state':'installed','existing':False}

    def health(self, ident):
        with self._lock():
            return self._health_locked(ident)

    def _health_locked(self, ident):
        with self.connection() as db:
            row = self._row(db,ident)
        try:
            slot = self._slot(ident)
            verify_slot(slot,row['manifest_digest'])
            with tempfile.TemporaryDirectory(prefix='jarvis-slot-health-') as temporary:
                result = subprocess.run([str(slot/'python/python.exe'),'-I','-B','-c',HEALTH_SCRIPT,
                                         str(slot/'source'),temporary],cwd=slot,env=self._environment(),
                                        capture_output=True,text=True,encoding='utf-8',timeout=60,
                                        creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
            if result.returncode:
                raise ValueError('Runtime check failed: '+result.stderr[-2000:])
            evidence = json.loads(result.stdout)
            if evidence.get('status') != 'passed' or evidence.get('version') != row['version']:
                raise ValueError('Runtime health/version mismatch')
            verify_slot(slot,row['manifest_digest'])
            state = 'verified'
        except Exception as exc:
            state = 'failed'
            evidence = {'status':'failed','error':type(exc).__name__,'message':str(exc)[:2500]}
        evidence['captured_at'] = timestamp()
        with self.connection() as db:
            db.execute('UPDATE releases SET state=?,health=? WHERE id=?',
                       (state,json.dumps(evidence,ensure_ascii=False),ident))
        return {'id':ident,'state':state,'health':evidence}

    def select(self, ident=None, *, rollback=False):
        with self._lock(), self.connection() as db:
            db.execute('BEGIN IMMEDIATE')
            selected = db.execute('SELECT * FROM selection').fetchone()
            ident = selected['previous'] if rollback else ident
            row = self._row(db,ident)
            if row['state'] != 'verified':
                raise ValueError('Run the isolated health check before selecting this release')
            verify_slot(self._slot(ident),row['manifest_digest'])
            if ident != selected['active']:
                db.execute('UPDATE selection SET active=?,previous=?,generation=generation+1',
                           (ident,selected['active']))
                db.execute('INSERT INTO history(operation,release_id,created_at) VALUES(?,?,?)',
                           ('rollback' if rollback else 'select',ident,timestamp()))
        return self.status()

    @staticmethod
    def _environment():
        return {**{k:os.environ[k] for k in ('SystemRoot','WINDIR','USERPROFILE','LOCALAPPDATA','TEMP','TMP') if k in os.environ},
                'PYTHONDONTWRITEBYTECODE':'1','PYTHONUTF8':'1'}

    @staticmethod
    def _launch_input(data_dir, mode, port):
        if mode not in {'status','inventory','web'}:
            raise ValueError('Unsupported runtime entry')
        if type(port) is not int or not 1024 <= port <= 65535:
            raise ValueError('Invalid loopback port')
        return policy.safe_path(data_dir,directory=True)

    def _run_locked(self, row, data, mode, port):
        slot = self._slot(row['id'])
        verify_slot(slot,row['manifest_digest'])
        if mode == 'web':
            arguments = [str(slot/'source/apps/web/server.py'),'--port',str(port)]
        else:
            arguments = [str(slot/'source/apps/cli/main.py'),mode]
        command = [str(slot/'python/python.exe'),'-I','-B',*arguments,'--data-dir',str(data)]
        return subprocess.run(command,cwd=slot,env=self._environment(),check=False).returncode

    def run(self, *, data_dir, mode='status', port=18181):
        data = self._launch_input(data_dir, mode, port)
        # This lifetime lock makes selection an explicit maintenance operation.
        # It does not stop the currently running unmanaged development server.
        with self._lock(), self.connection() as db:
            active = db.execute('SELECT active FROM selection').fetchone()['active']
            row = self._row(db,active)
            if row['state'] != 'verified':
                raise ValueError('Selected release is not verified')
            return self._run_locked(row,data,mode,port)

    @staticmethod
    def _data_format(data):
        # Read only. Do not use CoreService.status(), which reconciles tasks.
        result = {}
        for name, relative, expected in (('control','control.db',2), ('safety','safety/control.db',1)):
            path = policy.safe_path(data/relative,directory=False)
            for suffix in ('-wal','-shm','-journal'):
                policy.safe_path(str(path)+suffix,must_exist=False)
            db = sqlite3.connect(path.as_uri()+'?mode=ro',uri=True,timeout=2)
            try:
                version = db.execute('PRAGMA user_version').fetchone()[0]
                if version != expected:
                    raise ValueError('Unsupported data format; startup does not migrate databases')
                result[name+'_version'] = version
                if name == 'control':
                    row = db.execute('SELECT config,config_digest FROM control WHERE singleton=1').fetchone()
                    if row is None or policy.digest(row[0].encode('utf-8')) != row[1]:
                        raise ValueError('Business configuration is missing or corrupt')
                    config = json.loads(row[0]);policy.validate_config(config,data)
                    result['node_id'] = config['node_id']
                else:
                    row = db.execute('SELECT node_id,epoch,stopped FROM state WHERE id=1').fetchone()
                    if row is None or row[0] != result['node_id'] or row[1] < 1 or row[2] not in (0,1):
                        raise ValueError('Business and control data do not agree')
            finally:
                db.close()
        return result

    def _save_start(self, document, db=None):
        if db is None:
            with self.connection() as connection:
                self._save_start(document,connection)
            return
        db.execute('INSERT INTO starts VALUES(?,?) ON CONFLICT(id) DO UPDATE SET document=excluded.document',
                   (document['id'],json.dumps(document,ensure_ascii=False)))

    def start(self, *, data_dir, mode='web', port=18181, notify=None):
        """Check before an explicit launch; at most one known previous fallback.

        Never rerun after the business process has started: it may have effects.
        The lifetime lock belongs to this launcher; this is not a crash watchdog.
        """
        data = self._launch_input(data_dir,mode,port)
        if data == self.root or data.is_relative_to(self.root) or self.root.is_relative_to(data):
            raise ValueError('Runtime slots and business data must use separate directories')
        with self._lock():
            document = {'id':'start-'+uuid.uuid4().hex,'created_at':timestamp(),'mode':mode,
                        'status':'checking','attempts':[],'selected':None,'fallback':False,
                        'selection_committed':False}
            committed = False
            self._save_start(document)
            try:
                document['data_format'] = self._data_format(data)
                with self.connection() as db:
                    selected = dict(db.execute('SELECT * FROM selection').fetchone())
                    active = self._row(db,selected['active'])
                document['requested'] = active['id']
                if active['version'] not in START_DATA_VERSIONS:
                    raise ValueError('Selected release has no measured startup data compatibility')
                candidates = [active['id']]
                if selected['previous'] and selected['previous'] != active['id']:
                    candidates.append(selected['previous'])
                chosen = None
                for ident in candidates:
                    with self.connection() as db:
                        row = self._row(db,ident)
                    # Only the measured v2-data release family can participate.
                    # Future data formats require an explicit compatibility change.
                    if row['version'] not in START_DATA_VERSIONS:
                        result = {'id':ident,'state':'failed','health':{'error':'unsupported_data_compatibility'}}
                    elif row['state'] != 'verified':
                        result = {'id':ident,'state':'failed','health':{'error':'release_not_verified'}}
                    else:
                        result = self._health_locked(ident)
                    document['attempts'].append(result)
                    self._save_start(document)
                    if result['state'] == 'verified':
                        chosen = row
                        break
                if chosen is None:
                    raise ValueError('Neither the selected release nor its verified fallback is usable; inspect runtime status')
                # Data and package are rechecked before the only business launch.
                if self._data_format(data) != document['data_format']:
                    raise ValueError('Data identity changed during startup checks')
                verify_slot(self._slot(chosen['id']),chosen['manifest_digest'])
                document.update(selected=chosen['id'],version=chosen['version'],
                                fallback=chosen['id'] != active['id'],status='launching',selection_committed=True)
                with self.connection() as db:
                    db.execute('BEGIN IMMEDIATE')
                    if document['fallback']:
                        db.execute('UPDATE selection SET active=?,previous=?,generation=generation+1',
                                   (chosen['id'],active['id']))
                        db.execute('INSERT INTO history(operation,release_id,created_at) VALUES(?,?,?)',
                                   ('startup_fallback',chosen['id'],timestamp()))
                    self._save_start(document,db)
                committed = True
                if notify:
                    notify({'event':'runtime_launching',**document})
                code = self._run_locked(chosen,data,mode,port)
                document.update(status='exited',exit_code=code,finished_at=timestamp())
                self._save_start(document)
                return document
            except BaseException as exc:
                document.update(status='interrupted' if isinstance(exc,KeyboardInterrupt) else 'failed',
                                error=type(exc).__name__,message=str(exc)[:2500],finished_at=timestamp(),
                                selection_committed=committed)
                self._save_start(document)
                raise
