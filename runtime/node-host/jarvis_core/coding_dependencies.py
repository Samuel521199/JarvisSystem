"""Pinned, optional build assets. No installer, host imports, or network fallback."""
import io
import zipfile

from . import policy

RECIPE = 'python-jmespath-v1'
WHEEL = 'jmespath-1.1.0-py3-none-any.whl'
SHA256 = 'sha256:a5663118de4908c91729bea0acadca56526eb2698e83de10cd116ae0f4e97c64'
ASSET = policy.REPOSITORY_ROOT / 'third_party' / 'coding' / WHEEL
IMPORTS = {'jmespath': {'search'}, 'json': {'dumps'}}
LOCK = {'name': 'jmespath', 'version': '1.1.0', 'license': 'MIT',
        'wheel': WHEEL, 'sha256': SHA256, 'size_bytes': 20419, 'requires': [],
        'source': 'https://pypi.org/project/jmespath/1.1.0/',
        'exports': {'jmespath': ['search'], 'json': ['dumps']}}


def members():
    """Read only this reviewed wheel, bounded and hashed before ZIP parsing."""
    try:
        path = policy.safe_path(ASSET, directory=False)
        with path.open('rb') as stream:
            raw = stream.read(20420)
    except (OSError, policy.CoreError) as exc:
        raise policy.CoreError('missing_offline_dependency',
            '缺少已锁定的 JMESPath 离线依赖；请修复开发包。未下载、安装或调用模型。') from exc
    if len(raw) != 20419 or policy.digest(raw) != SHA256:
        raise policy.CoreError('coding_dependency_invalid', '离线依赖与锁定摘要不符；未运行或替换依赖。')
    # The complete wheel is pinned; copy library + attribution only, never scripts.
    with zipfile.ZipFile(io.BytesIO(raw)) as archive:
        selected = [n for n in archive.namelist() if n.startswith('jmespath/')
                    or n in {'jmespath-1.1.0.dist-info/LICENSE', 'jmespath-1.1.0.dist-info/METADATA'}]
        return {'_vendor/' + n: archive.read(n).decode('utf-8') for n in selected}


def lock():
    # Return a fresh JSON value so callers cannot mutate the trusted catalog.
    import json
    return json.loads(policy.canonical_json(LOCK))
