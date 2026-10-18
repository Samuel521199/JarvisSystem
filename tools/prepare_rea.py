"""Pin an explicitly installed REA 6.5.0 tree and Node into a dedicated runtime.

No downloads or setup hooks. Install the pinned release with --ignore-scripts
first, then pass its npm prefix and an existing supported Node executable.
"""
import argparse
import json
import shutil
import hashlib
from pathlib import Path


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--npm-prefix', type=Path, required=True)
    p.add_argument('--node', type=Path, required=True)
    p.add_argument('--destination', type=Path, required=True)
    args = p.parse_args()
    source = args.npm_prefix.resolve(strict=True) / 'node_modules'
    package = json.loads((source / 'rea-agents/package.json').read_text(encoding='utf-8'))
    if package['name'] != 'rea-agents' or package['version'] != '6.5.0': raise ValueError('Expected rea-agents 6.5.0')
    destination = args.destination.resolve()
    destination.mkdir(parents=True, exist_ok=False)
    shutil.copytree(source, destination / 'node_modules')
    shutil.copy2(args.node.resolve(strict=True), destination / 'node.exe')
    digest = lambda raw: 'sha256:' + hashlib.sha256(raw).hexdigest()
    files = {f.relative_to(destination).as_posix(): digest(f.read_bytes()) for f in sorted(destination.rglob('*')) if f.is_file()}
    bundle = {'version': '6.5.0', 'files': files}
    raw = (json.dumps(bundle, ensure_ascii=False, indent=2) + '\n').encode('utf-8')
    (destination / 'bundle.json').write_bytes(raw)
    profile = {'version': '6.5.0', 'root': str(destination), 'manifest_digest': digest(raw)}
    repo = Path(__file__).resolve().parents[1]
    (repo / 'config/skills/rea-runtime.json').write_text(json.dumps(profile, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps({'runtime': str(destination), 'files': len(files), 'manifest_digest': digest(raw)}))


if __name__ == '__main__': main()
