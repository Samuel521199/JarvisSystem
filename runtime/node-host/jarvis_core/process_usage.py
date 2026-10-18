"""Read selected owned process counters, without scanning process lists."""
import ctypes as C
import os


class MemoryCounters(C.Structure):
    _fields_ = [('cb',C.c_uint32),('page_faults',C.c_uint32),
                *[(key,C.c_size_t) for key in ('peak_working_set','working_set','peak_paged','paged',
                                             'peak_nonpaged','nonpaged','pagefile','peak_pagefile','private')]]


def process_usage(pid):
    if os.name != 'nt':
        raise OSError('Process counters unavailable')
    kernel = C.WinDLL('kernel32',use_last_error=True)
    kernel.OpenProcess.argtypes = [C.c_uint32,C.c_int,C.c_uint32]; kernel.OpenProcess.restype = C.c_void_p
    kernel.CloseHandle.argtypes = [C.c_void_p]
    handle = kernel.OpenProcess(0x1000,False,pid)
    if not handle:
        raise C.WinError(C.get_last_error())
    try:
        memory = MemoryCounters(); memory.cb = C.sizeof(memory)
        get = C.WinDLL('psapi',use_last_error=True).GetProcessMemoryInfo
        get.argtypes = [C.c_void_p,C.POINTER(MemoryCounters),C.c_uint32]; get.restype = C.c_int
        if not get(handle,C.byref(memory),memory.cb):
            raise C.WinError(C.get_last_error())
        times = [C.c_uint64() for _ in range(4)]
        get_times = kernel.GetProcessTimes
        get_times.argtypes = [C.c_void_p,*([C.POINTER(C.c_uint64)]*4)]; get_times.restype = C.c_int
        if not get_times(handle,*(C.byref(value) for value in times)):
            raise C.WinError(C.get_last_error())
        return {'pid':pid,'created':times[0].value,'cpu_seconds':(times[2].value+times[3].value)/10000000,
                'working_set_bytes':memory.working_set,'private_bytes':memory.private}
    finally:
        kernel.CloseHandle(handle)
