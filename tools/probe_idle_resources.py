"""Measure V-PC-02 on a fresh local web Host, with no model or browser task.

The default run records five minutes on this machine, not a low-end PC claim.
Only the synthetic Host created by this probe is closed. Existing services stay up.
"""
import argparse
import ctypes
from ctypes import wintypes
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import platform
import queue
import subprocess
import sys
import tempfile
import threading
import time
from urllib.request import urlopen

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT/'runtime/node-host'), str(ROOT/'apps/web')]
from jarvis_core import __version__
from jarvis_core.resources import memory_snapshot, MIB

THRESHOLDS = {'minimum_seconds': 300, 'private_bytes': 512*MIB,
              'cpu_percent_one_core': 1.0, 'ready_seconds': 5.0}


class WindowsProcesses:
    """Read-only process tree snapshots and counters; never open termination rights."""
    class Entry(ctypes.Structure):
        _fields_ = [('size', wintypes.DWORD), ('usage', wintypes.DWORD),
                    ('pid', wintypes.DWORD), ('heap', ctypes.c_size_t),
                    ('module', wintypes.DWORD), ('threads', wintypes.DWORD),
                    ('parent', wintypes.DWORD), ('priority', wintypes.LONG),
                    ('flags', wintypes.DWORD), ('name', wintypes.WCHAR*260)]

    class Memory(ctypes.Structure):
        _fields_ = [('size', wintypes.DWORD), ('faults', wintypes.DWORD),
                    *[(n, ctypes.c_size_t) for n in ('peak_working', 'working',
                       'peak_paged', 'paged', 'peak_nonpaged', 'nonpaged',
                       'commit', 'peak_commit', 'private')]]

    def __init__(self):
        self.api = ctypes.WinDLL('kernel32', use_last_error=True)
        signatures = {
            'CreateToolhelp32Snapshot': ([wintypes.DWORD, wintypes.DWORD], wintypes.HANDLE),
            'Process32FirstW': ([wintypes.HANDLE, ctypes.POINTER(self.Entry)], wintypes.BOOL),
            'Process32NextW': ([wintypes.HANDLE, ctypes.POINTER(self.Entry)], wintypes.BOOL),
            'CloseHandle': ([wintypes.HANDLE], wintypes.BOOL),
            'OpenProcess': ([wintypes.DWORD, wintypes.BOOL, wintypes.DWORD], wintypes.HANDLE),
            'GetProcessTimes': ([wintypes.HANDLE] + [ctypes.POINTER(wintypes.FILETIME)]*4, wintypes.BOOL),
            'K32GetProcessMemoryInfo': ([wintypes.HANDLE, ctypes.POINTER(self.Memory), wintypes.DWORD], wintypes.BOOL),
        }
        for name, (args, result) in signatures.items():
            fn = getattr(self.api, name); fn.argtypes = args; fn.restype = result

    def tree(self, root_pid):
        snapshot = self.api.CreateToolhelp32Snapshot(2, 0)
        if snapshot == ctypes.c_void_p(-1).value:
            raise ctypes.WinError(ctypes.get_last_error())
        rows = {}
        try:
            entry = self.Entry(); entry.size = ctypes.sizeof(entry)
            more = self.api.Process32FirstW(snapshot, ctypes.byref(entry))
            while more:
                rows[entry.pid] = {'pid': entry.pid, 'parent_pid': entry.parent, 'name': entry.name}
                more = self.api.Process32NextW(snapshot, ctypes.byref(entry))
        finally:
            self.api.CloseHandle(snapshot)
        selected = {root_pid}
        while True:
            expanded = selected | {pid for pid, row in rows.items() if row['parent_pid'] in selected}
            if selected == expanded: break
            selected = expanded
        return [rows[pid] for pid in sorted(selected) if pid in rows]

    def sample(self, root_pid):
        result = []
        for row in self.tree(root_pid):
            handle = self.api.OpenProcess(0x0400 | 0x0010, False, row['pid'])
            if not handle: raise ctypes.WinError(ctypes.get_last_error())
            try:
                created, exited, kernel, user = [wintypes.FILETIME() for _ in range(4)]
                if not self.api.GetProcessTimes(handle, *[ctypes.byref(v) for v in (created, exited, kernel, user)]):
                    raise ctypes.WinError(ctypes.get_last_error())
                ticks = lambda v: (v.dwHighDateTime << 32) | v.dwLowDateTime
                memory = self.Memory(); memory.size = ctypes.sizeof(memory)
                if not self.api.K32GetProcessMemoryInfo(handle, ctypes.byref(memory), memory.size):
                    raise ctypes.WinError(ctypes.get_last_error())
                result.append({**row, 'created_ticks': ticks(created),
                    'cpu_seconds': (ticks(kernel)+ticks(user))/10000000,
                    'private_bytes': memory.private, 'working_bytes': memory.working})
            finally:
                self.api.CloseHandle(handle)
        if not any(row['pid'] == root_pid for row in result):
            raise RuntimeError('Synthetic launcher exited during sampling')
        return result


