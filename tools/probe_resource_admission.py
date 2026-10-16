"""Real HTTP/UI plus injected memory shortage under two bounded CPU helpers.

Thresholds are fixed before measurement. No cloud request or real RAM exhaustion.
Helpers finish on their own after 12 seconds and hold 32 MiB of payload each.
"""
import ctypes
from datetime import datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import platform
import subprocess
import sys
import time
import uuid

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT/'tests'), str(ROOT/'runtime/node-host'), str(ROOT/'adapters/computer-use')]
from jarvis_core import __version__
from jarvis_core.resources import ResourceAdmission, memory_snapshot, MIB

SAMPLES = 20
P95_MS = 300
MAX_MS = 1000
CANCEL_MS = 1000
RESUME_MS = 10000


def process_memory():
    class Counters(ctypes.Structure):
        _fields_ = [('size', ctypes.c_uint32), ('faults', ctypes.c_uint32),
                    *[(name, ctypes.c_size_t) for name in ('peak_working', 'working',
                        'peak_paged', 'paged', 'peak_nonpaged', 'nonpaged', 'commit',
                        'peak_commit', 'private')]]
    value = Counters();value.size = ctypes.sizeof(value)
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    current = kernel.GetCurrentProcess;current.argtypes = [];current.restype = ctypes.c_void_p
    api = kernel.K32GetProcessMemoryInfo
    api.argtypes = [ctypes.c_void_p, ctypes.POINTER(Counters), ctypes.c_uint32]
    api.restype = ctypes.c_int
    if not api(current(), ctypes.byref(value), value.size):
        raise ctypes.WinError(ctypes.get_last_error())
    return {'working_bytes': value.working, 'peak_working_bytes': value.peak_working,
            'private_bytes': value.private, 'peak_private_bytes': value.peak_commit}


def helper():
    payload = bytearray(32 * MIB)
    print('ready', flush=True)
    wall = time.monotonic();cpu = time.process_time();loops = 0
    while time.monotonic() - wall < 12:
        hashlib.sha256(payload).digest();loops += 1
    print(json.dumps({'cpu_seconds': time.process_time()-cpu, 'elapsed_seconds': time.monotonic()-wall,
                      'payload_bytes': len(payload), 'loops': loops, 'memory': process_memory()}), flush=True)


