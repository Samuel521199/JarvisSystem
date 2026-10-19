"""PID + creation-time process ownership for Windows acceptance probes only.

Process parent IDs can refer to a newer, unrelated process after PID reuse.
Read creation metadata without opening unrelated processes, then read counters
only for proven descendants. Unsupported layouts fail instead of falling back.

API: https://learn.microsoft.com/en-us/windows/win32/api/winternl/nf-winternl-ntquerysysteminformation
Creation field: https://github.com/winsiderss/phnt/blob/master/ntexapi.h
"""
import ctypes as C
import os

from probe_idle_resources import WindowsProcesses


class UnicodeString(C.Structure):
    _fields_=[('length',C.c_uint16),('maximum',C.c_uint16),('buffer',C.c_void_p)]


class ProcessPrefix(C.Structure):
    _fields_=[('next',C.c_uint32),('threads',C.c_uint32),('private_working',C.c_uint64),
              ('faults',C.c_uint32),('peak_threads',C.c_uint32),('cycles',C.c_uint64),
              ('created',C.c_uint64),('user',C.c_uint64),('kernel',C.c_uint64),
              ('image',UnicodeString),('priority',C.c_int32),('pid',C.c_void_p),('parent',C.c_void_p)]


def processes():
    if os.name!='nt' or C.sizeof(C.c_void_p)!=8 or ProcessPrefix.created.offset!=32 or ProcessPrefix.pid.offset!=80:
        raise RuntimeError('Unverified Windows process-information layout')
    query=C.WinDLL('ntdll').NtQuerySystemInformation
    query.argtypes=[C.c_uint32,C.c_void_p,C.c_uint32,C.POINTER(C.c_uint32)];query.restype=C.c_int32
    size=65536
    while size<=16*1024*1024:
        buffer=C.create_string_buffer(size);required=C.c_uint32()
        status=query(5,buffer,size,C.byref(required)) & 0xffffffff
        if status==0:break
        if status!=0xc0000004:raise OSError('Process snapshot status '+hex(status))
        size=max(size*2,required.value+65536)
    else:raise RuntimeError('Process snapshot exceeds bound')
    used=required.value or size;base=C.addressof(buffer);offset=0;rows={}
    while True:
        if offset+C.sizeof(ProcessPrefix)>used:raise RuntimeError('Truncated process snapshot')
        row=ProcessPrefix.from_buffer(buffer,offset)
        name=''
        if row.image.length:
            address=row.image.buffer or 0
            if row.image.length%2 or row.image.length>row.image.maximum or address<base or address+row.image.length>base+used:
                raise RuntimeError('Invalid process-name boundary')
            name=C.string_at(address,row.image.length).decode('utf-16-le')
        pid=int(row.pid or 0)
        if pid in rows:raise RuntimeError('Duplicate process identity')
        rows[pid]={'pid':pid,'parent_pid':int(row.parent or 0),'name':name,'created_ticks':row.created}
        if not row.next:break
        if row.next<C.sizeof(ProcessPrefix) or offset+row.next>=used:raise RuntimeError('Invalid process-entry boundary')
        offset+=row.next
    return rows


class OwnedProcesses(WindowsProcesses):
    def __init__(self):
        super().__init__();self.roots={};self.known={}

    def tree(self,root_pid):
        rows=processes()
        if root_pid not in self.roots:
            if root_pid not in rows:return []
            self.roots[root_pid]=rows[root_pid]['created_ticks'];self.known[root_pid]=set()
        known=self.known[root_pid]
        selected={pid for pid,created in known if pid in rows and rows[pid]['created_ticks']==created}
        if root_pid in rows and rows[root_pid]['created_ticks']==self.roots[root_pid]:selected.add(root_pid)
        while True:
            added={pid for pid,row in rows.items() if pid not in selected and row['parent_pid'] in selected
                   and row['created_ticks']>=rows[row['parent_pid']]['created_ticks']}
            if not added:break
            selected.update(added)
        # Keep observed children across parent exit, but never a reused PID.
        self.known[root_pid]={(pid,rows[pid]['created_ticks']) for pid in selected}
        return [rows[pid] for pid in sorted(selected)]
