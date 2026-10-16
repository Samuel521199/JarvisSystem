"""Real Windows outbound isolation for disposable runtime slots, with UAC helper.

This never disables host adapters, changes firewall profiles, or stops Jarvis.
It is process-scoped OS evidence, not whole-machine disconnected acceptance.
"""
import argparse
from contextlib import closing
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import shutil
import socket
import sqlite3
import subprocess
import sys
import tempfile
import time
import traceback
import uuid

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'runtime/node-host'))
from jarvis_core.releases import RuntimeSlots
from release_bundle import verify, sha
from probe_task_faults import require

CONNECT = r'''
import json,socket,sys
try:
    with socket.create_connection((sys.argv[1],443),timeout=3): pass
    print(json.dumps({'connected':True}))
except OSError as exc:
    print(json.dumps({'connected':False,'error':type(exc).__name__,'winerror':getattr(exc,'winerror',None),'errno':exc.errno}))
'''


def powershell_literal(value): return "'"+str(value).replace("'", "''")+"'"


def allow_probe_results(shell, base):
    # Python's private temporary ACL uses OWNER RIGHTS. Files created elevated
    # may have Administrators as owner, so explicitly retain this user's access
    # to this newly created probe directory and its results only.
    command = ('$ErrorActionPreference="Stop"; '
        '$sid=[Security.Principal.WindowsIdentity]::GetCurrent().User.Value; & '+
        powershell_literal(Path(os.environ['SystemRoot'])/'System32/icacls.exe')+' '+
        powershell_literal(base)+' /grant ("*"+$sid+":(OI)(CI)(M)"); exit $LASTEXITCODE')
    subprocess.run([str(shell), '-NoProfile', '-NonInteractive', '-Command', command],
                   capture_output=True, check=True, timeout=15,
                   creationflags=subprocess.CREATE_NO_WINDOW)


def wait_json(path, launcher, timeout):
    deadline = time.monotonic()+timeout
    while time.monotonic() < deadline:
        if path.exists(): return json.loads(path.read_text(encoding='utf-8-sig'))
        if launcher.poll() is not None: raise RuntimeError('Elevated helper exited before writing '+path.name)
        time.sleep(.25)
    raise TimeoutError('Waiting for '+path.name)


def connect(executable, address):
    result = subprocess.run([str(executable), '-I', '-B', '-c', CONNECT, address],
        capture_output=True, text=True, encoding='utf-8', timeout=10,
        env=RuntimeSlots._environment(), creationflags=subprocess.CREATE_NO_WINDOW)
    require(result.returncode == 0, result.stderr)
    return json.loads(result.stdout)


def snapshot(data):
    tables = {}
    for name in ('control.db', 'safety/control.db'):
        with closing(sqlite3.connect((data/name).as_uri()+'?mode=ro', uri=True)) as db:
            tables[name] = sha('\n'.join(db.iterdump()).encode())
    return {'database_digests': tables,
            'artifacts': {p.name: sha(p.read_bytes()) for p in (data/'artifacts').iterdir() if p.is_file()}}