def main():
    from test_computer_web import ComputerWebTests
    from jarvis_computer.browser import DriverJob
    from playwright.sync_api import sync_playwright, expect
    fixture = ComputerWebTests();fixture.setUp()
    helpers = []
    output = Path(os.environ['LOCALAPPDATA'])/'Jarvis/data/diagnostics/resource-admission'
    output.mkdir(parents=True, exist_ok=True)
    try:
        actual_before = memory_snapshot()
        fixture.manager.queue.resources = ResourceAdmission(probe=lambda: {
            'total_bytes': 8*1024*MIB, 'available_bytes': 128*MIB, 'commit_available_bytes': 256*MIB})
        tasks = []
        for _ in range(2):
            response = fixture.request('POST', '/api/tasks', {'mode': 'inventory', 'request_id': 'web-'+uuid.uuid4().hex})
            assert response[0] == 202, response
            tasks.append(json.loads(response[2])['task_id'])
        with sync_playwright() as playwright:
            job = DriverJob(playwright)
            try:
                browser = playwright.chromium.launch(channel='msedge', headless=True, chromium_sandbox=True)
                page = browser.new_page(viewport={'width': 1440, 'height': 1000})
                errors = [];page.on('pageerror', lambda error: errors.append(str(error)))
                page.goto(fixture.origin)
                page.locator('#computer-nav').click()
                expect(page.locator('#queue-note')).to_contain_text('等待资源')
                expect(page.locator('#queue-note')).to_contain_text('聊天仍可使用')
                page.screenshot(path=str(output/'waiting.png'), full_page=True)
                page.set_viewport_size({'width': 390, 'height': 844})
                assert page.evaluate('document.documentElement.scrollWidth <= innerWidth'), 'Narrow UI overflows'
                page.screenshot(path=str(output/'waiting-narrow.png'), full_page=True)
                page.set_viewport_size({'width': 1440, 'height': 1000})
                for _ in range(2):
                    child = subprocess.Popen([sys.executable, '-I', '-B', str(Path(__file__).resolve()), '--load-helper'],
                        stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding='utf-8',
                        creationflags=subprocess.CREATE_NO_WINDOW)
                    helpers.append(child)
                    assert child.stdout.readline().strip() == 'ready', 'Load helper did not start'
                samples = {name: [] for name in ('status', 'tasks', 'chat')}
                memory_samples = []
                cpu_before = time.process_time();wall_before = time.monotonic()
                for _ in range(SAMPLES):
                    for name in samples:
                        begin = time.perf_counter()
                        response = (fixture.request('POST', '/api/chat', {'message': 'synthetic foreground'}) if name == 'chat'
                                    else fixture.get('/api/tasks') if name == 'tasks' else fixture.request('GET', '/api/status'))
                        samples[name].append((time.perf_counter()-begin)*1000)
                        assert response[0] == 200, response
                    assert all(child.poll() is None for child in helpers), 'Load ended before measurement'
                    memory_samples.append({'host': process_memory(), 'system': memory_snapshot()})
                host_cpu = time.process_time()-cpu_before;wall = time.monotonic()-wall_before
                begin = time.perf_counter()
                assert fixture.request('POST', '/api/tasks/'+tasks[0]+'/cancel', {})[0] == 200
                cancel_ms = (time.perf_counter()-begin)*1000
                assert fixture.core.ledger.record(task_id=tasks[0])['action']['status'] == 'CANCELLED'
                assert fixture.core.ledger.record(task_id=tasks[1])['action']['status'] == 'PREPARED'
                assert not fixture.core.ledger.control()['stopped']
                begin = time.perf_counter()
                fixture.manager.queue.resources.probe = memory_snapshot
                fixture.manager.queue.wake.set()
                deadline = time.monotonic()+RESUME_MS/1000
                while time.monotonic() < deadline:
                    record = fixture.core.ledger.record(task_id=tasks[1])
                    if record['action']['status'] == 'CONFIRMED': break
                    time.sleep(.05)
                resume_ms = (time.perf_counter()-begin)*1000
                assert record['action']['status'] == 'CONFIRMED', record
                fixture.core._verify_artifact(record['artifact'])
                expect(page.locator('#queue-note')).not_to_contain_text('等待资源', timeout=5000)
                assert not errors, errors
                browser.close()
            finally:
                job.close()
        helper_evidence = []
        for child in helpers:
            stdout, stderr = child.communicate(timeout=15)
            assert child.returncode == 0, stderr
            helper_evidence.append(json.loads(stdout))
        summary = {name: {'count': len(values), 'p95_ms': sorted(values)[math.ceil(.95*len(values))-1],
                         'max_ms': max(values)} for name, values in samples.items()}
        passed = all(item['p95_ms'] <= P95_MS and item['max_ms'] <= MAX_MS for item in summary.values()) and cancel_ms <= CANCEL_MS and resume_ms <= RESUME_MS
        report = {'version': __version__, 'captured_at': datetime.now(timezone.utc).isoformat(),
            'status': 'passed' if passed else 'failed', 'platform': platform.platform(), 'logical_cpus': os.cpu_count(),
            'thresholds': {'p95_ms': P95_MS, 'max_ms': MAX_MS, 'cancel_ms': CANCEL_MS, 'resume_ms': RESUME_MS},
            'profile': fixture.manager.queue.resources.profile, 'samples_ms': samples, 'summary': summary,
            'cancel_ms': cancel_ms, 'resume_ms': resume_ms, 'host_cpu_seconds': host_cpu, 'elapsed_seconds': wall,
            'actual_memory_before': actual_before, 'memory_samples': memory_samples, 'load_helpers': helper_evidence,
            'ui': {'waiting_text': True, 'recovery_text': True, 'errors': errors, 'screenshot': str(output/'waiting.png')},
            'limits': 'Low-memory readings are injected; actual memory and process counters are separate. Two real CPU helpers hold 64 MiB payload total. Synthetic chat, one real LPAC inventory after recovery; no cloud requests, actual RAM exhaustion, GPU pressure, low-end-device or long-duration proof.'}
        (output/'result.json').write_text(json.dumps(report, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
        print(json.dumps({'status': report['status'], 'summary': summary, 'cancel_ms': cancel_ms,
                          'resume_ms': resume_ms, 'report': str(output/'result.json')}))
        return 0 if passed else 1
    finally:
        # Helpers have finite internal deadlines; no unrelated process is stopped.
        for child in helpers:
            if child.poll() is None: child.communicate(timeout=15)
        fixture.doCleanups()


if __name__ == '__main__':
    if sys.argv[1:] == ['--load-helper']: helper()
    else: raise SystemExit(main())
