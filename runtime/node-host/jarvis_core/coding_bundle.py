"""Small, dependency-free Python bundles. Host validates; LPAC compiles/runs."""
import ast
import base64
import io
import re
import zipfile
from pathlib import PurePosixPath

from . import policy
from .evolution.runner import validate_code


def layout(paths, entry):
    if not 1 <= len(paths) <= 4 or entry not in paths:
        raise policy.CoreError('coding_invalid', '选择 1—4 个同目录 Python 文件；入口须在所选文件中。')
    from .project_files import relative
    parents, names = set(), set()
    for path in paths:
        relative(path)
        p = PurePosixPath(path)
        if '\\' in path or not re.fullmatch(r'[A-Za-z][A-Za-z0-9_]*\.py', p.name) or p.stem.lower() in {'csv','io','json','builtins','types','sys','run'}:
            raise policy.CoreError('coding_invalid', '模块使用普通英文文件名和 / 路径；不覆盖标准库或运行入口。')
        parents.add(str(p.parent)); names.add(p.stem.lower())
    if len(parents) != 1 or len(names) != len(paths):
        raise policy.CoreError('coding_invalid', '首期多文件任务要求同目录且模块名不重名。')


def validate_bundle(sources, entry, *, imports=None):
    if not isinstance(sources, dict):
        raise policy.CoreError('candidate_invalid', '候选必须包含冻结清单中的全部文件。')
    layout(list(sources), entry)
    if imports and any(PurePosixPath(p).stem.lower() in imports for p in sources):
        raise policy.CoreError('candidate_invalid', '本地模块不能覆盖构建配方中的依赖。')
    if any(not isinstance(v, str) or len(v.encode()) > 16384 for v in sources.values()) or sum(len(v.encode()) for v in sources.values()) > 32768:
        raise policy.CoreError('candidate_invalid', '候选源码总量超过 32 KiB。')
    try:
        trees = {PurePosixPath(p).stem: ast.parse(s) for p, s in sources.items()}
        exports = {m: {n.name for n in tree.body if isinstance(n, ast.FunctionDef)} for m, tree in trees.items()}
        dependencies = {m: set() for m in trees}
        for path, source in sources.items():
            name = PurePosixPath(path).stem
            validate_code(source, imports={**(imports or {}), **exports}, require_entry=path == entry)
            for node in ast.walk(trees[name]):
                if isinstance(node, ast.Import): dependencies[name].update(n.name for n in node.names if n.name in trees)
                if isinstance(node, ast.ImportFrom) and node.module in trees: dependencies[name].add(node.module)
        done = set()
        def visit(name, active):
            if name in active: raise ValueError('cyclic imports')
            if name in done: return
            for other in dependencies[name]: visit(other, active | {name})
            done.add(name)
        for name in trees: visit(name, set())
    except (SyntaxError, ValueError, RecursionError, TypeError):
        raise policy.CoreError('candidate_invalid', '模块解析或依赖检查失败；不安装依赖，不支持循环导入。') from None


HARNESS = r'''
import builtins, csv, io, json, types
from pathlib import Path
payload=json.loads(Path('input.json').read_text(encoding='utf-8'))
allowed={name:getattr(builtins,name) for name in ('str','int','float','bool','list','dict','tuple','set','len','range','enumerate','zip','sorted','sum','min','max','abs','round','reversed','isinstance','Exception','ValueError','TypeError','KeyError')}
sources={Path(p).stem:compile(s,p,'exec') for p,s in payload['sources'].items()}
loaded={}
def importer(name, globals=None, locals=None, fromlist=(), level=0):
    if level: raise ValueError('relative import denied')
    if name=='csv': return csv
    if name=='io': return io
    if name not in sources: raise ValueError('import denied')
    if name not in loaded:
        mod=types.ModuleType(name)
        mod.__dict__['__builtins__']=allowed
        exec(sources[name],mod.__dict__,mod.__dict__)
        loaded[name]=mod
    return loaded[name]
allowed['__import__']=importer
# Compile AND initialize every declared module, including otherwise unused ones.
for name in sources: importer(name)
entry=loaded[Path(payload['entry']).stem]
outputs=[]
for item in payload['inputs']:
    original=json.dumps(item,ensure_ascii=False,sort_keys=True)
    result=entry.transform(item)
    if not isinstance(result,str) or len(result.encode())>262144:raise ValueError('output limit')
    if json.dumps(item,ensure_ascii=False,sort_keys=True)!=original:raise ValueError('input mutated')
    outputs.append(result)
print(json.dumps({'binding':payload['binding'],'outputs':outputs},ensure_ascii=True))
'''


def package(sources, entry, cases_digest):
    """Deterministic source build; no arbitrary paths or executable deserialization."""
    validate_bundle(sources, entry)
    manifest = {'kind':'jarvis.python-source-build', 'version':1, 'entry':entry,
                'recipe':'offline-python-lpac-v1', 'dependency_install':False,
                'files':{p:policy.digest(s.encode()) for p,s in sorted(sources.items())},
                'cases_digest':cases_digest}
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, 'w', compression=zipfile.ZIP_DEFLATED) as archive:
        for name, content in sorted({**sources, 'jarvis-build.json':policy.canonical_json(manifest)}.items()):
            info=zipfile.ZipInfo(name, (2026,1,1,0,0,0)); info.compress_type=zipfile.ZIP_DEFLATED
            archive.writestr(info, content.encode())
    raw=stream.getvalue()
    return {'manifest':manifest, 'sha256':policy.digest(raw), 'size_bytes':len(raw),
            'filename':'candidate-python.zip', 'base64':base64.b64encode(raw).decode()}
