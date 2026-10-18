"""Compile and run generated functions only in the existing Windows LPAC boundary."""
import ast
import json

from .. import policy
from ..worker import verify_bundle, workspace
from ..worker_recovery import StageLease, recover
from jarvis_worker.windows import run, WorkerError, require_acl_volume

FORBIDDEN = {'open', 'eval', 'exec', 'compile', 'globals', 'locals', 'vars', 'getattr', 'setattr',
             'delattr', 'hasattr', 'breakpoint', 'input', 'help', 'exit', 'quit', 'memoryview', 'FileIO', 'open_code'}
IMPORTS = {'csv': {'writer', 'QUOTE_MINIMAL', 'QUOTE_ALL', 'QUOTE_NONNUMERIC', 'QUOTE_NONE'}, 'io': {'StringIO'}}


def validate_code(source):
    if not isinstance(source, str) or not 20 <= len(source.encode()) <= 24000:
        raise policy.CoreError('candidate_invalid', '候选代码大小无效。')
    try:
        tree = ast.parse(source)
        if len(list(ast.walk(tree))) > 3000:
            raise ValueError('AST quota')
        functions = [n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == 'transform']
        if len(functions) != 1 or len(functions[0].args.args) != 1:
            raise ValueError('entry')
        for node in tree.body:
            if not isinstance(node, (ast.Import, ast.ImportFrom, ast.FunctionDef)) and not (
                    isinstance(node, ast.Expr) and isinstance(node.value, ast.Constant) and isinstance(node.value.value, str)):
                raise ValueError('top level')
        for node in ast.walk(tree):
            if isinstance(node, (ast.ClassDef, ast.AsyncFunctionDef, ast.Global, ast.Nonlocal, ast.With, ast.AsyncWith)):
                raise ValueError('unsupported construct')
            if isinstance(node, ast.Name) and (node.id in FORBIDDEN or node.id.startswith('_')):
                raise ValueError('forbidden name')
            if isinstance(node, ast.Attribute) and (node.attr.startswith('_') or node.attr in FORBIDDEN):
                raise ValueError('private attribute')
            if isinstance(node, ast.Import) and any(n.name not in {'csv', 'io'} for n in node.names):
                raise ValueError('import')
            if isinstance(node, ast.ImportFrom) and (node.module not in IMPORTS or node.level or any(n.name not in IMPORTS[node.module] for n in node.names)):
                raise ValueError('import')
            if isinstance(node, ast.FunctionDef) and (node.decorator_list or node.returns or
                    node.args.defaults or node.args.kw_defaults or any(a.annotation for a in node.args.args)):
                raise ValueError('definition effects')
        compile(tree, '<candidate>', 'exec')  # Compilation only; never executed in Host.
    except (ValueError, SyntaxError, RecursionError, TypeError):
        raise policy.CoreError('candidate_invalid', '代码未通过纯转换函数的静态检查。') from None


# Source is input data. Candidate has no reference to this harness's globals or
# expected outputs. LPAC, not this Python namespace filter, is the OS boundary.
HARNESS = r'''
import builtins, csv, io, json
from pathlib import Path
payload=json.loads(Path('input.json').read_text(encoding='utf-8'))
allowed={name:getattr(builtins,name) for name in ('str','int','float','bool','list','dict','tuple','set','len','range','enumerate','zip','sorted','sum','min','max','abs','round','reversed','isinstance','Exception','ValueError','TypeError','KeyError')}
def importer(name, globals=None, locals=None, fromlist=(), level=0):
    if level or name not in ('csv','io'): raise ValueError('import denied')
    return csv if name=='csv' else io
allowed['__import__']=importer
scope={'__builtins__':allowed}
exec(compile(payload['source'],'<candidate>','exec'),scope,scope)
outputs=[]
for item in payload['inputs']:
    original=json.dumps(item,ensure_ascii=False,sort_keys=True)
    result=scope['transform'](item)
    if not isinstance(result,str) or len(result.encode('utf-8'))>262144:raise ValueError('output limit')
    if json.dumps(item,ensure_ascii=False,sort_keys=True)!=original:raise ValueError('input mutated')
    outputs.append(result)
print(json.dumps({'binding':payload['binding'],'outputs':outputs},ensure_ascii=True))
'''


class IsolatedRunner:
    def preflight(self):
        try: verify_bundle()
        except WorkerError as exc: raise policy.CoreError(exc.code, str(exc)) from exc

    def run(self, source, inputs, checkpoint):
        validate_code(source)
        checkpoint()
        runtime, bundle = verify_bundle()
        parent = policy.safe_path(workspace() / 'evolution-staging', directory=True, must_exist=False)
        parent.mkdir(parents=True, exist_ok=True)
        require_acl_volume(parent)
        recover(parent)
        binding = {'operation': 'evolution.transform.v1', 'source': policy.digest(source.encode()),
                   'input': policy.digest(policy.canonical_json(inputs).encode())}
        lease = StageLease(parent, binding)
        binding['nonce'] = lease.token
        try:
            (lease.stage / 'worker.py').write_text(HARNESS, encoding='utf-8')
            (lease.stage / 'input.json').write_text(policy.canonical_json(
                {'binding': binding, 'source': source, 'inputs': inputs}), encoding='utf-8')
            result = run(runtime, lease.stage, checkpoint=checkpoint, profile_name=lease.profile,
                         on_started=lease.started, seconds=12, output_limit=2*1024*1024,
                         memory_limit=192*1024*1024)
            checkpoint()
            if result['exit_code'] != 0:
                raise policy.CoreError('candidate_execution_failed', '隔离代码执行失败。')
            value = json.loads(result['stdout'])
            if (not isinstance(value, dict) or set(value) != {'binding', 'outputs'} or value['binding'] != binding or
                    not isinstance(value['outputs'], list) or len(value['outputs']) != len(inputs) or
                    any(not isinstance(v, str) or len(v.encode()) > 262144 for v in value['outputs'])):
                raise ValueError('invalid worker reply')
            return value['outputs'], {**bundle, **result['evidence']}
        except WorkerError as exc:
            raise policy.CoreError(exc.code, str(exc)) from exc
        except (ValueError, TypeError, KeyError):
            raise policy.CoreError('candidate_reply_invalid', '隔离执行回执无效。') from None
        finally:
            lease.close()
