"""Explicit one-owner/one-executor tasks. No failover or replay on uncertainty.

The first executor is deliberately pure: it summarizes explicitly supplied text.
It cannot read files, invoke models, run shell commands or modify personal memory.
"""
import copy
import re
import time
import uuid

from . import federation_protocol as p
from .federation_transport import exchange

FORMAT = 'jarvis.delegation.v1'
CAPABILITY = 'text.inventory.v1'
TERMINAL = {'SUCCEEDED', 'CANCELLED', 'UNKNOWN', 'FAILED'}
LIMIT = 32


def state(space):
    return space.get('delegation', {'enabled': False, 'revision': 0, 'tasks': {}})


def report(text):
    """A portable, independently reproducible result, with no external effects."""
    lines = text.splitlines()
    words = re.findall(r'[^\W_]+', text, re.UNICODE)
    return {'characters': len(text), 'lines': len(lines),
            'nonempty_lines': sum(bool(x.strip()) for x in lines),
            'words': len(words), 'utf8_bytes': len(text.encode()),
            'source_digest': p.digest(text)}


def validate_spec(spec):
    p.fields(spec, 'id owner executor generation capability title text scope')
    for key in ('id', 'owner', 'executor'):
        p.ident(spec[key])
    if spec['generation'] != 1 or type(spec['generation']) is not int or spec['capability'] != CAPABILITY:
        p.fail('此执行器只接收第一代文本清单任务。', 'federation_task_contract')
    p.text(spec['title'], 240); p.text(spec['text'], 16000)
    if spec['scope'] != 'explicit_input':
        p.fail('仅传输明确填写的任务资料，不自动读取个人或项目记忆。')