def exercise(slots, old, new, base):
    candidate = slots.slots/new['id']; fallback = slots.slots/old['id']; data = base/'data'
    sample = base/'input'; sample.mkdir(); (sample/'example.txt').write_text('offline fixture', encoding='utf-8')
    def cli(*args):
        result = subprocess.run([str(candidate/'python/python.exe'), '-I', '-B',
            str(candidate/'source/apps/cli/main.py'), *args, '--data-dir', str(data)],
            capture_output=True, text=True, encoding='utf-8', timeout=40,
            env=slots._environment(), creationflags=subprocess.CREATE_NO_WINDOW)
        require(result.returncode == 0, result.stderr)
        return json.loads(result.stdout)
    def start():
        result = subprocess.run([str(candidate/'python/python.exe'), '-I', '-B',
            str(candidate/'source/tools/runtime_releases.py'), '--root', str(slots.root), 'start',
            '--data-dir', str(data), '--mode', 'status'], capture_output=True, text=True,
            encoding='utf-8', timeout=150, env=slots._environment(), creationflags=subprocess.CREATE_NO_WINDOW)
        return result, slots.status()['starts'][0]
    cli('init', '--allowed-root', str(sample))
    confirmed = cli('inventory', '--request-id', 'network-confirmed')
    require(confirmed['action']['status'] == 'CONFIRMED', 'Inventory failed under OS network block')
    cli('inventory', '--request-id', 'network-waiting', '--prepare-only')
    before = snapshot(data)
    healthy, healthy_record = start()
    require(healthy.returncode == 0 and not healthy_record['fallback'], healthy.stderr)
    require(json.loads(healthy.stdout)['version'] == new['version'], 'Unexpected current version')
    require(snapshot(data) == before, 'Healthy start changed business state')
    # Corrupt only the temporary instance configuration, then restore the exact row.
    with closing(sqlite3.connect(data/'control.db')) as db:
        digest = db.execute('SELECT config_digest FROM control').fetchone()[0]
        db.execute("UPDATE control SET config_digest='bad probe digest'"); db.commit()
    damaged = snapshot(data)
    bad_config, bad_config_record = start()
    require(bad_config.returncode == 2 and not bad_config_record['selection_committed'], 'Bad config was launched')
    require(snapshot(data) == damaged and slots.status()['active'] == new['id'], 'Config failure modified state')
    with closing(sqlite3.connect(data/'control.db')) as db:
        db.execute('UPDATE control SET config_digest=?', (digest,)); db.commit()
    require(snapshot(data) == before, 'Synthetic configuration restoration differs')
    (candidate/'source/README.md').write_text('probe corruption', encoding='utf-8')
    recovered, recovered_record = start()
    require(recovered.returncode == 0 and recovered_record['fallback'] and
            recovered_record['selected'] == old['id'], recovered.stderr)
    require(json.loads(recovered.stdout)['version'] == old['version'], 'Fallback version mismatch')
    require(snapshot(data) == before, 'Fallback changed business state')
    (fallback/'source/README.md').write_text('second probe corruption', encoding='utf-8')
    failed, failed_record = start()
    require(failed.returncode == 2 and not failed_record['selection_committed'], 'Both corrupt slots launched')
    require(slots.status()['active'] == old['id'] and snapshot(data) == before, 'Failure changed business state')
    return {'healthy': healthy_record, 'invalid_configuration': bad_config_record,
            'fallback': recovered_record, 'both_corrupt': failed_record, 'business_data_unchanged': True,
            'tasks_preserved': 2, 'inventory_digest': confirmed['artifact']['digest'], 'snapshot': before}


