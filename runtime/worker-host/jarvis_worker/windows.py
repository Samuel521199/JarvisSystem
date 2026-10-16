"""Windows LPAC launcher with bounded anonymous pipes and a kill-on-close job.

The host remains trusted. This is not a sandbox for the host or an OS security
proof. Only staged, non-secret runtime/input files are granted to the worker.
"""
from __future__ import annotations

import ctypes as C
from ctypes import wintypes as W
import os
from pathlib import Path
import subprocess
import time
import uuid

P = C.c_void_p
SIZE = C.c_size_t


class WorkerError(RuntimeError):
    def __init__(self, code, message):
        super().__init__(message)
        self.code = code


class SecurityAttributes(C.Structure):
    _fields_ = [('length', W.DWORD), ('descriptor', P), ('inherit', W.BOOL)]


class StartupInfo(C.Structure):
    _fields_ = [('cb', W.DWORD), ('reserved', W.LPWSTR), ('desktop', W.LPWSTR), ('title', W.LPWSTR),
                ('x', W.DWORD), ('y', W.DWORD), ('cx', W.DWORD), ('cy', W.DWORD),
                ('chars_x', W.DWORD), ('chars_y', W.DWORD), ('fill', W.DWORD), ('flags', W.DWORD),
                ('show', W.WORD), ('reserved_size', W.WORD), ('reserved_ptr', P),
                ('stdin', W.HANDLE), ('stdout', W.HANDLE), ('stderr', W.HANDLE)]


class StartupInfoEx(C.Structure):
    _fields_ = [('startup', StartupInfo), ('attributes', P)]


class ProcessInformation(C.Structure):
    _fields_ = [('process', W.HANDLE), ('thread', W.HANDLE), ('pid', W.DWORD), ('tid', W.DWORD)]


class SecurityCapabilities(C.Structure):
    _fields_ = [('sid', P), ('capabilities', P), ('count', W.DWORD), ('reserved', W.DWORD)]


class GenericMapping(C.Structure):
    _fields_ = [('read',W.DWORD),('write',W.DWORD),('execute',W.DWORD),('all',W.DWORD)]


class SidAttributes(C.Structure):
    _fields_ = [('sid',P),('attributes',W.DWORD)]


class TokenGroups(C.Structure):
    _fields_ = [('count',W.DWORD),('groups',SidAttributes*1)]


class JobBasicLimits(C.Structure):
    _fields_ = [('process_time', C.c_longlong), ('job_time', C.c_longlong), ('flags', W.DWORD),
                ('minimum_ws', SIZE), ('maximum_ws', SIZE), ('active', W.DWORD),
                ('affinity', SIZE), ('priority', W.DWORD), ('scheduling', W.DWORD)]


class IoCounters(C.Structure):
    _fields_ = [(name, C.c_ulonglong) for name in ('read_ops','write_ops','other_ops','read_bytes','write_bytes','other_bytes')]


class JobLimits(C.Structure):
    _fields_ = [('basic', JobBasicLimits), ('io', IoCounters), ('process_memory', SIZE),
                ('job_memory', SIZE), ('peak_process', SIZE), ('peak_job', SIZE)]


def _api(dll, name, result, *args):
    function = getattr(dll, name)
    function.restype, function.argtypes = result, list(args)
    return function


