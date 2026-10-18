"""Bounded, read-only view of the shipped seed. Never an execution authority.

Only the four pinned seed files are read. No document traversal, credential
access, dynamic imports, extension launch or model calls. The manifest digest
must be reviewed when updating a seed release; it is not an OS trust boundary.
"""
import json
from pathlib import Path

from . import __version__, policy

MANIFEST = 'seed/system-manifest/seed-bundle.json'
MANIFEST_DIGEST = 'sha256:45a267b0ddf8068390049fd29b8e81ec0d2e466cc7780a2194285906d7c85bd7'
ASSETS = ('seed/knowledge/bootstrap.json', 'seed/rules/baseline.json', 'seed/skills/catalog.json')
MAX_FILE_BYTES = 65536


def _read(path):
    path = policy.safe_path(path, directory=False)
    if path.stat().st_nlink != 1:
        raise ValueError('Linked seed')
    with path.open('rb') as stream:
        raw = stream.read(MAX_FILE_BYTES + 1)
    if len(raw) > MAX_FILE_BYTES:
        raise ValueError('Oversized seed')
    return raw


class RuntimeCatalog:
    def __init__(self, core, *, root=None):
        self.core = core
        self.root = Path(root) if root is not None else policy.REPOSITORY_ROOT

    def snapshot(self):
        result = dict(version=__version__, status='unavailable', seed_version=None,
                      source=MANIFEST, digest=None, knowledge=[], rules=[], capabilities=[], skills=[],
                      chat_callable=False, rules_enforced_by='host_policy', privacy='local_only',
                      message='种子不可用或校验失败；未保留旧内容，不影响独立聊天和现有执行器。')
        try:
            raw = _read(self.root / MANIFEST)
            if policy.digest(raw) != MANIFEST_DIGEST:
                raise ValueError('Unapproved manifest')
            manifest = json.loads(raw)
            digests = {item['path']: item['sha256'] for item in manifest['assets']}
            loaded = []
            for name in ASSETS:
                content = _read(self.root / name)
                if policy.digest(content) != digests[name]:
                    raise ValueError('Seed drift')
                loaded.append(json.loads(content))
            knowledge, rules, catalog = loaded
            # The host's current boundary wins over historical seed declarations.
            try:
                self.core.assert_running()
                running = True
            except Exception:
                running = False
            bindings = {
                'system.status.v1': ('available', '本机状态入口；聊天尚无工具调用。'),
                'filesystem.read_sample.v1': ('conditional', '固定目录任务入口；执行前检查 Worker、根目录与授权。'),
                'artifact.write.v1': ('internal', '仅由宿主任务提交已核验产物，不开放任意写入。'),
            }
            capabilities = []
            for item in catalog['capabilities']:
                ident = item['capability_id']
                status, reason = bindings.get(ident, ('planned', '尚未实现执行器。'))
                if item['status'] != 'available' or ident not in policy.CAPABILITIES:
                    status, reason = 'planned', '种子或当前宿主未开放此能力。'
                elif not running:
                    status, reason = 'unavailable', '核心当前未就绪；本次观察不修改停止状态。'
                capabilities.append(dict(id=ident, version=item['version'], declared_status=item['status'],
                    status=status, description=item['description'], reason=reason, chat_callable=False,
                    source=ASSETS[2], digest=digests[ASSETS[2]]))
            states = {item['id']: item['status'] for item in capabilities}
            skills = []
            order = ('planned', 'unavailable', 'conditional', 'internal', 'available')
            for item in catalog['skills']:
                refs = item['capability_refs']
                status = next(s for s in order if s in [states.get(r, 'planned') for r in refs])
                if item['status'] != 'available':
                    status = 'planned'
                skills.append(dict(id=item['skill_id'], version=item['version'], status=status,
                    description=item['description'], capability_refs=refs, chat_callable=False))
            return {**result, 'status': 'ready', 'seed_version': manifest['version'],
                    'digest': MANIFEST_DIGEST, 'knowledge': knowledge['records'],
                    'rules': rules['rules'], 'rules_scope': rules['scope'],
                    'capabilities': capabilities, 'skills': skills,
                    'message': '已校验发布种子，仅作来源查询与能力说明；规则实际执行以宿主为准。'}
        except (OSError, ValueError, KeyError, TypeError, policy.CoreError):
            return result

    def chat_summary(self):
        # Do not export local-only seed prose, rules, file paths or registrations.
        state = self.snapshot()['status']
        return f'Seed catalog: {state}. Settings has bounded tool growth; Host upgrades/federation planned. '
