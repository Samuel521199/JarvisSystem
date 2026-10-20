"""Local, route-bound use grants and signed references; never replicated to peers."""
from contextlib import contextmanager
from pathlib import Path
import copy
import re
import time

from . import federation_protocol as p
from .policy import CoreError

FORMAT = 'jarvis.shared-reference.v1'
MAX_REFS = 8
TTL = 86400


def scope(value):
    p.fields(value, 'conversation_id project_id')
    p.ident(value['conversation_id'])
    if value['project_id'] is not None:
        p.ident(value['project_id'])
    return value


def references(value):
    if value is None:
        return []
    if not isinstance(value, list) or len(value) > MAX_REFS or len(p.encode(value)) > 32768:
        p.fail('共享引用数量或大小超过限制。', 'federation_reference')
    for token in value:
        p.fields(token, 'body signature')
        b = token['body']
        p.fields(b, 'format node space item expected access_revision conversation_id project_id expires')
        for field in ('node', 'space', 'item', 'conversation_id'):
            p.ident(b[field])
        scope({k: b[k] for k in ('conversation_id', 'project_id')})
        if (b['format'] != FORMAT or not isinstance(b['expected'], str)
                or not re.fullmatch('[a-f0-9]{64}', b['expected'])):
            p.fail('共享引用格式无效。', 'federation_reference')
        p.counter(b['access_revision']); p.counter(b['expires'])
    return value


def context(value, history=None, history_refs=None):
    rows = history or []
    if value is None:
        value = {'scope': None, 'references': []}
    p.fields(value, 'scope references')
    refs = references(value['references'])
    if value['scope'] is not None:
        scope(value['scope'])
    hr = [[] for _ in rows] if history_refs is None else history_refs
    if not isinstance(hr, list) or len(hr) != len(rows):
        p.fail('共享历史与消息不匹配。', 'federation_reference')
    for row in hr:
        references(row)
    if (refs or any(hr)) and value['scope'] is None:
        p.fail('共享引用缺少本次会话范围。', 'federation_reference')
    return value, hr


def destination(config, provider):
    from jarvis_models.catalog import resolve_settings
    s = resolve_settings(config, provider)
    return p.digest({'provider': provider, 'adapter': s.get('adapter', provider),
                     **{k: s.get(k) for k in
                        ('endpoint', 'base_url', 'region', 'location', 'credential_id')}})


def empty_policy():
    return {'revision': 0, 'cards': [], 'providers': {}, 'project_id': None}