class Windows:
    def __init__(self):
        if os.name != 'nt':
            raise WorkerError('worker_unavailable', 'Windows LPAC is required; no unrestricted fallback')
        k = C.WinDLL('kernel32', use_last_error=True)
        a = C.WinDLL('advapi32', use_last_error=True)
        u = C.WinDLL('userenv', use_last_error=True)
        self.close = _api(k,'CloseHandle',W.BOOL,W.HANDLE)
        self.free_sid = _api(a,'FreeSid',P,P)
        self.local_free = _api(k,'LocalFree',P,P)
        self.create_profile = _api(u,'CreateAppContainerProfile',C.c_long,W.LPCWSTR,W.LPCWSTR,W.LPCWSTR,P,W.DWORD,C.POINTER(P))
        self.delete_profile = _api(u,'DeleteAppContainerProfile',C.c_long,W.LPCWSTR)
        self.derive_capability = _api(C.WinDLL('kernelbase'),'DeriveCapabilitySidsFromName',W.BOOL,W.LPCWSTR,C.POINTER(P),C.POINTER(W.DWORD),C.POINTER(P),C.POINTER(W.DWORD))
        self.sid_string = _api(a,'ConvertSidToStringSidW',W.BOOL,P,C.POINTER(P))
        self.init_attrs = _api(k,'InitializeProcThreadAttributeList',W.BOOL,P,W.DWORD,W.DWORD,C.POINTER(SIZE))
        self.update_attr = _api(k,'UpdateProcThreadAttribute',W.BOOL,P,W.DWORD,SIZE,P,SIZE,P,P)
        self.delete_attrs = _api(k,'DeleteProcThreadAttributeList',None,P)
        self.create = _api(k,'CreateProcessW',W.BOOL,W.LPCWSTR,W.LPWSTR,P,P,W.BOOL,W.DWORD,P,W.LPCWSTR,P,P)
        self.pipe = _api(k,'CreatePipe',W.BOOL,C.POINTER(W.HANDLE),C.POINTER(W.HANDLE),P,W.DWORD)
        self.handle_flags = _api(k,'SetHandleInformation',W.BOOL,W.HANDLE,W.DWORD,W.DWORD)
        self.peek = _api(k,'PeekNamedPipe',W.BOOL,W.HANDLE,P,W.DWORD,P,C.POINTER(W.DWORD),P)
        self.read = _api(k,'ReadFile',W.BOOL,W.HANDLE,P,W.DWORD,C.POINTER(W.DWORD),P)
        self.wait = _api(k,'WaitForSingleObject',W.DWORD,W.HANDLE,W.DWORD)
        self.resume = _api(k,'ResumeThread',W.DWORD,W.HANDLE)
        self.exit_code = _api(k,'GetExitCodeProcess',W.BOOL,W.HANDLE,C.POINTER(W.DWORD))
        self.process_times = _api(k,'GetProcessTimes',W.BOOL,W.HANDLE,P,P,P,P)
        self.create_job = _api(k,'CreateJobObjectW',W.HANDLE,P,W.LPCWSTR)
        self.set_job = _api(k,'SetInformationJobObject',W.BOOL,W.HANDLE,C.c_int,P,W.DWORD)
        self.query_job = _api(k,'QueryInformationJobObject',W.BOOL,W.HANDLE,C.c_int,P,W.DWORD,P)
        self.kill_job = _api(k,'TerminateJobObject',W.BOOL,W.HANDLE,W.UINT)
        self.open_token = _api(a,'OpenProcessToken',W.BOOL,W.HANDLE,W.DWORD,C.POINTER(W.HANDLE))
        self.token_info = _api(a,'GetTokenInformation',W.BOOL,W.HANDLE,C.c_int,P,W.DWORD,C.POINTER(W.DWORD))
        self.duplicate_token = _api(a,'DuplicateToken',W.BOOL,W.HANDLE,C.c_int,C.POINTER(W.HANDLE))
        self.sddl = _api(a,'ConvertStringSecurityDescriptorToSecurityDescriptorW',W.BOOL,W.LPCWSTR,W.DWORD,C.POINTER(P),P)
        self.access_check = _api(a,'AccessCheck',W.BOOL,P,W.HANDLE,W.DWORD,P,P,C.POINTER(W.DWORD),C.POINTER(W.DWORD),C.POINTER(W.BOOL))
        self.equal_sid = _api(a,'EqualSid',W.BOOL,P,P)

    @staticmethod
    def check(value, stage):
        if not value:
            raise WorkerError('worker_isolation_failed', f'{stage} failed (Windows error {C.get_last_error()})')
        return value

    def verify_token(self, process, sid, capability_sid):
        token, size = W.HANDLE(), W.DWORD()
        self.check(self.open_token(process, 8|2, C.byref(token)), 'OpenProcessToken')
        try:
            for kind, label in ((29,'AppContainer'),):
                value = W.DWORD()
                self.check(self.token_info(token,kind,C.byref(value),C.sizeof(value),C.byref(size)),label)
                if value.value != 1:
                    raise WorkerError('worker_isolation_failed', f'{label} token not enforced')
            package = P()
            self.token_info(token,31,None,0,C.byref(size))
            buffer = C.create_string_buffer(size.value)
            self.check(self.token_info(token,31,buffer,size.value,C.byref(size)), 'Package SID')
            package = C.cast(buffer,C.POINTER(P))[0]
            self.check(self.equal_sid(package,sid), 'Package SID binding')
            self.token_info(token,30,None,0,C.byref(size))
            buffer = C.create_string_buffer(size.value)
            self.check(self.token_info(token,30,buffer,size.value,C.byref(size)), 'Capabilities')
            groups=C.cast(buffer,C.POINTER(TokenGroups)).contents
            if groups.count != 1 or not self.equal_sid(groups.groups[0].sid,capability_sid):
                raise WorkerError('worker_isolation_failed','Unexpected token capabilities')
            # Class 46 is not a portable GetTokenInformation query. Verify the
            # effective opt-out with the OS access checker before resuming:
            # own package grant must work; All Application Packages must not.
            text=P(); impersonation=W.HANDLE()
            self.check(self.sid_string(sid,C.byref(text)),'Package identity')
            try:
                self.check(self.duplicate_token(token,2,C.byref(impersonation)),'Duplicate token for access check')
                for principal,expected in ((C.wstring_at(text),True),('S-1-15-2-1',False)):
                    descriptor=P()
                    self.check(self.sddl(f'O:SYG:SYD:(A;;0x1;;;WD)(A;;0x1;;;{principal})',1,C.byref(descriptor),None),'Build check descriptor')
                    try:
                        mapping=GenericMapping(1,2,4,7); privileges=C.create_string_buffer(1024)
                        length=W.DWORD(len(privileges)); granted=W.DWORD(); allowed=W.BOOL()
                        self.check(self.access_check(descriptor,impersonation,1,C.byref(mapping),privileges,
                                                     C.byref(length),C.byref(granted),C.byref(allowed)),'Check LPAC access')
                        if bool(allowed.value)!=expected:
                            raise WorkerError('worker_isolation_failed','LPAC effective access did not match policy')
                    finally:
                        self.local_free(descriptor)
            finally:
                if impersonation:self.close(impersonation)
                self.local_free(text)
            return {'appcontainer':True,'lpac':True,'capabilities':['registryRead'],
                    'lpac_verification':'OS AccessCheck: own package allowed, ALL APPLICATION PACKAGES denied'}
        finally:
            self.close(token)