def summarize(samples, ready_seconds):
    if len(samples) < 2: raise ValueError('At least two samples required')
    elapsed = samples[-1]['elapsed_seconds'] - samples[0]['elapsed_seconds']
    if elapsed <= 0: raise ValueError('Sampling interval must be positive')
    identities = lambda sample: {(p['pid'], p['created_ticks']) for p in sample['processes']}
    first = identities(samples[0])
    stable = bool(first) and all(identities(s) == first for s in samples)
    # An unexpected child/exit invalidates the idle run instead of undercounting it.
    cpu = sum(p['cpu_seconds'] for p in samples[-1]['processes']) - sum(p['cpu_seconds'] for p in samples[0]['processes'])
    cpu_percent = 100*cpu/elapsed if stable and cpu >= 0 else None
    peak_private = max(sum(p['private_bytes'] for p in s['processes']) for s in samples)
    checks = {'full_duration': elapsed >= THRESHOLDS['minimum_seconds'],
              'stable_process_tree': stable,
              'private_memory': peak_private <= THRESHOLDS['private_bytes'],
              'idle_cpu': cpu_percent is not None and cpu_percent <= THRESHOLDS['cpu_percent_one_core'],
              'ready_time': ready_seconds <= THRESHOLDS['ready_seconds']}
    return {'status': 'passed_on_this_machine' if all(checks.values()) else 'incomplete_or_failed',
            'checks': checks, 'elapsed_seconds': elapsed, 'ready_seconds': ready_seconds,
            'cpu_percent_one_core': cpu_percent, 'peak_private_bytes': peak_private,
            'peak_working_bytes': max(sum(p['working_bytes'] for p in s['processes']) for s in samples)}


