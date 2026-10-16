"""Owned browser scratch directories, with crash recovery and no task replay.

Only registered directories under the fixed scratch root are eligible. Live
leases, uncertain process exits, reparse points and foreign contents survive.
No user profile, browser history or process selected by PID is modified.
"""
import ctypes as C
from ctypes import wintypes as W
import json
import os
from pathlib import Path
import re
import uuid

from .policy import CoreError, safe_path, canonical_json
from .worker_recovery import identity, locked, process_active


def scratch_root():
    from .worker import workspace
    parent = safe_path(workspace() / 'browser-staging', must_exist=False, directory=True)
    parent.mkdir(parents=True, exist_ok=True)
    return parent


def job_exists(name):
    kernel = C.WinDLL('kernel32', use_last_error=True)
    kernel.OpenJobObjectW.argtypes = [W.DWORD, W.BOOL, W.LPCWSTR]
    kernel.OpenJobObjectW.restype = W.HANDLE
    kernel.CloseHandle.argtypes = [W.HANDLE]
    handle = kernel.OpenJobObjectW(4, False, name)
    if handle:
        kernel.CloseHandle(handle)
        return True
    if C.get_last_error() == 2:
        return False
    raise CoreError('browser_exit_unconfirmed', 'Cannot inspect the registered browser job')


class BrowserLease:
    def __init__(self, parent=None):
        self.parent = safe_path(parent or scratch_root(), directory=True)
        self.token = uuid.uuid4().hex
        self.stage = self.parent / ('browser-' + self.token)
        self.job_name = 'Local\\Jarvis.Browser.' + self.token
        self.released = False
        with locked(self.parent / '.recovery.lock'):
            self.stage.mkdir()
            self.record = {'version': 1, 'token': self.token, 'stage_identity': identity(self.stage),
                           'job_name': self.job_name, 'pid': None, 'phase': 'created'}
            self._lease = locked(self.stage / '.lease.lock')
            self._lease.__enter__()
            self._save()
            self.profile = self.stage / 'profile'
            self.downloads = self.stage / 'downloads'
            self.profile.mkdir()
            self.downloads.mkdir()

    def _save(self):
        path = safe_path(self.stage / '.lease.next', must_exist=False)
        with path.open('xb') as handle:
            handle.write(canonical_json(self.record).encode())
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(path, self.stage / '.lease.json')

    def launching(self):
        self.record['phase'] = 'starting'
        self._save()

    def started(self, pid):
        self.record.update(pid=pid, phase='running')
        self._save()

    def close(self):
        if not self.released:
            # Called only after Playwright and the owned Job have been closed.
            self.record['phase'] = 'closed'
            try:
                self._save()
            finally:
                self._lease.__exit__(None, None, None)
                self.released = True
        return recover(self.parent, only=self.stage.name)


def _delete_tree(stage, lease_path):
    """Validate the complete absolute delete set before removing any file."""
    allowed = {'.lease.json', '.lease.next', '.lease.lock', 'profile', 'downloads'}
    if any(p.name not in allowed for p in stage.iterdir()):
        raise ValueError('Unexpected top-level content')
    files, directories = [], []
    pending = [stage]
    while pending:
        directory = pending.pop()
        for item in directory.iterdir():
            path = safe_path(item)
            if not path.is_relative_to(stage) or path == stage:
                raise ValueError('Scratch path escaped its registered root')
            if path.is_dir():
                if directory == stage and path.name not in {'profile', 'downloads'}:
                    raise ValueError('Unexpected directory')
                directories.append(path)
                pending.append(path)
            elif path.is_file():
                files.append(path)
            else:
                raise ValueError('Unsupported scratch entry')
            if len(files) + len(directories) > 20000:
                raise ValueError('Scratch cleanup limit exceeded')
    # Keep registration until all browser content is gone, so failed cleanup
    # remains recoverable on the next explicit/startup check.
    for path in files:
        if path.parent == stage and path.name.startswith('.lease.'):
            continue
        safe_path(path, directory=False).unlink()
    for path in sorted(directories, key=lambda p: len(p.parts), reverse=True):
        safe_path(path, directory=True).rmdir()
    for name in ('.lease.next', '.lease.json'):
        path = stage / name
        if path.exists():
            safe_path(path, directory=False).unlink()


def recover(parent=None, *, only=None):
    parent = safe_path(parent or scratch_root(), directory=True)
    if only is not None and not re.fullmatch(r'browser-[a-f0-9]{32}', only):
        raise CoreError('path_denied', 'Invalid registered browser directory')
    result = {'removed': [], 'active': [], 'retained': []}
    with locked(parent / '.recovery.lock'):
        stages = [parent / only] if only else sorted(parent.iterdir())
        for stage in stages:
            if not stage.name.startswith('browser-') or not stage.exists():
                continue
            try:
                if not re.fullmatch(r'browser-[a-f0-9]{32}', stage.name):
                    raise ValueError('Unregistered legacy directory')
                stage = safe_path(stage, directory=True)
                if stage.parent != parent:
                    raise ValueError('Unexpected scratch parent')
                meta = safe_path(stage / '.lease.json', directory=False)
                if meta.stat().st_size > 16384:
                    raise ValueError('Oversize registration')
                record = json.loads(meta.read_text(encoding='utf-8'))
                token = stage.name[8:]
                if (set(record) != {'version', 'token', 'stage_identity', 'job_name', 'pid', 'phase'}
                        or record['version'] != 1 or record['token'] != token
                        or record['stage_identity'] != identity(stage)
                        or record['job_name'] != 'Local\\Jarvis.Browser.' + token
                        or record['phase'] not in {'created', 'starting', 'running', 'closed'}
                        or (record['pid'] is not None and (type(record['pid']) is not int or record['pid'] <= 0))):
                    raise ValueError('Registration mismatch')
                lease_path = safe_path(stage / '.lease.lock', directory=False)
                with locked(lease_path):
                    if record['phase'] == 'starting' and record['pid'] is None:
                        raise CoreError('browser_exit_unconfirmed', 'Launch interrupted before PID registration')
                    if process_active(record['pid']) or job_exists(record['job_name']):
                        result['active'].append(stage.name)
                        continue
                    _delete_tree(stage, lease_path)
                lease_path.unlink()
                stage.rmdir()
                result['removed'].append(stage.name)
            except CoreError as exc:
                if exc.code == 'recovery_busy':
                    result['active'].append(stage.name)
                else:
                    result['retained'].append({'stage': stage.name, 'reason': exc.code})
            except (OSError, ValueError, KeyError, TypeError):
                result['retained'].append({'stage': stage.name, 'reason': 'registration_or_files_changed'})
    return result