class Delegation:
    def __init__(self, service):
        self.service = service

    def view(self, sid):
        s = self.service._space(self.service.store.read(self.service.node), sid, active=False)
        value = copy.deepcopy(state(s))
        for row in value['tasks'].values():
            if row['state'] == 'RUNNING' and row.get('host') != self.service.core.host_instance_id:
                row['state'] = 'UNKNOWN'
                row['message'] = '原执行进程已中断，只能核对结果，不能自动重新执行。'
        value.update(role=s['role'], active=s['state'] == 'active', node=self.service.node,
                     capability=CAPABILITY, limit=LIMIT, automatic_failover=False)
        return value

    def configure(self, sid, revision, enabled):
        if type(enabled) is not bool: p.fail()
        def update(data):
            s = self.service._space(data, sid)
            v = s.setdefault('delegation', state(s))
            if revision != v['revision'] or type(revision) is not int:
                p.fail('任务许可已改变，请刷新。', 'federation_conflict')
            v.update(enabled=enabled, revision=v['revision'] + 1)
            if not enabled:
                for row in v['tasks'].values():
                    if row['spec']['executor'] == self.service.node and row['state'] not in TERMINAL:
                        row.update(state='CANCELLED', result=None, version=row['version']+1)
        self.service.store.change(self.service.node, update)
        return self.view(sid)

    def create(self, sid, task_id, title, text):
        p.ident(task_id)
        def update(data):
            s = self.service._space(data, sid); v = state(s)
            if s['role'] != 'client' or not v['enabled']:
                p.fail('请先启用任务委派，并从加入端提交。', 'federation_task_disabled')
            spec = dict(id=task_id, owner=self.service.node, executor=s['peer'], generation=1,
                        capability=CAPABILITY, title=title, text=text, scope='explicit_input')
            validate_spec(spec)
            old = v['tasks'].get(task_id)
            if old:
                if old['spec'] != spec: p.fail('原任务编号不能用于新内容。', 'federation_conflict')
                return
            if len(v['tasks']) >= LIMIT: p.fail('任务回执容量已满；保留未知和终态记录，不自动删除。')
            v['tasks'][task_id] = dict(spec=spec, state='OFFERED', command=1, cancel=False,
                                      version=0, result=None, last_contact=None)
        self.service.store.change(self.service.node, update)
        return self.view(sid)

    def cancel(self, sid, task_id):
        def update(data):
            s = self.service._space(data, sid, active=False)
            row = state(s)['tasks'].get(p.ident(task_id))
            if not row: p.fail()
            if row['state'] in TERMINAL: return
            if row['spec']['owner'] == self.service.node:
                row.update(cancel=True, command=2)
                # A request is not a receipt; offline cancellation remains pending.
            else:
                row.update(state='CANCELLED', result=None, version=row['version']+1)
        self.service.store.change(self.service.node, update)
        return self.view(sid)

    def run(self, sid, task_id):
        service = self.service
        def reserve(data):
            s = service._space(data, sid); v = state(s)
            row = v['tasks'].get(p.ident(task_id))
            if not v['enabled'] or not row or row['spec']['executor'] != service.node:
                p.fail('本机没有此任务的执行许可。', 'federation_task_disabled')
            if row['state'] != 'WAITING_APPROVAL':
                p.fail('此任务已经处理或结果未知，未重复执行。', 'federation_task_replay')
            row.update(state='RUNNING', version=row['version']+1, host=service.core.host_instance_id)
            return copy.deepcopy(row), v['revision']
        row, revision = service.store.change(service.node, reserve)
        try:
            result = report(row['spec']['text'])
            def commit(data):
                s = service._space(data, sid); v = state(s); current = v['tasks'][task_id]
                if (not v['enabled'] or v['revision'] != revision or
                        current['state'] != 'RUNNING' or current['version'] != row['version']):
                    p.fail('执行期间许可或任务状态已改变，结果未发布。', 'federation_task_cancelled')
                current.update(state='SUCCEEDED', result=result, version=current['version']+1)
            service.store.change(service.node, commit)
        except Exception:
            # The reservation remains durable; it never becomes runnable again.
            def failed(data):
                current = state(service._space(data, sid, active=False))['tasks'][task_id]
                if current['state'] == 'RUNNING':
                    current.update(state='UNKNOWN', version=current['version']+1)
            service.store.change(service.node, failed)
            raise
        return self.view(sid)

    def receive(self, signed):
        service = self.service; network = service.online()
        body = signed.get('body', {}) if isinstance(signed, dict) else {}
        p.fields(body, 'format space sender target request_id tasks')
        p.ident(body['request_id'])
        def update(data):
            service.online(network)
            s = service._space(data, body['space']); v = state(s)
            p.verify(signed, s['members'][s['peer']])
            if (body['format'] != FORMAT or body['sender'] != s['peer'] or body['target'] != service.node
                    or s['role'] != 'host' or not v['enabled']):
                p.fail('对端任务接收未获许可。', 'federation_task_disabled')
            commands = body['tasks']
            if not isinstance(commands, list) or len(commands) > LIMIT: p.fail()
            ids = set(); receipts = []
            for command in commands:
                p.fields(command, 'spec command cancel')
                spec = command['spec']; validate_spec(spec); tid = spec['id']
                if tid in ids or spec['owner'] != s['peer'] or spec['executor'] != service.node: p.fail()
                ids.add(tid)
                if type(command['cancel']) is not bool or type(command['command']) is not int or command['command'] != (2 if command['cancel'] else 1):
                    p.fail()
                row = v['tasks'].get(tid)
                if row and row['spec'] != spec: p.fail('同编号任务内容不一致。', 'federation_conflict')
                if not row:
                    if len(v['tasks']) >= LIMIT: p.fail('接收任务容量已满。')
                    row = v['tasks'][tid] = dict(spec=copy.deepcopy(spec), state='WAITING_APPROVAL',
                        command=command['command'], cancel=command['cancel'], version=1, result=None)
                if row['state'] == 'RUNNING' and row.get('host') != service.core.host_instance_id:
                    row.update(state='UNKNOWN', version=row['version']+1)
                if command['cancel'] and row['state'] not in TERMINAL:
                    row.update(state='CANCELLED', result=None, version=row['version']+1)
                row['command'] = max(row['command'], command['command'])
                receipts.append({k:copy.deepcopy(row[k]) for k in ('spec', 'state', 'version', 'result', 'command')})
            return dict(format=FORMAT, space=s['id'], sender=service.node, target=s['peer'],
                        request_id=body['request_id'], receipts=receipts)
        response = service.store.change(service.node, update)
        return p.sign(response, service._identity().load().key)

    def sync(self, sid):
        service = self.service
        with service.connection.operation():
            network = service.online()
            s = service.connection.space(sid); v = state(s)
            if not v['enabled']: p.fail('本机任务委派尚未启用。')
            commands = [{k:copy.deepcopy(r[k]) for k in ('spec', 'command', 'cancel')} for r in v['tasks'].values()]
            body = dict(format=FORMAT, space=sid, sender=service.node, target=s['peer'],
                        request_id=uuid.uuid4().hex, tasks=commands)
            response = exchange(s['endpoint'], p.fingerprint(s['members'][s['peer']]), '/tasks',
                                p.sign(body, service._identity().load().key), lambda:service.online(network))
            reply = p.verify(response, s['members'][s['peer']])
            p.fields(reply, 'format space sender target request_id receipts')
            if any(reply[k] != body[k] for k in ('format','space','request_id')) or reply['sender'] != s['peer'] or reply['target'] != service.node:
                p.fail()
            def commit(data):
                service.online(network)
                current = state(service._space(data, sid))
                if not current['enabled'] or current['revision'] != v['revision']: p.fail('许可已改变。')
                rows = reply['receipts']
                if not isinstance(rows, list) or len(rows) != len(commands): p.fail()
                ids=set()
                for receipt in rows:
                    p.fields(receipt, 'spec state version result command')
                    tid=receipt['spec'].get('id'); row=current['tasks'].get(tid)
                    if tid in ids or not row or receipt['spec'] != row['spec']: p.fail()
                    ids.add(tid); p.counter(receipt['version'])
                    if receipt['state'] not in TERMINAL | {'RUNNING','WAITING_APPROVAL'}: p.fail()
                    if receipt['version'] < row['version']: p.fail('拒绝倒退的任务回执。')
                    if row['state'] in TERMINAL and any(receipt[k] != row[k] for k in ('state','result','version')): p.fail('终态回执不能改写。')
                    if receipt['state']=='SUCCEEDED':
                        if receipt['result'] != report(row['spec']['text']): p.fail('对端结果未通过独立校验。')
                    elif receipt['result'] is not None: p.fail()
                    row.update({k:receipt[k] for k in ('state','version','result')})
                    row['last_contact']=time.time()
            service.store.change(service.node, commit)
        return self.view(sid)

    def continuation(self, sid):
        value = self.view(sid)
        return {'kind':'task_status_only', 'source':'local_cached_receipts',
                'items':[dict(id=k, title=r['spec']['title'], state=r['state'],
                    owner=r['spec']['owner'], executor=r['spec']['executor'],
                    last_contact=r.get('last_contact'), cancel_pending=r.get('cancel',False) and r['state'] not in TERMINAL,
                    result=r['result']) for k,r in value['tasks'].items()],
                'notice':'这是本机已知回执；断连时不代表对端实时状态。不写入人格、偏好或个人事实。'}
