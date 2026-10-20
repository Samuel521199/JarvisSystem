"""Read-only peer proof and explicit, identity-preserving address recovery."""
from contextlib import contextmanager
import copy
import threading
import time
import uuid

from . import federation_protocol as p
from .federation_transport import exchange
from .policy import CoreError

PREVIEW_TTL = 120
MAX_PREVIEWS = 8
PROOF = 'jarvis.shared-connection.v1'


def binding(space):
    return p.digest({k: space[k] for k in ('id', 'role', 'state', 'peer', 'members', 'endpoint')})


class Connection:
    def __init__(self, service):
        self.service = service
        self.previews = {}
        self.lock = threading.RLock()

    def clear(self):
        with self.lock:
            self.previews.clear()

    @contextmanager
    def operation(self):
        if not self.service.flight.acquire(blocking=False):
            p.fail('已有配对、同步或连接检查正在进行。', 'federation_busy')
        try:
            yield
        finally:
            self.service.flight.release()

    def space(self, sid):
        service = self.service
        space = service._space(service.store.read(service.node), sid)
        if space['role'] != 'client':
            p.fail('请在加入端检查或更新对端地址；共享端只需重新打开本机监听。', 'federation_connection_role')
        return space

    def receive(self, signed):
        service = self.service
        revision = service.online()
        body = signed.get('body', {}) if isinstance(signed, dict) else {}
        p.fields(body, 'protocol kind space sender target request_id')
        p.ident(body['request_id'])
        space = service._space(service.store.read(service.node), body['space'])
        p.verify(signed, space['members'][space['peer']])
        if (body['protocol'] != p.PROTOCOL or body['kind'] != PROOF or
                body['sender'] != space['peer'] or body['target'] != service.node or space['role'] != 'host'):
            p.fail('设备连接证明与原配对不匹配。', 'federation_connection_proof')
        identity = service._identity().load()
        service.online(revision)
        # No snapshots, contents, sync counters or invitations in the proof.
        return p.sign({'protocol': p.PROTOCOL, 'kind': PROOF, 'space': space['id'],
                       'sender': service.node, 'target': space['peer'],
                       'request_id': body['request_id'], 'paired': True}, identity.key)

    def probe(self, space, endpoint, revision):
        service = self.service
        host, port = p.endpoint(endpoint)
        endpoint = f'https://{host}:{port}'
        identity = service._identity().load()
        rid = uuid.uuid4().hex
        request = {'protocol': p.PROTOCOL, 'kind': PROOF, 'space': space['id'],
                   'sender': service.node, 'target': space['peer'], 'request_id': rid}
        start = time.perf_counter()
        response = exchange(endpoint, p.fingerprint(space['members'][space['peer']]), '/inspect',
                            p.sign(request, identity.key), lambda: service.online(revision))
        result = p.verify(response, space['members'][space['peer']])
        expected = {'protocol': p.PROTOCOL, 'kind': PROOF, 'space': space['id'],
                    'sender': space['peer'], 'target': service.node, 'request_id': rid, 'paired': True}
        if result != expected:
            p.fail('设备连接证明已过期或不属于当前空间。', 'federation_connection_proof')
        return {'endpoint': endpoint, 'peer': space['peer'],
                'fingerprint': p.fingerprint(space['members'][space['peer']]),
                'latency_ms': round((time.perf_counter()-start)*1000, 2),
                'identity_verified': True}

    def check(self, sid):
        with self.operation():
            space = self.space(sid)
            try:
                revision = self.service.online()
                result = self.probe(space, space['endpoint'], revision)
                if binding(self.space(sid)) != binding(space):
                    p.fail('检查期间本机连接状态已变化，请刷新。', 'federation_connection_stale')
                return {**result, 'reachable': True, 'message': '原配对设备可达；只检查连接，未同步资料。'}
            except CoreError as exc:
                advice = {
                    'federation_unreachable': '请确认另一台设备已启动共享监听、网络可达；地址变化时使用下方恢复入口。',
                    'federation_pin': '目标证书不是原配对证书。请检查地址；不会自动信任新设备。',
                    'federation_peer_rejected': '对端未接受连接证明，可能是旧版本或空间已撤销；请先核对对端状态。',
                }.get(exc.code, str(exc))
                return {'endpoint': space['endpoint'], 'reachable': False,
                        'identity_verified': False, 'code': exc.code, 'message': advice}

    def preview(self, sid, endpoint):
        p.endpoint(endpoint)  # Reject non-private destinations before any socket operation.
        with self.operation():
            service = self.service
            revision = service.online()
            space = self.space(sid)
            result = self.probe(space, endpoint, revision)
            if binding(self.space(sid)) != binding(space):
                p.fail('检查期间连接状态已变化，请重新检查。', 'federation_connection_stale')
            service.online(revision)
            token = uuid.uuid4().hex
            with self.lock:
                self.previews = {key: row for key, row in self.previews.items()
                                 if row['expires'] > time.monotonic() and row['space'] != sid}
                if len(self.previews) >= MAX_PREVIEWS:
                    p.fail('连接预览已满，请等待旧预览到期。', 'federation_busy')
                self.previews[token] = {'space': sid, 'expected': binding(space),
                                       'endpoint': result['endpoint'], 'network_revision': revision,
                                       'expires': time.monotonic()+PREVIEW_TTL, 'receipt': None}
            return {**result, 'token': token, 'old_endpoint': space['endpoint'],
                    'expires_seconds': PREVIEW_TTL, 'space': sid,
                    'effect': '只更新原配对的连接地址；保留资料、冲突、删除记录和模型用途。不会自动同步。'}

    def apply(self, sid, token):
        p.ident(token)
        with self.operation():
            service = self.service
            with self.lock:
                saved = self.previews.get(token)
                if not saved or saved['space'] != sid or saved['expires'] <= time.monotonic():
                    p.fail('连接预览已到期或不属于当前宿主，请重新检查地址。', 'federation_connection_stale')
                row = copy.deepcopy(saved)
            service.online(row['network_revision'])
            current = self.space(sid)
            if row['receipt']:
                if binding(current) != row['receipt']['binding']:
                    p.fail('连接在确认后已变化，请刷新检查。', 'federation_connection_stale')
                return {k: v for k, v in row['receipt'].items() if k != 'binding'}
            if binding(current) != row['expected']:
                p.fail('原连接已变化，旧预览未应用。', 'federation_connection_stale')
            proof = self.probe(current, row['endpoint'], row['network_revision'])

            def update(state):
                service.online(row['network_revision'])
                with self.lock:
                    saved = self.previews.get(token)
                    if not saved or saved['expires'] <= time.monotonic():
                        p.fail('检查期间连接预览失效，地址未更新。', 'federation_connection_stale')
                space = service._space(state, sid)
                if binding(space) != row['expected']:
                    p.fail('确认期间原连接已变化，未覆盖。', 'federation_connection_stale')
                space['endpoint'] = row['endpoint']
                return binding(space)
            new_binding = service.store.change(service.node, update)
            receipt = {**proof, 'space': sid, 'binding': new_binding, 'changed': current['endpoint'] != row['endpoint'],
                       'message': '已保存原设备的新地址；资料未同步，可点击立即双向同步。'}
            with self.lock:
                if token in self.previews:
                    self.previews[token]['receipt'] = receipt
            return {k: v for k, v in receipt.items() if k != 'binding'}