def run(previous, candidate, *, elevate=False):
    report = {'schema_version': 1, 'captured_at': datetime.now(timezone.utc).isoformat(),
              'status': 'incomplete_or_failed', 'scope': 'Windows program-specific outbound block; host stays online',
              'limits': ['Not whole-machine disconnected boot, power-loss recovery, IPv6 coverage, schema downgrade or complete K1.',
                         'External check makes credential-free IPv4 TCP connections to www.microsoft.com:443; no application payload.',
                         'Firewall block does not isolate same-user code or localhost. Worker retains its separate LPAC boundary.',
                         'Rules cover only four temporary executable paths; helper removes them on stop/error or ten-minute timeout.']}
    base = Path(tempfile.mkdtemp(prefix='jarvis-network-probe-')).resolve()
    launcher = None; cleanup_ok = True
    try:
        require(os.name == 'nt', 'Windows only')
        slots = RuntimeSlots(base/'runtime')
        releases = []
        for path in (previous, candidate):
            manifest = verify(path)
            report.setdefault('packages', []).append({'name': path.name, 'version': manifest['version'], 'sha256': sha(path.read_bytes())})
            release = slots.install(path); releases.append(release)
            require(slots.health(release['id'])['state'] == 'verified', 'Package health failed before network test')
            slots.select(release['id'])
        old, new = releases
        require(old['id'] != new['id'], 'Two distinct packages required')
        hosts = [slots.slots/r['id']/'python/python.exe' for r in releases]
        programs = []
        for r, host in zip(releases, hosts):
            profile = json.loads((slots.slots/r['id']/'source/config/worker-profile.json').read_text(encoding='utf-8'))
            programs.extend([str(host), str(slots.slots/r['id']/'source/runtime-bundle'/profile['runtime_directory']/'python.exe')])
        address = socket.getaddrinfo('www.microsoft.com', 443, socket.AF_INET, socket.SOCK_STREAM)[0][4][0]
        report['endpoint'] = {'name': 'www.microsoft.com', 'ipv4': address, 'port': 443}
        report['before_block'] = [connect(host, address) for host in hosts]
        require(all(item['connected'] for item in report['before_block']), 'Positive network baseline unavailable')
        config = {'session_id': uuid.uuid4().hex, 'programs': programs}
        (base/'firewall.json').write_text(json.dumps(config), encoding='utf-8')
        shell = Path(os.environ['SystemRoot'])/'System32/WindowsPowerShell/v1.0/powershell.exe'
        allow_probe_results(shell, base)
        helper = ROOT/'tools/network_probe_firewall.ps1'
        # Capture errors before the helper body (for example script policy or
        # directory validation) instead of leaving the parent waiting blindly.
        bootstrap = ('try { & '+powershell_literal(helper)+' -SessionRoot '+powershell_literal(base)+
            ' } catch { @{status="failed";error=$_.Exception.Message} | ConvertTo-Json | '
            'Set-Content -LiteralPath '+powershell_literal(base/'firewall-ready.json')+
            ' -Encoding UTF8; exit 1 }')
        helper_command = [str(shell), '-NoProfile', '-NonInteractive', '-Command', bootstrap]
        arguments = subprocess.list2cmdline(helper_command[1:])
        if elevate:
            command = [str(shell), '-NoProfile', '-NonInteractive', '-Command',
                'Start-Process -FilePath '+powershell_literal(shell)+' -ArgumentList '+powershell_literal(arguments)+
                ' -Verb RunAs -WindowStyle Hidden -Wait -ErrorAction Stop']
        else: command = helper_command
        cleanup_ok = False
        launcher = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            creationflags=subprocess.CREATE_NO_WINDOW)
        report['firewall'] = wait_json(base/'firewall-ready.json', launcher, 90)
        require(report['firewall']['status'] == 'ready', str(report['firewall']))
        report['while_blocked'] = [connect(host, address) for host in hosts]
        report['unblocked_control'] = connect(sys.executable, address)
        require(not any(item['connected'] for item in report['while_blocked']) and report['unblocked_control']['connected'],
                'OS block was not effective or endpoint is unavailable')
        report['recovery'] = exercise(slots, old, new, base)
        # Recheck before removing rules so a timed-out helper cannot produce a false pass.
        report['block_after_work'] = [connect(host, address) for host in hosts]
        require(not any(item['connected'] for item in report['block_after_work']), 'Block ended before exercise finished')
        report['status'] = 'passed_with_documented_limits'
    except Exception as exc:
        report['error'] = f'{type(exc).__name__}: {exc}'
        report['traceback'] = traceback.format_exc(limit=8)
    finally:
        if launcher is not None:
            (base/'firewall-stop').write_text('end this probe', encoding='ascii')
            try:
                report['cleanup'] = wait_json(base/'firewall-cleanup.json', launcher, 45)
                cleanup_ok = report['cleanup']['status'] == 'removed'
                if cleanup_ok and 'while_blocked' in report:
                    report['after_cleanup'] = [connect(host, address) for host in hosts]
                    if not all(item['connected'] for item in report['after_cleanup']):
                        report['status'] = 'incomplete_or_failed'
            except Exception as exc: report['cleanup_error'] = f'{type(exc).__name__}: {exc}'
            if launcher.poll() is not None:
                stdout, stderr = launcher.communicate()
                report['helper_exit_code'] = launcher.returncode
                if stderr: report['helper_error'] = stderr.decode(errors='replace')[-4000:]
        if not cleanup_ok:
            report['status'] = 'incomplete_or_failed'; report['retained_probe_directory'] = str(base)
        else:
            require(base.parent == Path(tempfile.gettempdir()).resolve() and base.name.startswith('jarvis-network-probe-'),
                    'Cleanup path escaped temporary probe root')
            shutil.rmtree(base)
    report['source_sha256'] = {p: sha((ROOT/p).read_bytes()) for p in
        ('tools/probe_network_recovery.py', 'tools/network_probe_firewall.ps1', 'tools/probe_task_faults.py')}
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('previous', type=Path); parser.add_argument('candidate', type=Path)
    parser.add_argument('--elevate', action='store_true', help='Ask Windows UAC to elevate only the temporary firewall helper')
    parser.add_argument('--output', type=Path, default=ROOT/'evals/reports/network-recovery.json')
    args = parser.parse_args()
    report = run(args.previous.resolve(), args.candidate.resolve(), elevate=args.elevate)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
    print(json.dumps({'status': report['status'], 'error': report.get('error'), 'cleanup': report.get('cleanup'),
                      'retained_probe_directory': report.get('retained_probe_directory'), 'report': str(args.output)}))
    return 0 if report['status'] == 'passed_with_documented_limits' else 1


if __name__ == '__main__': raise SystemExit(main())
