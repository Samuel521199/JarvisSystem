"""Reversible project organization, separate from roots, exports and chat bodies."""
from contextlib import contextmanager
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys

from .policy import safe_path
from .workspace import fields, identifier, fail, identity


class ProjectCatalog:
    def __init__(self, core, workspace, conversations):
        self.core, self.workspace, self.conversations = core, workspace, conversations
        self.path = Path(core.data_dir) / 'project-catalog.db'

    @contextmanager
    def connection(self):
        safe_path(self.path.parent, directory=True)
        for suffix in ('', '-journal', '-wal', '-shm'):
            target=safe_path(str(self.path)+suffix, must_exist=False)
            if target.exists() and (not target.is_file() or target.stat().st_nlink>1):
                fail('project_catalog_unavailable','项目组织存储不是独立普通文件。')
        db = sqlite3.connect(self.path, timeout=5, isolation_level=None)
        db.row_factory = sqlite3.Row
        try:
            version = db.execute('PRAGMA user_version').fetchone()[0]
            if version not in (0, 1):fail('project_catalog_unavailable', '项目组织数据版本不兼容。')
            db.execute('PRAGMA synchronous=FULL')
            db.execute('CREATE TABLE IF NOT EXISTS profiles (id TEXT PRIMARY KEY, revision INTEGER NOT NULL, document TEXT NOT NULL)')
            db.execute('CREATE TABLE IF NOT EXISTS archived_chats (id TEXT PRIMARY KEY, project_id TEXT NOT NULL)')
            db.execute('PRAGMA user_version=1')
            yield db
        finally:db.close()

    @staticmethod
    def default():
        return {'name':'', 'description':'', 'pinned':False, 'section':'', 'removed':False}

    def snapshot(self):
        self.core.assert_running()
        with self.connection() as db:
            profiles={r['id']:{'revision':r['revision'], **json.loads(r['document'])}
                      for r in db.execute('SELECT * FROM profiles LIMIT 200')}
            archived=[dict(r) for r in db.execute('SELECT id,project_id FROM archived_chats LIMIT 10000')]
        return {'profiles':profiles, 'archived_chats':archived}

    def project(self, project_id):
        identifier(project_id)
        root=next((p for p in self.workspace.projects()['projects'] if p['id']==project_id),None)
        if root is None:fail('project_not_found', '该项目未登记。')
        return root

    def update(self, project_id, payload):
        fields(payload, {'revision','document'})
        self.project(project_id)
        expected=payload['revision'];doc=payload['document']
        if type(expected) is not int or expected<0 or not isinstance(doc,dict) or set(doc)!=set(self.default()):
            fail('invalid_request', '项目编辑字段或版本无效。')
        for key,limit in [('name',120),('description',2048),('section',64)]:
            value=doc[key]
            if not isinstance(value,str) or len(value)>limit or any(ord(c)<32 and not (key=='description' and c in '\n\t') for c in value):
                fail('invalid_request', '项目名称、说明或分区格式无效或超限。')
        if type(doc['pinned']) is not bool or type(doc['removed']) is not bool:
            fail('invalid_request', '项目状态无效。')
        doc={**doc,'name':doc['name'].strip(),'description':doc['description'].strip(),'section':doc['section'].strip()}
        encoded=json.dumps(doc,ensure_ascii=False,sort_keys=True)
        with self.core.effect_guard(), self.connection() as db:
            db.execute('BEGIN IMMEDIATE')
            row=db.execute('SELECT * FROM profiles WHERE id=?',(project_id,)).fetchone()
            current=row['revision'] if row else 0
            if row and row['document']==encoded and expected in (current,current-1):
                db.commit();return {'revision':current, **doc}
            if current!=expected:fail('project_conflict', '另一页面已修改项目，请重新打开菜单核对；输入已保留。')
            if doc['section']:
                sections={json.loads(r[0])['section'] for r in db.execute('SELECT document FROM profiles')}
                sections.discard('')
                if doc['section'] not in sections and len(sections)>=32:fail('project_limit','最多使用 32 个项目分区。')
            db.execute('INSERT INTO profiles VALUES (?,?,?) ON CONFLICT(id) DO UPDATE SET revision=excluded.revision,document=excluded.document', (project_id,current+1,encoded))
            db.commit()
        return {'revision':current+1, **doc}

    def archive(self, project_id, payload):
        fields(payload, {'archived','chat_ids'})
        self.project(project_id)
        ids=payload['chat_ids']
        if type(payload['archived']) is not bool or not isinstance(ids,list) or len(ids)>500:
            fail('invalid_request','聊天归档字段无效或超限。')
        for value in ids:identifier(value)
        if len(set(ids))!=len(ids):fail('invalid_request','聊天标识不能重复。')
        # Snapshot IDs are explicit: a retry cannot archive chats created later.
        chats={r['id']:r for r in self.conversations.list()['conversations']}
        if any(i not in chats or chats[i]['project_id']!=project_id for i in ids):
            fail('invalid_request','只能归档或恢复属于当前项目的已保存聊天。')
        with self.core.effect_guard(), self.connection() as db:
            db.execute('BEGIN IMMEDIATE')
            if payload['archived']:
                new_ids=sum(db.execute('SELECT 1 FROM archived_chats WHERE id=?',(i,)).fetchone() is None for i in ids)
                if db.execute('SELECT count(*) FROM archived_chats').fetchone()[0]+new_ids>10000:
                    fail('project_limit','聊天归档标记达到 10,000 项上限，请先恢复不需要隐藏的聊天。')
                db.executemany('INSERT OR IGNORE INTO archived_chats VALUES (?,?)',[(i,project_id) for i in ids])
            else:db.executemany('DELETE FROM archived_chats WHERE id=? AND project_id=?',[(i,project_id) for i in ids])
            db.commit()
        return {'status':'archived' if payload['archived'] else 'restored','chat_ids':ids}

    def reveal(self, project_id, payload):
        fields(payload,set())
        root=self.project(project_id)
        with self.core.effect_guard(),self.workspace.connection() as db:
            row=db.execute('SELECT identity FROM projects WHERE id=?',(project_id,)).fetchone()
            if identity(Path(root['path']))!=json.loads(row['identity']):fail('project_replaced','项目目录已被替换，不打开该位置。')
            path=str(safe_path(root['path'],directory=True))
            try:
                if os.name=='nt':
                    executable=Path(os.environ.get('SystemRoot',r'C:\Windows'))/'explorer.exe'
                    subprocess.Popen([str(executable),path],shell=False,close_fds=True)
                elif sys.platform=='darwin':subprocess.Popen(['/usr/bin/open',path],shell=False,close_fds=True)
                else:subprocess.Popen(['xdg-open',path],shell=False,close_fds=True)
            except OSError:fail('explorer_unavailable','系统资源管理器暂不可用，可从项目详情复制路径。')
        return {'status':'opened'}
