"""Build/verify a closed, credential-free Windows runtime archive. Never activate it.

Hashes detect corruption; this tool does not issue a trusted release signature.
An extracted package is a candidate until its independent checks pass.
"""
import argparse
import hashlib
from importlib import metadata
import json
import os
from pathlib import Path, PurePosixPath, PureWindowsPath
import shutil
import stat
import sys
import tempfile
import tomllib
import zipfile

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'runtime/node-host'))
from jarvis_core.policy import safe_path

LIMIT=512*1024*1024
MAX_FILES=20000


def sha(raw):return hashlib.sha256(raw).hexdigest()


def archive_path(value):
    if not isinstance(value,str) or not value or '\\' in value or ':' in value or '\0' in value:
        raise ValueError('Unsafe archive member')
    parts=PurePosixPath(value)
    if parts.is_absolute() or any(p in {'','.', '..'} or p.endswith((' ','.')) or PureWindowsPath(p).is_reserved() for p in value.split('/')):
        raise ValueError('Unsafe archive path')
    return parts


def source_files():
    selected=['pyproject.toml','uv.lock','README.md','tools/release_bundle.py','tools/runtime_releases.py']
    extensions={'.py','.json','.toml','.lock','.html','.css','.js','.md','.mmd','.txt','.ps1'}
    for folder in ('runtime','apps','adapters','config','contracts','seed','docs','tests/fixtures/workspace'):
        for path in (ROOT/folder).rglob('*'):
            if path.is_file() and path.suffix in extensions and '__pycache__' not in path.parts:
                selected.append(path.relative_to(ROOT).as_posix())
    return sorted(set(selected))


def dependencies():
    # Resolve from the installed, locked environment; no package manager/network.
    try:
        from packaging.requirements import Requirement
    except ImportError:
        # CPython's bundled pip supplies the standard PEP 508 parser offline;
        # this is a build-time tool, not an extra runtime dependency.
        wheels=list((Path(sys.base_prefix)/'Lib/ensurepip/_bundled').glob('pip-*.whl'))
        if len(wheels)!=1:raise RuntimeError('Install the packaging build tool or use CPython with bundled ensurepip')
        sys.path.insert(0,str(safe_path(wheels[0],directory=False)))
        from pip._vendor.packaging.requirements import Requirement
    project=tomllib.loads((ROOT/'pyproject.toml').read_text(encoding='utf-8'))['project']
    pending=[Requirement(value) for value in project['dependencies']]
    resolved={};files={};seen=set()
    while pending:
        request=pending.pop();key=(request.name,tuple(sorted(request.extras)))
        if key in seen:continue
        seen.add(key);dist=metadata.distribution(request.name)
        if dist.version not in request.specifier:raise ValueError('Installed dependency does not satisfy '+str(request))
        resolved[dist.metadata['Name']]=dist.version
        base=Path(dist.locate_file('')).resolve()
        for entry in dist.files or []:
            path=Path(dist.locate_file(entry)).absolute()
            if '__pycache__' in path.parts or path.suffix=='.pyc':continue
            # Wheel command wrappers outside site-packages are not runtime inputs.
            if '..' in entry.parts or not path.is_relative_to(base):continue
            path=safe_path(path,directory=False)
            relative=path.relative_to(base).as_posix();archive_path(relative)
            files[relative]=path
        for value in dist.requires or []:
            child=Requirement(value)
            if child.marker is None or any(child.marker.evaluate({'extra':extra}) for extra in ({''}|set(request.extras))):
                pending.append(child)
    return resolved,files


