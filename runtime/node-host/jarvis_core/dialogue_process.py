"""Bounded, disposable model transport processes; not a security sandbox.

The Host owns separate instances for dialogue and selected background analyses.
Reply context preparation can run in the child; personal commits stay in Host.
No prompts, keys or results are written to intermediate files or argv.
"""
from contextvars import ContextVar
import ctypes as C
import json
import os
from pathlib import Path
import subprocess
import sys
import threading
import time
import uuid

in_dialogue = ContextVar('jarvis_dialogue_transport', default=False)
MAX_INPUT = 24 * 1024 * 1024
MAX_OUTPUT = 2 * 1024 * 1024
MEMORY_LIMIT = 384 * 1024 * 1024


class ProcessJob:
    """Attach before sending any input. Closing the job kills its owned child."""
    def __init__(self):
        if os.name != 'nt':
            raise OSError('No verified dialogue process backend on this platform')
        from . import worker
        from jarvis_worker.windows import Windows, JobLimits
        self.api = Windows()
        self.handle = self.api.check(self.api.create_job(None, None), 'Create dialogue Job')
        try:
            limits = JobLimits()
            limits.basic.flags = 0x2000 | 0x8 | 0x200
            limits.basic.active = 1
            limits.job_memory = MEMORY_LIMIT
            self.api.check(self.api.set_job(self.handle, 9, C.byref(limits), C.sizeof(limits)), 'Bound dialogue Job')
        except BaseException:
            self.api.close(self.handle)
            raise

    def attach(self, process):
        assign = C.WinDLL('kernel32', use_last_error=True).AssignProcessToJobObject
        assign.argtypes = [C.c_void_p, C.c_void_p]; assign.restype = C.c_int
        self.api.check(assign(self.handle, int(process._handle)), 'Attach dialogue process')

    def kill(self):
        self.api.kill_job(self.handle, 1)

    def close(self):
        self.api.close(self.handle)


