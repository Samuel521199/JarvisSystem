"""Read-only final archive/source reconciliation; never rebuild a verified package."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path

from release_bundle import ROOT, source_files, verify


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('archive', type=Path)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        parser.error('Retain previous evidence; choose a fresh output')
    manifest = verify(args.archive)
    source_members = {
        name.removeprefix('source/'): value
        for name, value in manifest['files'].items()
        if name.startswith('source/') and not name.startswith('source/runtime-bundle/')
    }
    expected = set(source_files())
    missing = sorted(expected - source_members.keys())
    unexpected = sorted(source_members.keys() - expected)
    documentation = []
    runtime = []
    for relative, entry in source_members.items():
        path = ROOT / relative
        current = hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else None
        if current != entry['sha256']:
            row = {'path': relative, 'archive_sha256': entry['sha256'], 'workspace_sha256': current}
            # Only prose evidence updates may differ after the executable build.
            target = documentation if path.suffix == '.md' and (relative == 'README.md' or relative.startswith('docs/')) else runtime
            target.append(row)
    result = {
        'status': 'passed' if not (missing or unexpected or runtime) else 'failed',
        'version': manifest['version'], 'captured_at': datetime.now(timezone.utc).isoformat(),
        'archive': str(args.archive.resolve()),
        'archive_sha256': hashlib.sha256(args.archive.read_bytes()).hexdigest(),
        'archive_members_verified': len(manifest['files']),
        'source_members_compared': len(source_members),
        'missing_members': missing, 'unexpected_members': unexpected,
        'runtime_changes': runtime, 'post_build_documentation_changes': documentation,
        'limits': 'Full archive member hashes checked. Current source selection must match; only listed Markdown evidence updates may differ. Bundled dependencies/Worker runtime are verified against the archive manifest, not asserted to equal the development environment. No package rewritten or service restarted.',
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps({key: result[key] for key in ['status', 'version', 'source_members_compared', 'missing_members', 'unexpected_members', 'runtime_changes']}))
    return 0 if result['status'] == 'passed' else 1


if __name__ == '__main__':
    raise SystemExit(main())
