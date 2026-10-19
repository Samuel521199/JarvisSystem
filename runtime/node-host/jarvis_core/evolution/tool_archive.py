"""Reviewed offline version storage; keep receipts/files and never enable on load."""
import json
import os
import re
from .. import policy
from ..coding_build import bytes_from
from .catalog import fail
from .store import plain_file

OPERATIONS = {'archive-version','load-version'}
LIMIT = 4*1024*1024


class ToolArchive:
    def __init__(self, lifecycle):
        self.life=lifecycle;self.tools=lifecycle.tools;self.store=lifecycle.store

    def record(self, ident, base):
        with self.store.connection() as db:
            row=db.execute('SELECT state,document FROM tool_versions WHERE id=?',(ident,)).fetchone()
        if not row:fail('未找到此工具版本。')
        try:doc=json.loads(row['document'])
        except ValueError:fail('版本记录损坏，不能归档或载回。')
        if not isinstance(doc,dict) or any(doc.get(k)!=base[k] for k in ('project_id','tool_id')):fail('版本不属于当前项目和工具。')
        return row['state'],row['document'],doc

    def binding(self, ident, base):
        state,raw,_=self.record(ident,base)
        return {'state':state,'document_digest':policy.digest(raw.encode())}

    @staticmethod
    def references(base, value):
        return {base['active'],base['previous'],value.get('candidate'),value.get('retired_version'),value.get('retired_candidate')}

    def path(self, ident):
        if not re.fullmatch('[a-f0-9]{64}',ident):fail('归档版本标识无效。')
        root=policy.safe_path(self.store.root/'tool-archives',must_exist=False,directory=True)
        root.mkdir(exist_ok=True)
        return root,policy.safe_path(root/(ident+'.json'),must_exist=False,directory=False)

    def save(self, ident, raw):
        root,path=self.path(ident)
        # Bound managed archive storage, including complete or partial orphan files.
        entries=list(root.iterdir());size=0
        for p in entries:
            if not re.fullmatch(r'[a-f0-9]{64}\.json',p.name):fail('归档区有未识别材料，请先核对。')
            size+=plain_file(p,LIMIT).stat().st_size
        if not path.exists() and (len(entries)>=256 or size+len(raw)>64*1024*1024):fail('离线归档达到 256 项或 64 MiB 上限。')
        if not path.exists():
            with path.open('xb') as f:f.write(raw);f.flush();os.fsync(f.fileno())
        if plain_file(path,LIMIT).read_bytes()!=raw:fail('已有归档不完整或不一致；未覆盖材料。')
        return {'sha256':policy.digest(raw),'bytes':len(raw)}

    def execute(self, job, value):
        req=job['request'];base=req['base'];p=req['submission'];ident=p['version'];op=p['operation']
        state,old,doc=self.record(ident,base)
        if self.binding(ident,base)!=req['version_storage']:fail('版本存储基线变化。','evolution_conflict')
        if ident in self.references(base,value):fail('仍被稳定、灰度或恢复引用，不能整理此版本。')
        self.tools.manager._resources()
        if op=='archive-version':
            if state!='RETIRED':fail('先明确退役无引用版本，再归档。')
            self.tools.package(ident,base)
            raw=policy.canonical_json({'schema':1,'version':ident,'document':doc}).encode()
            if len(raw)>LIMIT:fail('单版本归档超过 4 MiB。')
            with self.tools.core.effect_guard():proof=self.save(ident,raw)
            new={k:doc[k] for k in ('project_id','tool_id','metadata')}
            new.update(archive={'version':ident,**proof})
            target='ARCHIVED';released=max(0,len(old.encode())-len(policy.canonical_json(new).encode()))
        else:
            if state!='ARCHIVED':fail('此版本不在离线归档。')
            _,path=self.path(ident)
            raw=plain_file(path,LIMIT).read_bytes();proof=doc.get('archive',{})
            if len(raw)!=proof.get('bytes') or policy.digest(raw)!=proof.get('sha256'):fail('归档摘要不符；未载回。')
            try:payload=json.loads(raw);new=payload['document']
            except (ValueError,KeyError,TypeError):fail('归档格式损坏。')
            if set(payload)!={'schema','version','document'} or payload['schema']!=1 or payload['version']!=ident:
                fail('归档版本或结构不符。')
            if policy.digest(policy.canonical_json(new).encode())[7:]!=ident or any(new.get(k)!=base[k] for k in ('project_id','tool_id')):
                fail('归档内容不属于原版本和作用域。')
            bytes_from(new['build'])
            with self.store.connection() as db:
                if db.execute("SELECT COUNT(*) FROM tool_versions WHERE state!='ARCHIVED'").fetchone()[0]>=64:fail('在线包名额已满，未载回。')
                used=(db.execute('PRAGMA page_count').fetchone()[0]-db.execute('PRAGMA freelist_count').fetchone()[0])*db.execute('PRAGMA page_size').fetchone()[0]
            if used+6*len(raw)+2*1024*1024>28*1024*1024:fail('在线账本恢复空间不足，未载回。')
            target='RETIRED';released=0
        new_raw=policy.canonical_json(new)
        self.life.fresh(job)
        effect={'version':ident,'from':state,'to':target,'archive_digest':proof['sha256'],
                'online_payload_bytes_released':released,'online_slot_released':op=='archive-version',
                'disk_space_freed_claimed':False,'receipts_deleted':0,'user_files_deleted':0,'model_calls':0}
        job['version_storage_effect']=effect
        self.life.write(job,value,version_update=(ident,state,old,target,new_raw))
        return effect


def capacity(store):
    with store.connection() as db:
        rows=db.execute('SELECT state FROM tool_versions').fetchall()
        page=db.execute('PRAGMA page_size').fetchone()[0]
        allocated=db.execute('PRAGMA page_count').fetchone()[0]*page
        reusable=db.execute('PRAGMA freelist_count').fetchone()[0]*page
        return {'online_versions':sum(r['state']!='ARCHIVED' for r in rows),'archived_versions':sum(r['state']=='ARCHIVED' for r in rows),
                'online_version_limit':64,'ledger_allocated_bytes':allocated,'ledger_reusable_bytes':reusable,
                'jobs':db.execute('SELECT COUNT(*) FROM jobs').fetchone()[0],'job_limit':1000,
                'note':'归档释放在线包名额并让 SQLite 页可复用；文件、历史回执保留，不宣称磁盘总占用下降。'}
