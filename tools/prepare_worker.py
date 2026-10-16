"""Prepare a small offline worker Python from the installed interpreter; no downloads."""
from pathlib import Path
import hashlib
import json
import os
import shutil
import sys
import tempfile
import zipfile

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'runtime/worker-host'))
from jarvis_worker.windows import grant_read
sys.path.insert(0,str(ROOT/'runtime/node-host'))
from jarvis_core.policy import safe_path
from jarvis_core.worker import verify_bundle


def prepare():
    if os.name!='nt' or sys.version_info[:2]!=(3,13):
        raise RuntimeError('The initial worker bundle is verified only with Windows Python 3.13')
    parent=safe_path(Path(os.environ['USERPROFILE'])/'.jarvis/worker-runtimes',must_exist=False,directory=True)
    parent.mkdir(parents=True,exist_ok=True)
    parent=parent.resolve(strict=True)
    target=parent/('worker-python-'+'.'.join(map(str,sys.version_info[:3]))+'-v1')
    if target.exists():
        runtime,evidence=verify_bundle()
        print(json.dumps({'runtime':str(runtime),'status':'verified_existing',**evidence}))
        return
    stage=Path(tempfile.mkdtemp(prefix='worker-build-',dir=parent)).resolve()
    assert stage.is_relative_to(parent) and stage!=parent
    try:
        base=Path(sys.base_prefix)
        # GUI-subsystem executable needs no console helper process; inherited
        # pipes still carry standard output, and the one-process job stays strict.
        shutil.copyfile(base/'pythonw.exe',stage/'python.exe')
        for name in ('python313.dll','python3.dll','vcruntime140.dll','vcruntime140_1.dll','LICENSE.txt'):
            shutil.copyfile(base/name,stage/name)
        (stage/'DLLs').mkdir()
        for file in (base/'DLLs').iterdir():
            if file.suffix.lower() in {'.pyd','.dll'} and not file.name.startswith('_test'):
                shutil.copyfile(file,stage/'DLLs'/file.name)
        excluded={'site-packages','test','tests','ensurepip','idlelib','tkinter','turtledemo','__pycache__'}
        with zipfile.ZipFile(stage/'stdlib.zip','w',compression=zipfile.ZIP_DEFLATED) as archive:
            for file in sorted((base/'Lib').rglob('*.py')):
                relative=file.relative_to(base/'Lib')
                if not excluded.intersection(relative.parts):
                    archive.write(file,relative.as_posix())
        (stage/'python313._pth').write_text('stdlib.zip\nDLLs\n.\n',encoding='ascii')
        hashes={file.relative_to(stage).as_posix():hashlib.sha256(file.read_bytes()).hexdigest()
                for file in sorted(stage.rglob('*')) if file.is_file()}
        payload=json.dumps({'schema_version':1,'python_version':list(sys.version_info[:3]),'files':hashes},indent=2)+'\n'
        (stage/'bundle.json').write_text(payload,encoding='utf-8')
        # Only this new runtime bundle is made readable to restricted packages.
        grant_read(stage,'S-1-15-2-2')
        if not stage.resolve().is_relative_to(parent) or target.exists():
            raise RuntimeError('Bundle target changed')
        stage.rename(target)
        print(json.dumps({'runtime':str(target),'manifest_sha256':hashlib.sha256((target/'bundle.json').read_bytes()).hexdigest(),
                          'bytes':sum(f.stat().st_size for f in target.rglob('*') if f.is_file()),'files':len(hashes)}))
    finally:
        if stage.exists():
            if not stage.resolve().is_relative_to(parent) or stage.is_symlink():
                raise RuntimeError('Refusing unsafe staging cleanup')
            shutil.rmtree(stage)


if __name__=='__main__':
    prepare()
