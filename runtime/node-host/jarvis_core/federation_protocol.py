"""Bounded two-node shared cards. No commands, model context or task ownership."""
import base64
import hashlib
import ipaddress
import json
import re
from urllib.parse import urlsplit

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec

from .policy import CoreError, canonical_json

PROTOCOL = 'jarvis.shared-cards.v1'
MAX_WIRE = 512 * 1024
MAX_CARDS = 32
MAX_SPACES = 8
MAX_SEEN = 4096


def fail(message='共享资料格式无效。', code='federation_invalid'):
    raise CoreError(code, message)


def fields(value, names):
    if not isinstance(value, dict) or set(value) != set(names.split()):
        fail()


def ident(value):
    if not isinstance(value, str) or not re.fullmatch(r'[a-f0-9]{32}', value):
        fail()
    return value


def text(value, limit):
    if not isinstance(value, str) or not value.strip() or len(value.encode('utf-8')) > limit:
        fail('名称或正文为空，或超过长度限制。')
    return value


def counter(value):
    if type(value) is not int or not 0 <= value <= 2**53-1:
        fail()
    return value


def encode(value):
    return canonical_json(value).encode('utf-8')


def decode(raw):
    if len(raw) > MAX_WIRE:
        fail('共享资料超过单次传输上限。')
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                fail()
            result[key] = value
        return result
    try:
        return json.loads(raw, object_pairs_hook=pairs,
                          parse_constant=lambda _: fail())
    except (ValueError, UnicodeError, RecursionError):
        fail()


def digest(value):
    return hashlib.sha256(encode(value)).hexdigest()


def endpoint(value):
    try:
        url = urlsplit(value)
        address = ipaddress.IPv4Address(url.hostname)
        private = any(address in ipaddress.ip_network(net) for net in
                      ('10.0.0.0/8', '172.16.0.0/12', '192.168.0.0/16', '127.0.0.0/8'))
        if (url.scheme != 'https' or not private or not url.port or url.username or
                url.password or url.path or url.query or url.fragment):
            fail()
        return str(address), url.port
    except (ValueError, TypeError):
        fail('仅支持明确的本机或局域网 IPv4 HTTPS 地址与端口。')


def certificate(pem):
    try:
        if not isinstance(pem, str) or len(pem) > 4096:
            fail()
        cert = x509.load_pem_x509_certificate(pem.encode('ascii'))
        key = cert.public_key()
        if not isinstance(key, ec.EllipticCurvePublicKey) or not isinstance(key.curve, ec.SECP256R1):
            fail()
        return cert
    except (ValueError, UnicodeError):
        fail('设备证书无效。')


def fingerprint(pem):
    return certificate(pem).fingerprint(hashes.SHA256()).hex()


def sign(value, key):
    return {'body': value, 'signature': base64.b64encode(
        key.sign(encode(value), ec.ECDSA(hashes.SHA256()))).decode('ascii')}


def verify(signed, pem):
    fields(signed, 'body signature')
    try:
        certificate(pem).public_key().verify(
            base64.b64decode(signed['signature'], validate=True), encode(signed['body']),
            ec.ECDSA(hashes.SHA256()))
    except Exception:
        fail('设备签名不匹配。', 'federation_signature')
    return signed['body']


def revision(signed, space):
    body = signed.get('body', {}) if isinstance(signed, dict) else {}
    fields(body, 'space item author seq clock deleted title text')
    ident(body['item'])
    if body['space'] != space['id'] or body['author'] not in space['members']:
        fail('资料不属于这个共享空间。')
    verify(signed, space['members'][body['author']])
    clock = body['clock']
    if not isinstance(clock, dict) or set(clock) != set(space['members']):
        fail()
    for value in clock.values():
        counter(value)
    if counter(body['seq']) < 1 or clock[body['author']] != body['seq']:
        fail()
    if type(body['deleted']) is not bool:
        fail()
    if body['deleted']:
        if body['title'] or body['text']:
            fail('删除记录不能携带正文。')
    else:
        text(body['title'], 240)
        text(body['text'], 4000)
    return body


def dominates(a, b):
    return all(a[k] >= b[k] for k in b) and any(a[k] > b[k] for k in b)


def merge(space, snapshot, local_id):
    """Mutates a transaction-local copy; validate every revision before persistence."""
    fields(snapshot, 'space sender seq items')
    peer = space['peer']
    if snapshot['space'] != space['id'] or snapshot['sender'] != peer:
        fail('共享空间或发送设备不匹配。')
    high = counter(snapshot['seq'])
    if high < space['peer_seq']:
        fail('检测到另一设备版本倒退；停止同步，请保留两端资料并检查恢复来源。',
             'federation_rollback')
    incoming = snapshot['items']
    if not isinstance(incoming, dict) or len(incoming) > MAX_CARDS:
        fail('每个共享空间最多保存 32 张卡（含删除记录）。')
    if len(set(space['items']) | set(incoming)) > MAX_CARDS:
        fail('两端合并后超过 32 张卡，未写入本次变更。')
    for item, heads in incoming.items():
        ident(item)
        if not isinstance(heads, list) or not 1 <= len(heads) <= 2:
            fail()
        for signed in heads:
            body = revision(signed, space)
            if body['item'] != item or body['clock'][peer] > high or body['clock'][local_id] > space['seq']:
                fail('版本号超出设备已知范围。', 'federation_rollback')
            seen_key = body['author'] + ':' + str(body['seq'])
            previous = space['seen'].get(seen_key)
            value = digest(body)
            if previous and previous != value:
                fail('检测到同一设备重复使用版本号；本次同步已停止。', 'federation_rollback')
            if body['author'] == local_id and previous != value:
                fail('收到本机没有登记过的修订。', 'federation_rollback')
            space['seen'][seen_key] = value
        combined = {digest(h['body']): h for h in space['items'].get(item, []) + heads}
        deletes = [h for h in combined.values() if h['body']['deleted']]
        if deletes:
            # Permanent delete-wins object ID; no old text survives in live state.
            space['items'][item] = [min(deletes, key=lambda h: digest(h['body']))]
        else:
            maximal = [h for h in combined.values() if not any(
                dominates(other['body']['clock'], h['body']['clock'])
                for other in combined.values())]
            if len(maximal) > 2:
                fail('修订分支超出双节点协议范围。')
            space['items'][item] = sorted(maximal, key=lambda h: digest(h['body']))
    if len(space['seen']) > MAX_SEEN:
        fail('此空间已到修订容量上限，请建立新的共享空间。')
    space['peer_seq'] = high


def snapshot(space, node):
    return {'space': space['id'], 'sender': node, 'seq': space['seq'], 'items': space['items']}


def heads_token(heads):
    return digest(sorted(digest(h['body']) for h in heads))
