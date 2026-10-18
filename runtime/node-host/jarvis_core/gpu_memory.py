"""Optional Windows resources: per-process WDDM allocation gauges, missing is unknown."""
import ctypes as C
from ctypes import wintypes as W
import os
import threading


class GpuMemory:
    def __init__(self,pid):
        self.lock=threading.RLock()
        self.pid=pid;self.query=None;self.counters={};self.error=None
        if os.name!='nt':self.error='not_windows';return
        self.api=C.WinDLL('pdh')
        self.api.PdhOpenQueryW.argtypes=[W.LPCWSTR,C.c_size_t,C.POINTER(W.HANDLE)]
        self.api.PdhAddEnglishCounterW.argtypes=[W.HANDLE,W.LPCWSTR,C.c_size_t,C.POINTER(W.HANDLE)]
        self.api.PdhCollectQueryData.argtypes=[W.HANDLE]
        self.api.PdhGetFormattedCounterArrayW.argtypes=[W.HANDLE,W.DWORD,C.POINTER(W.DWORD),C.POINTER(W.DWORD),C.c_void_p]
        self.api.PdhCloseQuery.argtypes=[W.HANDLE]
        for name in ('PdhOpenQueryW','PdhAddEnglishCounterW','PdhCollectQueryData','PdhGetFormattedCounterArrayW','PdhCloseQuery'):
            getattr(self.api,name).restype=W.DWORD
        handle=W.HANDLE()
        if self.api.PdhOpenQueryW(None,0,C.byref(handle)):self.error='query_unavailable';return
        self.query=handle
        for key,counter in [('dedicated_bytes','Dedicated Usage'),('shared_bytes','Shared Usage')]:
            value=W.HANDLE()
            status=self.api.PdhAddEnglishCounterW(handle,'\\GPU Process Memory(*)\\'+counter,0,C.byref(value))
            if status:self.error='counter_unavailable';self.close();return
            self.counters[key]=value
        self.api.PdhCollectQueryData(self.query)

    def sample(self):
        with self.lock:return self._sample()

    def _sample(self):
        if not self.query:return {'status':self.error or 'closed','dedicated_bytes':None,'shared_bytes':None}
        if self.api.PdhCollectQueryData(self.query):return {'status':'collect_failed','dedicated_bytes':None,'shared_bytes':None}
        class ValueUnion(C.Union):_fields_=[('large',C.c_longlong),('double',C.c_double),('long',W.LONG)]
        class Value(C.Structure):_fields_=[('status',W.DWORD),('value',ValueUnion)]
        class Item(C.Structure):_fields_=[('name',W.LPWSTR),('formatted',Value)]
        result={'status':'measured'}
        for key,counter in self.counters.items():
            size=W.DWORD();count=W.DWORD()
            status=self.api.PdhGetFormattedCounterArrayW(counter,0x400,C.byref(size),C.byref(count),None)
            if status not in (0,0x800007D2) or not size.value:
                result[key]=None;result['status']='no_counter_data';continue
            data=C.create_string_buffer(size.value)
            if self.api.PdhGetFormattedCounterArrayW(counter,0x400,C.byref(size),C.byref(count),data):
                result[key]=None;result['status']='read_failed';continue
            items=C.cast(data,C.POINTER(Item))
            values=[items[i].formatted.value.large for i in range(count.value)
                    if items[i].name.startswith('pid_'+str(self.pid)+'_') and items[i].formatted.status in (0,1)]
            result[key]=sum(values) if values else None
            if not values:result['status']='no_matching_instance'
        return result

    def close(self):
        with self.lock:
            if self.query:self.api.PdhCloseQuery(self.query);self.query=None
