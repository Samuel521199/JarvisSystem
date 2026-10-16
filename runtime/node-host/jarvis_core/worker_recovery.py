"""Recover only registered metadata-worker stages after their owner lock is gone.

This is same-user crash recovery, not protection against hostile same-user edits.
Unknown old stages are reported and never deleted. No process is killed by PID.
"""
from contextlib import contextmanager
import ctypes
from ctypes import wintypes
import json
import os
from pathlib import Path
import re
import uuid

from .policy import CoreError, safe_path, canonical_json


@contextmanager
def locked(path):
    import msvcrt
    path = safe_path(path, must_exist=False)
    with path.open('a+b') as handle:
        if handle.tell() == 0:
            handle.write(b'0'); handle.flush()
        handle.seek(0)
        try:
            msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
        except OSError as exc:
            raise CoreError('recovery_busy', 'A live owner holds this recovery lock') from exc
        try:
            yield
        finally:
            handle.seek(0)
            msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)


def identity(path):
    info = safe_path(path, directory=True).stat()
    return [info.st_dev, info.st_ino]


def process_active(pid):
    if not pid: return False
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel.OpenProcess.restype = wintypes.HANDLE
    kernel.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    handle = kernel.OpenProcess(0x100000, False, pid)
    if not handle:
        if ctypes.get_last_error() == 87: return False
        raise CoreError('recovery_unconfirmed', 'Cannot confirm worker termination')
    try:
        result = kernel.WaitForSingleObject(handle, 0)
        if result not in (0, 258): raise CoreError('recovery_unconfirmed', 'Cannot inspect worker state')
        return result == 258
    finally:
        kernel.CloseHandle(handle)


class StageLease:
    def __init__(self, parent, binding):
        self.parent = safe_path(parent, directory=True)
        self.token = uuid.uuid4().hex
        self.stage = self.parent / ('job-' + self.token)
        self.profile = 'Jarvis.Worker.' + self.token
        with locked(self.parent / '.recovery.lock'):
            self.stage.mkdir()
            self.record = {'version':1, 'token':self.token, 'stage_identity':identity(self.stage),
                           'profile':self.profile, 'pid':None, 'binding':binding}
            self._lease = locked(self.stage / '.lease.lock')
            self._lease.__enter__()
            self._save()

    def _save(self):
        path = self.stage / '.lease.json'
        temporary = safe_path(self.stage / '.lease.next', must_exist=False)
        with temporary.open('xb') as handle:
            handle.write(canonical_json(self.record).encode())
            handle.flush(); os.fsync(handle.fileno())
        os.replace(temporary, path)

    def started(self, pid):
        self.record['pid'] = pid
        self._save()

    def close(self):
        # A competing sweeper still sees the owner lock until launch has ended.
        self._lease.__exit__(None,None,None)
        result = recover(self.parent, only=self.stage.name)
        if result['retained'] or result['active']:
            raise CoreError('worker_cleanup_failed', 'Owned stage retained for explicit recovery: '+str(result['retained']))


def recover(parent, *, only=None):
    from jarvis_worker.windows import Windows, require_acl_volume
    parent = safe_path(parent, directory=True)
    require_acl_volume(parent)
    result = {'removed':[], 'active':[], 'retained':[]}
    with locked(parent / '.recovery.lock'):
        stages = [parent / only] if only is not None else sorted(parent.iterdir())
        for stage in stages:
            if not stage.name.startswith('job-'): continue
            if not stage.exists(): continue
            try:
                if not re.fullmatch(r'job-[a-f0-9]{32}', stage.name):
                    raise CoreError('unregistered_stage', 'Legacy or unregistered stage')
                if safe_path(stage, directory=True).parent != parent:
                    raise CoreError('path_denied', 'Unexpected stage path')
                meta = safe_path(stage / '.lease.json', directory=False)
                if meta.stat().st_size > 16384: raise ValueError('Oversize registration')
                record = json.loads(meta.read_text(encoding='utf-8'))
                token = stage.name[4:]
                if record.get('version') != 1 or record.get('token') != token or record.get('stage_identity') != identity(stage) or record.get('profile') != 'Jarvis.Worker.'+token:
                    raise ValueError('Registration does not match stage identity')
                if record.get('pid') is not None and (type(record['pid']) is not int or record['pid'] <= 0):
                    raise ValueError('Invalid PID')
                lease_path = safe_path(stage / '.lease.lock', directory=False)
                with locked(lease_path):
                    if process_active(record['pid']):
                        result['active'].append(stage.name); continue
                    # Validate the complete delete set first; never recurse into
                    # unknown content, links, directories or user-selected paths.
                    allowed = {'input.json','worker.py','.lease.json','.lease.lock','.lease.next'}
                    files = list(stage.iterdir())
                    for path in files:
                        if path.name not in allowed: raise ValueError('Unexpected stage content')
                        safe_path(path, directory=False)
                    hr = Windows().delete_profile(record['profile'])
                    if hr not in (0, -2147024894, -2147024893):
                        raise CoreError('recovery_unconfirmed', 'Profile deletion failed: '+str(hr))
                    for path in files:
                        if path != lease_path: path.unlink()
                # Global recovery lock serializes this last release/delete gap.
                lease_path.unlink()
                stage.rmdir()
                result['removed'].append(stage.name)
            except CoreError as exc:
                if exc.code == 'recovery_busy': result['active'].append(stage.name)
                else: result['retained'].append({'stage':stage.name,'reason':exc.code})
            except (OSError, ValueError, KeyError, TypeError):
                result['retained'].append({'stage':stage.name,'reason':'registration_or_files_changed'})
    return result
