"""Read process memory without importing a model runtime; missing is not zero."""
import ctypes as C
import os


def process_memory(pid=None):
    if os.name != 'nt': return None
    from ctypes import wintypes as W
    class Counters(C.Structure):
        _fields_ = [('cb', W.DWORD), ('faults', W.DWORD)] + [(name, C.c_size_t) for name in (
            'peak_ws', 'ws', 'peak_paged', 'paged', 'peak_nonpaged', 'nonpaged', 'pagefile', 'peak_pagefile', 'private')]
    k = C.WinDLL('kernel32', use_last_error=True)
    k.OpenProcess.argtypes = [W.DWORD, W.BOOL, W.DWORD]; k.OpenProcess.restype = W.HANDLE
    k.CloseHandle.argtypes = [W.HANDLE]
    handle = k.OpenProcess(0x0410, False, pid or os.getpid())
    if not handle: return None
    try:
        value = Counters(); value.cb = C.sizeof(value)
        api = C.WinDLL('psapi').GetProcessMemoryInfo
        api.argtypes = [W.HANDLE, C.POINTER(Counters), W.DWORD]; api.restype = W.BOOL
        if not api(handle, C.byref(value), value.cb): return None
        return {'working_set_bytes': value.ws, 'peak_working_set_bytes': value.peak_ws,
                'private_commit_bytes': value.private, 'peak_private_commit_bytes': value.peak_pagefile}
    finally: k.CloseHandle(handle)