def require_acl_volume(path):
    if os.name!='nt':
        raise WorkerError('worker_unavailable','Native worker requires Windows')
    k=C.WinDLL('kernel32',use_last_error=True)
    volume_name=_api(k,'GetVolumePathNameW',W.BOOL,W.LPCWSTR,W.LPWSTR,W.DWORD)
    volume_info=_api(k,'GetVolumeInformationW',W.BOOL,W.LPCWSTR,W.LPWSTR,W.DWORD,P,P,C.POINTER(W.DWORD),W.LPWSTR,W.DWORD)
    volume=C.create_unicode_buffer(1024); filesystem=C.create_unicode_buffer(32); flags=W.DWORD()
    Windows.check(volume_name(str(path),volume,len(volume)),'Locate staging volume')
    Windows.check(volume_info(volume,None,0,None,None,C.byref(flags),filesystem,len(filesystem)),'Inspect staging filesystem')
    if not flags.value&8:
        raise WorkerError('worker_storage_unsupported','Worker staging/runtime requires persistent ACLs; '+filesystem.value+' is unsupported')
    return filesystem.value


def grant_read(path, sid):
    """Only call for newly owned staging/runtime directories, never user inputs."""
    require_acl_volume(path)
    command = [str(Path(os.environ['SystemRoot'])/'System32/icacls.exe'), str(path),
               '/grant', f'*{sid}:(OI)(CI)(RX)', '/T', '/Q']
    try:
        result = subprocess.run(command,capture_output=True,timeout=5,creationflags=subprocess.CREATE_NO_WINDOW)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise WorkerError('worker_isolation_failed','Could not complete staging ACL setup') from exc
    if result.returncode:
        raise WorkerError('worker_isolation_failed','Could not grant read-only staging access')


