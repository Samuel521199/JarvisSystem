"""On-demand, read-only machine usage. No model calls or persistent sampler."""
from __future__ import annotations

import ctypes as C
from datetime import datetime, timezone
import math
import os
import re
import threading
import time
import uuid

from .resources import memory_snapshot


def percent(used, total):
    if total is None or used is None or total <= 0:
        return None
    return round(max(0, min(100, used / total * 100)), 1)


def cpu_percent(before, after):
    idle = after[0] - before[0]
    total = after[1] + after[2] - before[1] - before[2]
    return percent(total - idle, total) if idle >= 0 else None


def busiest_engine(samples):
    """Sum process usage per physical engine, then take the busiest engine."""
    engines = {}
    for name, value in samples.items():
        match = re.search(r'(luid_0x[0-9a-f]+_0x[0-9a-f]+_phys_\d+_eng_\d+)', name.lower())
        if match and math.isfinite(value) and value >= 0:
            key = match.group(1)
            engines[key] = engines.get(key, 0) + value
    return round(min(100, max(engines.values())), 1) if engines else None


class _Luid(C.Structure):
    _fields_ = [('low', C.c_uint32), ('high', C.c_int32)]


class _AdapterDesc(C.Structure):
    _fields_ = [('description', C.c_wchar * 128), ('vendor', C.c_uint32),
                ('device', C.c_uint32), ('subsystem', C.c_uint32), ('revision', C.c_uint32),
                ('dedicated', C.c_size_t), ('system', C.c_size_t), ('shared', C.c_size_t),
                ('luid', _Luid), ('flags', C.c_uint32)]


def _method(obj, index, result, *args):
    table = C.cast(obj, C.POINTER(C.POINTER(C.c_void_p))).contents
    return C.WINFUNCTYPE(result, C.c_void_p, *args)(table[index])


def _adapters():
    # IDXGIFactory1::EnumAdapters1, IDXGIAdapter1::GetDesc1. Size_t avoids the
    # 32-bit Win32_VideoController.AdapterRAM truncation on large/UMA GPUs.
    library = C.WinDLL('dxgi')
    create = library.CreateDXGIFactory1
    create.argtypes = [C.c_void_p, C.POINTER(C.c_void_p)]
    create.restype = C.c_int32
    iid = C.create_string_buffer(uuid.UUID('770aae78-f26f-4dba-a829-253c83d1b387').bytes_le)
    factory = C.c_void_p()
    if create(iid, C.byref(factory)) < 0:
        raise OSError('DXGI unavailable')
    result = []
    try:
        enum = _method(factory, 12, C.c_int32, C.c_uint32, C.POINTER(C.c_void_p))
        for index in range(32):
            adapter = C.c_void_p()
            if enum(factory, index, C.byref(adapter)) < 0:
                break
            try:
                desc = _AdapterDesc()
                if _method(adapter, 10, C.c_int32, C.POINTER(_AdapterDesc))(adapter, C.byref(desc)) >= 0 and not desc.flags & 2:
                    result.append({'id': f'luid_0x{desc.luid.high & 0xffffffff:08x}_0x{desc.luid.low:08x}',
                                   'name': desc.description, 'dedicated_total_bytes': desc.dedicated,
                                   'shared_total_bytes': desc.shared})
            finally:
                _method(adapter, 2, C.c_uint32)(adapter)
    finally:
        _method(factory, 2, C.c_uint32)(factory)
    return result


class _Number(C.Union):
    _fields_ = [('double', C.c_double), ('integer', C.c_int64)]


class _Value(C.Structure):
    _fields_ = [('status', C.c_uint32), ('number', _Number)]


class _Item(C.Structure):
    _fields_ = [('name', C.c_wchar_p), ('value', _Value)]


