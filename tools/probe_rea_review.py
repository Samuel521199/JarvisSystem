"""Probe a caller-installed, pinned REA package against self-owned static fixtures.

This is research evidence, not a Jarvis runtime adapter. Never installs REA,
registers MCP, executes the fixture, or calls a model.
"""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import tempfile
import time


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def check_report(report):
    positive, negative = report['cases']
    evidence = positive['result']
    summary = evidence.get('normalized_result', {}).get('summary', {})
    edges = evidence.get('normalized_result', {}).get('graph', {}).get('edges', [])
    return {
        'positive_exit_and_evidence': positive['exit_code'] == 0 and str(evidence.get('evidence_id', '')).startswith('ev_'),
        'context_bridge_found': summary.get('context_bridge_apis') == 1,
        'ipc_pair_found': summary.get('ipc', {}).get('paired_renderer_transmissions') == 1,
        'exact_ipc_channel_and_source': any(edge.get('relation') == 'invokes' and
            edge.get('properties', {}).get('channel') == 'jarvis:sum' and
            edge.get('properties', {}).get('handler_path') == 'main.js' for edge in edges),
        'derived_static_result_with_limits': evidence.get('confidence') == 'derived' and
            evidence.get('authority') == 'shipped-artifact' and bool(evidence.get('limitations')),
        'missing_target_is_error': negative['exit_code'] != 0 and negative['result'].get('code') == 'invalid_request',
        'inputs_unchanged': report['input_unchanged'],
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--package-root', type=Path, required=True)
    parser.add_argument('--node', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    package = args.package_root.resolve(strict=True)
    entry = package / 'scripts/rea.mjs'
    metadata = json.loads((package / 'package.json').read_text(encoding='utf-8'))
    if metadata['name'] != 'rea-agents' or metadata['version'] != '6.5.0':
        raise ValueError('This review is pinned to rea-agents 6.5.0')
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='jarvis-rea-fixture-') as temporary:
        base = Path(temporary)
        fixture = base / 'application'
        fixture.mkdir()
        sources = {
            'package.json': json.dumps({'name': 'jarvis-owned-rea-fixture', 'version': '1.0.0', 'main': 'main.js'}),
            'main.js': "const {ipcMain} = require('electron');\nconst {sum} = require('./math');\nipcMain.handle('jarvis:sum', (_event, left, right) => sum(left, right));\nthrow new Error('STATIC_ONLY_DO_NOT_EXECUTE');\n",
            'math.js': 'exports.sum = (left, right) => left + right;\n',
            'preload.js': "const {contextBridge, ipcRenderer} = require('electron');\ncontextBridge.exposeInMainWorld('jarvisFixture', {sum: (left, right) => ipcRenderer.invoke('jarvis:sum', left, right)});\n",
        }
        for name, content in sources.items():
            (fixture / name).write_text(content, encoding='utf-8')
        before = {name: digest(fixture / name) for name in sources}
        # All child commands are REA static inspection. The target JS is never loaded.
        cases = []
        for name, target in [('javascript_directory', fixture), ('missing_target', base / 'absent')]:
            command = [str(args.node), str(entry), 'analyze-javascript-application', str(target),
                       '--max-heap-mb', '256', '--analysis-timeout-ms', '15000', '--json']
            start = time.perf_counter()
            run = subprocess.run(command, cwd=base, capture_output=True, check=False, timeout=90)
            elapsed = round(time.perf_counter() - start, 3)
            (output / f'{name}.stdout.json').write_bytes(run.stdout)
            (output / f'{name}.stderr.txt').write_bytes(run.stderr)
            try:
                data = json.loads(run.stdout)
            except ValueError:
                data = {'invalid_json': True}
            cases.append({'name': name, 'command': command, 'exit_code': run.returncode,
                          'elapsed_seconds': elapsed, 'stdout_bytes': len(run.stdout),
                          'stdout_sha256': hashlib.sha256(run.stdout).hexdigest(),
                          'stderr_sha256': hashlib.sha256(run.stderr).hexdigest(),
                          'top_level_keys': list(data) if isinstance(data, dict) else [],
                          'result': data})
        after = {name: digest(fixture / name) for name in sources}
        report = {'schema_version': 1, 'review_date': '2026-10-18', 'package_version': metadata['version'],
                  'node_version': subprocess.check_output([str(args.node), '--version'], text=True).strip(),
                  'package_root': str(package), 'target_kind': 'self_owned_synthetic_javascript',
                  'fixture_sources': sources, 'fixture_sha256': before, 'input_unchanged': before == after,
                  'model_calls': 0, 'jarvis_integration': False, 'mcp_registered': False,
                  'cases': cases}
        report['checks'] = check_report(report)
        report['passed'] = all(report['checks'].values())
        (output / 'probe.json').write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
        print(json.dumps({k: v for k, v in report.items() if k not in ('cases', 'fixture_sources')}, ensure_ascii=False))
        for case in cases:
            print(json.dumps({k: v for k, v in case.items() if k != 'result'}, ensure_ascii=False))
        if not report['passed']:
            raise SystemExit('REA probe did not satisfy the declared fixture checks')


if __name__ == '__main__':
    main()
