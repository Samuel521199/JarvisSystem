"""Pinned, lazy QuickJS toolchain; generated JavaScript only runs in LPAC."""
import io
import zipfile
from . import policy

RECIPE = 'javascript-scene-v1'
WHEEL = 'quickjs_ng-0.17.0.1-cp310-abi3-win_amd64.whl'
SHA256 = '355511615baa17bc98092680f068e3536ea1ee5a650b16f59bf6871f497f3780'
MAX_SOURCE = 16384


def lock():
    return {'name':'quickjs-ng','version':'0.17.0.1','platform':'Windows AMD64 CPython 3.10+',
            'sha256':'sha256:'+SHA256,'size_bytes':519389,'license':'MIT','installed_in_host':False}


def asset():
    try:
        path=policy.safe_path(policy.REPOSITORY_ROOT/'third_party/coding'/WHEEL,directory=False)
        raw=path.read_bytes()
        if len(raw)!=519389 or policy.digest(raw)!='sha256:'+SHA256:raise ValueError('digest')
        with zipfile.ZipFile(io.BytesIO(raw)) as z:
            info=z.getinfo('_quickjs.pyd')
            if info.file_size!=989696:raise ValueError('size')
            return z.read(info)
    except (OSError,ValueError,KeyError,zipfile.BadZipFile,policy.CoreError) as exc:
        raise policy.CoreError('coding_js_unavailable','离线 JavaScript 执行器缺失或摘要不符；未安装或联网替换。') from exc


def layout(paths,entry):
    from .project_files import relative
    if not isinstance(paths,list) or len(paths)!=1 or entry!=paths[0]:
        raise policy.CoreError('coding_invalid','场景配方选择一个 .js 文件，入口 transform(data) 返回 JSON 字符串。')
    relative(entry)
    if not entry.endswith('.js') or '\\' in entry or len(entry.split('/'))>4:
        raise policy.CoreError('coding_invalid','JavaScript 场景使用项目内 .js 文件，最多三级目录。')


def validate(sources,entry):
    layout(list(sources),entry)
    if not isinstance(sources[entry],str) or not 1<=len(sources[entry].encode())<=MAX_SOURCE:
        raise policy.CoreError('candidate_invalid','JavaScript 候选大小应为 1—16 KiB。')


HARNESS = r'''
import importlib.util,json
from pathlib import Path
payload=json.loads(Path('input.json').read_text(encoding='utf-8'))
spec=importlib.util.spec_from_file_location('_quickjs','_quickjs.pyd')
engine=importlib.util.module_from_spec(spec);spec.loader.exec_module(engine)
outputs=[]
for item in payload['inputs']:
    context=engine.Context()
    context.set_memory_limit(16*1024*1024)
    context.set_max_stack_size(512*1024)
    context.set_time_limit(.04)
    context.eval('"use strict";\n'+payload['source'])
    argument=context.parse_json(json.dumps(item,ensure_ascii=False))
    result=context.get('transform')(argument)
    if not isinstance(result,str) or len(result.encode())>262144:raise ValueError('output limit')
    if json.loads(argument.json())!=item:raise ValueError('input changed')
    outputs.append(result)
    del context
print(json.dumps({'binding':payload['binding'],'outputs':outputs},ensure_ascii=True))
'''


class Runner:
    def __init__(self,runner=None):
        from .evolution.runner import IsolatedRunner
        self.runner=runner or IsolatedRunner()
    def preflight(self):
        self.runner.preflight();asset()
    def run(self,sources,entry,inputs,checkpoint):
        validate(sources,entry)
        return self.runner._execute({'source':sources[entry],'inputs':inputs},HARNESS,'coding.javascript.v1',
                                    checkpoint,js_engine=asset())
