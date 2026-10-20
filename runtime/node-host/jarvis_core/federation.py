"""Two-node explicitly shared notebook; isolated from memory, tools and task queues."""
import base64
import copy
import hashlib
import hmac
import threading
import time
import uuid
import secrets
import sqlite3

from . import federation_protocol as p
from .federation_identity import Identity
from .federation_store import FederationStore
from .federation_transport import Listener, exchange
from .network_policy import NetworkPolicy
from .federation_lifecycle import Lifecycle, MAX_ARCHIVES
from .policy import CoreError


class Federation:
    def __init__(self, core, config_path=None):
        self.core = core
        self.store = FederationStore(core)
        self.network = NetworkPolicy(core.data_dir)
        self.listener = None
        self.identity = None
        self.lock = threading.RLock()
        self.flight = threading.Lock()
        self.lifecycle = Lifecycle(self)
        from .federation_access import Access
        self.access = Access(self, config_path)
        from .federation_connection import Connection
        self.connection = Connection(self)
        from .federation_scoped import Scoped
        self.scoped = Scoped(self)
        from .federation_tasks import Delegation
        self.delegation = Delegation(self)

    @property
    def node(self):
        return uuid.UUID(self.core.assert_running()['config']['node_id']).hex

    def _identity(self):
        with self.lock:
            if self.identity is None:
                self.identity = Identity(self.core.data_dir, self.node)
            return self.identity

    def online(self, revision=None):
        self.core.assert_running()
        return self.network.require_online(revision)

    def initialize(self):
        with self.core.effect_guard():
            self._identity().load(create=True)
        return self.status()

    def status(self):
        node = self.node
        stored = self.store.read(node)
        spaces = stored['spaces']
        result = []
        for space in spaces.values():
            cards = []
            for item, heads in space['items'].items():
                cards.append({'id': item, 'expected': p.heads_token(heads),
                              'deleted': any(h['body']['deleted'] for h in heads),
                              'conflict': len(heads) > 1, 'versions': [
                                  {k: h['body'][k] for k in ('author', 'title', 'text', 'clock')}
                                  for h in heads]})
            from .federation_scoped import received_cards, state as scoped_state
            result.append({'id': space['id'], 'label': space['label'], 'role': space['role'],
                           'scoped_enabled': scoped_state(space)['enabled'],
                           'scoped_revision': scoped_state(space)['revision'],
                           'scoped_seq': scoped_state(space)['seq'],
                           'received_cards': received_cards(space),
                           'state': space['state'], 'peer': space.get('peer'),
                           'endpoint': space.get('endpoint'), 'cards': cards,
                           'access_revision': space.get('model_access', {}).get('revision', 0),
                           'revisions': len(space['seen']), 'last_sync': space.get('last_sync')})
        identity = self._identity()
        enabled = identity.root.exists()
        if enabled:
            identity.load()  # Corrupt identities are visible; never regenerate them.
        with self.lock:
            endpoint = (f'https://{self.listener.server_address[0]}:{self.listener.server_address[1]}'
                        if self.listener else None)
        return {'initialized': enabled, 'node': node, 'protocol': p.PROTOCOL,
                'fingerprint': p.fingerprint(identity.pem) if enabled else None,
                'endpoint': endpoint, 'offline': self.network.snapshot()['offline'],
                'spaces': result, 'archives': [
                    {'id': sid, **row, 'restored': sid in spaces}
                    for sid, row in stored.get('archives', {}).items()],
                'recovery_required': False,
                'limits': {'spaces': p.MAX_SPACES, 'cards': p.MAX_CARDS,
                           'text_bytes': 4000, 'revisions': p.MAX_SEEN, 'archives': MAX_ARCHIVES}}

    def view(self):
        try:
            return self.status()
        except (CoreError, OSError, ValueError, sqlite3.Error) as exc:
            if isinstance(exc, CoreError) and not exc.code.startswith('federation_'):
                raise
            return {'recovery_required': True, 'spaces': [], 'archives': [],
                    'message': '共享状态无法正常读取。可关闭监听并检查恢复材料；聊天继续使用原有功能。',
                    'listener_open': self.listener is not None}

    def listen(self, address, port):
        if type(port) is not int or not 0 <= port <= 65535:
            p.fail()
        p.endpoint(f'https://{address}:{port or 1}')
        self.online()
        with self.lock:
            if self.listener:
                p.fail('共享监听已启动，请先关闭后再切换地址。')
            identity = self._identity().load()
            self.listener = Listener((address, port), identity, self)
        return self.status()

    def close(self):
        self.connection.clear()
        with self.lock:
            listener, self.listener = self.listener, None
        if listener:
            listener.close()

    def _space(self, state, sid, active=True):
        space = state['spaces'].get(p.ident(sid))
        if not space or (active and space['state'] != 'active'):
            p.fail('此共享空间尚未配对或已撤销。', 'federation_inactive')
        return space

    def invite(self, label):
        label = p.text(label, 160)
        self.online()
        endpoint = self.status()['endpoint']
        if not endpoint:
            p.fail('请先启动共享监听，再创建配对码。')
        identity = self._identity().load()
        sid, token = uuid.uuid4().hex, secrets.token_urlsafe(32)
        invitation = {'protocol': p.PROTOCOL, 'space': sid, 'label': label, 'node': self.node,
                      'endpoint': endpoint, 'certificate': identity.pem, 'token': token}
        def create(state):
            state['spaces'][sid] = {
                'id': sid, 'label': label, 'role': 'host', 'state': 'inviting',
                'endpoint': endpoint, 'members': {self.node: identity.pem}, 'peer': None,
                'seq': 0, 'peer_seq': 0, 'items': {}, 'seen': {},
                'invitation': {'hash': hashlib.sha256(token.encode('ascii')).hexdigest(),
                               'host': self.core.host_instance_id, 'expires': time.monotonic() + 600}}
        self.store.change(self.node, create)
        return {'invitation': base64.urlsafe_b64encode(p.encode(invitation)).decode('ascii'),
                'space': sid, 'expires_seconds': 600}

    def join(self, invitation):
        self.online()
        identity = self._identity().load()
        try:
            if not isinstance(invitation, str) or len(invitation) > 12000:
                p.fail()
            data = p.decode(base64.b64decode(invitation, altchars=b'-_', validate=True))
        except (ValueError, UnicodeError):
            p.fail('配对码无效。')
        p.fields(data, 'protocol space label node endpoint certificate token')
        p.ident(data['space']); p.ident(data['node']); p.text(data['label'], 160)
        p.endpoint(data['endpoint']); p.certificate(data['certificate'])
        if data['protocol'] != p.PROTOCOL or data['node'] == self.node or not isinstance(data['token'], str) or len(data['token']) != 43:
            p.fail('配对协议或设备身份无效。')
        sid = data['space']
        with self.flight:
            def pending(state):
                if sid in state['spaces'] or sid in state.get('archives', {}):
                    p.fail('配对已登记，请使用该空间的重试配对入口。')
                if len(state['spaces']) >= p.MAX_SPACES:
                    p.fail('共享空间容量已满。')
                self._identity().seal_join(sid, data)
                state['spaces'][sid] = {
                    'id': sid, 'label': data['label'], 'role': 'client', 'state': 'pending',
                    'endpoint': data['endpoint'], 'members': {self.node: identity.pem, data['node']: data['certificate']},
                    'peer': data['node'], 'request_id': uuid.uuid4().hex,
                    'seq': 0, 'peer_seq': 0, 'items': {}, 'seen': {}}
            self.store.change(self.node, pending)
            return self._retry(sid)

    def retry(self, sid):
        with self.flight:
            return self._retry(sid)

    def _retry(self, sid):
        revision = self.online()
        space = self._space(self.store.read(self.node), sid, active=False)
        if space['state'] != 'pending':
            p.fail('此空间不处于待确认配对状态。')
        data = self._identity().load_join(sid)
        request = {'protocol': p.PROTOCOL, 'space': sid, 'sender': self.node,
                   'target': space['peer'], 'request_id': space['request_id'],
                   'certificate': self._identity().pem, 'token': data['token']}
        response = exchange(space['endpoint'], p.fingerprint(space['members'][space['peer']]), '/pair',
                            p.sign(request, self._identity().key), lambda: self.online(revision))
        body = p.verify(response, space['members'][space['peer']])
        p.fields(body, 'protocol space sender target request_id paired')
        if body != {'protocol': p.PROTOCOL, 'space': sid, 'sender': space['peer'],
                    'target': self.node, 'request_id': space['request_id'], 'paired': True}:
            p.fail()
        def activate(state):
            self.online(revision)
            current = self._space(state, sid, active=False)
            if current['state'] != 'pending':
                p.fail('配对状态已改变。')
            current['state'] = 'active'
        self.store.change(self.node, activate)
        self._identity().clear_join(sid)
        return self.status()

    def receive(self, route, signed):
        if route == '/tasks':
            return self.delegation.receive(signed)
        if route == '/domains':
            return self.scoped.receive(signed)
        if route == '/inspect':
            return self.connection.receive(signed)
        revision = self.online()
        identity = self._identity().load()
        body = signed.get('body', {}) if isinstance(signed, dict) else {}
        if route == '/pair':
            p.fields(body, 'protocol space sender target request_id certificate token')
            p.ident(body['sender']); p.ident(body['request_id'])
            p.verify(signed, body['certificate'])
            if (body['protocol'] != p.PROTOCOL or body['target'] != self.node or
                    body['sender'] == self.node or not isinstance(body['token'], str) or len(body['token']) != 43):
                p.fail()
            def pair(state):
                self.online(revision)
                space = self._space(state, body['space'], active=False)
                invite = space.get('invitation', {})
                if (space['role'] != 'host' or space['state'] not in {'inviting', 'active'} or
                        invite.get('host') != self.core.host_instance_id or
                        time.monotonic() > invite.get('expires', 0) or not hmac.compare_digest(
                            invite.get('hash', ''), hashlib.sha256(body['token'].encode('utf-8')).hexdigest())):
                    p.fail('配对码无效或已到期。')
                if space['state'] == 'active':
                    if (space['peer'] != body['sender'] or space['members'][body['sender']] != body['certificate']
                            or space['request_id'] != body['request_id']):
                        p.fail('配对码已被使用。')
                else:
                    space.update(state='active', peer=body['sender'], request_id=body['request_id'])
                    space['members'][body['sender']] = body['certificate']
            self.store.change(self.node, pair)
            return p.sign({'protocol': p.PROTOCOL, 'space': body['space'], 'sender': self.node,
                           'target': body['sender'], 'request_id': body['request_id'], 'paired': True}, identity.key)
        if route != '/sync':
            p.fail()
        p.fields(body, 'protocol space sender target request_id snapshot')
        p.ident(body['request_id'])
        def sync(state):
            self.online(revision)
            space = self._space(state, body['space'])
            self._validate_envelope(signed, space)
            p.merge(space, body['snapshot'], self.node)
            space['last_sync'] = time.time()
            return copy.deepcopy(p.snapshot(space, self.node))
        result = self.store.change(self.node, sync)
        return p.sign({'protocol': p.PROTOCOL, 'space': body['space'], 'sender': self.node,
                       'target': body['sender'], 'request_id': body['request_id'], 'snapshot': result}, identity.key)

    def _validate_envelope(self, signed, space):
        if space.get('scoped', {}).get('enabled'):
            p.fail('此空间已启用分域接收控制，请使用分域同步。', 'federation_scope')
        body = p.verify(signed, space['members'][space['peer']])
        p.fields(body, 'protocol space sender target request_id snapshot')
        if (body['protocol'] != p.PROTOCOL or body['space'] != space['id'] or
                body['sender'] != space['peer'] or body['target'] != self.node):
            p.fail('同步身份或空间不匹配。')
        return body

    def sync(self, sid):
        if not self.flight.acquire(blocking=False):
            p.fail('已有配对或同步正在进行。', 'federation_busy')
        try:
            revision = self.online()
            space = self._space(self.store.read(self.node), sid)
            if space.get('scoped', {}).get('enabled'):
                p.fail('此空间已启用分域接收控制，请使用分域同步。', 'federation_scope')
            if space['role'] != 'client':
                p.fail('请在加入此空间的另一台设备点击同步；本机将同时收取和发送变更。')
            identity = self._identity().load()
            rid = uuid.uuid4().hex
            request = {'protocol': p.PROTOCOL, 'space': sid, 'sender': self.node, 'target': space['peer'],
                       'request_id': rid, 'snapshot': p.snapshot(space, self.node)}
            response = exchange(space['endpoint'], p.fingerprint(space['members'][space['peer']]), '/sync',
                                p.sign(request, identity.key), lambda: self.online(revision))
            def apply(state):
                self.online(revision)
                current = self._space(state, sid)
                body = self._validate_envelope(response, current)
                if body['request_id'] != rid:
                    p.fail('同步回复不属于当前请求。')
                p.merge(current, body['snapshot'], self.node)
                current['last_sync'] = time.time()
            self.store.change(self.node, apply)
            return self.status()
        finally:
            self.flight.release()

    def edit(self, sid, item, expected, title, text, deleted=False):
        p.ident(item)
        if type(deleted) is not bool or not isinstance(expected, str):
            p.fail()
        if deleted:
            title = text = ''
        else:
            p.text(title, 240); p.text(text, 4000)
        identity = self._identity().load()
        def update(state):
            space = self._space(state, sid)
            heads = space['items'].get(item, [])
            if p.heads_token(heads) != expected:
                p.fail('资料已改变；请保留草稿，刷新后合并新版本。', 'federation_conflict')
            if any(h['body']['deleted'] for h in heads):
                p.fail('此资料已删除；如需恢复内容，请另建一张卡。')
            if not heads and len(space['items']) >= p.MAX_CARDS:
                p.fail('共享卡容量已满（包括删除记录）。')
            if len(space['seen']) >= p.MAX_SEEN:
                p.fail('共享空间已到修订容量上限。')
            space['seq'] = p.counter(space['seq'] + 1)
            clock = {node: max([h['body']['clock'][node] for h in heads] or [0])
                     for node in space['members']}
            clock[self.node] = space['seq']
            body = {'space': sid, 'item': item, 'author': self.node, 'seq': space['seq'],
                    'clock': clock, 'deleted': deleted, 'title': title, 'text': text}
            space['items'][item] = [p.sign(body, identity.key)]
            space['seen'][self.node + ':' + str(space['seq'])] = p.digest(body)
        self.store.change(self.node, update)
        return self.status()

    def revoke(self, sid):
        def update(state):
            space = self._space(state, sid, active=False)
            space['state'] = 'revoked'
            space.pop('invitation', None)
        self.store.change(self.node, update)
        self._identity().clear_join(sid)
        return self.status()

    def action(self, payload):
        if not isinstance(payload, dict):
            p.fail()
        action = payload.get('action')
        if isinstance(action, str) and action.startswith('task_'):
            schemas = {'task_view':'action space', 'task_continuation':'action space',
                       'task_policy':'action space revision enabled',
                       'task_create':'action space task title text',
                       'task_sync':'action space', 'task_cancel':'action space task',
                       'task_run':'action space task'}
            if action not in schemas: p.fail()
            p.fields(payload, schemas[action])
            sid = payload['space']
            if action == 'task_view': return self.delegation.view(sid)
            if action == 'task_continuation': return self.delegation.continuation(sid)
            if action == 'task_policy': return self.delegation.configure(sid, payload['revision'], payload['enabled'])
            if action == 'task_create': return self.delegation.create(sid, payload['task'], payload['title'], payload['text'])
            if action == 'task_sync': return self.delegation.sync(sid)
            if action == 'task_cancel': return self.delegation.cancel(sid, payload['task'])
            return self.delegation.run(sid, payload['task'])
        schemas = {'initialize': 'action', 'listen': 'action address port', 'close': 'action',
                   'invite': 'action label', 'join': 'action invitation', 'retry': 'action space',
                   'sync': 'action space', 'revoke': 'action space',
                   'edit': 'action space item expected title text deleted',
                   'export': 'action space archived', 'archive_preview': 'action space',
                   'archive': 'action space expected', 'restore_archive': 'action space',
                   'reference': 'action space item expected', 'recovery_preview': 'action',
                   'recover': 'action expected', 'access_options': 'action space',
                   'access_change': 'action space revision cards providers project_id',
                   'reference_issue': 'action space item expected scope',
                   'connection_check': 'action space', 'connection_preview': 'action space endpoint',
                   'connection_apply': 'action space token',
                   'scope_options': 'action space kind project_id',
                   'scope_change': 'action space revision selected grants',
                   'scope_catalog': 'action space', 'scope_sync': 'action space'}
        if action not in schemas:
            p.fail()
        p.fields(payload, schemas[action])
        if action == 'scope_options':
            return self.scoped.options(payload['space'], payload['kind'], payload['project_id'])
        if action == 'scope_change':
            return self.scoped.configure(payload['space'], payload['revision'], payload['selected'], payload['grants'])
        if action in ('scope_catalog', 'scope_sync'):
            return self.scoped.sync(payload['space'], action == 'scope_sync')
        if action == 'connection_check': return self.connection.check(payload['space'])
        if action == 'connection_preview': return self.connection.preview(payload['space'], payload['endpoint'])
        if action == 'connection_apply': return self.connection.apply(payload['space'], payload['token'])
        if action == 'access_options': return self.access.options(payload['space'])
        if action == 'access_change':
            return self.access.change(payload['space'], payload['revision'], payload['cards'], payload['providers'], payload['project_id'])
        if action == 'reference_issue':
            return self.access.issue(payload['space'], payload['item'], payload['expected'], payload['scope'])
        if action == 'export':
            if type(payload['archived']) is not bool: p.fail()
            return self.lifecycle.export(payload['space'], payload['archived'])
        if action == 'archive_preview': return self.lifecycle.preview(payload['space'])
        if action == 'archive': return self.lifecycle.archive(payload['space'], payload['expected'])
        if action == 'restore_archive': return self.lifecycle.restore(payload['space'])
        if action == 'reference': p.fail('共享资料已改为受控引用，请保存草稿后刷新页面。', 'federation_reference_upgrade')
        if action == 'recovery_preview':
            return {k:v for k,v in self.lifecycle.recovery_preview().items() if not k.startswith('_')}
        if action == 'recover': return self.lifecycle.recover(payload['expected'])
        if action == 'initialize': return self.initialize()
        if action == 'listen': return self.listen(payload['address'], payload['port'])
        if action == 'close':
            self.close()
            return self.view()
        if action == 'invite': return self.invite(payload['label'])
        if action == 'join': return self.join(payload['invitation'])
        if action == 'retry': return self.retry(payload['space'])
        if action == 'sync': return self.sync(payload['space'])
        if action == 'revoke': return self.revoke(payload['space'])
        return self.edit(payload['space'], payload['item'], payload['expected'],
                         payload['title'], payload['text'], payload['deleted'])