def run(runtime, stage, *, entry='worker.py', arguments=(), checkpoint=lambda: None,
        seconds=10.0, output_limit=2*1024*1024, memory_limit=256*1024*1024,
        profile_name=None, on_started=lambda pid: None):
    """Trusted launcher API; public task dispatch never accepts entry/argv overrides."""
    api = Windows()
    sid, sid_text = P(), P()
    handles, attributes, initialized, process = [], None, False, ProcessInformation()
    job, started = None, time.monotonic()
    capability_groups, capability_sids=P(),P()
    group_count,capability_count=W.DWORD(),W.DWORD()
    profile = profile_name or 'Jarvis.Worker.'+uuid.uuid4().hex
    if not isinstance(profile,str) or len(profile)!=46 or not profile.startswith('Jarvis.Worker.') or any(c not in '0123456789abcdef' for c in profile[14:]):
        raise WorkerError('worker_isolation_failed','Invalid owned profile name')
    profile_created = False
    try:
        hr = api.create_profile(profile,profile,'Temporary isolated Jarvis worker',None,0,C.byref(sid))
        if hr < 0:
            raise WorkerError('worker_isolation_failed',f'Package SID creation failed ({hr})')
        profile_created = True
        api.check(api.sid_string(sid,C.byref(sid_text)), 'Convert SID')
        identity = C.wstring_at(sid_text)
        grant_read(stage,identity)
        require_acl_volume(runtime)
        api.check(api.derive_capability('registryRead',C.byref(capability_groups),C.byref(group_count),
                                      C.byref(capability_sids),C.byref(capability_count)),'Derive fixed runtime capability')
        if capability_count.value!=1:
            raise WorkerError('worker_isolation_failed','Unexpected registryRead capability definition')
        capability_sid=C.cast(capability_sids,C.POINTER(P))[0]
        capability_array=(SidAttributes*1)(SidAttributes(capability_sid,4))
        checkpoint()
        job = api.check(api.create_job(None,None),'CreateJobObject')
        handles.append(job)
        limits = JobLimits()
        limits.basic.flags = 0x2000 | 0x8 | 0x100 | 0x2  # kill-on-close, process count, memory, CPU time
        limits.basic.active = 1
        limits.basic.process_time = 3 * 10_000_000
        limits.process_memory = memory_limit
        api.check(api.set_job(job,9,C.byref(limits),C.sizeof(limits)),'Set job limits')
        security = SecurityAttributes(C.sizeof(SecurityAttributes),None,True)
        pipes = []
        for _ in range(3):
            read,write = W.HANDLE(),W.HANDLE()
            api.check(api.pipe(C.byref(read),C.byref(write),C.byref(security),0),'CreatePipe')
            handles.extend([read.value,write.value]); pipes.append((read.value,write.value))
        stdin,stdout,stderr = pipes[0][0],pipes[1][1],pipes[2][1]
        # EOF stdin; no ambient handles or environment secrets are inherited.
        api.close(pipes[0][1]); handles.remove(pipes[0][1])
        for read in (pipes[1][0],pipes[2][0]):
            api.check(api.handle_flags(read,1,0),'Protect read handle')
        size = SIZE()
        api.init_attrs(None,6,0,C.byref(size))
        attributes = C.create_string_buffer(size.value)
        api.check(api.init_attrs(attributes,6,0,C.byref(size)),'Initialize attributes'); initialized=True
        capabilities = SecurityCapabilities(sid,C.cast(capability_array,P),1,0)
        lpac,children = W.DWORD(1),W.DWORD(1)
        desktop_policy=W.DWORD(1)  # Do not inherit a packaged caller's desktop app identity.
        inherited = (W.HANDLE*3)(stdin,stdout,stderr)
        jobs = (W.HANDLE*1)(job)
        for key,value in ((0x20009,capabilities),(0x2000F,lpac),(0x2000E,children),
                          (0x20002,inherited),(0x2000D,jobs),(0x20012,desktop_policy)):
            api.check(api.update_attr(attributes,0,key,C.byref(value),C.sizeof(value),None,None),f'Set process attribute {key:#x}')
        startup = StartupInfoEx()
        startup.startup.cb=C.sizeof(startup); startup.attributes=C.cast(attributes,P)
        startup.startup.flags=0x100; startup.startup.stdin=stdin
        startup.startup.stdout=stdout; startup.startup.stderr=stderr
        executable = str(Path(runtime)/'python.exe')
        command = C.create_unicode_buffer(subprocess.list2cmdline([executable,'-I','-B',str(Path(stage)/entry),*map(str,arguments)]))
        environment = {'SystemRoot':os.environ['SystemRoot'],'WINDIR':os.environ['SystemRoot'],
                       'LOCALAPPDATA':os.environ['LOCALAPPDATA'],'USERPROFILE':os.environ['USERPROFILE'],
                       'TEMP':str(stage),'TMP':str(stage),'PATH':str(runtime)}
        env = C.create_unicode_buffer('\0'.join(f'{k}={v}' for k,v in sorted(environment.items()))+'\0\0')
        checkpoint()
        api.check(api.create(executable,command,None,None,True,0x80000|0x400|0x8000000|0x4,
                             env,str(stage),C.byref(startup),C.byref(process)),'Create isolated process')
        handles.extend([process.process,process.thread])
        on_started(process.pid)
        token = api.verify_token(process.process,sid,capability_sid)
        checkpoint()
        if api.resume(process.thread) == 0xFFFFFFFF:
            api.check(False,'Resume worker')
        for handle in (stdin,stdout,stderr):
            api.close(handle); handles.remove(handle)
        buffers = [bytearray(),bytearray()]
        limits_bytes = [output_limit,16384]
        finished_seen = False
        while True:
            checkpoint()
            created, exited, kernel_time, user_time = (C.c_ulonglong() for _ in range(4))
            api.check(api.process_times(process.process,C.byref(created),C.byref(exited),
                                       C.byref(kernel_time),C.byref(user_time)), 'Read process CPU accounting')
            cpu_seconds = (kernel_time.value + user_time.value) / 10_000_000
            if cpu_seconds > 3:
                raise WorkerError('worker_cpu_limit', 'Worker CPU-time budget exceeded')
            if time.monotonic()-started > seconds:
                raise WorkerError('worker_timeout','Worker wall-time budget exceeded')
            for index,handle in enumerate((pipes[1][0],pipes[2][0])):
                while True:
                    available=W.DWORD()
                    if not api.peek(handle,None,0,None,C.byref(available),None):
                        if C.get_last_error()==109: break
                        api.check(False,'Read worker pipe')
                    if not available.value: break
                    if len(buffers[index])+available.value>limits_bytes[index]:
                        raise WorkerError('worker_output_limit','Worker output quota exceeded')
                    block=C.create_string_buffer(min(available.value,65536)); count=W.DWORD()
                    api.check(api.read(handle,block,len(block),C.byref(count),None),'Read worker output')
                    buffers[index].extend(block.raw[:count.value])
            if api.wait(process.process,0)==0:
                # The process has no children; repeat once to drain bytes written
                # between the last peek and exit before returning.
                if finished_seen: break
                finished_seen=True
            else:
                finished_seen=False
                time.sleep(.015)
        code=W.DWORD(); api.check(api.exit_code(process.process,C.byref(code)),'Get exit code')
        measured=JobLimits()
        api.check(api.query_job(job,9,C.byref(measured),C.sizeof(measured),None),'Measure worker job')
        return {'stdout':bytes(buffers[0]),'stderr':bytes(buffers[1]),'exit_code':code.value,
                'evidence':{**token,'pid':process.pid,'package_sid':identity,'active_process_limit':1,
                            'cpu_time_limit_seconds':3,'wall_time_limit_seconds':seconds,
                            'cpu_seconds':cpu_seconds,'cpu_enforcement':'Host polls OS process accounting and terminates Job',
                            'memory_limit_bytes':memory_limit,'peak_process_memory_bytes':measured.peak_process,
                            'elapsed_seconds':round(time.monotonic()-started,4)}}
    finally:
        if job:
            api.kill_job(job,1)
            if process.process: api.wait(process.process,5000)
        for handle in reversed(handles): api.close(handle)
        if initialized: api.delete_attrs(attributes)
        if sid_text: api.local_free(sid_text)
        if sid: api.free_sid(sid)
        for pointer,count in ((capability_groups,group_count.value),(capability_sids,capability_count.value)):
            if pointer:
                for i in range(count):api.local_free(C.cast(pointer,C.POINTER(P))[i])
                api.local_free(pointer)
        if profile_created:
            hr = api.delete_profile(profile)
            if hr < 0:
                raise WorkerError('worker_cleanup_failed', f'Temporary AppContainer profile cleanup failed ({hr})')
