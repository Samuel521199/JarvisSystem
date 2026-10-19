"""Measure the disposable UI probe and its own Edge tree separately from the Host.

No existing browser is inspected or closed. This is an interaction sample, not
five-minute idle or physical reference-device certification.
"""
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT/'tools'), str(ROOT/'runtime/node-host')]
from jarvis_core.process_usage import process_usage
from jarvis_core.resources import memory_snapshot
from windows_process_snapshot import OwnedProcesses as WindowsProcesses


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=False)
    report = {'status': 'running', 'captured_at': datetime.now(timezone.utc).isoformat(),
              'version': '0.1.62', 'samples': [], 'sample_errors': [], 'real_model_calls': 0,
              'limits': ['Real headless Edge with the current UI flow, not a user browser session.',
                         'Host includes test harness; driver and Edge are listed separately.',
                         'Periodic observations can miss short process peaks; not a leak or 8 GiB claim.']}
    reader = WindowsProcesses()
    started = time.monotonic()
    with (args.output/'ui.log').open('w', encoding='utf-8') as log:
        process = subprocess.Popen([sys.executable, str(ROOT/'tools/probe_k2_personal_ui.py'),
                                    '--output', str(args.output/'ui')], cwd=ROOT,
                                   stdout=log, stderr=subprocess.STDOUT,
                                   creationflags=subprocess.CREATE_NO_WINDOW)
        try:
            while process.poll() is None:
                if time.monotonic()-started > 180:
                    raise TimeoutError('UI probe exceeded its bounded run')
                values = []
                exited = []
                for row in reader.tree(process.pid):
                    try:
                        value = process_usage(row['pid'])
                        # A Windows venv python.exe may launch the base Python
                        # child. Both belong to the Host/fixture, not Playwright.
                        values.append({**row, **value, 'group': 'edge' if row['name'].lower() == 'msedge.exe'
                                       else 'host_and_fixture' if row['name'].lower() in {'python.exe', 'pythonw.exe'}
                                       else 'driver'})
                    except OSError as error:
                        still_present = {p['pid'] for p in reader.tree(process.pid)}
                        if error.winerror == 87 and row['pid'] not in still_present:
                            exited.append(row)
                        else:
                            report['sample_errors'].append(repr(error))
                report['samples'].append({'seconds': time.monotonic()-started, 'processes': values,
                                           'exited_during_sample': exited, 'memory': memory_snapshot()})
                time.sleep(.25)
            report['exit_code'] = process.returncode
            ui = json.loads((args.output/'ui/report.json').read_text(encoding='utf-8'))
            report['ui_status'] = ui['status']
            import hashlib
            report['source_sha256'] = {**ui['source_sha256'],**{
                p.relative_to(ROOT).as_posix():hashlib.sha256(p.read_bytes()).hexdigest()
                for p in (Path(__file__), ROOT/'tools/windows_process_snapshot.py')}}
            report['summary'] = {
                group: {'peak_private_bytes': max(sum(p['private_bytes'] for p in row['processes'] if p['group'] == group)
                                                  for row in report['samples']),
                        'peak_working_bytes': max(sum(p['working_set_bytes'] for p in row['processes'] if p['group'] == group)
                                                  for row in report['samples'])}
                for group in ('host_and_fixture', 'driver', 'edge')}
            report['seconds'] = time.monotonic()-started
            report['owned_tree_reclaimed'] = not reader.tree(process.pid)
            report['status'] = 'passed' if (process.returncode == 0 and ui['status'] == 'passed'
                and not report['sample_errors'] and report['summary']['edge']['peak_private_bytes'] > 0
                and report['owned_tree_reclaimed']) else 'failed'
        except Exception as error:
            report.update(status='failed', error=repr(error))
            raise
        finally:
            if process.poll() is None:
                # The child owns the browser Job; exiting it closes only that Job.
                process.terminate()
                process.wait(timeout=15)
            (args.output/'report.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps({k: v for k, v in report.items() if k not in {'samples', 'source_sha256'}}, ensure_ascii=False))
    return 0 if report['status'] == 'passed' else 1


if __name__ == '__main__':
    raise SystemExit(main())