class _Counters:
    """Each observation owns and closes its PDH handles, including on error."""
    def __init__(self):
        self.api = C.WinDLL('pdh')
        self.query = C.c_void_p()
        self.handles = {}
        signatures = {
            'PdhOpenQueryW': [C.c_wchar_p, C.c_size_t, C.POINTER(C.c_void_p)],
            'PdhAddEnglishCounterW': [C.c_void_p, C.c_wchar_p, C.c_size_t, C.POINTER(C.c_void_p)],
            'PdhCollectQueryData': [C.c_void_p], 'PdhCloseQuery': [C.c_void_p],
            'PdhGetFormattedCounterArrayW': [C.c_void_p, C.c_uint32, C.POINTER(C.c_uint32), C.POINTER(C.c_uint32), C.c_void_p],
        }
        for name, args in signatures.items():
            fn = getattr(self.api, name)
            fn.argtypes, fn.restype = args, C.c_uint32
        if self.api.PdhOpenQueryW(None, 0, C.byref(self.query)):
            raise OSError('PDH unavailable')
        try:
            for key, path in {
                'cpu': r'\Processor Information(_Total)\% Processor Time',
                'engines': r'\GPU Engine(*)\Utilization Percentage',
                'dedicated': r'\GPU Adapter Memory(*)\Dedicated Usage',
                'shared': r'\GPU Adapter Memory(*)\Shared Usage',
            }.items():
                handle = C.c_void_p()
                if not self.api.PdhAddEnglishCounterW(self.query, path, 0, C.byref(handle)):
                    self.handles[key] = handle
        except Exception:
            self.close()
            raise

    def collect(self):
        self.api.PdhCollectQueryData(self.query)

    def values(self, key):
        if key not in self.handles:
            return {}
        size, count = C.c_uint32(), C.c_uint32()
        fn = self.api.PdhGetFormattedCounterArrayW
        # PDH_FMT_DOUBLE | PDH_FMT_NOCAP100 (aggregate processes ourselves).
        flags = 0x200 | 0x8000
        status = fn(self.handles[key], flags, C.byref(size), C.byref(count), None)
        if status != 0x800007D2 or not 0 < size.value <= 8 * 1024 * 1024:
            return {}
        buffer = C.create_string_buffer(size.value)
        if fn(self.handles[key], flags, C.byref(size), C.byref(count), buffer):
            return {}
        items = C.cast(buffer, C.POINTER(_Item))
        return {items[i].name.lower(): items[i].value.number.double for i in range(count.value)
                if items[i].value.status in (0, 1) and math.isfinite(items[i].value.number.double)}

    def close(self):
        if self.query:
            self.api.PdhCloseQuery(self.query)
            self.query = C.c_void_p()


def _cpu_times():
    values = [C.c_uint64() for _ in range(3)]
    fn = C.WinDLL('kernel32', use_last_error=True).GetSystemTimes
    fn.argtypes, fn.restype = [C.POINTER(C.c_uint64)] * 3, C.c_int
    if not fn(*(C.byref(value) for value in values)):
        raise OSError('CPU counters unavailable')
    return tuple(value.value for value in values)


def collect_usage():
    result = {'cpu_percent': None, 'memory': None, 'gpu_percent': None, 'adapters': []}
    if os.name != 'nt':
        return result
    try:
        memory = memory_snapshot()
        total = memory['total_bytes']
        used = total - memory['available_bytes']
        result['memory'] = {'used_bytes': used, 'total_bytes': total, 'percent': percent(used, total)}
    except OSError:
        pass
    try:
        result['adapters'] = _adapters()
    except (OSError, AttributeError):
        pass
    counters, before = None, None
    try:
        try:
            counters = _Counters()
            counters.collect()
        except OSError:
            pass
        try:
            before = _cpu_times()
        except OSError:
            pass
        time.sleep(0.35)
        if before is not None and (os.cpu_count() or 1) <= 64:
            try:
                result['cpu_percent'] = cpu_percent(before, _cpu_times())
            except OSError:
                pass
        if counters:
            counters.collect()
            # PDH's total includes all processor groups on machines with >64 CPUs.
            cpu = counters.values('cpu').get('_total')
            if cpu is not None:
                result['cpu_percent'] = round(max(0, min(100, cpu)), 1)
            result['gpu_percent'] = busiest_engine(counters.values('engines'))
            dedicated, shared = counters.values('dedicated'), counters.values('shared')
            for adapter in result['adapters']:
                def usage(rows):
                    values = [value for name, value in rows.items() if name.startswith(adapter['id'] + '_phys_') and value >= 0]
                    return int(sum(values)) if values else None
                adapter['dedicated_used_bytes'] = usage(dedicated)
                adapter['shared_used_bytes'] = usage(shared)
    finally:
        if counters:
            counters.close()
    return result


class ResourceUsage:
    """Fast cache API: at most one finite background sample, only on demand."""
    def __init__(self, collector=collect_usage, *, ttl=3, clock=time.monotonic):
        self.collector, self.ttl, self.clock = collector, ttl, clock
        self.lock = threading.Lock()
        self.closed = False
        self.refreshing = False
        self.last = float('-inf')
        self.data = {'scope': 'machine', 'sampled_at': None, 'cpu_percent': None,
                     'memory': None, 'gpu_percent': None, 'adapters': []}

    def snapshot(self):
        with self.lock:
            age = self.clock() - self.last
            if not self.closed and not self.refreshing and age >= self.ttl:
                self.refreshing = True
                threading.Thread(target=self._refresh, name='jarvis-resource-sample', daemon=True).start()
            return {**self.data, 'refreshing': self.refreshing,
                    'stale': age >= 15, 'age_seconds': round(age, 1) if math.isfinite(age) else None}

    def _refresh(self):
        try:
            data = self.collector()
            data = {**data, 'scope': 'machine', 'sampled_at': datetime.now(timezone.utc).isoformat()}
        except Exception:
            # Never expose host details or cached values as a successful new sample.
            data = {'scope': 'machine', 'sampled_at': None, 'cpu_percent': None,
                    'memory': None, 'gpu_percent': None, 'adapters': []}
        with self.lock:
            if not self.closed:
                self.data, self.last = data, self.clock()
            self.refreshing = False

    def close(self):
        with self.lock:
            self.closed = True
