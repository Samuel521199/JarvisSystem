"""Explicit small package graphs. No directory discovery or implicit imports."""
import ast
import re
from pathlib import PurePosixPath

from . import policy
from .evolution.runner import IMPORTS, validate_code

RECIPE = 'python-package-v1'
QUERY = 'python-package-query-v1'
RECIPES = {RECIPE, QUERY}
RESERVED = {'csv', 'io', 'json', 'builtins', 'types', 'sys', 'run', 'jmespath'}


def layout(paths, entry):
    from .project_files import relative
    if not isinstance(paths, list) or not 1 <= len(paths) <= 8 or entry not in paths:
        raise policy.CoreError('coding_invalid', '包任务选择 1—8 个文件，入口须在清单内。')
    modules = {}
    for path in paths:
        relative(path)
        p = PurePosixPath(path)
        parts = list(p.parts)
        if len(parts) > 4 or p.suffix != '.py' or '\\' in path:
            raise policy.CoreError('coding_invalid', 'Python 包最多三级子目录，使用 / 和 .py 文件。')
        pieces = parts[:-1]+[p.stem]
        if any(not re.fullmatch(r'[A-Za-z][A-Za-z0-9_]*', n) for n in pieces[:-1]) or (
                pieces[-1] != '__init__' and not re.fullmatch(r'[A-Za-z][A-Za-z0-9_]*', pieces[-1])):
            raise policy.CoreError('coding_invalid', '包与模块使用普通英文名称；仅包入口允许 __init__.py。')
        if pieces[0].lower() in RESERVED or (pieces[-1] == '__init__' and len(pieces) == 1):
            raise policy.CoreError('coding_invalid', '模块不能覆盖固定运行库或根目录入口。')
        name = '.'.join(pieces[:-1] if pieces[-1] == '__init__' else pieces)
        if name.casefold() in {n.casefold() for n in modules}:
            raise policy.CoreError('coding_invalid', '文件和包的模块名冲突。')
        modules[name] = path
    for name, path in modules.items():
        parts = name.split('.')
        for i in range(1, len(parts)):
            parent = '.'.join(parts[:i])
            if modules.get(parent) != '/'.join(parts[:i])+'/__init__.py':
                raise policy.CoreError('coding_invalid', '请显式选择所有父包的 __init__.py；不读取清单外文件。')
    if PurePosixPath(entry).name == '__init__.py':
        raise policy.CoreError('coding_invalid', '入口必须是提供 transform(data) 的普通模块。')
    return modules


def absolute(name, package, level):
    if not level: return name
    parts = package.split('.') if package else []
    if level > len(parts): raise ValueError('relative import escapes package')
    base = '.'.join(parts[:len(parts)-level+1])
    return base + ('.'+name if name else '')


def validate(sources, entry, *, extra=None):
    modules = layout(list(sources), entry)
    if any(not isinstance(v, str) or len(v.encode()) > 16384 for v in sources.values()) or sum(len(v.encode()) for v in sources.values()) > 32768:
        raise policy.CoreError('candidate_invalid', '候选仍限每文件 16 KiB、合计 32 KiB。')
    try:
        trees = {n: ast.parse(sources[p]) for n, p in modules.items()}
        exports = {n: {f.name for f in t.body if isinstance(f, ast.FunctionDef)} for n, t in trees.items()}
        allowed = {**IMPORTS, **(extra or {})}
        graph = {n: set() for n in modules}
        for name, path in modules.items():
            package = name if path.endswith('/__init__.py') else name.rpartition('.')[0]
            def check(node):
                if any((x.asname or x.name).startswith('_') for x in node.names): raise ValueError('private import')
                if isinstance(node, ast.Import):
                    targets = [x.name for x in node.names]
                    if any(n not in modules and n not in allowed for n in targets): raise ValueError('import')
                else:
                    target = absolute(node.module or '', package, node.level)
                    targets = [target]
                    for alias in node.names:
                        if alias.name not in exports.get(target, allowed.get(target, set())):
                            child = target+'.'+alias.name
                            if child not in modules: raise ValueError('import symbol')
                            targets.append(child)
                graph[name].update(n for n in targets if n in modules and n != name)
                if name in targets and not path.endswith('/__init__.py'): raise ValueError('self import')
            source = sources[path]
            if not source.strip() and path.endswith('/__init__.py'): continue
            # Pad short package initializers solely for the legacy minimum-size check.
            validate_code(source+'\n'*(max(0,20-len(source.encode()))), require_entry=path==entry, import_resolver=check)
        done = set()
        def visit(n, active):
            if n in active: raise ValueError('cyclic imports')
            if n in done: return
            for target in graph[n]: visit(target, active|{n})
            done.add(n)
        for n in graph: visit(n,set())
    except (SyntaxError, ValueError, RecursionError, TypeError) as exc:
        raise policy.CoreError('candidate_invalid', '包导入、导出或依赖图无效；不允许循环或越界导入。') from exc
    return modules


# This launcher has a separate recipe identity; the old v1 launchers never change.
IMPORTER = '''    records = manifest['modules']
    sources = {name: compile(archive_sources[path], path, 'exec') for name,path in records.items()}
    packages = {name for name,path in records.items() if path.endswith('/__init__.py')}
    loaded, active = {}, set()
    def load(name):
        if name in active: raise ValueError('cyclic initialization')
        if name in loaded: return loaded[name]
        if name not in sources: raise ValueError('import denied')
        parent, _, short = name.rpartition('.')
        if parent: load(parent)
        mod = types.ModuleType(name)
        mod.__dict__['__package__'] = name if name in packages else parent
        mod.__dict__['__builtins__'] = allowed
        loaded[name] = mod; active.add(name)
        try: exec(sources[name], mod.__dict__, mod.__dict__)
        finally: active.remove(name)
        if parent: setattr(loaded[parent], short, mod)
        return mod
    def importer(name, globals=None, locals=None, fromlist=(), level=0):
        if level:
            parts = (globals or {}).get('__package__', '').split('.')
            if not parts or level > len(parts): raise ValueError('relative import denied')
            name = '.'.join(parts[:len(parts)-level+1]) + ('.'+name if name else '')
        if name == 'csv': return csv
        if name == 'io': return io
        if name == 'jmespath' and 'query_api' in extensions: return extensions['query_api']
        if name == 'json' and 'json_api' in extensions: return extensions['json_api']
        mod = load(name)
        if fromlist:
            for item in fromlist:
                child = name+'.'+item
                if child in sources: setattr(mod,item,load(child))
            return mod
        return load(name.split('.')[0])
    allowed['__import__'] = importer
    for name in sources: load(name)
    result = loaded[manifest['entry_module']].transform(data)
'''


def launcher(query=False):
    from .coding_build import MAIN
    from .coding_dependency_launcher import MAIN as QUERY_MAIN
    text = QUERY_MAIN if query else MAIN
    text = text.replace('        sources = {}', '        archive_sources = {}')
    text = text.replace("sources[path.rsplit('/', 1)[-1][:-3]] = compile(source.decode('utf-8'), path, 'exec')",
                        "archive_sources[path] = source.decode('utf-8')")
    start = text.index('    loaded = {}');end = text.index('    if not isinstance(result', start)
    extension = "    extensions = {'query_api':query_api,'json_api':json_api}\n" if query else "    extensions = {}\n"
    return text[:start]+extension+IMPORTER+text[end:]
