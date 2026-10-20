"""Opt-in, source-owned sharing with bilateral selection and receiver scope grants."""
import copy
import re
import time
import uuid

from . import federation_protocol as p
from . import federation_sources as source
from .federation_transport import exchange

FORMAT = 'jarvis.scoped-sharing.v1'
MAX_ITEMS = 32


def empty():
    return dict(enabled=False, revision=0, selected={}, grants={}, catalog={},
                inbox={}, seq=0, peer_seq=0, peer_digest=None)


def state(space):
    return space.get('scoped', empty())


def active(space):
    value = state(space)
    if not value['enabled']:
        p.fail('请先在两端启用分域接收控制。', 'federation_scope_disabled')
    return value


def descriptors(rows):
    if not isinstance(rows, dict) or len(rows) > MAX_ITEMS:
        p.fail()
    for item, row in rows.items():
        p.ident(item); p.fields(row, 'domain source_project title')
        if row['domain'] not in ('card', 'personal', 'project'):
            p.fail()
        if row['domain'] == 'project':
            p.ident(row['source_project'])
        elif row['source_project'] is not None:
            p.fail()
        p.text(row['title'], 480)
    return rows


def validate_grants(value):
    p.fields(value, 'revision items')
    p.counter(value['revision'])
    if not isinstance(value['items'], dict) or len(value['items']) > MAX_ITEMS:
        p.fail()
    for item, row in value['items'].items():
        p.ident(item); p.fields(row, 'domain source_project project_id')
        descriptors({item: dict(domain=row['domain'], source_project=row['source_project'], title='grant')})
        if row['domain'] == 'project':
            p.ident(row['project_id'])
        elif row['project_id'] is not None:
            p.fail('个人/普通资料不能映射为项目记忆。', 'federation_scope')
    return value


def bound(row, grant):
    return all(row[k] == grant[k] for k in ('domain', 'source_project'))


def virtual_id(space, item):
    return p.digest([FORMAT, space['id'], space['peer'], item])[:32]


def content_token(row):
    return p.digest({'body':row['signed']['body'],'project_id':row['project_id'],
                     'grant_revision':row['grant_revision'],'admission_seq':row['admission_seq']})


def validate_entry(signed, space):
    b = p.verify(signed, space['members'][space['peer']])
    p.fields(b, 'format space sender item domain source_project title text source_revision model_targets expires_at classification')
    if b['format'] != FORMAT or b['space'] != space['id'] or b['sender'] != space['peer']:
        p.fail()
    descriptors({b['item']: {k:b[k] for k in ('domain', 'source_project', 'title')}})
    p.text(b['text'], 8192); p.text(b['classification'], 80)
    if not isinstance(b['source_revision'], str) or not re.fullmatch('[a-f0-9]{64}', b['source_revision']):
        p.fail()
    if not isinstance(b['model_targets'], dict) or len(b['model_targets']) > 17:
        p.fail()
    for provider, digest in b['model_targets'].items():
        if not re.fullmatch('[a-z][a-z0-9_-]{0,63}', provider) or not isinstance(digest, str) or not re.fullmatch('[a-f0-9]{64}', digest):
            p.fail()
    if b['expires_at'] is not None:
        from .memory_policy import expiry
        try: expiry(b['expires_at'])
        except (ValueError, TypeError): p.fail()
    return b


def received_cards(space):
    result = []
    for item, row in state(space)['inbox'].items():
        b = validate_entry(row['signed'], space)
        expected = content_token(row)
        result.append(dict(id=virtual_id(space, item), expected=expected, deleted=False,
                           conflict=False, project_id=row['project_id'], domain=b['domain'],
                           versions=[dict(author=b['sender'], title=b['title'], text=b['text'])]))
    return result


def received_body(space, item, project_id, provider=None, destination=None):
    for source_id, row in active(space)['inbox'].items():
        if virtual_id(space, source_id) != item:
            continue
        b = validate_entry(row['signed'], space)
        grant = state(space)['grants'].get(source_id)
        if not grant or not bound(b, grant) or row['project_id'] != project_id or grant['project_id'] != project_id:
            p.fail('共享记忆不属于当前个人/项目范围。', 'federation_scope')
        if b['expires_at']:
            from .memory_policy import expiry
            if expiry(b['expires_at']).timestamp() <= time.time():
                p.fail('共享记忆已到期。', 'federation_reference_stale')
        if provider is not None and b['model_targets'].get(provider) != destination:
            p.fail('来源未许可此模型接入方；接收许可不能扩大模型用途。', 'federation_route_denied')
        return dict(title=b['title'], text=f"[来源分类：{b['classification']}；{b['domain']}]\n"+b['text'],
                    expected=content_token(row))
    p.fail('接收资料已撤回或不存在。', 'federation_reference_stale')


