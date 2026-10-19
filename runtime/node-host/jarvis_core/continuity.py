"""Owner-entered conversation checkpoints; never an execution/task ledger.

Sources are exact archived owner messages. Only explicitly selected records
may enter a model request, after scope, provider, source and revision checks.
"""
from contextlib import contextmanager
import hashlib
import json
from pathlib import Path
import re
import sqlite3
import uuid

from .conversations import ConversationStore, ConversationError
from .memory import MemoryError, validate as memory_validate, normalized, timestamp, validate_history_references as memory_history
from .policy import safe_path, canonical_json
from .work_state import WorkState, validate_links

MAX_RECORDS, MAX_IDS, MAX_COMMANDS = 200, 2000, 10000
MAX_SELECTED, MAX_BYTES = 3, 4096
COMMAND = re.compile(r'^(?:请)?(保存接续|更新接续|继续话题|完成接续|重新打开接续|忘记接续)\s*[：:]\s*([^\r\n]+)$')


def parse(message):
    value = message.strip()
    if value == '查看接续':
        return value, ''
    match = COMMAND.fullmatch(value)
    return (match[1], match[2].strip()) if match else None


def validate_source(value):
    if not isinstance(value, dict) or set(value) != {'conversation_id', 'message_index'}:
        raise MemoryError('invalid_continuity', '接续需要来源会话和消息位置。')
    memory_validate('id', value['conversation_id'])
    if type(value['message_index']) is not int or not 0 <= value['message_index'] < 500:
        raise MemoryError('invalid_continuity', '来源消息位置无效。')
    return value


def validate_context(value):
    if value is None:
        return {'enabled': False, 'ids': []}
    if (not isinstance(value, dict) or set(value) != {'enabled', 'ids'} or type(value['enabled']) is not bool
            or not isinstance(value['ids'], list) or len(value['ids']) > MAX_SELECTED):
        raise MemoryError('invalid_continuity', '每个会话最多选择三条接续记录。')
    for ident in value['ids']:
        memory_validate('id', ident)
    if len(set(value['ids'])) != len(value['ids']):
        raise MemoryError('invalid_continuity', '接续选择不能重复。')
    return value


def validate_history_references(value, history):
    if value is None:return [[] for _ in (history or [])]
    if not isinstance(value,list) or len(value)>1000:
        raise MemoryError('invalid_continuity','接续历史引用无效。')
    stripped=[]
    for refs in value:
        if not isinstance(refs,list) or len(refs)>100:raise MemoryError('invalid_continuity','接续引用无效。')
        clean=[]
        for ref in refs:
            if not isinstance(ref,dict) or not {'id','revision'}<=set(ref) or set(ref)-{'id','revision','work_digest'}:
                raise MemoryError('invalid_continuity','接续引用字段无效。')
            if 'work_digest' in ref and (not isinstance(ref['work_digest'],str) or not re.fullmatch('[a-f0-9]{64}',ref['work_digest'])):
                raise MemoryError('invalid_continuity','任务状态摘要无效。')
            clean.append({k:ref[k] for k in ('id','revision')})
        stripped.append(clean)
    memory_history(stripped,history)
    return value


