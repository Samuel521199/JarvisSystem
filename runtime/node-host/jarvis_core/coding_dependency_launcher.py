"""Fixed v1 dependency launcher, executed only in workers or downloaded PYZs."""

MAIN = '''"""Jarvis offline JSON query tool. Requires CPython 3.11-3.13."""
import builtins, csv, hashlib, io, json, sys, types, zipfile

def main():
    if not (3, 11) <= sys.version_info[:2] < (3, 14):
        raise ValueError('Requires CPython 3.11-3.13')
    raw = sys.stdin.buffer.read(65537)
    if len(raw) > 65536: raise ValueError('input limit')
    data = json.loads(raw.decode('utf-8-sig'))
    original = json.dumps(data, ensure_ascii=False, sort_keys=True)
    with zipfile.ZipFile(sys.argv[0]) as archive:
        manifest = json.loads(archive.read('jarvis-build.json'))
        for path, digest in manifest['dependency_files'].items():
            if 'sha256:' + hashlib.sha256(archive.read(path)).hexdigest() != digest:
                raise ValueError('dependency digest mismatch')
        sources = {}
        for path, digest in manifest['files'].items():
            source = archive.read(path)
            if 'sha256:' + hashlib.sha256(source).hexdigest() != digest:
                raise ValueError('source digest mismatch')
            sources[path.rsplit('/', 1)[-1][:-3]] = compile(source.decode('utf-8'), path, 'exec')
    # Always load the bundled version, never a global/previously cached installation.
    for name in list(sys.modules):
        if name == 'jmespath' or name.startswith('jmespath.'): del sys.modules[name]
    vendor = sys.argv[0] + '/_vendor'
    sys.path.insert(0, vendor)
    try:
        import jmespath
    finally:
        sys.path.remove(vendor)
    if jmespath.__version__ != '1.1.0': raise ValueError('dependency version mismatch')
    def search(expression, value):
        if not isinstance(expression, str) or len(expression.encode('utf-8')) > 4096:
            raise ValueError('query limit')
        return jmespath.search(expression, value)
    query_api = types.ModuleType('jmespath'); query_api.search = search
    json_api = types.ModuleType('json'); json_api.dumps = json.dumps
    allowed = {name:getattr(builtins,name) for name in ('str','int','float','bool','list','dict','tuple','set','len','range','enumerate','zip','sorted','sum','min','max','abs','round','reversed','isinstance','Exception','ValueError','TypeError','KeyError')}
    loaded = {}
    def importer(name, globals=None, locals=None, fromlist=(), level=0):
        if level: raise ValueError('relative import denied')
        if name == 'csv': return csv
        if name == 'io': return io
        if name == 'jmespath': return query_api
        if name == 'json': return json_api
        if name not in sources: raise ValueError('import denied')
        if name not in loaded:
            mod = types.ModuleType(name)
            mod.__dict__['__builtins__'] = allowed
            exec(sources[name], mod.__dict__, mod.__dict__)
            loaded[name] = mod
        return loaded[name]
    allowed['__import__'] = importer
    for name in sources: importer(name)
    result = loaded[manifest['entry'].rsplit('/', 1)[-1][:-3]].transform(data)
    if not isinstance(result, str) or len(result.encode('utf-8')) > 262144:
        raise ValueError('output limit')
    if json.dumps(data, ensure_ascii=False, sort_keys=True) != original:
        raise ValueError('input mutated')
    sys.stdout.buffer.write(result.encode('utf-8'))

if __name__ == '__main__': main()
'''

README = '''Jarvis offline JSON query tool

Requires CPython 3.11-3.13. JSON on stdin; exact UTF-8 string on stdout.
JMESPath 1.1.0 (MIT) is bundled; no pip, network or global installation needed.
The original license and package metadata are under _vendor/ in this archive.
Only jmespath.search(expression, data) and json.dumps are exposed to candidates.
The manifest records the reviewed wheel digest and all bundled library digests.
Example (replace input.json with the JSON structure required by your task):
  Get-Content input.json -Raw -Encoding utf8 | python candidate-python.pyz

Jarvis checks this artifact in its Windows LPAC worker before delivery.
Manual execution uses your account permissions, not an OS sandbox.
Tests, private expected answers, credentials and Python are not bundled.
Applying candidate source files does not install libraries into your project.
'''