def host(base, with_tray=False):
    from jarvis_core.service import CoreService
    from server import create_server
    sample = base/'input'; sample.mkdir()
    core = CoreService(base/'data'); core.initialize(sample)
    server = create_server(core=core, port=0)
    thread = threading.Thread(target=server.serve_forever, kwargs={'poll_interval': .2}, daemon=True)
    thread.start()
    tray = None
    try:
        if with_tray:
            sys.path.insert(0, str(ROOT/'apps/tray'))
            from companion import TrayCompanion
            tray = TrayCompanion(server, core.data_dir)
        print(json.dumps({'pid': os.getpid(), 'port': server.server_address[1], 'tray': with_tray}), flush=True)
        sys.stdin.readline()
    finally:
        server.shutdown(); thread.join(timeout=5)
        try: server.server_close()
        finally:
            if tray: tray.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--host', type=Path, help=argparse.SUPPRESS)
    parser.add_argument('--seconds', type=float, default=300)
    parser.add_argument('--interval', type=float, default=5)
    parser.add_argument('--tray', action='store_true', help='Include the real Windows notification-area companion')
    parser.add_argument('--output', type=Path, default=ROOT/'evals/reports/idle-resources.json')
    args = parser.parse_args()
    if os.name != 'nt': parser.error('This probe requires Windows')
    if args.host: host(args.host, args.tray); return 0
    if not 1 <= args.seconds <= 3600 or not 0.1 <= args.interval <= 10:
        parser.error('seconds must be 1..3600; interval must be 0.1..10')
    reader = WindowsProcesses()
    report = {'schema_version': 1, 'version': __version__, 'captured_at': datetime.now(timezone.utc).isoformat(),
              'platform': platform.platform(), 'logical_cpus': os.cpu_count(), 'thresholds': THRESHOLDS,
              'startup_condition': 'Fresh Python process and fresh synthetic data; OS file caches not flushed.',
              'samples': [], 'status': 'incomplete_or_failed',
              'limits': 'This development PC only; not the 4 CPU/8 GiB target, offline acceptance, or a model/browser load test. No user data or credentials are read by a model call. Sampler is excluded; all observed synthetic Host descendants are included. Short-lived processes between samples are not observable. No independent supervisor is implemented.'}
    try:
        with tempfile.TemporaryDirectory(prefix='jarvis-idle-probe-') as temporary:
            with tempfile.TemporaryFile() as stderr:
                begin = time.monotonic()
                command = [sys.executable, '-I', '-B', str(Path(__file__).resolve()), '--host', temporary]
                if args.tray: command.append('--tray')
                child = subprocess.Popen(command,
                    stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=stderr, text=True, encoding='utf-8',
                    creationflags=subprocess.CREATE_NO_WINDOW)
                try:
                    ready_queue = queue.Queue()
                    threading.Thread(target=lambda: ready_queue.put(child.stdout.readline()), daemon=True).start()
                    ready = json.loads(ready_queue.get(timeout=30))
                    url = f"http://127.0.0.1:{ready['port']}/api/status"
                    with urlopen(url, timeout=3) as response: status = json.load(response)
                    if status.get('assistant_state') != 'standby': raise RuntimeError('Host is not in standby')
                    ready_seconds = time.monotonic()-begin
                    report.update(ready=ready, ready_status=status, launcher_pid=child.pid)
                    start = time.monotonic()
                    while True:
                        processes = reader.sample(child.pid)
                        sample = {'elapsed_seconds': time.monotonic()-start, 'processes': processes,
                                  'system_memory': memory_snapshot()}
                        report['samples'].append(sample)
                        elapsed = sample['elapsed_seconds']-report['samples'][0]['elapsed_seconds']
                        if elapsed >= args.seconds: break
                        time.sleep(min(args.interval, args.seconds-elapsed))
                    with urlopen(url, timeout=3) as response: report['final_status'] = json.load(response)
                    if report['final_status'].get('assistant_state') != 'standby': raise RuntimeError('Host left standby')
                    report['summary'] = summarize(report['samples'], ready_seconds)
                    report['status'] = report['summary']['status']
                finally:
                    if child.poll() is None:
                        child.stdin.write('close synthetic probe\n'); child.stdin.flush()
                    child.wait(timeout=15)
                    child.stdin.close(); child.stdout.close()
                    report['host_exit_code'] = child.returncode
                    if child.returncode: report['status'] = 'incomplete_or_failed'
    except Exception as exc:
        report['status'] = 'incomplete_or_failed'
        report['error'] = f'{type(exc).__name__}: {exc}'
    report['source_sha256'] = {p: hashlib.sha256((ROOT/p).read_bytes()).hexdigest() for p in (
        'tools/probe_idle_resources.py', 'apps/web/server.py', 'runtime/node-host/jarvis_core/resources.py',
        'runtime/node-host/jarvis_core/task_queue.py',
        'adapters/computer-use/jarvis_computer/task_queue.py')}
    if args.tray:
        report['source_sha256'].update({p: hashlib.sha256((ROOT/p).read_bytes()).hexdigest() for p in (
            'apps/tray/companion.py','apps/tray/tray.ps1','apps/tray/TrayApplication.cs')})
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
    print(json.dumps({'status': report['status'], 'summary': report.get('summary'), 'error': report.get('error'), 'report': str(args.output)}))
    return 0 if report['status'] == 'passed_on_this_machine' else 1


if __name__ == '__main__': raise SystemExit(main())