def execute(command, *, core, project_id, source=None, message=None, request_id, cancel_event=None):
    name, body = command
    store = ContinuityStore(core)
    if name == '查看接续':
        rows = store.list(project_id)['records']
        text = '当前范围还没有接续记录。' if not rows else '\n\n'.join(
            f"{r['document']['title']} · {'待续' if r['document']['state']=='open' else '主人标记完成'}\n"
            f"进展：{r['document']['progress']}\n下一步：{r['document']['next_step']}\n标识 {r['id']} · 修订 {r['revision']}"
            for r in rows[:20])
        return text, {'kind': 'continuity', 'action': 'view', 'committed': False}
    if name == '继续话题':
        matches = [r for r in store.list(project_id)['records'] if r['id'] == body or normalized(r['document']['title']) == normalized(body)]
        if len(matches) != 1:
            raise MemoryError('continuity_ambiguous', '未找到唯一话题；请查看接续并使用完整标题或标识。')
        row = matches[0]
        records, _ = store.snapshot({'enabled': True, 'ids': [row['id']]}, project_id, 'local')
        if not records:
            raise MemoryError('continuity_source_missing', '来源会话已变化或删除，请重新明确记录进展后继续。')
        work=records[0].get('work',{}).get('items',[])
        actual='\n关联执行记录：\n'+'\n'.join(r['id']+' · '+r['label'] for r in work) if work else ''
        return ('已选择这条接续，下一轮对话按接入方许可使用。\n'
                f"进展：{row['document']['progress']}\n下一步：{row['document']['next_step']}\n"
                '进展文字是明确记录；关联执行状态以本次核对为准。选择接续不启动或重试任务。'+actual), {'kind': 'continuity', 'action': 'resume', 'id': row['id'], 'revision': row['revision'], 'committed': False}
    action = {'保存接续': 'save', '更新接续': 'update', '完成接续': 'close', '重新打开接续': 'reopen', '忘记接续': 'forget'}[name]
    title, progress, next_step = body, None, None
    if action in ('save', 'update'):
        parts = re.split('[=＝]', body, maxsplit=1)
        details = re.split('[|｜]', parts[1], maxsplit=1) if len(parts) == 2 else []
        if len(details) != 2:
            raise MemoryError('invalid_continuity', '请使用“保存接续：标题=当前进展｜下一步”；更新时改为“更新接续”。')
        title, progress, next_step = parts[0].strip(), details[0].strip(), details[1].strip()
    receipt = store.change(action, target=title, progress=progress, next_step=next_step, source=source, message=message,
                           project_id=project_id, request_id=request_id, cancel_event=cancel_event)
    if receipt['replayed']:
        return '这次接续操作已处理，未重复执行或恢复旧内容。请查看接续核对当前状态。', receipt
    text = {'save': '已保存接续并关联原会话。默认仅本地使用；可在记忆面板的“接续”页授权云端接入方。',
            'update': '已更新进展与下一步，并关联本轮明确记录；旧修订退出后续上下文。',
            'close': '已标记为“主人确认完成”。这不是后台任务执行成功的回执。',
            'reopen': '已重新标记待续，未启动后台任务。',
            'forget': '已忘记接续；原会话和导出未删除，相关派生上下文下轮失效。'}[action]
    return text, receipt


