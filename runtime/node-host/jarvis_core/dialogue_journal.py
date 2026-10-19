"""Bounded reply recovery in the existing conversation database; never replay.

No input text, history, attachments or credentials are copied to this table.
Conversation deletion and receipt erasure share one SQLite transaction.
"""
from contextlib import contextmanager
import json
import time

from .turns import TurnError, identifier


class DialogueJournal:
    MAX_IDS = 8192
    MAX_RESULTS = 64
    MAX_BYTES = 16 * 1024 * 1024
    ID_TTL = 7 * 86400
    RESULT_TTL = 86400

    def __init__(self, conversations, owner, *, clock=time.time):
        self.store, self.owner, self.clock = conversations, identifier(owner), clock
        with self.transaction() as db:
            db.execute('CREATE TABLE IF NOT EXISTS dialogue_owner (singleton INTEGER PRIMARY KEY CHECK(singleton=1), owner TEXT NOT NULL)')
            db.execute('''CREATE TABLE IF NOT EXISTS dialogue_receipts (
                id TEXT PRIMARY KEY, conversation_id TEXT NOT NULL, owner TEXT NOT NULL,
                digest TEXT, status TEXT NOT NULL, revision INTEGER NOT NULL,
                result TEXT, size INTEGER NOT NULL, cancelled INTEGER NOT NULL,
                created REAL NOT NULL, updated REAL NOT NULL, deleted INTEGER NOT NULL DEFAULT 0)''')
            db.execute('CREATE INDEX IF NOT EXISTS dialogue_conversation ON dialogue_receipts(conversation_id)')
            db.execute('INSERT OR REPLACE INTO dialogue_owner VALUES(1,?)', (owner,))
            # A surviving provider/old worker may have done work. Never retry it.
            result=json.dumps({'status':'UNKNOWN','outcome_uncertain':True,
                'user_message':'服务在回复完成前中断，结果未确认；没有重发。个人修改或文件操作请先核对原记录。'},ensure_ascii=False)
            db.execute("UPDATE dialogue_receipts SET status='UNKNOWN',result=?,size=?,revision=revision+1,updated=? WHERE status IN ('RUNNING','CANCELLING') AND deleted=0 AND owner<>?",
                       (result,len(result.encode()),clock(),owner))
            self._trim(db)

    @contextmanager
    def transaction(self):
        with self.store.connection(timeout=.05) as db:
            db.execute('BEGIN IMMEDIATE')
            yield db
            db.commit()

    def _owned(self, db):
        row=db.execute('SELECT owner FROM dialogue_owner WHERE singleton=1').fetchone()
        if not row or row[0]!=self.owner:
            raise TurnError('dialogue_owner_changed','回复服务已由新实例接管；原请求不会重发。',409)

    def _trim(self, db):
        now=self.clock()
        db.execute("DELETE FROM dialogue_receipts WHERE status NOT IN ('RUNNING','CANCELLING') AND updated<?",(now-self.ID_TTL,))
        db.execute("UPDATE dialogue_receipts SET result=NULL,size=0 WHERE status NOT IN ('RUNNING','CANCELLING') AND updated<?",(now-self.RESULT_TTL,))
        rows=db.execute("SELECT id,size FROM dialogue_receipts WHERE result IS NOT NULL ORDER BY updated DESC,id").fetchall()
        size=0
        for i,row in enumerate(rows):
            size+=row['size']
            if i>=self.MAX_RESULTS or size>self.MAX_BYTES:
                db.execute('UPDATE dialogue_receipts SET result=NULL,size=0 WHERE id=?',(row['id'],))

    def _row(self, db, conversation, ident):
        row=db.execute('SELECT * FROM dialogue_receipts WHERE id=?',(ident,)).fetchone()
        if row and (row['conversation_id']!=conversation or row['deleted']):
            raise TurnError('turn_not_found','当前会话没有此回复，或会话已经删除。',404)
        return row

    def _view(self, row):
        finished=row['status'] not in ('RUNNING','CANCELLING')
        result={'request_id':row['id'],'conversation_id':row['conversation_id'],
                'instance_id':self.owner,'origin_instance_id':row['owner'],
                'status':row['status'],'revision':row['revision'],'finished':finished,
                'expired':finished and row['result'] is None,'durable':True,
                'cancel_requested':bool(row['cancelled'])}
        if row['result'] is not None:result['result']=json.loads(row['result'])
        if result['expired']:result['user_message']='回复正文已过期或被缓存限额回收；没有自动重发。'
        return result

    def get(self, conversation, ident):
        identifier(conversation);identifier(ident)
        with self.transaction() as db:
            self._owned(db);self._trim(db);row=self._row(db,conversation,ident)
            return self._view(row) if row else None

    def lookup(self, conversation, ident, digest):
        with self.transaction() as db:
            self._owned(db);self._trim(db);row=self._row(db,conversation,ident)
            if row and row['digest'] is not None and row['digest']!=digest:
                raise TurnError('turn_conflict','已登记的回复编号不能更换内容。',409)
            return self._view(row) if row else None

    def admit(self, conversation, ident, digest):
        with self.transaction() as db:
            self._owned(db);self._trim(db)
            row=self._row(db,conversation,ident)
            if row:raise TurnError('turn_conflict','回复编号已经受理，请查询原回执。',409)
            chat=db.execute('SELECT deleted FROM conversations WHERE id=?',(conversation,)).fetchone()
            if not chat or chat['deleted']:
                raise TurnError('conversation_not_archived','请先保存当前会话，再发送；原消息未调用模型。',409)
            if db.execute('SELECT count(*) FROM dialogue_receipts').fetchone()[0]>=self.MAX_IDS:
                raise TurnError('dialogue_capacity','回复恢复记录已达上限，原消息未调用模型。',429)
            now=self.clock()
            db.execute('INSERT INTO dialogue_receipts VALUES (?,?,?,?,?,1,NULL,0,0,?,?,0)',
                       (ident,conversation,self.owner,digest,'RUNNING',now,now))

    def cancel(self, conversation, ident):
        with self.transaction() as db:
            self._owned(db);row=self._row(db,conversation,ident)
            if row and row['status'] in ('RUNNING','CANCELLING'):
                db.execute("UPDATE dialogue_receipts SET cancelled=1,status='CANCELLING',revision=revision+1 WHERE id=?",(ident,))

    def finish(self, conversation, ident, result):
        encoded=json.dumps(result,ensure_ascii=False,allow_nan=False)
        with self.transaction() as db:
            self._owned(db);row=self._row(db,conversation,ident)
            if not row or row['owner']!=self.owner or row['status'] not in ('RUNNING','CANCELLING'):
                raise TurnError('turn_fenced','原回复已结束或交接，不能覆盖恢复结果。',409)
            db.execute('UPDATE dialogue_receipts SET status=?,result=?,size=?,updated=?,revision=revision+1 WHERE id=?',
                       (result['status'],encoded,len(encoded.encode()),self.clock(),ident))
            self._trim(db)