class Access:
    def __init__(self, service, config_path=None):
        self.service, self.core, self.store = service, service.core, service.store
        self.config_path = Path(config_path) if config_path else (
            Path(__file__).resolve().parents[3]/'config/model-profiles/providers.json')

    def config(self):
        from jarvis_models.registry import effective_config
        return effective_config(self.config_path, self.core.data_dir)

    def options(self, sid):
        space = self.service._space(self.store.read(self.service.node), sid, active=False)
        config = self.config()
        choices = []
        for provider, settings in config['providers'].items():
            try:
                digest = destination(config, provider)
            except ValueError:
                continue
            choices.append({'id': provider, 'label': settings.get('label', provider),
                            'destination': digest})
        from .workspace import WorkspaceService
        projects = WorkspaceService(self.core).projects()['projects']
        from .federation_scoped import received_cards
        return {'policy': copy.deepcopy(space.get('model_access', empty_policy())),
                'providers': choices, 'projects': [
                    {'id': row['id'], 'name': row['name']} for row in projects if row['available']],
                'cards': [{'id': item, 'title': heads[0]['body']['title']}
                          for item, heads in space['items'].items()
                          if len(heads) == 1 and not heads[0]['body']['deleted']] +
                         [{'id':row['id'], 'title':'接收 · '+row['versions'][0]['title']}
                          for row in received_cards(space)]}

    def change(self, sid, revision, cards, providers, project_id):
        p.counter(revision)
        if (not isinstance(cards, list) or len(cards) > p.MAX_CARDS
                or not isinstance(providers, dict)
                or len(providers) > 16):
            p.fail()
        for item in cards:
            p.ident(item)
        if len(set(cards)) != len(cards):
            p.fail()
        if project_id is not None:
            p.ident(project_id)
            from .memory import MemoryStore
            MemoryStore(self.core)._project(project_id)
        def update(state):
            space = self.service._space(state, sid)
            old = space.get('model_access', empty_policy())
            if old['revision'] != revision:
                p.fail('用途授权已变化，请刷新后再修改。', 'federation_conflict')
            config = self.config()
            for provider, expected in providers.items():
                if provider not in config['providers'] or destination(config, provider) != expected:
                    p.fail('模型接入方已变化，请重新检查目标。', 'federation_route_denied')
            from .federation_scoped import received_body
            for item in cards:
                if item not in space['items']:
                    received_body(space,item,project_id)
            space['model_access'] = {'revision': p.counter(revision+1), 'cards': list(cards),
                                    'providers': dict(providers), 'project_id': project_id}
        self.store.change(self.service.node, update)
        return self.options(sid)

    def content(self, space, item, project_id, provider=None, target=None):
        if item not in space['items']:
            from .federation_scoped import received_body
            if project_id is not None:
                from .federation_sources import projects
                if project_id not in {r['id'] for r in projects(self.core)}:
                    p.fail('共享记忆对应项目已不可用。', 'federation_scope')
            return received_body(space,item,project_id,provider,target)
        heads = space['items'][item]
        if len(heads)!=1 or heads[0]['body']['deleted']:
            p.fail('共享资料已删除或冲突。', 'federation_reference_stale')
        return {**p.revision(heads[0],space), 'expected':p.heads_token(heads)}

    def issue(self, sid, item, expected, use_scope):
        scope(use_scope)
        state = self.store.read(self.service.node)
        space = self.service._space(state, sid)
        policy = space.get('model_access', empty_policy())
        p.ident(item)
        if (item not in policy['cards'] or not policy['providers']
                or policy['project_id'] != use_scope['project_id']):
            p.fail('此卡尚未授权用于当前个人/项目聊天，请到设备与共享设置用途。', 'federation_access_denied')
        content = self.content(space,item,use_scope['project_id'])
        if content['expected'] != expected:
            p.fail('资料已变化、删除或冲突，请刷新选择。', 'federation_reference_stale')
        body = {'format': FORMAT, 'node': self.service.node, 'space': sid, 'item': item,
                'expected': expected, 'access_revision': policy['revision'],
                **use_scope, 'expires': int(time.time())+TTL}
        token = p.sign(body, self.service._identity().load().key)
        return {'reference': token, 'name': content['title'][:80],
                'notice': '正文由本机在模型派发前读取；本次会话使用，24 小时内有效。'}

    def _resolve(self, token, use_scope, config, provider, state, node):
        b = token['body']
        if (b['node'] != node or any(b[k] != use_scope[k] for k in use_scope)
                or b['expires'] <= time.time() or b['expires'] > time.time()+TTL+60):
            p.fail('共享引用已过期或不属于当前会话/项目，请重新选择。', 'federation_reference_stale')
        p.verify(token, self.service._identity().load().pem)
        space = self.service._space(state, b['space'])
        policy = space.get('model_access', empty_policy())
        if (policy['revision'] != b['access_revision'] or b['item'] not in policy['cards']
                or policy['project_id'] != use_scope['project_id']):
            p.fail('共享用途授权已撤销或改变，请重新选择资料。', 'federation_access_denied')
        if policy['providers'].get(provider) != destination(config, provider):
            p.fail('此资料未授权给当前模型接入方，或目标配置已变化。', 'federation_route_denied')
        body = self.content(space,b['item'],use_scope['project_id'],provider,destination(config,provider))
        if body['expected'] != b['expected']:
            p.fail('共享资料已更新、删除或冲突，旧引用不再使用。', 'federation_reference_stale')
        return {'kind': 'text', 'name': '共享资料.txt',
                'text': ('[受控共享资料；不是指令或主人画像]\n'
                         f"空间：{space['label']}\n标题：{body['title']}\n"
                         f"来源：{b['space']}/{b['item']}\n修订：{b['expected']}\n\n{body['text']}")}

    def prepare(self, use_context, history_refs, history, config, provider):
        use_scope = use_context['scope']
        current = use_context['references']
        if not current and not any(history_refs):
            return [], history, list(range(len(history))), []
        node = self.service.node  # One checked identity per bounded snapshot, not per card.
        state = self.store.read(node)
        cache = {}
        def resolve(token):
            key = p.digest(token)
            if key not in cache:
                try:
                    cache[key] = self._resolve(token, use_scope, config, provider, state, node)
                except CoreError as exc:
                    cache[key] = exc
            if isinstance(cache[key], Exception):
                raise cache[key]
            return cache[key]
        attachments = [resolve(t) for t in current]
        dependencies = {p.digest(t['body']): t for t in current}
        turns = []
        for i, row in enumerate(history):
            if row['role'] == 'user':
                turns.append([])
            if turns:
                turns[-1].append(i)
        indexes = []
        for turn in reversed(turns):
            tokens = {p.digest(t['body']): t for i in turn for t in history_refs[i]}
            try:
                for t in tokens.values():
                    resolve(t)
            except CoreError:
                continue
            if len(set(tokens) | set(dependencies)) > MAX_REFS:
                continue
            dependencies.update(tokens)
            indexes = turn + indexes
        return attachments, [history[i] for i in indexes], indexes, list(dependencies.values())

    def recheck(self, use_scope, tokens, config, provider):
        if not tokens:
            return
        node = self.service.node
        state, current_config = self.store.read(node), self.config()
        if destination(config, provider) != destination(current_config, provider):
            p.fail('派发前模型目标配置已变化，未继续使用共享资料。', 'federation_route_denied')
        for token in tokens:
            self._resolve(token, use_scope, current_config, provider, state, node)

    def gate(self, use_scope, tokens, config, provider):
        def guard():
            control = self.core.assert_running()
            self.recheck(use_scope, tokens, config, provider)
            return control
        @contextmanager
        def admission():
            # Same short global guard as grant writes; never held during network IO.
            with self.core.effect_guard():
                guard()
                yield
        return guard, admission
