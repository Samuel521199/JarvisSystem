"""Disposable two-process TLS and Edge settings acceptance; never uses owner data."""
from contextlib import closing
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import queue
import subprocess
import sys
import tempfile
import threading
import time
import uuid

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT/'tools'), str(ROOT/'runtime/node-host'),
               str(ROOT/'adapters/models/provider-native'), str(ROOT/'adapters/computer-use')]
from jarvis_core import __version__
from jarvis_core.service import CoreService
from jarvis_core.federation import Federation
from jarvis_core.federation_protocol import heads_token
from jarvis_core.process_usage import process_usage


def child(directory, source):
    core = CoreService(Path(directory))
    if not core.ledger.db_path.exists():
        core.initialize(Path(source))
    service = Federation(core)
    try:
        for line in sys.stdin:
            request = json.loads(line)
            try:
                if request == {'action': 'quit'}: break
                if request == {'action': 'status'}: value = service.status()
                elif request == {'action': 'metrics'}: value = process_usage(os.getpid())
                elif request.get('action') == 'offline':
                    value = service.network.change(request['offline'], service.network.snapshot()['revision'])
                    if request['offline']: service.close()
                else: value = service.action(request)
                print(json.dumps({'ok': True, 'value': value}, ensure_ascii=False), flush=True)
            except Exception as exc:
                print(json.dumps({'ok': False, 'code': getattr(exc, 'code', type(exc).__name__)}), flush=True)
    finally:
        service.close()