class ContinuityStore:
    def __init__(self, core):
        self.core = core
        self.path = Path(core.data_dir)/'continuity.db'
        self.conversations = ConversationStore(core)

    @contextmanager
    def connection(self, *, write=False):
        for suffix in ('', '-journal', '-wal', '-shm'):
            safe_path(str(self.path)+suffix, must_exist=False)
        db = sqlite3.connect(self.path if write else self.path.absolute().as_uri()+'?mode=ro',
                             uri=not write, isolation_level=None, timeout=2)
        db.row_factory = sqlite3.Row
        try:
            version = db.execute('PRAGMA user_version').fetchone()[0]
            if version not in ((0, 1) if write else (1,)):
                raise MemoryError('continuity_unavailable', '接续库版本不兼容；未改写。')
            if write:
                db.execute('PRAGMA synchronous=FULL')
                db.execute('PRAGMA secure_delete=ON')
                db.execute('BEGIN IMMEDIATE')
                db.execute('CREATE TABLE IF NOT EXISTS notes (id TEXT PRIMARY KEY, revision INTEGER NOT NULL, document TEXT, project_id TEXT, updated_at TEXT NOT NULL, deleted INTEGER NOT NULL DEFAULT 0)')
                db.execute('CREATE TABLE IF NOT EXISTS commands (id TEXT PRIMARY KEY, digest TEXT NOT NULL, receipt TEXT NOT NULL)')
                db.execute('PRAGMA user_version=1')
                # A rejected first write must leave a readable empty database.
                # Schema creation and the owner action are separate transactions.
                db.commit()
                db.execute('BEGIN IMMEDIATE')
            yield db
        finally:
            db.close()

    @staticmethod
    def public(row):
        try:
            doc = json.loads(row['document'])
            if not {'title','progress','next_step','project_id','providers','state','source'}<=set(doc) or set(doc)-{'title','progress','next_step','project_id','providers','state','source','work_refs'}:
                raise ValueError('fields')
            validate_links(doc.get('work_refs',[]))
            memory_validate('document', {key: doc[key] for key in ('title','project_id','providers')} | {'content': doc['progress']})
            source = doc['source']
            required_source = {'conversation_id','message_index','sha256','archive_revision','recorded_at'}
            if not required_source <= set(source) or set(source)-required_source-{'owner_confirmed_candidate'}:
                raise ValueError('source')
            if 'owner_confirmed_candidate' in source and source['owner_confirmed_candidate'] is not True: raise ValueError('source kind')
            validate_source({key: source[key] for key in ('conversation_id','message_index')})
            memory_validate('revision', source['archive_revision'])
            if (doc['project_id'] != row['project_id'] or doc['state'] not in ('open','owner_completed')
                    or not isinstance(doc['next_step'], str) or not 1 <= len(doc['next_step']) <= 1024
                    or not isinstance(source['sha256'], str) or not re.fullmatch('[a-f0-9]{64}', source['sha256'])
                    or not isinstance(source['recorded_at'], str) or len(source['recorded_at']) > 64):
                raise ValueError('record')
        except (ValueError, TypeError, KeyError):
            raise MemoryError('continuity_unavailable', '接续记录格式异常；未采用或覆盖，可取消选用后继续聊天。') from None
        return {'id': row['id'], 'revision': row['revision'], 'document': doc, 'updated_at': row['updated_at']}

    def list(self, project_id=None):
        if project_id is not None:
            memory_validate('id', project_id)
        if not self.path.exists():
            return {'records': [], 'max_records': MAX_RECORDS}
        with self.connection() as db:
            rows = db.execute('SELECT * FROM notes WHERE deleted=0 AND project_id IS ? ORDER BY updated_at DESC,id', (project_id,)).fetchall()
        return {'records': [self.public(r) for r in rows], 'max_records': MAX_RECORDS}

    def source(self, source, message, project_id, *, candidate_source=False):
        validate_source(source)
        try:
            archive = self.conversations.get(source['conversation_id'])
            row = archive['document']['messages'][source['message_index']]
        except (ConversationError, IndexError):
            raise MemoryError('continuity_source_missing', '来源会话尚未保存或消息不可用；请确认会话保存成功后重试。') from None
        if (not isinstance(message, str) or archive['document']['project_id'] != project_id or row['role'] != 'user'
                or (candidate_source and any(row.get(flag) for flag in ('personal_control', 'task_control', 'attachments_omitted', 'incomplete')))
                or (not candidate_source and row.get('personal_control') is not True) or row['content'].strip() != message.strip()):
            raise MemoryError('continuity_source_conflict', '来源与本轮明确记录不一致，未保存接续。')
        return {**source, 'sha256': hashlib.sha256(row['content'].encode()).hexdigest(), 'archive_revision': archive['revision'], 'recorded_at': timestamp(),
                **({'owner_confirmed_candidate': True} if candidate_source else {})}

    def source_current(self, document, cache):
        source = document['source']; ident = source['conversation_id']
        if ident not in cache:
            try:
                cache[ident] = self.conversations.get(ident)['document']
            except ConversationError:
                cache[ident] = None
        archive = cache[ident]
        if archive is None or archive['project_id'] != document['project_id']:
            return False
        try:
            row = archive['messages'][source['message_index']]
            return (row['role'] == 'user' and (row.get('personal_control') is True or source.get('owner_confirmed_candidate') is True)
                    and (not source.get('owner_confirmed_candidate') or not any(row.get(flag) for flag in ('personal_control', 'task_control', 'attachments_omitted', 'incomplete')))
                    and hashlib.sha256(row['content'].encode()).hexdigest() == source['sha256'])
        except IndexError:
            return False

    def change(self, action, *, request_id, project_id=None, target=None, progress=None, next_step=None,
               source=None, message=None, revision=None, providers=None, work_refs=None, cancel_event=None, candidate_source=False):
        memory_validate('id', request_id)
        if project_id is not None:
            memory_validate('id', project_id)
        if action not in ('save', 'update', 'close', 'reopen', 'forget', 'permissions', 'link_work'):
            raise MemoryError('invalid_continuity', '未知接续操作。')
        if not isinstance(target, str) or not 1 <= len(target.strip()) <= 120 or '\0' in target:
            raise MemoryError('invalid_continuity', '请提供不超过 120 字的接续标题或完整标识。')
        if action in ('save', 'update'):
            for text, limit in ((progress, 2048), (next_step, 1024)):
                if not isinstance(text, str) or not text.strip() or len(text) > limit or '\0' in text:
                    raise MemoryError('invalid_continuity', '请分别填写已讨论的进展（最多 2048 字）和下一步（最多 1024 字）。')
            validate_source(source)
        if action == 'permissions':
            memory_validate('document', {'title': 'scope', 'content': 'scope', 'project_id': project_id, 'providers': providers})
        if action == 'link_work':validate_links(work_refs)
        digest = hashlib.sha256(canonical_json([action, target, progress, next_step, source, project_id, revision, providers, message]).encode()).hexdigest()
        if action=='link_work':digest=hashlib.sha256(canonical_json([digest,work_refs]).encode()).hexdigest()
        if candidate_source:digest=hashlib.sha256(canonical_json([digest,'owner_confirmed_candidate']).encode()).hexdigest()
        with self.core.effect_guard(), self.connection(write=True) as db:
            previous = db.execute('SELECT * FROM commands WHERE id=?', (request_id,)).fetchone()
            if previous:
                if previous['digest'] != digest:
                    raise MemoryError('continuity_conflict', '同一请求标识不能用于不同接续操作。')
                return {**json.loads(previous['receipt']), 'replayed': True}
            if cancel_event is not None and cancel_event.is_set():
                raise MemoryError('personal_cancelled', '已取消；本次未修改接续。')
            if db.execute('SELECT count(*) FROM commands').fetchone()[0] >= MAX_COMMANDS:
                raise MemoryError('continuity_limit', '接续操作回执达到本版上限，未清理或覆盖历史。')
            rows = db.execute('SELECT * FROM notes WHERE deleted=0 AND project_id IS ?', (project_id,)).fetchall()
            matches = [r for r in rows if r['id'] == target or normalized(self.public(r)['document']['title']) == normalized(target)]
            if len(matches) > 1:
                raise MemoryError('continuity_ambiguous', '同名接续不唯一，请使用完整标识。')
            row = matches[0] if matches else None
            if action == 'save' and row:
                raise MemoryError('continuity_conflict', '已存在同名接续；请用“更新接续”明确更新。')
            if action != 'save' and row is None:
                raise MemoryError('continuity_not_found', '当前范围没有这条接续。')
            if revision is not None and (type(revision) is not int or revision != (row['revision'] if row else 0)):
                raise MemoryError('continuity_conflict', '接续已在其他页面更新，请刷新核对；未覆盖。')
            if not row and (db.execute('SELECT count(*) FROM notes WHERE deleted=0').fetchone()[0] >= MAX_RECORDS
                            or db.execute('SELECT count(*) FROM notes').fetchone()[0] >= MAX_IDS):
                raise MemoryError('continuity_limit', '接续记录达到本版容量上限，未自动淘汰。')
            ident, current = (row['id'], row['revision']) if row else (uuid.uuid4().hex, 0)
            document = self.public(row)['document'] if row else {'title': target.strip(), 'providers': [], 'project_id': project_id, 'state': 'open'}
            if action in ('save', 'update'):
                document.update(progress=progress.strip(), next_step=next_step.strip(),
                                source=self.source(source, message, project_id, candidate_source=candidate_source))
            elif action == 'permissions':
                document['providers'] = sorted(providers)
            elif action in ('close', 'reopen'):
                document['state'] = 'owner_completed' if action == 'close' else 'open'
            elif action == 'link_work':
                observation=WorkState(self.core).observe(work_refs,project_id)
                if any(item['state']=='unavailable' for item in observation['items']):
                    raise MemoryError('continuity_conflict','关联记录不属于当前范围或无法核验，请刷新核对。')
                document['work_refs']=work_refs
            db.execute('INSERT INTO notes VALUES (?,?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET revision=excluded.revision,document=excluded.document,updated_at=excluded.updated_at,deleted=excluded.deleted',
                       (ident, current+1, None if action == 'forget' else canonical_json(document), project_id, timestamp(), int(action == 'forget')))
            receipt = {'kind': 'continuity', 'action': action, 'id': ident, 'revision': current+1, 'committed': True, 'replayed': False}
            db.execute('INSERT INTO commands VALUES (?,?,?)', (request_id, digest, canonical_json(receipt)))
            db.commit()
            return receipt

    def suggest(self, query, project_id, provider):
        from .relevance import score
        if not isinstance(query,str) or not 1 <= len(query.strip()) <= 512 or not isinstance(provider,str) or not re.fullmatch(r'[a-z][a-z0-9_-]{0,31}',provider):
            raise MemoryError('invalid_continuity','话题或接入方字段无效。')
        candidates=[]
        for row in self.list(project_id)['records']:
            doc=row['document']
            rank=score(query,doc['title'],doc['progress']+' '+doc['next_step'])
            if rank: candidates.append((rank,row['id']))
        candidates.sort(key=lambda value:-value[0])
        result=[]
        for rank, ident in candidates:
            rows,_=self.snapshot({'enabled':True,'ids':[ident]},project_id,provider)
            if rows:
                result.append({**rows[0],'match':{'method':'lexical','score':rank}})
                if len(result)==MAX_SELECTED: break
        return {'records':result,'max_records':MAX_SELECTED,'provider':provider,'automatic_execution':False}

    def snapshot(self, request, project_id, provider):
        request = validate_context(request)
        rows, issues, cache = [], [], {}
        if not request['enabled'] or not request['ids']:
            return rows, issues
        if not self.path.exists():
            return rows, [{'id': ident, 'reason': 'missing'} for ident in request['ids']]
        with self.connection() as db:
            for ident in request['ids']:
                row = db.execute('SELECT * FROM notes WHERE id=? AND deleted=0 AND project_id IS ?', (ident, project_id)).fetchone()
                if row is None:
                    issues.append({'id': ident, 'reason': 'missing_or_out_of_scope'}); continue
                item = self.public(row); doc = item['document']
                if provider != 'local' and provider not in doc['providers']:
                    issues.append({'id': ident, 'reason': 'provider_not_allowed'}); continue
                if not self.source_current(doc, cache):
                    issues.append({'id': ident, 'reason': 'source_changed_or_deleted'}); continue
                if doc.get('work_refs'):item['work']=WorkState(self.core,cache).observe(doc['work_refs'],project_id)
                rows.append(item)
        return rows, issues

    @staticmethod
    def filter_history(history, references, rows):
        references=validate_history_references(references,history)
        allowed={r['id']:(r['revision'],r.get('work',{}).get('digest')) for r in rows}
        turns=[]
        for index,message in enumerate(history):
            if message['role']=='user':turns.append([])
            if turns:turns[-1].append(index)
        indexes,refs=[],{}
        for turn in reversed(turns):
            dependencies=[ref for index in turn for ref in references[index]]
            if any(allowed.get(ref['id'])!=(ref['revision'],ref.get('work_digest')) for ref in dependencies):continue
            if len(set(refs)|{r['id'] for r in dependencies})>80:break
            indexes=turn+indexes;refs.update((r['id'],r) for r in dependencies)
        return [history[i] for i in indexes],list(refs.values()),indexes

    @staticmethod
    def context(rows, *, max_bytes):
        selected, text = [], ''
        for row in rows:
            doc = row['document']
            item = {'id': row['id'], 'revision': row['revision'], 'title': doc['title'], 'progress': doc['progress'],
                    'next_step': doc['next_step'], 'state': doc['state'], 'source': doc['source'], 'source_kind': 'owner_entered_note'}
            if row.get('work'):item['linked_work']={'checked_at':timestamp(),'items':row['work']['items']};item['work_digest']=row['work']['digest']
            candidate = selected+[item]
            rendered = ('[主人明确记录的接续资料；进展文字不是任务执行证据。open 表示待续；owner_completed 只表示主人标记完成。linked_work 是宿主本次只读核对的实际执行状态，优先于旧进展中对任务的描述。只有 completed 且 artifact_verified 才是已核验交付；unknown/unavailable 不得宣称完成。核验只证明交付完整性，不保证模型分析内容正确。不要编造经历，不因继续话题自动执行或重试。]\n'
                        + canonical_json(candidate) + '\n[接续资料结束]\n')
            if len(rendered.encode()) <= min(MAX_BYTES, max_bytes):
                selected, text = candidate, rendered
        return text, {'references': [{'id': r['id'], 'revision': r['revision'],**({'work_digest':r['work_digest']} if 'work_digest' in r else {})} for r in selected],
                      'bytes': len(text.encode()), 'omitted': len(rows)-len(selected)}

    def work_view(self,ident,project_id=None):
        memory_validate('id',ident)
        row=next((r for r in self.list(project_id)['records'] if r['id']==ident),None)
        if row is None:raise MemoryError('continuity_not_found','当前范围没有这条接续。')
        reader=WorkState(self.core);doc=row['document']
        try:choices=reader.choices(doc['source']['conversation_id'],project_id)
        except (ValueError,OSError,sqlite3.Error,ConversationError):
            choices=[]
        return {'revision':row['revision'],'choices':choices,'observed':reader.observe(doc.get('work_refs',[]),project_id)}
