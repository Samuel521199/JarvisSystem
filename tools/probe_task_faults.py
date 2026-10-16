"""V-K1-05 real process exits at durable inventory boundaries; synthetic data only."""
import argparse
from contextlib import contextmanager
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'runtime/node-host'))
from jarvis_core import __version__
from jarvis_core.service import CoreService
from jarvis_core.policy import CoreError

POINTS = ('before_accept_commit', 'after_accept_commit', 'after_dispatch_commit',
          'partial_artifact', 'after_artifact_sync', 'before_receipt_commit', 'after_receipt_commit')
EXIT_CODE = 91


def require(condition, message):
    if not condition: raise AssertionError(message)


def crash_child(data, point):
    core = CoreService(data)
    def crash(*args, **kwargs): os._exit(EXIT_CODE)
    if point in POINTS[:2]:
        original = core.ledger.prepare
        def prepare(*args, **kwargs):
            if point == 'before_accept_commit': kwargs['_on_prepared'] = crash
            record = original(*args, **kwargs)
            crash()
            return record
        core.ledger.prepare = prepare
    elif point == 'after_dispatch_commit':
        original = core.ledger.begin_dispatch
        def dispatch(*args, **kwargs):
            original(*args, **kwargs); crash()
        core.ledger.begin_dispatch = dispatch
    elif point == 'partial_artifact':
        original = Path.open
        class PartialFile:
            def __init__(self, handle): self.handle = handle
            def __enter__(self): return self
            def __exit__(self, *args): self.handle.close()
            def write(self, content):
                self.handle.write(content[:max(1, len(content)//2)])
                self.handle.flush(); os.fsync(self.handle.fileno()); crash()
        def open_file(path, *args, **kwargs):
            handle = original(path, *args, **kwargs)
            if path.parent == core.ledger.artifact_dir and args and args[0] == 'xb':
                return PartialFile(handle)
            return handle
        Path.open = open_file
    elif point == 'after_artifact_sync':
        original = core._verify_artifact
        def verify(artifact): original(artifact); crash()
        core._verify_artifact = verify
    elif point == 'before_receipt_commit':
        original = core.ledger.complete
        def complete(*args): original(*args); crash()
        core.ledger.complete = complete
    elif point == 'after_receipt_commit':
        original = core.ledger.effect_guard
        @contextmanager
        def guard(*args, **kwargs):
            with original(*args, **kwargs) as db: yield db
            crash()
        core.ledger.effect_guard = guard
    else: raise ValueError('Unknown crash point')
    core.inventory(request_id='durable-request')
    raise AssertionError('Crash point was not reached')


def files(core):
    return {p.name: {'bytes': p.stat().st_size, 'sha256': hashlib.sha256(p.read_bytes()).hexdigest()}
            for p in core.ledger.artifact_dir.iterdir() if p.is_file()}


def exercise(point):
    with tempfile.TemporaryDirectory(prefix='jarvis-fault-probe-') as temporary:
        base = Path(temporary); sample = base/'input'; sample.mkdir()
        (sample/'sample.txt').write_text('synthetic fault input', encoding='utf-8')
        core = CoreService(base/'data'); core.initialize(sample)
        control_before = core.ledger.control()
        response = subprocess.run([sys.executable, '-I', '-B', str(Path(__file__).resolve()),
            '--child', str(core.data_dir), '--point', point], capture_output=True, text=True,
            encoding='utf-8', timeout=45, creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        require(response.returncode == EXIT_CODE, response.stderr or 'Fault did not exit at expected point')
        core = CoreService(core.data_dir)
        state = core.status(); before_retry = files(core)
        expected = ('ABSENT' if point == POINTS[0] else 'PREPARED' if point == POINTS[1]
                    else 'CONFIRMED' if point == POINTS[-1] else 'UNKNOWN')
        require(len(state['tasks']) == (0 if expected == 'ABSENT' else 1), 'Accepted task lost/duplicated')
        if state['tasks']:
            record = core.ledger.record(task_id=state['tasks'][0]['task_id'])
            require(record['action']['status'] == expected, 'Incorrect recovered action status')
        result = core.inventory(request_id='durable-request')
        after_retry = files(core)
        if expected in {'ABSENT', 'PREPARED'}:
            require(result['action']['status'] == 'CONFIRMED', 'Explicit resubmission did not finish')
            core._verify_artifact(result['artifact'])
            require(not before_retry and len(after_retry) == 1, 'Unexpected effect before dispatch')
        else:
            require(before_retry == after_retry, 'Retry modified an existing effect')
            require(result['action']['status'] == expected, 'Retry changed uncertain outcome')
        again = core.inventory(request_id='durable-request')
        require(again == result and files(core) == after_retry, 'Repeated request was not idempotent')
        require(len(core.status()['tasks']) == 1, 'Duplicate task created')
        control_after = core.ledger.control()
        require(control_before['config'] == control_after['config'] and
                control_before['security_epoch'] == control_after['security_epoch'] and
                not control_after['stopped'], 'Recovery changed node, config or control state')
        if expected == 'CONFIRMED': core._verify_artifact(result['artifact'])
        return {'point': point, 'exit_code': response.returncode, 'recovered_action': expected,
                'retry_action': result['action']['status'], 'files_before_retry': before_retry,
                'files_after_retry': after_retry, 'task_count': 1, 'status': 'passed'}


def corrupt_artifact(mode):
    with tempfile.TemporaryDirectory(prefix='jarvis-fault-artifact-') as temporary:
        base = Path(temporary); sample = base/'input'; sample.mkdir()
        core = CoreService(base/'data'); core.initialize(sample)
        record = core.inventory(request_id='artifact-check')
        destination = core.ledger.artifact_dir/record['artifact']['path']
        if mode == 'changed': destination.write_bytes(b'changed test output')
        elif mode == 'missing': destination.unlink()  # This exact newly generated test artifact only.
        else: raise ValueError(mode)
        before = files(core)
        try: CoreService(core.data_dir).inventory(request_id='artifact-check')
        except CoreError as exc: error = exc.code
        else: raise AssertionError('Damaged confirmed output was accepted')
        require(files(core) == before, 'Damaged output was silently rebuilt')
        require(core.ledger.record(task_id=record['task']['task_id']) == record, 'Committed receipt was rewritten')
        return {'case': mode, 'error': error, 'not_rebuilt': True, 'status': 'passed'}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--child', type=Path, help=argparse.SUPPRESS)
    parser.add_argument('--point', choices=POINTS, help=argparse.SUPPRESS)
    parser.add_argument('--output', type=Path, default=ROOT/'evals/reports/task-fault-matrix.json')
    args = parser.parse_args()
    if args.child: crash_child(args.child, args.point); return 1
    report = {'schema_version': 1, 'version': __version__, 'captured_at': datetime.now(timezone.utc).isoformat(),
              'cases': [], 'status': 'incomplete_or_failed',
              'limits': 'Fixed inventory capability, real LPAC Worker and SQLite/NTFS behavior on this machine. Child-only fault hooks call os._exit; not power-loss, disk-controller failure, arbitrary browser effects, or complete K1 acceptance. No user data, credentials or default service changed.'}
    try:
        for point in POINTS:
            report['cases'].append(exercise(point))
            print(json.dumps({'point': point, 'status': 'passed'}), flush=True)
        report['corruption'] = [corrupt_artifact(mode) for mode in ('changed', 'missing')]
        report['status'] = 'passed_with_documented_limits'
    except Exception as exc: report['error'] = f'{type(exc).__name__}: {exc}'
    report['source_sha256'] = {p: hashlib.sha256((ROOT/p).read_bytes()).hexdigest() for p in (
        'tools/probe_task_faults.py', 'runtime/node-host/jarvis_core/service.py',
        'runtime/node-host/jarvis_core/ledger.py', 'runtime/node-host/jarvis_core/worker.py')}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
    print(json.dumps({'status': report['status'], 'error': report.get('error'), 'report': str(args.output)}))
    return 0 if report['status'] == 'passed_with_documented_limits' else 1


if __name__ == '__main__': raise SystemExit(main())
