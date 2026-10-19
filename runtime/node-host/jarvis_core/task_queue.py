"""One durable FIFO for fixed inventory and browser actions in the existing ledger.

The legacy computer_queue table names are retained to preserve existing tasks.
Task/action states remain solely in the ledger; this module only owns scheduling.
"""
import os
from datetime import datetime, timezone
import threading
import uuid

from . import __version__, policy
from .policy import CoreError, digest
from .resources import ResourceAdmission
ROOT = policy.REPOSITORY_ROOT


class TaskQueue:
    capacity = 20  # Waiting tasks; the one executing task has its own slot.

    def __init__(self, core, executor=None, *, error_type=CoreError, resources=None, sample_executor=None, skill_executor=None, mcp_executor=None, metrics=None):
        self.core, self.executor = core, executor
        self.sample_executor = sample_executor
        self.skill_executor = skill_executor
        self.mcp_executor = mcp_executor
        self.error_type = error_type
        self.owner = uuid.uuid4().hex
        self.wake, self.closing = threading.Event(), threading.Event()
        self.active_id = None
        self.metrics = metrics
        self.metric_token = None
        self.resources = resources if resources is not None else ResourceAdmission()
        core._recover()
        # Each cleanup backend only touches its registered, inactive stages.
        self.recovery = {'removed':[], 'active':[], 'retained':[]}
        self.browser_recovery = {'removed':[], 'active':[], 'retained':[]}
        if os.name == 'nt':
            from .worker import workspace
            from .worker_recovery import recover
            parent = workspace() / 'worker-staging'
            if parent.exists():
                try:
                    self.recovery = recover(parent)
                except CoreError as exc:
                    if exc.code != 'recovery_busy': raise
                    self.recovery['deferred'] = 'another_recovery_owner'
            from .browser_recovery import recover as recover_browser
            skill_parent = workspace() / 'skill-staging'
            if skill_parent.exists():
                try:
                    self.skill_recovery = recover(skill_parent)
                except CoreError as exc:
                    if exc.code != 'recovery_busy': raise
            browser_parent = workspace() / 'browser-staging'
            if browser_parent.exists():
                try:
                    self.browser_recovery = recover_browser(browser_parent)
                except CoreError as exc:
                    if exc.code != 'recovery_busy': raise
                    self.browser_recovery['deferred'] = 'another_recovery_owner'
        with core.ledger.transaction() as db:
            db.execute('CREATE TABLE IF NOT EXISTS computer_queue(task_id TEXT PRIMARY KEY REFERENCES tasks(task_id),version TEXT NOT NULL,demo_digest TEXT,unknown_reviewed INTEGER NOT NULL DEFAULT 0 CHECK(unknown_reviewed IN(0,1)))')
            db.execute('CREATE TABLE IF NOT EXISTS computer_queue_control(singleton INTEGER PRIMARY KEY CHECK(singleton=1),owner TEXT NOT NULL,paused INTEGER NOT NULL CHECK(paused IN(0,1)),error TEXT)')
            previous = db.execute('SELECT paused FROM computer_queue_control WHERE singleton=1').fetchone()
            inflight = db.execute("SELECT 1 FROM actions WHERE json_extract(document,'$.status')='DISPATCHING'").fetchone()
            paused = bool(self._pending(db)) or bool(previous and previous['paused']) or bool(inflight) or self._unreviewed(db)
            # A newer web host fences the older dispatcher. The shared worker
            # lock still protects any already executing action across hosts.
            db.execute('INSERT OR REPLACE INTO computer_queue_control VALUES(1,?,?,?)',
                       (self.owner, int(paused), 'restart_review' if paused else None))
        self.thread = threading.Thread(target=self._work, daemon=True, name='jarvis-task-queue')
        self.thread.start()

    @staticmethod
    def _pending(db):
        return db.execute("SELECT q.task_id,q.version,q.demo_digest,t.request_key,a.action_id,json_extract(a.document,'$.capability_id') AS capability FROM computer_queue q JOIN tasks t USING(task_id) JOIN actions a USING(task_id) WHERE json_extract(a.document,'$.status')='PREPARED' ORDER BY q.rowid").fetchall()

    @staticmethod
    def _unreviewed(db):
        return bool(db.execute("SELECT 1 FROM computer_queue q JOIN actions a USING(task_id) WHERE q.unknown_reviewed=0 AND json_extract(a.document,'$.status')='UNKNOWN' LIMIT 1").fetchone())

    def _owned(self, db):
        state = db.execute('SELECT * FROM computer_queue_control WHERE singleton=1').fetchone()
        if state is None or state['owner'] != self.owner or self.closing.is_set():
            raise self.error_type('queue_owner_changed', '队列已由新服务接管或正在关闭，请刷新当前服务页面。')
        return state

    def enqueue(self, task, options):
        control = self.core.assert_running()
        html = options['demo_html']
        html_digest = digest(html.encode('utf-8')) if html is not None else None
        args = {'task':task, 'model':options['model'], 'scripted':options['scripted'], 'demo':html is not None}

        def register(db, record):
            self._owned(db)
            if self.core.ledger._admit(db)['security_epoch'] != control['security_epoch']:
                raise CoreError('stale_authorization', 'Safety generation changed during queue admission')
            task_id = record['task']['task_id']
            if record['action']['status'] != 'PREPARED':
                return  # Terminal and in-flight re-submissions never replay.
            if db.execute('SELECT 1 FROM computer_queue WHERE task_id=?', (task_id,)).fetchone():
                return
            # The tentative task is rolled back too if the queue is full.
            if len(self._pending(db)) >= self.capacity:
                raise self.error_type('queue_full', '等待队列已满（20 个），请先完成或取消部分任务。')
            db.execute('INSERT INTO computer_queue(task_id,version,demo_digest) VALUES(?,?,?)', (task_id, __version__, html_digest))

        record = self.core.ledger.prepare(options['request_id'], args, capability='browser.operate.v1',
                  runtime_seconds=task['timeout_seconds'], model_requests=0 if options['scripted'] else task['max_steps']*5,
                  _on_prepared=register)
        self.wake.set()
        return {'task_id':record['task']['task_id'], 'request_id':options['request_id']}

    @staticmethod
    def inventory_digest():
        paths = ('runtime/node-host/jarvis_core/policy.py', 'runtime/node-host/jarvis_core/worker.py',
                 'runtime/node-host/jarvis_core/service.py',
                 'runtime/node-host/jarvis_core/worker_recovery.py',
                 'runtime/worker-host/jarvis_worker/windows.py', 'runtime/worker-host/worker.py',
                 'config/worker-profile.json')
        return digest(policy.canonical_json({p: digest((ROOT / p).read_bytes()) for p in paths}).encode())

    def enqueue_inventory(self, *, request_id, relative_path='.', max_files=None, max_bytes=None):
        control = self.core.assert_running()
        args = policy.arguments(relative_path, max_files, max_bytes, config=control['config'])
        binding = self.inventory_digest()
        def register(db, record):
            self._owned(db)
            if self.core.ledger._admit(db)['security_epoch'] != control['security_epoch']:
                raise CoreError('stale_authorization', 'Safety generation changed during queue admission')
            task_id = record['task']['task_id']
            if record['action']['status'] != 'PREPARED': return
            if db.execute('SELECT 1 FROM computer_queue WHERE task_id=?', (task_id,)).fetchone(): return
            if len(self._pending(db)) >= self.capacity:
                raise self.error_type('queue_full', '等待队列已满（20 个），请先完成或取消部分任务。')
            db.execute('INSERT INTO computer_queue(task_id,version,demo_digest) VALUES(?,?,?)',
                       (task_id, __version__, binding))
        record = self.core.ledger.prepare(request_id, args, _on_prepared=register)
        self.wake.set()
        return {'task_id':record['task']['task_id'], 'request_id':request_id}

    def sample_digest(self):
        from .sample_tasks import SOURCE_PATHS
        return digest(policy.canonical_json({'inventory': self.inventory_digest(),
            'workflow': {p: digest((ROOT/p).read_bytes()) for p in SOURCE_PATHS},
            'seed': digest((ROOT/'seed/system-manifest/seed-bundle.json').read_bytes())}).encode())

    def enqueue_sample(self, *, request_id, prompt, model='auto', relative_path='.', conversation_id=None,
                       _origin=None, _replacement=None):
        from .sample_tasks import CAPABILITY, TIMEOUT_SECONDS, validate_request
        if self.sample_executor is None: raise self.error_type('executor_unavailable', '固定报告执行器尚未接入。')
        control = self.core.assert_running()
        args = validate_request(prompt, model, relative_path, control['config'], conversation_id=conversation_id)
        binding = self.sample_digest()
        def register(db, record):
            self._owned(db)
            if self.core.ledger._admit(db)['security_epoch'] != control['security_epoch']:
                raise CoreError('stale_authorization', 'Safety generation changed during queue admission')
            task_id = record['task']['task_id']
            if _origin is not None:
                from .task_revisions import register_origin
                register_origin(self.core.ledger, db, record, _origin, _replacement)
            if record['action']['status'] != 'PREPARED': return
            if db.execute('SELECT 1 FROM computer_queue WHERE task_id=?', (task_id,)).fetchone(): return
            if len(self._pending(db)) >= self.capacity:
                raise self.error_type('queue_full', '等待队列已满（20 个），请先完成或取消部分任务。')
            db.execute('INSERT INTO computer_queue(task_id,version,demo_digest) VALUES(?,?,?)', (task_id, __version__, binding))
        record = self.core.ledger.prepare(request_id, args, capability=CAPABILITY,
                  runtime_seconds=TIMEOUT_SECONDS, model_requests=10, _on_prepared=register)
        self.wake.set()
        return {'task_id': record['task']['task_id'], 'request_id': request_id}

    def snapshot(self):
        with self.core.ledger.connection() as db:
            state = db.execute('SELECT * FROM computer_queue_control WHERE singleton=1').fetchone()
            pending = self._pending(db)
            running = db.execute("SELECT a.task_id FROM actions a WHERE json_extract(a.document,'$.status')='DISPATCHING'").fetchall()
            unreviewed = self._unreviewed(db)
        return {'paused':bool(state['paused']), 'owned':state['owner']==self.owner and not self.closing.is_set(),
                'waiting':len(pending), 'capacity':self.capacity, 'running':[r['task_id'] for r in running],
                'positions':{r['task_id']:i+1 for i,r in enumerate(pending)}, 'error':state['error'],
                'unreviewed_unknown':unreviewed,
                'resources':self.resources.snapshot()}

    def enqueue_skill(self, *, request_id, payload):
        from .skill_tasks import CAPABILITY, TIMEOUT_SECONDS
        if self.skill_executor is None:
            raise CoreError('executor_unavailable', '技能执行器尚未接入。')
        control = self.core.assert_running()
        service = self.skill_executor()
        args = service.admit(payload)
        binding = service.binding()
        def register(db, record):
            self._owned(db)
            if self.core.ledger._admit(db)['security_epoch'] != control['security_epoch']:
                raise CoreError('stale_authorization', '技能任务受理期间状态代际已变化。')
            if record['action']['status'] != 'PREPARED': return
            if db.execute('SELECT 1 FROM computer_queue WHERE task_id=?', (record['task']['task_id'],)).fetchone(): return
            if len(self._pending(db)) >= self.capacity:
                raise CoreError('queue_full', '等待队列已满。')
            db.execute('INSERT INTO computer_queue(task_id,version,demo_digest) VALUES(?,?,?)', (record['task']['task_id'], __version__, binding))
        selected = service.selection(args)['selected'][0]['id']
        record = self.core.ledger.prepare(request_id, args, capability=CAPABILITY, runtime_seconds=240 if args.get('coding') else TIMEOUT_SECONDS,
                                          model_requests=2 if args.get('coding') else 0 if selected=='anatomy.explainer' or selected=='rea.software-analysis' and not args.get('explain') else 1, _on_prepared=register)
        self.wake.set()
        return {'task_id': record['task']['task_id'], 'request_id': request_id}

    def enqueue_mcp(self, *, request_id, payload, automatic=None):
        from .mcp_tasks import CAPABILITY, TIMEOUT_SECONDS
        if self.mcp_executor is None:
            raise CoreError('executor_unavailable', 'MCP 文档执行器尚未接入。')
        control = self.core.assert_running()
        service = self.mcp_executor()
        args = service.admit(payload, automatic=automatic)
        binding = service.binding_for(args)
        def register(db, record):
            self._owned(db)
            if self.core.ledger._admit(db)['security_epoch'] != control['security_epoch']:
                raise CoreError('stale_authorization', 'MCP 任务受理期间状态代际已变化。')
            if record['action']['status'] != 'PREPARED': return
            if db.execute('SELECT 1 FROM computer_queue WHERE task_id=?', (record['task']['task_id'],)).fetchone(): return
            if len(self._pending(db)) >= self.capacity:
                raise CoreError('queue_full', '等待队列已满。')
            db.execute('INSERT INTO computer_queue(task_id,version,demo_digest) VALUES(?,?,?)', (record['task']['task_id'], __version__, binding))
        record = self.core.ledger.prepare(request_id, args, capability=CAPABILITY, runtime_seconds=TIMEOUT_SECONDS,
                                          model_requests=0, _on_prepared=register)
        self.wake.set()
        return {'task_id': record['task']['task_id'], 'request_id': request_id}

    def set_paused(self, paused):
        if type(paused) is not bool:
            raise self.error_type('invalid_request', 'paused 必须是布尔值。')
        if not paused:self.core.assert_running()
        with self.core.ledger.transaction() as db:
            self._owned(db)
            if not paused:
                for row in self._pending(db):
                    self.core.ledger._admit(db, row['task_id'])
                    self._validate_binding(row)
                # Continuing acknowledges only UNKNOWNs already visible now.
                # A previous host's still-running task may become UNKNOWN later.
                db.execute("UPDATE computer_queue SET unknown_reviewed=1 WHERE task_id IN (SELECT task_id FROM actions WHERE json_extract(document,'$.status')='UNKNOWN')")
            db.execute('UPDATE computer_queue_control SET paused=?,error=NULL WHERE singleton=1', (int(paused),))
        self.wake.set()
        return self.snapshot()

    def _validate_binding(self, row):
        if row['version'] != __version__:
            raise self.error_type('queue_version_changed', '队列中有旧版本任务，请核对并取消后按当前版本重新提交。')
        if row['capability'] == 'sample.report.v1':
            if row['demo_digest'] != self.sample_digest():
                raise self.error_type('queue_content_changed', '报告规划/执行器或种子清单已改变，请核对并取消旧任务后重新提交。')
            return None
        if row['capability'] == 'skill.report.v1':
            from .skill_tasks import SkillTaskService
            if row['demo_digest'] != SkillTaskService.binding():
                raise CoreError('queue_content_changed', '技能目录或执行器已变化，请核对旧任务。')
            return None
        if row['capability'] == 'mcp.documentation.v1':
            from .mcp_tasks import McpTaskService
            args = self.core.ledger.record(task_id=row['task_id'])['action']['arguments']
            if row['demo_digest'] != McpTaskService(self.core).binding_for(args):
                raise CoreError('queue_content_changed', 'MCP 执行器、连接或策略已变化，请核对旧任务。')
            return None
        if row['capability'] == 'filesystem.read_sample.v1':
            if row['demo_digest'] != self.inventory_digest():
                raise self.error_type('queue_content_changed', '目录执行器或配置已改变，请取消旧任务后重新提交。')
            return None
        html = (ROOT/'apps/computer-use/demo.html').read_text(encoding='utf-8') if row['demo_digest'] else None
        if html is not None and digest(html.encode('utf-8')) != row['demo_digest']:
            raise self.error_type('queue_content_changed', '演示页面已改变，请取消旧任务后重新提交。')
        return html

    def _admission(self, db, record):
        state = self._owned(db)
        if state['paused']:
            raise self.error_type('queue_paused', '队列已暂停；尚未派发此任务。')
        if self._unreviewed(db):
            raise self.error_type('result_unknown', '出现新的未确认结果，请核对任务记录后继续队列。')
        pending = self._pending(db)
        if not pending or pending[0]['task_id'] != record['task']['task_id']:
            raise self.error_type('queue_changed', '等待队列已改变，重新读取队列。')
        self._validate_binding(pending[0])
        # Recheck at the transaction that changes PREPARED to DISPATCHING.
        # Waiting never spends a model request or creates an execution intent.
        if not self.resources.check(pending[0]['capability']):
            raise self.error_type('resource_wait', '可用内存不足或尚未稳定，后台任务继续等待。')
        self.active_id = record['task']['task_id']
        if self.metrics is not None:
            # Queue age includes explicit pauses and service downtime; do not
            # call it pure scheduler latency. Wall-clock changes are clamped.
            try:
                created = datetime.fromisoformat(record['task']['created_at'])
                wait = max(0,(datetime.now(timezone.utc)-created).total_seconds()*1000)
            except (KeyError,ValueError,TypeError):
                wait = None
            self.metric_token = self.metrics.begin('task',queue_wait_ms=round(wait,2) if wait is not None else None)

    def _pause_on_error(self, code):
        with self.core.ledger.transaction() as db:
            if code=='result_unknown':
                if self._unreviewed(db):
                    db.execute('UPDATE computer_queue_control SET paused=1,error=? WHERE singleton=1', (code,))
            else:
                db.execute('UPDATE computer_queue_control SET paused=1,error=? WHERE singleton=1 AND owner=?', (code, self.owner))

    def _work(self):
        while not self.closing.is_set():
            self.wake.clear()
            retry = False
            delay = .25
            outcome = 'UNKNOWN'
            try:
                with self.core.ledger.connection() as db:
                    state = self._owned(db)
                    pending = self._pending(db) if not state['paused'] else []
                if pending:
                    retry = True
                    row = pending[0]
                    if not self.resources.check(row['capability']):
                        delay = self.resources.retry_seconds
                        raise self.error_type('resource_wait', '后台任务正在等待内存。')
                    html = self._validate_binding(row)
                    record = self.core.ledger.record(task_id=row['task_id'])
                    args = record['action']['arguments']
                    if row['capability'] == 'filesystem.read_sample.v1':
                        result = self.core.run(record['action']['action_id'], _before_dispatch=self._admission)
                    elif row['capability'] == 'sample.report.v1':
                        if self.sample_executor is None: raise self.error_type('executor_unavailable', '报告执行器尚未接入。')
                        result = self.sample_executor().run(record['action']['action_id'], _before_dispatch=self._admission)
                    elif row['capability'] == 'skill.report.v1':
                        if self.skill_executor is None: raise CoreError('executor_unavailable', '技能执行器尚未接入。')
                        result = self.skill_executor().run(record['action']['action_id'], _before_dispatch=self._admission)
                    elif row['capability'] == 'mcp.documentation.v1':
                        if self.mcp_executor is None: raise CoreError('executor_unavailable', 'MCP 执行器尚未接入。')
                        result = self.mcp_executor().run(record['action']['action_id'], _before_dispatch=self._admission)
                    else:
                        if self.executor is None:
                            raise self.error_type('executor_unavailable', '浏览器执行器尚未安装。')
                        result = self.executor().run(args['task'], request_id=row['request_key'], model=args['model'],
                                      scripted=args['scripted'], demo_html=html, _before_dispatch=self._admission)
                    if result['action']['status']=='UNKNOWN':
                        self._pause_on_error('result_unknown')
                    outcome = result['action']['status']
                else:
                    self.resources.idle()
            except Exception as exc:
                code = getattr(exc, 'code', 'queue_execution_failed')
                if code == 'resource_wait':
                    delay = self.resources.retry_seconds
                if code not in {'worker_busy','queue_changed','queue_paused','queue_owner_changed','cancelled','resource_wait'}:
                    try:
                        self.core._recover()
                        self._pause_on_error(code)
                    except (CoreError, OSError):pass
            finally:
                if self.metric_token is not None:
                    self.metrics.finish(self.metric_token,outcome)
                    self.metric_token = None
                self.active_id = None
            if not self.closing.is_set():
                self.wake.wait(delay if retry else None)

    def close(self):
        self.closing.set()
        # Serializes with begin_dispatch: after this transaction no new action
        # from this owner can start, including a race with the worker callback.
        with self.core.ledger.transaction() as db:
            db.execute('UPDATE computer_queue_control SET paused=1,error=? WHERE singleton=1 AND owner=?', ('service_closed', self.owner))
        active = self.active_id
        if active:self.core.cancel(active)
        self.wake.set()
        self.thread.join(12)