class Scoped:
    def __init__(self, service):
        self.service = service

    def options(self, sid, kind='memory', project_id=None):
        space = self.service._space(self.service.store.read(self.service.node), sid)
        value = state(space)
        return dict(enabled=value['enabled'], revision=value['revision'],
                    selected=copy.deepcopy(value['selected']), grants=copy.deepcopy(value['grants']),
                    catalog=copy.deepcopy(value['catalog']), received=received_cards(space),
                    projects=source.projects(self.service.core),
                    sources=source.sources(self.service, space, kind, project_id))

    def configure(self, sid, revision, selected, grants):
        p.counter(revision)
        if not isinstance(selected, list) or len(selected) > MAX_ITEMS:
            p.fail()
        validate_grants({'revision': revision, 'items': grants})
        def update(data):
            space = self.service._space(data, sid)
            old = state(space)
            if old['revision'] != revision:
                p.fail('共享选择或接收许可已变化，请重新读取。', 'federation_conflict')
            choices = {}
            for row in selected:
                p.fields(row, 'kind source source_project expected')
                p.ident(row['source'])
                candidates = source.sources(self.service, space, row['kind'], row['source_project'])
                match = next((v for v in candidates if v['id'] == row['source']), None)
                if not match or match['expected'] != row['expected']:
                    p.fail('来源已变化，请重新选择。', 'federation_conflict')
                domain = 'card' if row['kind'] == 'card' else 'project' if row['source_project'] else 'personal'
                key = p.digest([space['id'], self.service.node, row['kind'], row['source'], row['source_project']])[:32]
                if key in choices: p.fail()
                choices[key] = {**row, 'domain': domain}
            available = {row['id'] for row in source.projects(self.service.core)}
            for item, grant in grants.items():
                offered = old['catalog'].get(item)
                if not offered or not bound(offered, grant):
                    p.fail('接收许可必须来自当前对端目录。', 'federation_scope')
                if grant['project_id'] is not None and grant['project_id'] not in available:
                    p.fail('请映射到本机可用项目。', 'federation_scope')
            new = {**old, 'enabled': True, 'revision': p.counter(revision+1),
                   'selected': choices, 'grants': copy.deepcopy(grants)}
            # Revocation/remapping clears contents immediately, not just the UI.
            new['inbox'] = {item: row for item, row in old['inbox'].items()
                            if item in grants and old['grants'].get(item) == grants[item]}
            space['scoped'] = new
        self.service.store.change(self.service.node, update)
        return {'message': '分域共享设置已保存；未许可正文不会交换，旧整空间同步已停用。'}

    def outgoing(self, space):
        value = active(space); catalog, contents, cache = {}, {}, {}
        for item, selection in value['selected'].items():
            body = source.read(self.service, space, selection, cache)
            if body is None: continue
            descriptor = dict(domain=selection['domain'], source_project=selection['source_project'], title=body['title'])
            catalog[item] = descriptor
            contents[item] = p.sign(dict(format=FORMAT, space=space['id'], sender=self.service.node,
                                        item=item, **descriptor, **{k:v for k,v in body.items() if k!='title'}),
                                    self.service._identity().load().key)
        descriptors(catalog)
        return catalog, contents

    @staticmethod
    def permitted(contents, policy):
        validate_grants(policy)
        return {item: signed for item, signed in contents.items()
                if item in policy['items'] and bound(signed['body'], policy['items'][item])}

    @staticmethod
    def policy(space):
        value = active(space)
        return {'revision':value['revision'], 'items':copy.deepcopy(value['grants'])}

    def apply(self, space, body, expected):
        value = active(space)
        if value['revision'] != expected or body['receiver_revision'] != expected:
            p.fail('接收许可已改变；在途资料未纳入。', 'federation_conflict')
        seq = p.counter(body['seq']); digest = p.digest(body['items'])
        if seq < value['peer_seq'] or (seq == value['peer_seq'] and digest != value['peer_digest']):
            p.fail('对端共享版本倒退或重用，未接收。', 'federation_rollback')
        rows = body['items']
        if not isinstance(rows, dict) or len(rows) > MAX_ITEMS: p.fail()
        inbox = {}
        for item, signed in rows.items():
            b = validate_entry(signed, space)
            grant = value['grants'].get(item)
            if b['item'] != item or not grant or not bound(b, grant):
                p.fail('收到未许可的条目或记忆域。', 'federation_scope')
            if item not in body['catalog'] or not bound(b, body['catalog'][item]):
                p.fail()
            old=value['inbox'].get(item)
            grant_revision=old['grant_revision'] if old and old['project_id']==grant['project_id'] else value['revision']
            admission_seq=old['admission_seq'] if old else seq
            inbox[item] = {'signed': signed, 'project_id':grant['project_id'],
                           'grant_revision':grant_revision,'admission_seq':admission_seq}
        value.update(inbox=inbox, peer_seq=seq, peer_digest=digest, catalog=copy.deepcopy(body['catalog']))

    def receive(self, signed):
        service = self.service; revision = service.online()
        raw = signed.get('body', {}) if isinstance(signed, dict) else {}
        p.fields(raw, 'format space sender target request_id operation catalog receive receiver_revision seq items')
        def update(data):
            service.online(revision)
            space = service._space(data, raw['space']); value = active(space)
            body = p.verify(signed, space['members'][space['peer']])
            self.validate(body, space)
            catalog, contents = self.outgoing(space)
            if body['operation'] == 'transfer':
                self.apply(space, body, value['revision'])
            else:
                if body['items'] or body['receiver_revision'] is not None or body['seq'] != 0: p.fail()
                value['catalog'] = copy.deepcopy(body['catalog'])
            value['seq'] = p.counter(value['seq']+1)
            return dict(format=FORMAT, space=space['id'], sender=service.node, target=space['peer'],
                        request_id=body['request_id'], operation=body['operation'], catalog=catalog,
                        receive=self.policy(space), receiver_revision=body['receive']['revision'],
                        seq=value['seq'], items=self.permitted(contents,body['receive']) if body['operation']=='transfer' else {})
        response = service.store.change(service.node, update)
        return p.sign(response, service._identity().load().key)

    def validate(self, body, space):
        p.fields(body, 'format space sender target request_id operation catalog receive receiver_revision seq items')
        p.ident(body['request_id'])
        if (body['format'] != FORMAT or body['space'] != space['id'] or body['sender'] != space['peer']
                or body['target'] != self.service.node or body['operation'] not in ('catalog', 'transfer')):
            p.fail('分域交换身份或操作不匹配。')
        descriptors(body['catalog']); validate_grants(body['receive'])

    def sync(self, sid, transfer=False):
        service = self.service
        with service.connection.operation():
            revision = service.online()
            # Fresh receiver policy first; never send content based on cached grants.
            response = self.round(sid, 'catalog', revision, None)
            if transfer:
                self.round(sid, 'transfer', revision, response['receive'])
            return {'message': '已按双方许可交换正文；未授权条目未发送。' if transfer else '已交换候选目录；未发送正文。'}

    def round(self, sid, operation, revision, peer_policy):
        service = self.service
        def prepare(data):
            service.online(revision)
            space = service._space(data,sid); value = active(space)
            if space['role'] != 'client': p.fail('请在加入端执行目录交换或同步。')
            catalog, contents = self.outgoing(space)
            value['seq'] = p.counter(value['seq']+1)
            body = dict(format=FORMAT,space=sid,sender=service.node,target=space['peer'],
                        request_id=uuid.uuid4().hex,operation=operation,catalog=catalog,
                        receive=self.policy(space),receiver_revision=peer_policy['revision'] if peer_policy else None,
                        seq=value['seq'] if peer_policy else 0,
                        items=self.permitted(contents,peer_policy) if peer_policy else {})
            return copy.deepcopy(space),body
        space,body=service.store.change(service.node,prepare)
        response=exchange(space['endpoint'],p.fingerprint(space['members'][space['peer']]),'/domains',
                          p.sign(body,service._identity().load().key),lambda:service.online(revision))
        reply=p.verify(response,space['members'][space['peer']]);self.validate(reply,space)
        if reply['request_id']!=body['request_id'] or reply['operation']!=operation: p.fail()
        def commit(data):
            service.online(revision);current=service._space(data,sid);value=active(current)
            if value['revision']!=body['receive']['revision']:p.fail('许可已变化，请重新同步。','federation_conflict')
            if operation=='transfer':self.apply(current,reply,body['receive']['revision'])
            else:
                if reply['items']:p.fail()
                value['catalog']=copy.deepcopy(reply['catalog'])
        service.store.change(service.node,commit)
        return reply
