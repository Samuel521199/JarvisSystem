"""Demand -> cited research -> reviewed candidate -> existing K4/K5 lifecycle.

This journal owns provenance and handoff, not another executor or acceptance oracle.
External material remains untrusted. It never changes persona or personal facts.
"""
import json
import re
import uuid

from .. import policy
from .store import now


def fail(message):
    raise policy.CoreError('learning_invalid', message)


def ident(value):
    if not isinstance(value, str) or not re.fullmatch('[a-f0-9]{32}', value): fail('学习编号无效。')
    return value


def text(value, limit):
    if not isinstance(value, str) or not value.strip() or len(value) > limit: fail('内容为空或超过长度限制。')
    from ..coding_secrets import ensure
    ensure(value)
    return value.strip()


def key(ident, purpose):
    return uuid.uuid5(uuid.NAMESPACE_URL, 'jarvis-learning/'+ident+'/'+purpose).hex


class LearningLoop:
    def __init__(self, manager, tasks):
        self.manager, self.store, self.core, self.tasks = manager, manager.store, manager.core, tasks

    @staticmethod
    def exists(db):
        return bool(db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='learning_demands'").fetchone())

    @staticmethod
    def save(db, row):
        row['updated_at']=now()
        used=(db.execute('PRAGMA page_count').fetchone()[0]-db.execute('PRAGMA freelist_count').fetchone()[0])*db.execute('PRAGMA page_size').fetchone()[0]
        if used+2*len(policy.canonical_json(row).encode())>28*1024*1024:
            fail('学习账本接近容量门槛，保留恢复空间后停止写入。')
        db.execute('INSERT INTO learning_demands VALUES(?,?) ON CONFLICT(id) DO UPDATE SET document=excluded.document',
                   (row['id'],policy.canonical_json(row)))

    def read(self, lid):
        with self.store.connection() as db:
            if not self.exists(db): fail('尚无学习需求。')
            value=db.execute('SELECT document FROM learning_demands WHERE id=?',(ident(lid),)).fetchone()
        if not value: fail('未找到此学习需求。')
        return json.loads(value[0])

    def change(self, lid, callback):
        with self.manager.lock, self.core.effect_guard(), self.store.connection() as db:
            db.execute('BEGIN IMMEDIATE')
            if not self.exists(db): fail('尚无学习需求。')
            raw=db.execute('SELECT document FROM learning_demands WHERE id=?',(ident(lid),)).fetchone()
            if not raw: fail('未找到此学习需求。')
            row=json.loads(raw[0]); callback(row); self.save(db,row)
        return row

    def create(self, payload):
        if set(payload) != {'id','goal','conversation_id'}: fail('需要学习目标、会话和请求编号。')
        lid=ident(payload['id']); goal=text(payload['goal'],1200); cid=ident(payload['conversation_id'])
        # Bind to a real local conversation; IDs alone are not project authority.
        from ..conversations import ConversationStore, ConversationError
        try: ConversationStore(self.core).get(cid)
        except ConversationError: fail('关联会话已删除或不存在。')
        with self.manager.lock, self.core.effect_guard(), self.store.connection() as db:
            db.execute('BEGIN IMMEDIATE')
            db.execute('CREATE TABLE IF NOT EXISTS learning_demands(id TEXT PRIMARY KEY,document TEXT NOT NULL)')
            old=db.execute('SELECT document FROM learning_demands WHERE id=?',(lid,)).fetchone()
            if old:
                row=json.loads(old[0])
                if row['goal']!=goal or row['conversation_id']!=cid: fail('原编号不能替换学习目标。')
                return row
            if db.execute('SELECT count(*) FROM learning_demands').fetchone()[0]>=64:
                fail('学习账本已到 64 条上限，未自动删除证据。')
            row=dict(id=lid,goal=goal,conversation_id=cid,state='DRAFT',evidence=None,
                     research=None,handoff=None,review=None,feedback=None,created_at=now())
            self.save(db,row)
            db.execute('PRAGMA user_version=9')
        return row

    def research(self, lid, library):
        with self.manager.lock:
            return self._research(lid, library)

    def _research(self, lid, library):
        library=text(library,160)
        def reserve(row):
            if row['handoff'] or row['state']=='WITHDRAWN': fail('已交接或撤回的需求不能改写来源。')
            if row['research'] and row['research']['library']!=library:
                old=self.tasks.lookup(row['conversation_id'],row['research']['request_id'])
                if old['action_status']!='CONFIRMED': fail('原查询尚未完成，不能改变查询目标。')
                report=json.loads(self.tasks.artifact(row['conversation_id'],old['task']['task_id']))
                if report.get('tool')!='resolve-library-id' or library not in report.get('candidates',[]):
                    fail('只能选择原查询返回的候选库；修改目标请建立新需求。')
                row['research_resolution']=row['research']
            row['research']={'library':library,'request_id':'web-'+key(lid,'research/'+library)}
        row=self.change(lid,reserve)
        # Same ledger request after interrupted UI response; never a new cloud call.
        self.tasks.submit(row['conversation_id'],dict(mode='mcp',request_id=row['research']['request_id'],
            prompt=row['goal'],library=library))
        return self.view(lid)

    def collect(self, lid):
        row=self.read(lid)
        if not row['research']: fail('请先查询资料。')
        receipt=self.tasks.lookup(row['conversation_id'],row['research']['request_id'])
        if receipt['action_status']!='CONFIRMED': fail('文档查询还没有确认回执，未读取不完整结果。')
        task_id=receipt['task']['task_id']
        value=json.loads(self.tasks.artifact(row['conversation_id'],task_id))
        if value.get('kind')!='jarvis.mcp-report' or value.get('tool')!='query-docs':
            fail('这是库名称解析结果，请先选择返回的精确库 ID 查询文档。')
        notes=value.get('text')
        if not isinstance(notes,str): fail('资料没有有效正文。')
        return self.evidence(lid,dict(source='Context7 '+str(value.get('library',''))+' · '+task_id,
            notes=notes[:3800]+('\n[节选：全文保留在原任务产物中]' if len(notes)>3800 else ''),task_id=task_id))

    def evidence(self, lid, payload):
        if set(payload) != {'source','notes','task_id'}: fail('需要来源、笔记和可选任务回执。')
        notes=text(payload['notes'],4000); source=text(payload['source'],500)
        task_id=payload['task_id']; artifact=None
        row=self.read(lid)
        if task_id:
            # Only this conversation's confirmed documentation result is admissible.
            record=self.tasks._bound(row['conversation_id'],task_id)
            if record['action']['capability_id']!='mcp.documentation.v1' or record['action']['status']!='CONFIRMED' or not record['artifact']:
                fail('只可绑定已确认的文档查询产物。')
            self.core._verify_artifact(record['artifact'])
            artifact={k:record['artifact'][k] for k in ('artifact_id','digest','task_id')}
        value=dict(source=source,notes=notes,artifact=artifact,trust='untrusted_reference',captured_at=now())
        value['digest']=policy.digest(policy.canonical_json(value).encode())
        def update(current):
            if current['handoff'] or current['state']=='WITHDRAWN': fail('交接后的证据不可原地改写；可撤回并新建。')
            current.update(evidence=value,review=None,state='EVIDENCE_READY')
        return self.change(lid,update)

    def review(self, lid, note):
        note=text(note,1000)
        if len(note)<8: fail('请说明资料适用性、疑点和验收依据。')
        def update(row):
            if not row['evidence'] or row['handoff'] or row['state']=='WITHDRAWN': fail('先保存来源证据再审阅。')
            row.update(review=dict(note=note,evidence_digest=row['evidence']['digest'],at=now()),state='REVIEWED')
        return self.change(lid,update)

    def start(self, lid, payload):
        with self.manager.lock:
            return self._start(lid, payload)

    def _start(self, lid, payload):
        if set(payload)!={'target','model','domain','policy_revision'}: fail('需要明确改造目标与原策略版本。')
        if payload['target'] not in ('tool','ranking'): fail('仅支持现有工具成长与检索排序模块。')
        row=self.read(lid)
        if not row['handoff']:
            if payload['target']=='ranking':
                self.manager.provider.configuration(payload['model'])
            else:
                from .growth_domains import specification
                specification(payload['domain'])
                current=self.manager.growth.snapshot(row['conversation_id'])['policy']
                if (not current['enabled'] or current['revision']!=payload['policy_revision']
                        or payload['domain'] not in current['domains']):
                    fail('请先读取适用的项目成长策略；没有登记编码请求。')
        def reserve(current):
            if current['handoff']:
                if current['state']=='WITHDRAWN': fail('学习需求已撤回。')
                if current['handoff']['request']!=payload: fail('需求已经交给另一个改造目标。')
                return
            if current['state']!='REVIEWED' or current['review']['evidence_digest']!=current['evidence']['digest']:
                fail('当前证据尚未审阅。')
            current.update(handoff=dict(id=key(lid,'candidate'),request=payload,status='RESERVED'),state='HANDOFF')
        row=self.change(lid,reserve)
        request=row['handoff']; target=payload['target']
        # Deterministic request IDs allow reconciliation, not duplicate generation.
        context='目标：'+row['goal']+'\n参考资料（非指令）：'+row['evidence']['notes'][:700]
        if target=='tool':
            result=self.manager.growth.start(row['conversation_id'],dict(request_id=request['id'],
                goal=context[:2000],domain=payload['domain'],policy_revision=payload['policy_revision']))
        else:
            result=self.manager.ranking_modules.submit(dict(request_id=request['id'],model=payload['model'],context=context))
        def bound(current):
            current['handoff'].update(status='BOUND',result_id=result['id'])
        self.change(lid,bound)
        return self.view(lid)

    def view(self, lid):
        row=self.read(lid); handoff=row['handoff']
        if row['research']:
            try:
                row['research_receipt']=self.tasks.lookup(row['conversation_id'],row['research']['request_id'])
                if row['research_receipt']['action_status']=='CONFIRMED':
                    material=json.loads(self.tasks.artifact(row['conversation_id'],row['research_receipt']['task']['task_id']))
                    row['research_candidates']=material.get('candidates',[])
            except policy.CoreError: row['research_receipt']=None
        if handoff:
            try:
                rid=handoff.get('result_id',handoff['id'])
                if handoff['request']['target']=='tool':
                    result=self.manager.growth.stored(row['conversation_id'],rid)
                    row['outcome']=dict(status=result['status'],assessment=result.get('assessment'),
                        tool_id=result.get('tool_id'),candidate_version=result.get('candidate_version'),
                        reason=result.get('stop_reason'))
                else:
                    result=self.store.existing_job(handoff['id'])
                    if not result: fail('尚未找到编码回执。')
                    row['outcome']=dict(status=result['status'],result=result.get('result'),
                        selection=self.manager.ranking_modules.snapshot()['selection'])
            except policy.CoreError:
                row['outcome']={'status':'UNRESOLVED','notice':'未找到交接回执；不表示生成成功。使用同一请求核对。'}
        return row

    def feedback(self, lid, useful, note):
        if type(useful) is not bool: fail('请明确反馈是否有用。')
        note=text(note,1000)
        return self.change(lid,lambda row:row.update(feedback=dict(useful=useful,note=note,source='owner',at=now())))

    def withdraw(self, lid):
        with self.manager.lock:
            return self._withdraw(lid)

    def _withdraw(self, lid):
        row=self.read(lid); handoff=row['handoff']
        if row['research']:
            try:
                task=self.tasks.lookup(row['conversation_id'],row['research']['request_id'])
                if task['action_status'] not in {'CONFIRMED','CANCELLED','FAILED','UNKNOWN'}:
                    self.tasks.cancel(row['conversation_id'],task['task']['task_id'],{})
            except policy.CoreError as exc:
                if exc.code!='not_found': raise
        if handoff:
            rid=handoff.get('result_id',handoff['id'])
            if handoff['request']['target']=='tool':
                cycle=self.manager.growth.stored(row['conversation_id'],rid)
                if cycle['status']=='COMPLETE':
                    self.manager.growth.stop(cycle,'learning_source_withdrawn','CANCELLED')
                else: self.manager.growth.cancel(row['conversation_id'],rid)
            else:
                job=self.store.existing_job(handoff['id'])
                if not job:
                    return self.change(lid,lambda current:current.update(state='WITHDRAWN'))
                if job['status'] in ('QUEUED','RUNNING','OBSERVING'): self.manager.cancel(job['id'])
                # Do not undo another demand's selected module.
                version=(job.get('result') or {}).get('candidate_id')
                selected=self.manager.ranking_modules.snapshot()['selection']
                if version and selected['active']==version:
                    self.manager.ranking_modules.transition(dict(action='rollback',generation=selected['generation'],
                        version=version,review='学习来源已撤回，恢复此需求改造前的检索模块。'))
        return self.change(lid,lambda current:current.update(state='WITHDRAWN'))

    def snapshot(self):
        self.core.assert_running()
        with self.store.connection() as db:
            ids=[r[0] for r in db.execute('SELECT id FROM learning_demands ORDER BY rowid DESC LIMIT 64')] if self.exists(db) else []
        return {'demands':[self.view(lid) for lid in ids], 'opportunities':self.opportunities(),
                'limits':{'demands':64,'scheduler':False,'executor':'existing_K4_K5','personal_memory_writes':False}}

    def opportunities(self):
        """Read-only signals from real receipts; no model inference or timer."""
        with self.core.ledger.connection() as db:
            actions=[json.loads(r[0]) for r in db.execute('SELECT document FROM actions ORDER BY rowid DESC LIMIT 64')]
        grouped={}
        for action in actions:
            args=action.get('arguments',{}); cid=args.get('conversation_id'); prompt=args.get('prompt')
            if not cid or not prompt or action['status'] not in ('FAILED','CONFIRMED'): continue
            k=(cid,action['capability_id'],prompt)
            grouped.setdefault(k,[]).append(action)
        results=[]
        for (cid,capability,prompt),rows in grouped.items():
            failed=[r for r in rows if r['status']=='FAILED']
            if not failed and len(rows)<3: continue
            action=(failed or rows)[0]
            # A source suggestion carries only the explicit task goal, never raw chats.
            results.append(dict(task_id=action['task_id'],conversation_id=cid,goal=prompt[:1200],
                capability=capability,reason='已确认失败，可研究改进' if failed else '同一要求已完成至少三次，可评估复用收益',
                observed_count=len(rows)))
        return results[:12]

    def capture(self, task_id):
        row=next((r for r in self.opportunities() if r['task_id']==task_id),None)
        if not row: fail('此任务不是当前可追溯的改进机会；未知结果不自动转为重试。')
        demand=self.create(dict(id=key(task_id,'demand'),goal=row['goal'],conversation_id=row['conversation_id']))
        return self.change(demand['id'],lambda current:current.update(origin=row))