class DialogueProcesses:
    def __init__(self, core, *, capacity=2, context_seconds=12):
        self.core = core
        self.capacity, self.context_seconds = capacity, context_seconds
        self.lock = threading.RLock()
        self.slots = threading.BoundedSemaphore(capacity)
        self.active = {}
        self.closed = False
        self.completed = 0
        self.last = None
        # Fixed repository entry point; never configurable through HTTP/models.
        # Windows venv python.exe is a launcher that creates another process.
        # Use the actual interpreter with this runtime's dependency paths so
        # the single-process Job limit and PID memory samples are accurate.
        self._command = [getattr(sys, '_base_executable', sys.executable), '-u',
                         str(Path(__file__).with_name('dialogue_worker.py'))]

    @staticmethod
    def failure(code, *, uncertain=False, cancelled=False):
        return {'status': 'UNKNOWN' if uncertain else 'CANCELLED' if cancelled else 'FAILED',
                'error': code, 'error_category': 'chat_cancelled' if cancelled else 'dialogue_process',
                'cancel_requested': cancelled, 'outcome_uncertain': uncertain, 'automatic_retry': False,
                'user_message': '本次模型进程已结束，未采用后续输出；远端请求可能已计费，未自动重发。' if uncertain else
                                '对话模型进程未启动或已停止，本次未请求模型。'}

    def probe(self, config, provider, prompt, data_dir, guard, *, admission_context=None,
              cancel_event=None, deadline_seconds=60, task_id=None, **options):
        packet = {'action': 'probe', 'config': config, 'provider': provider, 'prompt': prompt,
                  'data_dir': str(data_dir), 'deadline_seconds': deadline_seconds, 'options': options,
                  **({'task_id':task_id} if task_id else {})}
        return self._run(packet, guard, cancel_event, min(85., max(1., float(deadline_seconds)+20.)))

    def reply(self, chat, message, *, cancel_event=None, **options):
        packet = {'action': 'reply', 'config_path': str(chat.config_path), 'data_dir': str(chat.core.data_dir),
                  'message': message, 'options': options, 'task_id': getattr(chat.core, 'task_id', None)}
        return self._run(packet, chat.core.assert_running, cancel_event, 110.)

    def _run(self, packet, guard, cancel_event, limit):
        if cancel_event is not None and cancel_event.is_set():
            return self.failure('dialogue_cancelled_before_start', cancelled=True)
        if not self.slots.acquire(blocking=False):
            return self.failure('dialogue_process_busy')
        ident = uuid.uuid4().hex
        process = job = None
        threads = []
        started = time.monotonic()
        sent = False
        reason = 'start_failed'
        try:
            control = guard()
            packet = {**packet, 'id': ident, 'epoch': control['security_epoch']}
            raw = json.dumps(packet, ensure_ascii=False, allow_nan=False).encode('utf-8')
            if len(raw) > MAX_INPUT:
                return self.failure('dialogue_process_input_limit')
            with self.lock:
                if self.closed:
                    return self.failure('dialogue_process_closed')
                job = ProcessJob()
                environment = {**os.environ, 'PYTHONPATH': os.pathsep.join(
                    str(Path(p).absolute()) for p in sys.path if p), 'PYTHONIOENCODING': 'utf-8'}
                process = subprocess.Popen(self._command, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                    stderr=subprocess.DEVNULL, creationflags=subprocess.CREATE_NO_WINDOW, close_fds=True,
                    cwd=Path(__file__).resolve().parents[3], env=environment)
                job.attach(process)
                self.active[ident] = {'process': process, 'job': job, 'started': started, 'phase': 'starting', 'phase_at': started}
            output = []
            io_failed = threading.Event()
            overflow = threading.Event()
            def write():
                try:
                    process.stdin.write(raw); process.stdin.close()
                except (OSError, ValueError):
                    io_failed.set()
            def read():
                try:
                    total, frames = 0, 0
                    while True:
                        block = process.stdout.readline(MAX_OUTPUT + 1)
                        if not block: break
                        total += len(block); frames += 1
                        if total > MAX_OUTPUT or frames > 16:
                            overflow.set(); break
                        frame = json.loads(block)
                        if frame.get('id') != ident: raise ValueError('Mismatched frame')
                        if set(frame) == {'id', 'phase'} and frame['phase'] in {'context','model'}:
                            if output: raise ValueError('Phase after result')
                            with self.lock:
                                self.active[ident].update(phase=frame['phase'], phase_at=time.monotonic())
                        elif set(frame) == {'id', 'result'} and not output:
                            output.append(frame)
                        else: raise ValueError('Invalid frame')
                except (OSError, ValueError, TypeError, AttributeError):
                    io_failed.set()
            threads = [threading.Thread(target=read, daemon=True, name='dialogue-output'),
                       threading.Thread(target=write, daemon=True, name='dialogue-input')]
            guard()
            if cancel_event is not None and cancel_event.is_set():
                reason = 'cancelled_before_input'
                return self.failure('dialogue_cancelled_before_start', cancelled=True)
            sent = True  # From this point a remote dispatch is possible; fail closed to UNKNOWN.
            for thread in threads: thread.start()
            with self.lock:
                # Do not overwrite an early phase frame from the child.
                if self.active[ident]['phase']=='starting':
                    self.active[ident].update(phase='context' if packet['action']=='reply' else 'waiting')
            next_guard = 0.
            while True:
                if cancel_event is not None and cancel_event.is_set():
                    reason = 'cancelled'
                    return self.failure('dialogue_process_cancelled', uncertain=True, cancelled=True)
                with self.lock: closed = self.closed
                if closed:
                    reason = 'host_closed'
                    return self.failure('dialogue_process_closed', uncertain=True)
                now = time.monotonic()
                with self.lock:
                    phase = self.active[ident]['phase']; phase_at = self.active[ident]['phase_at']
                if packet['action']=='reply' and phase=='context' and now-phase_at > self.context_seconds:
                    reason = 'context_timeout'
                    return self.failure('dialogue_context_timeout', uncertain=True)
                if now >= next_guard:
                    guard(); next_guard = now + .5
                if now - started > limit:
                    reason = 'timeout'
                    return self.failure('dialogue_process_timeout', uncertain=True)
                if overflow.is_set() or io_failed.is_set():
                    reason = 'invalid_output'
                    return self.failure('dialogue_process_protocol', uncertain=True)
                if process.poll() is not None and not threads[0].is_alive(): break
                time.sleep(.02)
            if process.returncode != 0:
                reason = 'crashed'
                return self.failure('dialogue_process_exit', uncertain=True)
            response = output[0]
            if response.get('id') != ident or not isinstance(response.get('result'), dict):
                raise ValueError('Mismatched response')
            result = response['result']
            if result.get('status') not in {'SUCCEEDED', 'FAILED', 'UNKNOWN', 'CANCELLED'}:
                raise ValueError('Invalid result')
            guard()
            if cancel_event is not None and cancel_event.is_set():
                reason = 'cancelled'
                return self.failure('dialogue_process_cancelled', uncertain=True, cancelled=True)
            reason = result['status'].lower()
            return result
        except Exception:
            reason = 'unavailable' if not sent else 'invalid_or_stopped'
            return self.failure('dialogue_process_unavailable', uncertain=sent)
        finally:
            # Release capacity only after the process has actually exited.
            if job: job.kill()
            if process:
                if process.poll() is None: process.kill()
                process.wait()
                for thread in threads:
                    if thread.ident is not None: thread.join(2)
                process.stdin.close(); process.stdout.close()
            with self.lock:
                self.active.pop(ident, None)
                if job: job.close()
                self.completed += 1
                self.last = {'reason': reason, 'seconds': round(time.monotonic()-started, 3)}
            self.slots.release()

    def snapshot(self):
        with self.lock:
            entries = [(r['process'].pid, r['started'], r['phase']) for r in self.active.values()]
            result = {'enabled': True, 'closed': self.closed, 'capacity': self.capacity, 'active': len(entries),
                      'memory_limit_bytes': MEMORY_LIMIT, 'completed': self.completed, 'last': self.last}
        from .process_usage import process_usage
        rows = []
        for pid, started, phase in entries:
            row = {'pid': pid, 'seconds': round(time.monotonic()-started, 2), 'phase': phase}
            try: row.update(process_usage(pid), status='available')
            except OSError: row['status'] = 'exited_or_unavailable'
            rows.append(row)
        return {**result, 'processes': rows}

    def close(self):
        with self.lock:
            self.closed = True
            for row in self.active.values(): row['job'].kill()
