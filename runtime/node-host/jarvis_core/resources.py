"""Bounded queue memory admission; estimates are not OS reservations or limits."""
import ctypes
from datetime import datetime, timezone
import json
import os
import threading
import time

from .policy import CoreError, REPOSITORY_ROOT

MIB = 1024 * 1024
CAPABILITIES = {'filesystem.read_sample.v1', 'browser.operate.v1'}


def memory_snapshot():
    if os.name != 'nt':
        raise OSError('Memory admission currently supports Windows only')

    class MemoryStatus(ctypes.Structure):
        _fields_ = [('length', ctypes.c_uint32), ('load', ctypes.c_uint32),
                    *[(name, ctypes.c_uint64) for name in (
                        'total', 'available', 'commit_limit', 'commit_available',
                        'virtual_total', 'virtual_available', 'extended')]]

    value = MemoryStatus()
    value.length = ctypes.sizeof(value)
    api = ctypes.WinDLL('kernel32', use_last_error=True).GlobalMemoryStatusEx
    api.argtypes = [ctypes.POINTER(MemoryStatus)]
    api.restype = ctypes.c_int
    if not api(ctypes.byref(value)):
        raise ctypes.WinError(ctypes.get_last_error())
    return {'total_bytes': value.total, 'available_bytes': value.available,
            # This is the calling process's commit headroom, not page-file bytes.
            'commit_available_bytes': value.commit_available}


def load_profile(path=None):
    profile = json.loads((path or REPOSITORY_ROOT / 'config/resource-profile.json').read_text(encoding='utf-8'))
    keys = {'schema_version', 'foreground_reserve_mib', 'resume_margin_mib',
            'recovery_seconds', 'retry_seconds', 'task_memory_mib'}
    if not isinstance(profile, dict) or set(profile) != keys or type(profile['schema_version']) is not int or profile['schema_version'] != 1:
        raise CoreError('invalid_resource_profile', 'Resource profile schema is invalid')
    ranges = {'foreground_reserve_mib': (256, 16384), 'resume_margin_mib': (64, 4096),
              'recovery_seconds': (1, 60), 'retry_seconds': (1, 30)}
    for key, (lower, upper) in ranges.items():
        if type(profile[key]) is not int or not lower <= profile[key] <= upper:
            raise CoreError('invalid_resource_profile', 'Invalid resource threshold: ' + key)
    budgets = profile['task_memory_mib']
    if not isinstance(budgets, dict) or set(budgets) != CAPABILITIES or any(
            type(value) is not int or not 64 <= value <= 16384 for value in budgets.values()):
        raise CoreError('invalid_resource_profile', 'Resource task estimates are invalid')
    return profile


class ResourceAdmission:
    def __init__(self, *, profile_path=None, probe=memory_snapshot, clock=time.monotonic):
        self.profile = load_profile(profile_path)
        self.probe, self.clock = probe, clock
        self.retry_seconds = self.profile['retry_seconds']
        self._lock = threading.Lock()
        self._blocked = False
        self._healthy_since = None
        self._capability = None
        self._state = {'waiting': False, 'reason': None, 'sample': None}

    def snapshot(self):
        with self._lock:
            return json.loads(json.dumps(self._state))

    def idle(self):
        with self._lock:
            self._blocked = False
            self._healthy_since = None
            self._capability = None
            self._state = {'waiting': False, 'reason': None, 'sample': None}

    def check(self, capability):
        with self._lock:
            if capability not in CAPABILITIES:
                raise CoreError('resource_profile_missing', 'No resource profile for this capability')
            if self._capability != capability:
                self._healthy_since = None
                self._capability = capability
            reserve = self.profile['foreground_reserve_mib'] * MIB
            required = reserve + self.profile['task_memory_mib'][capability] * MIB
            threshold = required + (self.profile['resume_margin_mib'] * MIB if self._blocked else 0)
            state = {'waiting': True, 'reason': None, 'sample': None, 'capability': capability,
                     'required_bytes': required, 'resume_threshold_bytes': threshold,
                     'foreground_reserve_bytes': reserve,
                     'checked_at': datetime.now(timezone.utc).isoformat()}
            try:
                sample = self.probe()
                if not isinstance(sample, dict) or any(type(sample.get(k)) is not int or sample[k] < 0
                        for k in ('total_bytes', 'available_bytes', 'commit_available_bytes')) or not sample['total_bytes'] or sample['available_bytes'] > sample['total_bytes']:
                    raise OSError('Memory sample is invalid')
                state['sample'] = sample
                enough = min(sample['available_bytes'], sample['commit_available_bytes']) >= threshold
                if not enough:
                    state['reason'] = 'memory_pressure'
                    self._blocked = True
                    self._healthy_since = None
                elif self._blocked:
                    now = self.clock()
                    if self._healthy_since is None:
                        self._healthy_since = now
                    if now - self._healthy_since < self.profile['recovery_seconds']:
                        state['reason'] = 'resource_recovering'
                    else:
                        self._blocked = False
                        self._healthy_since = None
                        state['waiting'] = False
                else:
                    state['waiting'] = False
            except (OSError, ValueError, TypeError, KeyError):
                state['reason'] = 'resource_unavailable'
                self._blocked = True
                self._healthy_since = None
            self._state = state
            return not state['waiting']
