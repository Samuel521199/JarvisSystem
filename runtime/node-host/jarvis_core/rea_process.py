"""Fixed parser process lifetime and resource bounds; not an OS security sandbox.

No shell, arbitrary command API, target execution or ambient credentials. The
Windows job contains REA's parser children and is terminated on every exit path.
"""
import ctypes as C
from ctypes import wintypes as W
import os
from pathlib import Path
import subprocess
import time

from . import policy


def run(argv, stage, checkpoint, *, seconds=60, output_limit=1200 * 1024, output_path=None, on_started=lambda pid: None,
        stdin_file=None, environment_extra=None):
    from . import worker  # Register the shared Win32 structures.
    from jarvis_worker.windows import Windows, JobLimits, SecurityAttributes, StartupInfoEx, ProcessInformation, SIZE, P
    api = Windows()
    handles, job, attributes, initialized = [], None, None, False
    sink = None
    input_stream = None
    process = ProcessInformation()
    started = time.monotonic()
    try:
        checkpoint()
        if output_path is not None:
            output_path = policy.safe_path(Path(output_path), must_exist=False)
            if output_path.parent != policy.safe_path(Path(stage), directory=True):
                raise policy.CoreError('rea_output_path', '解析暂存证据必须位于本次工作目录。')
            sink = output_path.open('xb')
        job = api.check(api.create_job(None, None), 'Create REA Job'); handles.append(job)
        limits = JobLimits()
        limits.basic.flags = 0x2000 | 0x8 | 0x200 | 0x4
        limits.basic.active = 4
        limits.basic.job_time = 45 * 10_000_000
        limits.job_memory = 1024 * 1024 * 1024
        api.check(api.set_job(job, 9, C.byref(limits), C.sizeof(limits)), 'Set REA Job limits')
        security = SecurityAttributes(C.sizeof(SecurityAttributes), None, True)
        pipes = []
        for _ in range(3):
            read, write = W.HANDLE(), W.HANDLE()
            api.check(api.pipe(C.byref(read), C.byref(write), C.byref(security), 0), 'Create REA pipe')
            handles.extend([read.value, write.value]); pipes.append((read.value, write.value))
        stdin, stdout, stderr = pipes[0][0], pipes[1][1], pipes[2][1]
        api.close(pipes[0][1]); handles.remove(pipes[0][1])
        if stdin_file is not None:
            import msvcrt
            source = policy.safe_path(Path(stdin_file))
            if source.parent != policy.safe_path(Path(stage), directory=True) or source.stat().st_size > 131072:
                raise policy.CoreError('process_input_invalid', '受控进程输入必须在本次目录且不超过 128 KiB。')
            api.close(stdin); handles.remove(stdin)
            input_stream = source.open('rb')
            stdin = msvcrt.get_osfhandle(input_stream.fileno())
            os.set_handle_inheritable(stdin, True)
        for read in (pipes[1][0], pipes[2][0]):
            api.check(api.handle_flags(read, 1, 0), 'Protect REA read handle')
        size = SIZE(); api.init_attrs(None, 2, 0, C.byref(size))
        attributes = C.create_string_buffer(size.value)
        api.check(api.init_attrs(attributes, 2, 0, C.byref(size)), 'Initialize REA attributes'); initialized = True
        inherited, jobs = (W.HANDLE * 3)(stdin, stdout, stderr), (W.HANDLE * 1)(job)
        for key, value in ((0x20002, inherited), (0x2000D, jobs)):
            api.check(api.update_attr(attributes, 0, key, C.byref(value), C.sizeof(value), None, None), 'Attach REA Job and handles')
        startup = StartupInfoEx(); startup.startup.cb = C.sizeof(startup); startup.attributes = C.cast(attributes, P)
        startup.startup.flags = 0x100; startup.startup.stdin = stdin; startup.startup.stdout = stdout; startup.startup.stderr = stderr
        environment = {'SystemRoot': os.environ['SystemRoot'], 'WINDIR': os.environ['SystemRoot'],
                       'TEMP': str(stage), 'TMP': str(stage), 'USERPROFILE': str(stage),
                       'LOCALAPPDATA': str(stage), 'APPDATA': str(stage), 'PATH': str(Path(argv[0]).parent)}
        extra = environment_extra or {}
        if set(extra) - {'CODEX_HOME','HTTP_PROXY','HTTPS_PROXY','NO_PROXY'} or any(not isinstance(v,str) or '\0' in v for v in extra.values()):
            raise policy.CoreError('process_environment_invalid','受控进程环境项不在允许清单中。')
        environment.update(extra)
        env = C.create_unicode_buffer('\0'.join(k + '=' + v for k, v in sorted(environment.items())) + '\0\0')
        api.check(api.create(argv[0], C.create_unicode_buffer(subprocess.list2cmdline(argv)), None, None, True,
                             0x80000 | 0x400 | 0x8000000 | 0x4, env, str(stage), C.byref(startup), C.byref(process)), 'Start REA parser')
        handles.extend([process.process, process.thread]); on_started(process.pid); checkpoint()
        if api.resume(process.thread) == 0xFFFFFFFF: api.check(False, 'Resume REA parser')
        for handle in (stdout, stderr): api.close(handle); handles.remove(handle)
        if input_stream is None: api.close(stdin); handles.remove(stdin)
        else: input_stream.close(); input_stream = None
        buffers, sizes, finished = [bytearray(), bytearray()], [0, 0], False
        while True:
            checkpoint()
            if time.monotonic() - started > seconds:
                raise policy.CoreError('rea_timeout', '软件解析达到 60 秒预算；本次解析进程及子进程已回收。')
            for index, handle in enumerate((pipes[1][0], pipes[2][0])):
                while True:
                    checkpoint()
                    available = W.DWORD()
                    if not api.peek(handle, None, 0, None, C.byref(available), None):
                        if C.get_last_error() == 109: break
                        api.check(False, 'Read REA pipe')
                    if not available.value: break
                    if sizes[index] + available.value > (output_limit if index == 0 else 65536):
                        raise policy.CoreError('rea_output_limit', '解析证据超过本次预算，请选择更小的应用目录。未截断交付。')
                    block = C.create_string_buffer(min(available.value, 65536)); count = W.DWORD()
                    api.check(api.read(handle, block, len(block), C.byref(count), None), 'Read REA output')
                    data = block.raw[:count.value]; sizes[index] += count.value
                    if index == 0 and sink is not None: sink.write(data)
                    else: buffers[index].extend(data)
            if api.wait(process.process, 0) == 0:
                if finished: break
                finished = True
            else:
                finished = False; time.sleep(.02)
        code = W.DWORD(); api.check(api.exit_code(process.process, C.byref(code)), 'Read REA exit code')
        measured = JobLimits(); api.check(api.query_job(job, 9, C.byref(measured), C.sizeof(measured), None), 'Measure REA Job')
        if sink is not None:
            sink.flush(); os.fsync(sink.fileno())
        return {'stdout': bytes(buffers[0]), 'stdout_bytes': sizes[0], 'stderr': bytes(buffers[1]), 'exit_code': code.value,
                'process': {'pid': process.pid, 'elapsed_seconds': round(time.monotonic() - started, 3),
                            'peak_job_memory_bytes': measured.peak_job, 'job_memory_limit_bytes': limits.job_memory,
                            'active_process_limit': 4, 'job_cpu_limit_seconds': 45, 'wall_limit_seconds': seconds,
                            'kill_on_close': True, 'os_sandbox': False}}
    finally:
        if job:
            api.kill_job(job, 1)
            if process.process: api.wait(process.process, 5000)
        for handle in reversed(handles): api.close(handle)
        if initialized: api.delete_attrs(attributes)
        if sink is not None: sink.close()
        if input_stream is not None: input_stream.close()