class Node:
    def __init__(self, directory, source, script=None):
        self.proc = subprocess.Popen([sys.executable, '-X', 'utf8', '-u', '-B', script or __file__,
                                      '--node', str(directory), str(source)], stdin=subprocess.PIPE,
                                     stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                                     encoding='utf-8', creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        self.queue = queue.Queue()
        def read():
            for line in self.proc.stdout: self.queue.put(line)
        threading.Thread(target=read, daemon=True).start()

    def request(self, **request):
        self.proc.stdin.write(json.dumps(request) + '\n'); self.proc.stdin.flush()
        result = json.loads(self.queue.get(timeout=25))
        assert result['ok'], result
        return result['value']

    def close(self):
        if self.proc.poll() is None:
            self.proc.stdin.write('{"action":"quit"}\n'); self.proc.stdin.flush()
            try: self.proc.wait(timeout=10)
            except subprocess.TimeoutExpired: self.proc.kill(); self.proc.wait(timeout=5)
        for stream in (self.proc.stdin, self.proc.stdout, self.proc.stderr): stream.close()


def processes():
    with tempfile.TemporaryDirectory(prefix='jarvis-two-node-') as directory:
        base = Path(directory); source = base/'source'; source.mkdir()
        a, b = Node(base/'a', source), Node(base/'b', source)
        try:
            for n in (a, b): n.request(action='initialize')
            baseline = [n.request(action='metrics') for n in (a, b)]
            endpoint = a.request(action='listen', address='127.0.0.1', port=0)['endpoint']
            invitation = a.request(action='invite', label='跨进程验证')
            b.request(action='join', invitation=invitation['invitation'])
            sid = invitation['space']; item = uuid.uuid4().hex
            a.request(action='edit', space=sid, item=item, expected=heads_token([]),
                      title='计划', text='跨进程初始内容', deleted=False)
            b.request(action='sync', space=sid)
            b.request(action='offline', offline=True)
            state = b.request(action='status')['spaces'][0]['cards'][0]
            b.request(action='edit', space=sid, item=item, expected=state['expected'],
                      title='计划', text='离线进程的修改', deleted=False)
            b.request(action='offline', offline=False)
            b.request(action='sync', space=sid)
            assert a.request(action='status')['spaces'][0]['cards'][0]['versions'][0]['text'] == '离线进程的修改'
            before = a.request(action='status')
            a.close()
            a = Node(base/'a', source)
            restarted = a.request(action='status')
            assert restarted['endpoint'] is None and restarted['fingerprint'] == before['fingerprint']
            assert restarted['spaces'] == before['spaces']
            a.request(action='listen', address='127.0.0.1', port=int(endpoint.rsplit(':', 1)[1]))
            b.request(action='sync', space=sid)
            before_idle = [n.request(action='metrics') for n in (a, b)]
            time.sleep(1)
            after_idle = [n.request(action='metrics') for n in (a, b)]
            storage = {name: sum(p.stat().st_size for p in (base/name).glob('federation*') if p.is_file()) +
                       sum(p.stat().st_size for p in (base/name/'federation').glob('*') if p.is_file())
                       for name in ('a', 'b')}
            return {'status': 'passed', 'checks': ['separate_processes', 'pinned_tls_pair',
                    'two_way_sync', 'offline_edit_then_reconcile', 'process_restart_listener_off',
                    'stable_device_identity', 'reconnect_after_restart'],
                    'resources': {'baseline_private_bytes': [v['private_bytes'] for v in baseline],
                                  'post_sync_private_bytes': [v['private_bytes'] for v in after_idle],
                                  'one_second_idle_cpu_seconds': [round(y['cpu_seconds']-x['cpu_seconds'], 4)
                                                                 for x,y in zip(before_idle, after_idle)],
                                  'shared_storage_bytes': storage},
                    'limits': ['Two processes on one Windows PC; not two physical machines.',
                               'One-second idle sample is not a long-term resource test; only one synthetic card.']}
        finally:
            a.close(); b.close()


def ui(output):
    from probe_parallel_runtime import fixture, web, serve, request
    from probe_workspace_ui import SyntheticChat
    from jarvis_computer.browser import DriverJob
    from playwright.sync_api import sync_playwright, expect
    errors, checks = [], []
    with tempfile.TemporaryDirectory(prefix='jarvis-sharing-ui-') as directory:
        base = Path(directory)
        servers, threads = [], []
        for name in ('a', 'b'):
            folder = base/name; folder.mkdir()
            server = web.create_server(core=fixture(folder), chat=SyntheticChat(), port=0)
            servers.append(server); threads.append(serve(server))
        try:
            with sync_playwright() as pw, closing(DriverJob(pw)):
                browser = pw.chromium.launch(channel='msedge', headless=True, chromium_sandbox=True)
                pages = []
                for server in servers:
                    page = browser.new_page(viewport={'width': 1440, 'height': 1150})
                    page.on('pageerror', lambda exc: errors.append(str(exc)))
                    page.goto(f'http://127.0.0.1:{server.server_port}/settings#federation')
                    expect(page.locator('#shared-initialize')).to_be_visible()
                    page.locator('#shared-initialize').click()
                    expect(page.locator('#shared-controls')).to_be_visible()
                    pages.append(page)
                a, b = pages
                assert not servers[0].federation.status()['endpoint']
                checks.append('visit_does_not_listen')
                # Actual ephemeral HTTPS listener; the UI shows its bound address after refresh.
                servers[0].federation.listen('127.0.0.1', 0)
                a.locator('#shared-refresh').click()
                a.get_by_text('接收另一台设备的连接', exact=True).click()
                expect(a.locator('#shared-invite')).to_be_enabled()
                a.locator('#shared-label').fill('一起成长')
                a.locator('#shared-invite').click()
                expect(a.locator('#shared-code')).to_be_visible()
                code = a.locator('#shared-code').input_value()
                b.get_by_text('加入另一台设备的共享空间', exact=True).click()
                b.locator('#shared-join-code').fill(code)
                b.locator('#shared-join').click()
                expect(b.locator('#shared-save')).to_be_enabled()
                b.locator('#shared-title').fill('周末计划')
                b.locator('#shared-text').fill('<img src=x onerror=alert(1)> 一起学习，不执行这段文字。')
                b.locator('#shared-save').click()
                expect(b.locator('#shared-message')).to_have_text('已保存到本机。')
                b.locator('#shared-sync').click()
                expect(b.locator('#shared-message')).to_contain_text('两端资料已对账')
                a.locator('#shared-refresh').click()
                expect(a.locator('#shared-cards option')).to_have_count(2)
                a.locator('#shared-cards').select_option(index=1)
                assert a.locator('#shared-text').input_value().startswith('<img')
                assert a.locator('#shared-versions img').count() == 0
                checks.extend(['pair_from_settings', 'save_and_two_way_sync', 'received_text_not_html'])
                a.locator('#shared-text').fill('未保存草稿')
                a.locator('#shared-refresh').click()
                expect(a.locator('#shared-refresh')).to_be_enabled()
                assert a.locator('#shared-text').input_value() == '未保存草稿'
                checks.append('refresh_preserves_unsaved_draft')
                output.mkdir(parents=True, exist_ok=True)
                a.screenshot(path=str(output/'desktop.png'), full_page=True)
                a.set_viewport_size({'width': 390, 'height': 844})
                a.screenshot(path=str(output/'mobile.png'), full_page=True)
                assert a.evaluate('document.documentElement.scrollWidth <= innerWidth+1')
                checks.append('mobile_no_horizontal_overflow')
                # Nonce and Origin protections remain on the local API.
                assert request(servers[0], '/api/federation')[0] == 200
                response = a.request.post(f'http://127.0.0.1:{servers[0].server_port}/api/federation',
                                          data={'action': 'initialize'})
                assert response.status == 403
                checks.append('local_api_requires_nonce')
                code, _, _ = request(servers[0], '/api/network', 'POST', {'offline': True, 'revision': 0})
                assert code == 200 and servers[0].federation.status()['endpoint'] is None
                checks.append('offline_toggle_closes_listener')
                browser.close()
            assert not errors, errors
            return {'status': 'passed', 'checks': checks, 'page_errors': errors,
                    'screenshots': [str(output/'desktop.png'), str(output/'mobile.png')]}
        finally:
            for server in servers: server.shutdown(); server.server_close()
            for thread in threads: thread.join(timeout=5)
            time.sleep(2)


def main():
    if len(sys.argv) > 1 and sys.argv[1] == '--node':
        child(sys.argv[2], sys.argv[3]); return
    output = Path('H:/JarvisData/diagnostics/k6-federation-20261020')
    report = {'version': __version__, 'captured_at': datetime.now(timezone.utc).isoformat(),
              'processes': processes(), 'ui': ui(output), 'cloud_model_calls': 0,
              'scope': 'K6 bounded explicitly shared cards, not personal-memory federation or unified task authority'}
    path = ROOT/'evals/reports/k6-federation-2026-10-20.json'
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps({'status': 'passed', 'report': str(path)}))


if __name__ == '__main__':
    main()