def build(destination):
    from jarvis_core import __version__
    from jarvis_core.worker import verify_bundle
    if os.name!='nt' or sys.version_info[:2]!=(3,13):raise ValueError('Requires verified Windows Python 3.13 runtime')
    destination=safe_path(destination,must_exist=False)
    safe_path(destination.parent,directory=True)
    if destination.exists():raise FileExistsError(destination)
    runtime,evidence=verify_bundle()
    versions,packages=dependencies()
    files={}
    def add(name,raw):
        archive_path(name)
        if name.casefold() in {n.casefold() for n in files}:raise ValueError('Duplicate package file')
        files[name]=raw
    for relative in source_files():add('source/'+relative,safe_path(ROOT/relative,directory=False).read_bytes())
    for relative,path in packages.items():add('site-packages/'+relative,path.read_bytes())
    for path in sorted(runtime.rglob('*')):
        if not path.is_file():continue
        path=safe_path(path,directory=False);relative=path.relative_to(runtime).as_posix()
        raw=path.read_bytes()
        add('source/runtime-bundle/'+runtime.name+'/'+relative,raw)
        if relative=='bundle.json':continue
        if relative=='python.exe':raw=safe_path(Path(sys.base_prefix)/'python.exe',directory=False).read_bytes()
        if relative=='python313._pth':raw=b'stdlib.zip\nDLLs\n.\n../site-packages\n'
        add('python/'+relative,raw)
    if len(files)>MAX_FILES or sum(map(len,files.values()))>LIMIT:raise ValueError('Package exceeds bounds')
    manifest={'schema_version':1,'version':__version__,'python':sys.version.split()[0],
              'scope':'Windows K1 CLI/recovery and core Python dependencies; optional browser/speech/models not bundled',
              'dependencies':versions,'worker':evidence,
              'files':{name:{'sha256':sha(raw),'size':len(raw)} for name,raw in sorted(files.items())}}
    # Exclusive destination creation; a failed/incomplete archive is not activated.
    with destination.open('xb') as target:
        with zipfile.ZipFile(target,'w',compression=zipfile.ZIP_DEFLATED) as archive:
            for name,raw in sorted(files.items()):archive.writestr(name,raw)
            archive.writestr('release.json',json.dumps(manifest,ensure_ascii=False,indent=2).encode())
        target.flush();os.fsync(target.fileno())
    verify(destination)
    return {'version':__version__,'path':str(destination),'sha256':sha(destination.read_bytes()),
            'files':len(files),'bytes':destination.stat().st_size,'status':'candidate_verified','dependencies':versions}


def verify(archive_file):
    archive_file=safe_path(archive_file,directory=False)
    if archive_file.stat().st_size>LIMIT:raise ValueError('Archive too large')
    with zipfile.ZipFile(archive_file) as archive:
        entries=archive.infolist();names=[item.filename for item in entries]
        if len(entries)>MAX_FILES+1 or len({n.casefold() for n in names})!=len(names):raise ValueError('Duplicate or too many members')
        if sum(item.file_size for item in entries)>LIMIT:raise ValueError('Expanded size exceeded')
        for item in entries:
            archive_path(item.filename)
            if stat.S_ISLNK(item.external_attr>>16) or item.is_dir():raise ValueError('Links/directories not permitted in package')
        meta=archive.getinfo('release.json')
        if meta.file_size>4*1024*1024:raise ValueError('Oversize manifest')
        manifest=json.loads(archive.read(meta))
        if manifest.get('schema_version')!=1 or not isinstance(manifest.get('files'),dict):raise ValueError('Invalid manifest')
        if set(names)!=set(manifest['files'])|{'release.json'}:raise ValueError('Package membership changed')
        for name,expected in manifest['files'].items():
            raw=archive.read(name)
            if len(raw)!=expected['size'] or sha(raw)!=expected['sha256']:raise ValueError('Package content changed: '+name)
        return manifest


def extract(archive_file,destination):
    manifest=verify(archive_file)
    destination=safe_path(destination,must_exist=False)
    safe_path(destination.parent,directory=True)
    destination.mkdir()  # Never merge into or replace an existing runtime slot.
    with zipfile.ZipFile(archive_file) as archive:
        for name in [*manifest['files'],'release.json']:
            relative=archive_path(name);path=destination.joinpath(*relative.parts)
            path.parent.mkdir(parents=True,exist_ok=True)
            safe_path(path.parent,directory=True)
            with path.open('xb') as handle:handle.write(archive.read(name))
    profile=destination/'source/config/worker-profile.json'
    if profile.exists():
        name=json.loads(profile.read_text(encoding='utf-8'))['runtime_directory']
        if not name.startswith('worker-python-') or '/' in name or '\\' in name or Path(name).name!=name:
            raise ValueError('Invalid worker runtime directory')
        # ZIP does not preserve Windows ACLs. Only this new, pinned runtime
        # bundle is made readable to restricted packages, never the Host/source.
        from jarvis_core.worker import require_acl_volume
        from jarvis_worker.windows import grant_read
        runtime=safe_path(destination/'source/runtime-bundle'/name,directory=True)
        require_acl_volume(runtime);grant_read(runtime,'S-1-15-2-2')
    return {'path':str(destination),'version':manifest['version'],'activated':False}


def main():
    parser=argparse.ArgumentParser(description=__doc__);sub=parser.add_subparsers(dest='command',required=True)
    for name in ('build','verify','extract'):
        part=sub.add_parser(name);part.add_argument('archive',type=Path)
        if name=='extract':part.add_argument('destination',type=Path)
    args=parser.parse_args()
    if args.command=='build':result=build(args.archive)
    elif args.command=='extract':result=extract(args.archive,args.destination)
    else:
        manifest=verify(args.archive);result={'version':manifest['version'],'files':len(manifest['files']),'status':'verified','trusted_signature':False}
    print(json.dumps(result,ensure_ascii=False))


if __name__=='__main__':main()
