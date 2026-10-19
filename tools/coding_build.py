"""Inspect, reproduce and optionally verify a Jarvis Python artifact without models/network."""
import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'runtime/node-host'))
from jarvis_core import policy
from jarvis_core.coding_build import inspect, bytes_from, executable
from jarvis_core.coding_workflow import check_code, validate
from jarvis_core.evolution.runner import IsolatedRunner


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--archive', required=True, type=Path)
    parser.add_argument('--sha256', help='Expected digest from the original delivery receipt, including sha256:')
    parser.add_argument('--output', type=Path, help='New output path; existing files are never replaced')
    parser.add_argument('--cases', type=Path, help='Local JSON list of input/expected pairs; not bundled or uploaded')
    parser.add_argument('--report', type=Path, help='New JSON evidence path')
    args = parser.parse_args()
    def offline(event, unused):
        if event in {'socket.connect', 'socket.connect_ex', 'socket.getaddrinfo'}:
            raise RuntimeError('Offline build command cannot connect to the network')
    sys.addaudithook(offline)
    output_paths = [policy.safe_path(p.resolve(), must_exist=False) for p in (args.output, args.report) if p]
    if len(set(output_paths)) != len(output_paths) or any(p.exists() for p in output_paths):
        parser.error('Use distinct new output/report paths; existing evidence is preserved')
    archive = policy.safe_path(args.archive.resolve(), directory=False)
    with archive.open('rb') as stream: raw = stream.read(65537)
    sources, entry, rebuilt = inspect(raw, args.sha256)
    result = {'status': 'reproduced', 'recipe': rebuilt['manifest']['recipe'], 'sha256': rebuilt['sha256'],
              'bytes': len(raw), 'byte_identical': bytes_from(rebuilt) == raw, 'model_calls': 0,
              'expected_digest_checked': args.sha256 is not None, 'execution': 'not_requested'}
    if args.cases:
        with policy.safe_path(args.cases.resolve(), directory=False).open('rb') as stream:
            body = stream.read(16385)
        if len(body) > 16384: parser.error('Case file exceeds 16 KiB')
        cases = json.loads(body)
        validate({'coding': True, 'paths': [entry], 'skill_id': 'matt-pocock.tdd',
                  'model': 'offline::verification', 'cases': cases})
        runner = IsolatedRunner(); runner.preflight()
        class ArtifactRunner:
            def run(self, artifact, inputs, check):
                if executable(rebuilt['manifest']['recipe']): return runner.run_build(artifact, inputs, check)
                return runner.run_bundle(sources, entry, inputs, check)
        result['validation'] = check_code(ArtifactRunner(), rebuilt, cases, lambda: None)
        result['execution'] = 'windows-lpac'
        result['status'] = 'verified' if result['validation']['passed'] else 'failed'
    if args.output and result['status'] != 'failed':
        with output_paths[0].open('xb') as stream: stream.write(raw)
    if args.report:
        with policy.safe_path(args.report.resolve(), must_exist=False).open('x', encoding='utf-8') as stream:
            json.dump(result, stream, ensure_ascii=False, indent=2); stream.write('\n')
    print(json.dumps(result, ensure_ascii=False))
    return 1 if result['status'] == 'failed' else 0


if __name__ == '__main__':
    raise SystemExit(main())
