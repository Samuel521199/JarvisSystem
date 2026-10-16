"""Browser executor sharing the core's single task ledger and stop authority."""
from contextlib import contextmanager
import json
import os
from pathlib import Path
import queue
import threading
import time
import uuid

from jarvis_core.policy import CoreError, canonical_json, digest, safe_path
from jarvis_core.ledger import TERMINAL_ACTIONS, now
from .browser import EdgeBrowser
from .planner import ModelPlanner, ScriptedDemoPlanner
from .protocol import ComputerError, validate_task, validate_action


class ScopedModelCore:
    def __init__(self, core, checkpoint):
        self.core, self.checkpoint, self.data_dir = core, checkpoint, core.data_dir

    def assert_running(self):
        self.checkpoint()
        return self.core.assert_running()

    @contextmanager
    def effect_guard(self):
        self.checkpoint()
        with self.core.effect_guard():
            self.checkpoint()
            yield


class ComputerService:
    def __init__(self, core, *, browser_factory=EdgeBrowser, planner_factory=ModelPlanner):
        self.core = core
        self.browser_factory, self.planner_factory = browser_factory, planner_factory

    def _steps(self, task_id):
        with self.core.ledger.connection() as db:
            if not db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='computer_steps'").fetchone():
                return []
            return [dict(row) for row in db.execute('SELECT ordinal,state,action_json,observation_digest,model_json FROM computer_steps WHERE task_id=? ORDER BY ordinal',(task_id,))]

    def _step(self, task_id, ordinal, state, *, action=None, observation=None, metadata=None, epoch=None):
        if state == 'IN_FLIGHT':
            with self.core.ledger.effect_guard(task_id, expected_epoch=epoch) as db:
                db.execute('INSERT INTO computer_steps VALUES(?,?,?,?,?,?,?)',
                           (task_id,ordinal,state,canonical_json(action),observation['digest'],canonical_json(metadata),now()))
        else:
            # Audit completion remains possible after STOP; no new effect.
            with self.core.ledger.transaction() as db:
                db.execute('UPDATE computer_steps SET state=? WHERE task_id=? AND ordinal=?',(state,task_id,ordinal))

    def _verify_receipt(self, record):
        self.core._verify_artifact(record['artifact'])
        report = json.loads((self.core.ledger.artifact_dir / record['artifact']['path']).read_text(encoding='utf-8'))
        image = report['screenshot']
        if Path(image['path']).name != image['path']:
            raise CoreError('artifact_unavailable','Invalid screenshot receipt')
        path = safe_path(self.core.ledger.artifact_dir / image['path'],directory=False)
        if path.stat().st_size > 2*1024*1024 or digest(path.read_bytes()) != image['digest']:
            raise CoreError('artifact_unavailable','Screenshot changed after commit')
        return report

    @staticmethod
    def _plan(planner, task, observation, checkpoint):
        results = queue.Queue(maxsize=1)
        def work():
            try:results.put((True,planner.plan(task,observation)))
            except Exception as exc:results.put((False,exc))
        threading.Thread(target=work,daemon=True,name='jarvis-computer-model').start()
        while True:
            checkpoint()
            try:ok,value = results.get(timeout=.1)
            except queue.Empty:continue
            checkpoint()
            if not ok:raise value
            return value

    def run(self, task, *, request_id=None, model='auto', scripted=False, headed=False, demo_html=None, _on_prepared=None, _before_dispatch=None):
        task = validate_task(task)
        control = self.core.assert_running()
        epoch = control['security_epoch']
        args = {'task':task,'model':model,'scripted':scripted,'demo':demo_html is not None}
        ledger = self.core.ledger
        with ledger.worker_lock():
            ledger.recover_orphans()
            record = ledger.prepare(request_id or uuid.uuid4().hex, args, capability='browser.operate.v1',
                                    runtime_seconds=task['timeout_seconds'], model_requests=0 if scripted else task['max_steps']*5)
            task_id, action_id = record['task']['task_id'], record['action']['action_id']
            if _on_prepared is not None:
                _on_prepared(record)
            if record['action']['status'] in TERMINAL_ACTIONS:
                if record['action']['status']=='CONFIRMED':self._verify_receipt(record)
                return record
            if _before_dispatch is None:
                with ledger.connection() as db:
                    queued = db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='computer_queue'").fetchone()
                    if queued and db.execute('SELECT 1 FROM computer_queue WHERE task_id=?',(task_id,)).fetchone():
                        raise ComputerError('queue_managed','此任务已进入持久队列，请从队列继续或取消。')
            with ledger.effect_guard(task_id,expected_epoch=epoch) as db:
                db.execute('CREATE TABLE IF NOT EXISTS computer_steps(task_id TEXT,ordinal INTEGER,state TEXT,action_json TEXT,observation_digest TEXT,model_json TEXT,created_at TEXT,PRIMARY KEY(task_id,ordinal))')
            record = ledger.begin_dispatch(action_id,self.core.host_instance_id, _admission=_before_dispatch)
            deadline = time.monotonic()+task['timeout_seconds']
            ended = threading.Event()
            def checkpoint():
                if ended.is_set():raise CoreError('cancelled','Browser run ended; late model output is discarded')
                self.core.assert_running()
                ledger.assert_admitted(task_id)
                if time.monotonic()>deadline:raise ComputerError('computer_timeout','Browser task time budget exhausted')
            browser = None
            effect_attempted, writing = False, False
            active_step = None
            try:
                scoped = ScopedModelCore(self.core, checkpoint)
                planner = ScriptedDemoPlanner() if scripted else self.planner_factory(scoped,model)
                browser = self.browser_factory(task,headed=headed,demo_html=demo_html)
                checkpoint(); browser.start(); checkpoint()
                for ordinal in range(task['max_steps']+1):
                    checkpoint()
                    observation = browser.observe()
                    if browser.succeeded():break
                    if ordinal == task['max_steps']:
                        raise ComputerError('computer_step_limit','Action budget exhausted before the expected result appeared')
                    action = self._plan(planner,task,observation,checkpoint)
                    validate_action(action,task,observation)
                    browser.check_fresh(observation)
                    checkpoint()
                    self._step(task_id,ordinal,'IN_FLIGHT',action=action,observation=observation,
                               metadata=planner.last_metadata,epoch=epoch)
                    active_step = ordinal
                    checkpoint()
                    effect_attempted = True
                    browser.act(action)
                    checkpoint()
                    self._step(task_id,ordinal,'CONFIRMED')
                    active_step = None
                checkpoint()
                screenshot = browser.screenshot()
                report = {'schema_version':1,'kind':'jarvis.computer-use','task_id':task_id,'action_id':action_id,
                          'scope':'fresh browser context; fixed targets; no native desktop access',
                          'observation_mode':'DOM; screenshots retained locally, not sent to the model',
                          'planner':'scripted-test' if scripted else 'model','verified':True,'success':task['success'],
                          'budget_unit':'maximum model requests (at most five provider attempts per planning turn), not currency',
                          'blocked_requests':browser.blocked_requests,'steps':self._steps(task_id),
                          'screenshot':{'path':action_id+'.png','digest':digest(screenshot),'size_bytes':len(screenshot)}}
                output = (canonical_json(report)+'\n').encode('utf-8')
                browser.close()
                browser = None
                if len(output)>2*1024*1024:raise ComputerError('output_limit','Receipt exceeds size limit')
                artifact={'schema_version':'1.0.0','artifact_id':'artifact_'+action_id[4:],'task_id':task_id,
                          'action_id':action_id,'path':action_id+'.json','digest':digest(output),
                          'media_type':'application/json','size_bytes':len(output)}
                # Stop is checked again before the bounded local commit.
                checkpoint()
                with ledger.effect_guard(task_id,expected_epoch=epoch) as db:
                    for name,raw in ((report['screenshot']['path'],screenshot),(artifact['path'],output)):
                        destination=safe_path(ledger.artifact_dir/name,must_exist=False)
                        writing=True
                        with destination.open('xb') as file:
                            file.write(raw);file.flush();os.fsync(file.fileno())
                    ledger.complete(db,action_id,artifact)
            except Exception as exc:
                code=getattr(exc,'code','computer_execution_failed')
                if active_step is not None:self._step(task_id,active_step,'UNKNOWN')
                uncertain=effect_attempted or writing or code=='model_unknown'
                state='UNKNOWN' if uncertain else ('CANCELLED' if code in {'cancelled','stopped','stale_authorization'} else 'FAILED')
                ledger.finish_without_receipt(action_id,state,{'code':code,'message':str(exc) if isinstance(exc,(CoreError,ComputerError)) else 'Browser execution failed; inspect recorded steps before retrying'})
            finally:
                ended.set()
                if browser:
                    try:browser.close()
                    except Exception:
                        # Lifecycle Job.close still executes in the backend's
                        # finally; completion is never claimed on this path.
                        ledger.finish_without_receipt(action_id,'UNKNOWN',{'code':'browser_cleanup_failed','message':'Browser cleanup failed; verify process state before resuming'})
            return ledger.record(action_id)

    def inspect(self, task_id):
        record=self.core.status(task_id)['record']
        if record['action']['capability_id']!='browser.operate.v1':
            raise CoreError('wrong_executor','Task is not a browser operation')
        report=self._verify_receipt(record) if record['action']['status']=='CONFIRMED' else None
        return {'record':record,'steps':self._steps(task_id),'report':report}
