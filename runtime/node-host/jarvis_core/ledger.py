"""SQLite ownership and action ledger for a single-machine validation shell.

All participating processes must use this API and the worker lock. The control
file is not protected from another process running as this operating-system user.
"""
from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import sqlite3
import uuid

from . import policy
from .control import ControlGate
from .policy import CoreError, canonical_json, digest, safe_path

TERMINAL_ACTIONS = {"CONFIRMED", "FAILED", "CANCELLED", "UNKNOWN"}


def now():
    return datetime.now(timezone.utc).isoformat()


class Ledger:
    def __init__(self, data_dir):
        self.data_dir = Path(os.path.abspath(os.fspath(data_dir)))
        self.db_path = self.data_dir / "control.db"
        self.artifact_dir = self.data_dir / "artifacts"
        self.safety = ControlGate(self.data_dir)

    def _check_paths(self):
        safe_path(self.data_dir, directory=True)
        safe_path(self.db_path, directory=False)
        for suffix in ("-wal", "-shm", "-journal"):
            safe_path(str(self.db_path) + suffix, must_exist=False)

    @contextmanager
    def connection(self, timeout=5):
        from .storage_budget import timeout as bounded_timeout
        timeout = bounded_timeout(timeout)
        self._check_paths()
        connection = None
        try:
            connection = sqlite3.connect(self.db_path.as_uri() + "?mode=rw", uri=True, timeout=timeout, isolation_level=None)
            connection.row_factory = sqlite3.Row
            connection.execute("PRAGMA foreign_keys=ON")
            connection.execute("PRAGMA synchronous=FULL")
            if connection.execute("PRAGMA user_version").fetchone()[0] not in (1, 2):
                raise CoreError("control_invalid", "Unsupported or incomplete control database")
            yield connection
        except sqlite3.Error as exc:
            raise CoreError("control_unavailable", f"Control database refused the operation: {exc}") from exc
        finally:
            if connection is not None:
                connection.close()

    @contextmanager
    def transaction(self, timeout=5):
        with self.connection(timeout=timeout) as connection:
            connection.execute("BEGIN IMMEDIATE")
            try:
                yield connection
                connection.execute("COMMIT")
            except BaseException:
                if connection.in_transaction:
                    connection.execute("ROLLBACK")
                raise

    def initialize(self, allowed_root=None):
        safe_path(self.data_dir, must_exist=False)
        if self.db_path.exists():
            control = self.control()
            if allowed_root is not None:
                requested = safe_path(allowed_root, directory=True)
                if str(requested) != control["config"]["allowed_root"]:
                    raise CoreError("reconfiguration_denied", "init cannot change an existing allowed root")
            return
        if self.data_dir.exists() and any(self.data_dir.iterdir()):
            raise CoreError("control_invalid", "Missing control.db in nonempty data directory; refusing to reset state")
        root = safe_path(policy.DEFAULT_ALLOWED_ROOT if allowed_root is None else allowed_root, directory=True)
        info = root.stat()
        config = {"schema_version": 1, "node_id": str(uuid.uuid4()), "allowed_root": str(root),
                  "root_device": info.st_dev, "root_inode": info.st_ino,
                  "max_files": policy.MAX_FILES, "max_bytes": policy.MAX_BYTES, "policy_version": policy.POLICY_VERSION}
        policy.validate_config(config, self.data_dir)
        self.data_dir.mkdir(parents=True, exist_ok=True)
        safe_path(self.data_dir, directory=True)
        try:
            descriptor = os.open(self.db_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        except FileExistsError as exc:
            raise CoreError("initialization_busy", "Another process initialized this data directory; retry status") from exc
        os.close(descriptor)
        self.artifact_dir.mkdir()
        with (self.data_dir / "worker.lock").open("xb") as lock_file:
            lock_file.write(b"0")
            lock_file.flush()
            os.fsync(lock_file.fileno())
        connection = sqlite3.connect(self.db_path, isolation_level=None)
        try:
            connection.execute("PRAGMA journal_mode=WAL")
            connection.execute("PRAGMA synchronous=FULL")
            connection.execute("BEGIN IMMEDIATE")
            connection.execute("CREATE TABLE control (singleton INTEGER PRIMARY KEY CHECK(singleton=1), config TEXT NOT NULL, config_digest TEXT NOT NULL, stopped INTEGER NOT NULL CHECK(stopped IN(0,1)), stop_reason TEXT, stopped_at TEXT, worker_epoch INTEGER NOT NULL)")
            connection.execute("CREATE TABLE tasks (task_id TEXT PRIMARY KEY, request_key TEXT UNIQUE NOT NULL, arguments_digest TEXT NOT NULL, document TEXT NOT NULL, cancel_requested INTEGER NOT NULL DEFAULT 0, security_epoch INTEGER NOT NULL)")
            connection.execute("CREATE TABLE actions (action_id TEXT PRIMARY KEY, task_id TEXT UNIQUE NOT NULL REFERENCES tasks(task_id), document TEXT NOT NULL)")
            connection.execute("CREATE TABLE artifacts (artifact_id TEXT PRIMARY KEY, action_id TEXT UNIQUE NOT NULL REFERENCES actions(action_id), document TEXT NOT NULL)")
            encoded = canonical_json(config)
            connection.execute("INSERT INTO control VALUES (1,?,?,0,NULL,NULL,0)", (encoded, digest(encoded.encode("utf-8"))))
            self.safety.call("initialize", config["node_id"])
            connection.execute("PRAGMA user_version=2")
            connection.execute("COMMIT")
        except BaseException:
            if connection.in_transaction:
                connection.execute("ROLLBACK")
            raise
        finally:
            connection.close()

    def _control(self, connection):
        row = connection.execute("SELECT * FROM control WHERE singleton=1").fetchone()
        if row is None or row["stopped"] not in (0, 1):
            raise CoreError("control_invalid", "Missing or invalid safety control state")
        encoded = row["config"]
        if digest(encoded.encode("utf-8")) != row["config_digest"]:
            raise CoreError("control_invalid", "Control configuration digest mismatch")
        try:
            config = json.loads(encoded)
            policy.validate_config(config, self.data_dir)
        except (TypeError, ValueError, KeyError) as exc:
            raise CoreError("control_invalid", "Invalid control configuration") from exc
        result = {"config": config, "stopped": bool(row["stopped"]), "stop_reason": row["stop_reason"],
                  "stopped_at": row["stopped_at"], "worker_epoch": row["worker_epoch"]}
        if connection.execute("PRAGMA user_version").fetchone()[0] == 2:
            safety = self.safety.call("status")
            if safety["node_id"] != config["node_id"]:
                raise CoreError("safety_binding", "Control databases belong to different nodes")
            first = safety["incidents"][0] if safety["incidents"] else {}
            result.update(stopped=safety["stopped"], stop_reason=first.get("reason"),
                          stopped_at=first.get("created_at"), security_epoch=safety["security_epoch"])
        return result

    def upgrade_control(self):
        """Explicit v1 -> v2 migration; never clear a pre-existing stop."""
        with self.worker_lock(), self.transaction() as connection:
            if connection.execute("PRAGMA user_version").fetchone()[0] == 2:
                return self._control(connection)
            previous = self._control(connection)
            self.safety.call("initialize", previous["config"]["node_id"], stopped=previous["stopped"],
                             reason=previous["stop_reason"] or "Imported legacy stop")
            # Legacy pending work has no independent authorization. It remains
            # queryable, but cannot silently acquire the new security generation.
            connection.execute("ALTER TABLE tasks ADD COLUMN security_epoch INTEGER NOT NULL DEFAULT 0")
            connection.execute("PRAGMA user_version=2")
            return self._control(connection)

    def control(self):
        with self.connection() as connection:
            return self._control(connection)

    def _admit(self, connection, task_id=None):
        if connection.execute("PRAGMA user_version").fetchone()[0] != 2:
            raise CoreError("control_upgrade_required", "Run explicit upgrade-control before new work with this version")
        control = self._control(connection)
        if control["stopped"]:
            raise CoreError("stopped", "Persistent stop is latched; use the independent owner recovery entry")
        if task_id is not None:
            row = connection.execute("SELECT cancel_requested,security_epoch FROM tasks WHERE task_id=?", (task_id,)).fetchone()
            if row is None:
                raise CoreError("not_found", "Unknown task")
            if row["cancel_requested"]:
                raise CoreError("cancelled", "Task cancellation was requested")
            if row["security_epoch"] != control["security_epoch"]:
                raise CoreError("stale_authorization", "Task belongs to an old safety generation; no automatic re-admission")
        return control

    def assert_admitted(self, task_id=None):
        # Fast denial does not wait for a business database writer or corruption.
        if self.safety.store.directory.exists():
            self.safety.call("assert_running")
        with self.connection() as connection:
            return self._admit(connection, task_id)

    @contextmanager
    def effect_guard(self, task_id=None, expected_epoch=None):
        """Short local effect transaction; never hold this over a model request."""
        with self.transaction() as connection:
            control = self._admit(connection, task_id)
            epoch = control["security_epoch"] if expected_epoch is None else expected_epoch
            with self.safety.effect_guard(control["config"]["node_id"], epoch):
                yield connection

    @contextmanager
    def worker_lock(self):
        """OS releases the exclusive lock on process death; no PID/TTL guessing."""
        lock_path = safe_path(self.data_dir / "worker.lock", directory=False)
        with lock_path.open("r+b") as handle:
            identity = handle.fileno()
            if os.name == "nt":
                import msvcrt
                try:
                    handle.seek(0)
                    msvcrt.locking(identity, msvcrt.LK_NBLCK, 1)
                except OSError as exc:
                    raise CoreError("worker_busy", "Another local worker owns execution") from exc
                try:
                    yield
                finally:
                    handle.seek(0)
                    msvcrt.locking(identity, msvcrt.LK_UNLCK, 1)
            else:
                import fcntl
                try:
                    fcntl.flock(identity, fcntl.LOCK_EX | fcntl.LOCK_NB)
                except OSError as exc:
                    raise CoreError("worker_busy", "Another local worker owns execution") from exc
                try:
                    yield
                finally:
                    fcntl.flock(identity, fcntl.LOCK_UN)

    def _record(self, connection, action_id):
        action_row = connection.execute("SELECT * FROM actions WHERE action_id=?", (action_id,)).fetchone()
        if action_row is None:
            raise CoreError("not_found", "Unknown action")
        task_row = connection.execute("SELECT * FROM tasks WHERE task_id=?", (action_row["task_id"],)).fetchone()
        artifact_row = connection.execute("SELECT document FROM artifacts WHERE action_id=?", (action_id,)).fetchone()
        try:
            return {"task": json.loads(task_row["document"]), "action": json.loads(action_row["document"]),
                    "artifact": None if artifact_row is None else json.loads(artifact_row["document"]),
                    "cancel_requested": bool(task_row["cancel_requested"])}
        except (TypeError, ValueError, KeyError) as exc:
            raise CoreError("control_invalid", "Invalid ledger document") from exc

    def record(self, action_id=None, task_id=None):
        with self.connection() as connection:
            self._control(connection)
            if action_id is None:
                row = connection.execute("SELECT action_id FROM actions WHERE task_id=?", (task_id,)).fetchone()
                if row is None:
                    raise CoreError("not_found", "Unknown task")
                action_id = row["action_id"]
            return self._record(connection, action_id)

    def _save(self, connection, record):
        record["task"]["updated_at"] = now()
        connection.execute("UPDATE tasks SET document=? WHERE task_id=?", (canonical_json(record["task"]), record["task"]["task_id"]))
        connection.execute("UPDATE actions SET document=? WHERE action_id=?", (canonical_json(record["action"]), record["action"]["action_id"]))

    def prepare(self, request_key, arguments, *, capability="filesystem.read_sample.v1", runtime_seconds=policy.MAX_SECONDS, model_requests=0, _on_prepared=None):
        # Internal extension point: model output cannot select a capability or
        # enlarge a budget. Browser tasks enter only through their own validator.
        if capability not in {"filesystem.read_sample.v1", "browser.operate.v1", "sample.report.v1", "skill.report.v1", "mcp.documentation.v1"}:
            raise CoreError("invalid_capability", "Unsupported task executor")
        if not isinstance(request_key, str) or not 1 <= len(request_key) <= 128:
            raise CoreError("invalid_arguments", "request_id must contain 1 to 128 characters")
        arguments_digest = digest(canonical_json(arguments).encode("utf-8"))
        with self.transaction() as connection:
            control = self._admit(connection)
            config = control["config"]
            existing = connection.execute("SELECT * FROM tasks WHERE request_key=?", (request_key,)).fetchone()
            if existing is not None:
                if arguments_digest != existing["arguments_digest"]:
                    raise CoreError("idempotency_conflict", "The request_id already names different arguments")
                action = connection.execute("SELECT action_id FROM actions WHERE task_id=?", (existing["task_id"],)).fetchone()
                if self._record(connection, action["action_id"])["action"]["capability_id"] != capability:
                    raise CoreError("idempotency_conflict", "The request_id belongs to another executor")
                if existing["security_epoch"] != control["security_epoch"]:
                    raise CoreError("stale_authorization", "Request belongs to an old safety generation; inspect it, then use an explicit new request")
                record = self._record(connection, action["action_id"])
                if _on_prepared is not None:
                    _on_prepared(connection, record)
                return record
            token = uuid.uuid5(uuid.UUID(config["node_id"]), request_key).hex
            task_id, action_id = "task_" + token, "act_" + token
            task = {"schema_version": "1.0.0", "task_id": task_id, "goal_id": "goal_" + token,
                    "parent_task_id": None, "scope": "local", "owner_node_id": "node_" + config["node_id"],
                    "owner_epoch": 1, "workflow_version": "1.0.0", "skill_version": "1.0.0",
                    "planning_policy_version": config["policy_version"], "authorization_ref": "local:init:sample-input",
                    "checkpoint_schema": "task.checkpoint.v1", "budget": {"max_cost_units": 0, "max_runtime_seconds": policy.MAX_SECONDS, "max_attempts": 1},
                    "required_capabilities": ["filesystem.read_sample.v1", "artifact.write.v1"], "cancellation_ref": "cancel_" + token,
                    "status": "READY", "title": "Sample directory inventory", "created_at": now(), "updated_at": now(), "result_refs": []}
            action = {"schema_version": "1.0.0", "action_id": action_id, "intent_id": "intent_" + token, "task_id": task_id,
                      "capability_id": "filesystem.read_sample.v1", "resource_id": "sample-input", "host_instance_id": "host_pending",
                      "host_epoch": 0, "owner_epoch": 1, "enforcement_policy_version": config["policy_version"],
                      "arguments_digest": arguments_digest, "idempotency_support": "receiver_verified", "status": "PREPARED", "arguments": arguments}
            if capability == "browser.operate.v1":
                task.update(title="Scoped browser operation", authorization_ref="local:browser-task:"+arguments_digest[7:],
                            required_capabilities=[capability,"artifact.write.v1"],
                            budget={"max_cost_units":model_requests,"max_runtime_seconds":runtime_seconds,"max_attempts":1})
                action.update(capability_id=capability,resource_id="browser-task",idempotency_support="none")
            elif capability == 'sample.report.v1':
                task.update(title='Sample directory report',
                            authorization_ref='local:init:sample-input',
                            required_capabilities=['filesystem.read_sample.v1','artifact.write.v1'],
                            budget={'max_cost_units':model_requests,'max_runtime_seconds':runtime_seconds,'max_attempts':1})
                action.update(capability_id=capability, resource_id='sample-input')
            elif capability == 'skill.report.v1':
                task.update(title='Scoped skill workflow', authorization_ref='local:project-skill:'+arguments['project_id'],
                            required_capabilities=[capability, 'artifact.write.v1'],
                            budget={'max_cost_units': model_requests, 'max_runtime_seconds': runtime_seconds, 'max_attempts': 1})
                action.update(capability_id=capability, resource_id='project-skill')
            elif capability == 'mcp.documentation.v1':
                task.update(title='Context7 documentation query', authorization_ref='local:mcp-task:'+arguments_digest[7:],
                            required_capabilities=[capability, 'artifact.write.v1'],
                            budget={'max_cost_units': 0, 'max_runtime_seconds': runtime_seconds, 'max_attempts': 1})
                action.update(capability_id=capability, resource_id='context7', idempotency_support='local_ledger')
            connection.execute("INSERT INTO tasks(task_id,request_key,arguments_digest,document,security_epoch) VALUES (?,?,?,?,?)", (task_id, request_key, arguments_digest, canonical_json(task), control["security_epoch"]))
            connection.execute("INSERT INTO actions VALUES (?,?,?)", (action_id, task_id, canonical_json(action)))
            record = {"task": task, "action": action, "artifact": None, "cancel_requested": False}
            if _on_prepared is not None:
                _on_prepared(connection, record)
            return record

    def recover_orphans(self):
        """Caller holds worker_lock, so no compliant worker is still in flight."""
        recovered = []
        with self.transaction() as connection:
            self._control(connection)
            for row in connection.execute("SELECT action_id,document FROM actions").fetchall():
                if json.loads(row["document"])["status"] == "DISPATCHING":
                    record = self._record(connection, row["action_id"])
                    record["action"]["status"] = "UNKNOWN"
                    record["action"]["error"] = {"code": "missing_receipt", "message": "Worker ended without a committed receipt; automatic replay is forbidden"}
                    record["task"]["status"] = "UNKNOWN"
                    self._save(connection, record)
                    recovered.append(row["action_id"])
        return recovered

    def begin_dispatch(self, action_id, host_instance_id, *, _admission=None):
        with self.transaction() as connection:
            record = self._record(connection, action_id)
            control = self._admit(connection, record["task"]["task_id"])
            if record["action"]["status"] != "PREPARED":
                raise CoreError("invalid_state", "Only a prepared action can dispatch")
            if _admission is None:
                queued = connection.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='computer_queue'").fetchone()
                if queued and connection.execute('SELECT 1 FROM computer_queue WHERE task_id=?', (record['task']['task_id'],)).fetchone():
                    raise CoreError('queue_managed', 'This task is queue managed; resume or cancel it through the queue')
            # Trusted host extension, atomic with the dispatch transition.
            # Never pass a model or network callback here.
            if _admission is not None:
                _admission(connection, record)
            epoch = control["worker_epoch"] + 1
            connection.execute("UPDATE control SET worker_epoch=? WHERE singleton=1", (epoch,))
            record["action"].update(status="DISPATCHING", host_instance_id=host_instance_id, host_epoch=epoch,
                                    attempt_id="attempt_" + uuid.uuid4().hex, enforcement_policy_version=control["config"]["policy_version"])
            record["task"]["status"] = "RUNNING"
            self._save(connection, record)
            return record

    def complete(self, connection, action_id, artifact):
        record = self._record(connection, action_id)
        if record["action"]["status"] != "DISPATCHING":
            raise CoreError("invalid_state", "A receipt requires an executing action")
        record["action"].update(status="CONFIRMED", receipt_ref=artifact["artifact_id"])
        record["task"].update(status="SUCCEEDED", result_refs=[artifact["artifact_id"]])
        connection.execute("INSERT INTO artifacts VALUES (?,?,?)", (artifact["artifact_id"], action_id, canonical_json(artifact)))
        self._save(connection, record)

    def finish_without_receipt(self, action_id, state, error):
        if state not in {"FAILED", "CANCELLED", "UNKNOWN"}:
            raise ValueError("Invalid action outcome")
        with self.transaction() as connection:
            self._control(connection)
            record = self._record(connection, action_id)
            if record["action"]["status"] != "DISPATCHING":
                return
            record["action"].update(status=state, error=error)
            record["task"]["status"] = state
            self._save(connection, record)

    def cancel(self, task_id):
        with self.transaction() as connection:
            self._control(connection)
            row = connection.execute("SELECT action_id FROM actions WHERE task_id=?", (task_id,)).fetchone()
            if row is None:
                raise CoreError("not_found", "Unknown task")
            record = self._record(connection, row["action_id"])
            self._cancel_record(connection, record)
            return record

    def _cancel_record(self, connection, record):
        """Caller owns the transaction; replacement and cancellation commit together."""
        if record["action"]["status"] == "CONFIRMED":
            return
        connection.execute("UPDATE tasks SET cancel_requested=1 WHERE task_id=?", (record['task']['task_id'],))
        record["cancel_requested"] = True
        if record["action"]["status"] == "PREPARED":
            record["task"]["status"] = record["action"]["status"] = "CANCELLED"
        elif record["action"]["status"] == "DISPATCHING":
            record["task"]["status"] = "CANCELLING"
        self._save(connection, record)

    def stop(self, reason):
        if not isinstance(reason, str) or not 1 <= len(reason) <= 512:
            raise CoreError("invalid_arguments", "Stop reason must contain 1 to 512 characters")
        if self.safety.store.directory.exists():
            safety = self.safety.call("stop", reason)
        else:
            # Legacy instances retain their stop entry until explicit migration.
            with self.transaction() as connection:
                self._control(connection)
                connection.execute("UPDATE control SET stopped=1, stop_reason=COALESCE(stop_reason,?), stopped_at=COALESCE(stopped_at,?) WHERE singleton=1", (reason, now()))
            safety = {"stopped": True}
        try:
            with self.transaction(timeout=.05) as connection:
                for row in connection.execute("SELECT action_id FROM actions").fetchall():
                    record = self._record(connection, row["action_id"])
                    if record["action"]["status"] in {"PREPARED", "DISPATCHING"}:
                        connection.execute("UPDATE tasks SET cancel_requested=1 WHERE task_id=?", (record["task"]["task_id"],))
                        if record["action"]["status"] == "PREPARED":
                            record["task"]["status"] = record["action"]["status"] = "CANCELLED"
                        else:
                            record["task"]["status"] = "CANCELLING"
                        self._save(connection, record)
        except (CoreError, ValueError, KeyError, TypeError, OSError) as exc:
            return {"safety": safety, "reconciliation_error": str(exc)}
        return {"safety": safety}

    def summary(self):
        with self.connection() as connection:
            control = self._control(connection)
            tasks = [json.loads(row["document"]) for row in connection.execute("SELECT document FROM tasks ORDER BY rowid DESC LIMIT 100")]
            counts = {}
            for row in connection.execute("SELECT document FROM actions"):
                state = json.loads(row["document"])["status"]
                counts[state] = counts.get(state, 0) + 1
            return control, tasks, counts
