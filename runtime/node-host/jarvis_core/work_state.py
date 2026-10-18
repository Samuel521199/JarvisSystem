"""Read-only, bounded views of existing task/growth ledgers for continuity.

No executor, observer, recovery or new store. Never exposes report contents,
local paths, provider receipts or arbitrary errors to a conversation model.
"""
from contextlib import contextmanager
import hashlib
import json
from pathlib import Path
import re
import sqlite3

from . import policy
from .conversations import ConversationStore, ConversationError
from .memory import MemoryError, validate

MAX_LINKS = 3
STATES = {'READY':'pending','PROPOSED':'pending','QUEUED':'pending','RUNNING':'running',
          'OBSERVING':'running','CANCELLING':'running','SUCCEEDED':'completed','FAILED':'failed',
          'CANCELLED':'cancelled','UNKNOWN':'unknown','INTERRUPTED':'interrupted'}
LABELS = {'pending':'待办，尚未完成','running':'执行中，尚未完成','completed':'已完成且交付核验通过',
          'failed':'失败','cancelled':'已取消','unknown':'结果未知，需核对','interrupted':'中断，未自动重试',
          'unavailable':'记录或交付不可核验'}


def validate_links(value):
    if not isinstance(value,list) or len(value)>MAX_LINKS:
        raise MemoryError('invalid_continuity','每条接续最多关联三个任务或成长单。')
    seen=set()
    for ref in value:
        if not isinstance(ref,dict) or set(ref)!={'kind','id','conversation_id'} or ref['kind'] not in ('task','growth'):
            raise MemoryError('invalid_continuity','关联任务字段无效。')
        validate('id',ref['conversation_id'])
        pattern=r'task_[a-f0-9]{32}' if ref['kind']=='task' else r'[a-f0-9]{32}'
        if not isinstance(ref['id'],str) or not re.fullmatch(pattern,ref['id']):
            raise MemoryError('invalid_continuity','关联任务标识无效。')
        key=(ref['kind'],ref['id'])
        if key in seen:raise MemoryError('invalid_continuity','不能重复关联同一任务。')
        seen.add(key)
    return value


class WorkState:
    def __init__(self,core,archive_cache=None):
        self.core=core;self.archives=ConversationStore(core)
        self.archive_cache=archive_cache if archive_cache is not None else {}

    @contextmanager
    def growth_db(self):
        path=Path(self.core.data_dir)/'evolution/evolution.db'
        for suffix in ('','-wal','-shm','-journal'):
            file=policy.safe_path(str(path)+suffix,must_exist=False)
            if file.exists() and (file.stat().st_size>32*1024*1024 or file.stat().st_nlink!=1):raise ValueError('ledger quota')
        db=sqlite3.connect(path.absolute().as_uri()+'?mode=ro',uri=True,timeout=2)
        try:
            if db.execute('PRAGMA user_version').fetchone()[0]!=1:raise ValueError('schema')
            yield db
        finally:db.close()

    def scope(self,cid,project_id):
        if cid not in self.archive_cache:
            try:self.archive_cache[cid]=self.archives.get(cid)['document']
            except ConversationError:self.archive_cache[cid]=None
        doc=self.archive_cache[cid]
        if doc is None or doc['project_id']!=project_id:raise ValueError('scope')

    def read(self,ref,project_id):
        validate_links([ref])
        self.scope(ref['conversation_id'],project_id)
        evidence=None
        if ref['kind']=='task':
            value=self.core.ledger.record(task_id=ref['id']);action=value['action']
            if action['capability_id'] not in ('sample.report.v1','skill.report.v1') or action['arguments'].get('conversation_id')!=ref['conversation_id']:
                raise ValueError('binding')
            status=value['task']['status'];error=action.get('error');evidence=value.get('artifact')
            if status=='SUCCEEDED':
                if action['status']!='CONFIRMED' or evidence is None:raise ValueError('unconfirmed')
                self.core._verify_artifact(evidence)
            summary={'raw_status':status,'action_status':action['status'],
                     'error_code':error.get('code') if isinstance(error,dict) else None}
            digest=evidence.get('digest') if evidence and status=='SUCCEEDED' else None
        else:
            with self.growth_db() as db:
                row=db.execute('SELECT document FROM jobs WHERE id=?',(ref['id'],)).fetchone()
            if row is None:raise ValueError('missing')
            if len(row[0].encode())>1024*1024:raise ValueError('record quota')
            value=json.loads(row[0]);origin=value['request'].get('origin',{})
            if (value['request']['action']!='fulfill' or origin.get('conversation_id')!=ref['conversation_id']
                    or origin.get('project_id')!=project_id):raise ValueError('binding')
            status=value['status'];result=value.get('result') or {};digest=None
            if status=='SUCCEEDED':
                from .evolution import recipes
                text=result['text'];digest=result['result_digest']
                if policy.digest(text.encode())!=digest or text!=recipes.expected(value['request']['input']):raise ValueError('result')
            summary={'raw_status':status,'error_code':value.get('error')}
        if status not in STATES:raise ValueError('status')
        # Codes are machine labels only. Never forward server messages or paths.
        code=summary['error_code']
        if code is not None and (not isinstance(code,str) or not re.fullmatch('[A-Za-z0-9_-]{1,96}',code)):
            summary['error_code']='work_failed'
        return {**ref,**summary,'state':STATES[status],'label':LABELS[STATES[status]],
                'artifact_verified':status=='SUCCEEDED','result_digest':digest}

    def observe(self,refs,project_id):
        validate_links(refs);rows=[]
        for ref in refs:
            try:row=self.read(ref,project_id)
            except (policy.CoreError,ConversationError,MemoryError,ValueError,TypeError,KeyError,OSError,sqlite3.Error):
                row={**ref,'state':'unavailable','label':LABELS['unavailable'],'artifact_verified':False}
            rows.append(row)
        digest=hashlib.sha256(policy.canonical_json(rows).encode()).hexdigest()
        return {'items':rows,'digest':digest}

    def choices(self,cid,project_id):
        self.scope(cid,project_id);refs=[]
        with self.core.ledger.connection() as db:
            rows=db.execute("SELECT tasks.task_id FROM tasks JOIN actions USING(task_id) WHERE json_extract(actions.document,'$.arguments.conversation_id')=? AND json_extract(actions.document,'$.capability_id') IN ('sample.report.v1','skill.report.v1') ORDER BY tasks.rowid DESC LIMIT 30",(cid,)).fetchall()
        refs += [{'kind':'task','id':r[0],'conversation_id':cid} for r in rows]
        if (Path(self.core.data_dir)/'evolution/evolution.db').exists():
            with self.growth_db() as db:
                rows=db.execute("SELECT id FROM jobs WHERE json_extract(document,'$.request.action')='fulfill' AND json_extract(document,'$.request.origin.conversation_id')=? AND json_extract(document,'$.request.origin.project_id') IS ? ORDER BY rowid DESC LIMIT 30",(cid,project_id)).fetchall()
            refs += [{'kind':'growth','id':r[0],'conversation_id':cid} for r in rows]
        return refs
