"""Small deterministic service facade; this is not an OS-protected supervisor."""
from __future__ import annotations

from contextlib import contextmanager
import json
import os
from pathlib import Path
import uuid
import threading
import time

from . import __version__, policy, worker
from .ledger import Ledger, TERMINAL_ACTIONS, now
from .policy import CoreError, canonical_json, digest, safe_path

LIMITATIONS = [
    "Restricted K1 validation prototype; K1 production isolation is not complete.",
    "The metadata Worker uses Windows LPAC/Job isolation; control and host remain under the caller OS user.",
    "Path checks do not defeat hostile concurrent filesystem mutation by that OS user.",
    "Stop blocks new guarded local effects; it cannot undo completed effects or cancel remote requests.",
    "Personal use has no recovery keys/passwords; legacy stopped data has an explicit local migration path.",
    "No semantic G0 proof, general-purpose sandbox, autonomous code execution or devices.",
    "Inventory is bounded metadata enumeration, not an atomic filesystem snapshot.",
]


class CoreService:
    def __init__(self, data_dir=None):
        self.data_dir = Path(policy.default_data_dir() if data_dir is None else data_dir).absolute()
        self.ledger = Ledger(self.data_dir)
        self.host_instance_id = "host_" + uuid.uuid4().hex
        self._security_epoch = None
        self._epoch_lock = threading.Lock()
        self.last_worker_evidence = None

    def initialize(self, allowed_root=None):
        self.ledger.initialize(allowed_root)
        return self.status()

    init = initialize

    def assert_running(self):
        """Instantaneous admission check; callers must handle later stop races."""
        control = self.ledger.assert_admitted()
        with self._epoch_lock:
            if self._security_epoch is None:
                self._security_epoch = control["security_epoch"]
            if self._security_epoch != control["security_epoch"]:
                raise CoreError("stale_authorization", "Restart the business host after owner recovery; old in-flight work remains invalid")
        return control

    @contextmanager
    def effect_guard(self):
        """Serialize a short local effect with stop; not for slow network work."""
        self.assert_running()
        with self.ledger.effect_guard(expected_epoch=self._security_epoch):
            yield

    def _recover(self):
        try:
            with self.ledger.worker_lock():
                return self.ledger.recover_orphans()
        except CoreError as exc:
            if exc.code == "worker_busy":
                return []
            raise

    def status(self, task_id=None):
        if not self.ledger.db_path.exists():
            return {"initialized": False, "stopped": True, "reason": "not_initialized",
                    "version": __version__, "limitations": LIMITATIONS}
        recovered = self._recover()
        control, tasks, counts = self.ledger.summary()
        result = {"initialized": True, "stopped": control["stopped"], "stop_reason": control["stop_reason"],
                  "stopped_at": control["stopped_at"], "version": __version__, "policy_version": control["config"]["policy_version"],
                  "allowed_root": control["config"]["allowed_root"], "artifact_dir": str(self.ledger.artifact_dir),
                  "capabilities": list(policy.CAPABILITIES), "action_counts": counts, "tasks": tasks,
                  "pending": sum(counts.get(state, 0) for state in ("PREPARED", "DISPATCHING", "UNKNOWN")),
                  "recovered_unknown": recovered, "limitations": LIMITATIONS}
        if task_id is not None:
            result["record"] = self.ledger.record(task_id=task_id)
        return result

    def prepare_inventory(self, *, relative_path=".", request_id=None, max_files=None, max_bytes=None):
        config = self.assert_running()["config"]
        args = policy.arguments(relative_path, max_files, max_bytes, config=config)
        request_id = uuid.uuid4().hex if request_id is None else request_id
        return self.ledger.prepare(request_id, args)

    def inventory(self, *, relative_path=".", request_id=None, max_files=None, max_bytes=None, prepare_only=False):
        prepared = self.prepare_inventory(relative_path=relative_path, request_id=request_id, max_files=max_files, max_bytes=max_bytes)
        if prepare_only:
            return prepared
        return self.run(prepared["action"]["action_id"])

    def _verify_artifact(self, artifact):
        if not isinstance(artifact, dict):
            raise CoreError("artifact_unavailable", "Confirmed action has no artifact receipt")
        relative = artifact["path"]
        if Path(relative).name != relative:
            raise CoreError("control_invalid", "Unexpected artifact path in receipt")
        path = safe_path(self.ledger.artifact_dir / relative, directory=False)
        if path.stat().st_size != artifact["size_bytes"] or path.stat().st_size > policy.MAX_OUTPUT_BYTES:
            raise CoreError("artifact_unavailable", "Artifact size no longer matches its committed receipt")
        if digest(path.read_bytes()) != artifact["digest"]:
            raise CoreError("artifact_unavailable", "Artifact digest no longer matches its committed receipt")

    def run(self, action_id, *, _before_dispatch=None):
        return self._run_inventory_action(action_id, _before_dispatch=_before_dispatch)

    def _run_inventory_action(self, action_id, *, capability='filesystem.read_sample.v1',
                              prepare=None, render=None, timeout_seconds=policy.MAX_SECONDS,
                              _before_dispatch=None):
        # Host-owned callbacks bind one fixed workflow; never accept callables
        # or executors from a plan, HTTP payload, skill file or extension.
        with self.ledger.worker_lock():
            self.ledger.recover_orphans()
            record = self.ledger.record(action_id)
            if record['action']['capability_id'] != capability:
                raise CoreError('wrong_executor', 'This action requires its registered executor')
            if record["action"]["status"] in TERMINAL_ACTIONS:
                if record["action"]["status"] == "CONFIRMED":
                    self._verify_artifact(record["artifact"])
                return record
            # A recovered node does not re-authorize an old host, even when
            # another host supplies a newly prepared task to this entry point.
            self.assert_running()
            record = self.ledger.begin_dispatch(action_id, self.host_instance_id, _admission=_before_dispatch)
            task_id = record["task"]["task_id"]
            write_attempted = False
            try:
                deadline = time.monotonic() + timeout_seconds
                def checkpoint():
                    self.assert_running()
                    self.ledger.assert_admitted(task_id)
                    if time.monotonic() > deadline:
                        raise CoreError('limit_exceeded', 'Task wall-time budget exceeded')
                config = self.ledger.assert_admitted(task_id)["config"]
                args = prepare(record, checkpoint) if prepare else record["action"]["arguments"]
                checkpoint()
                inventory = policy.collect_inventory(config, args, checkpoint)
                inventory, self.last_worker_evidence = worker.compute_inventory(
                    inventory, record=record, node_id=config['node_id'], host_id=self.host_instance_id,
                    epoch=self._security_epoch, checkpoint=checkpoint)
                checkpoint()
                result = render(inventory) if render else inventory
                output = (canonical_json(result) + "\n").encode("utf-8")
                if len(output) > policy.MAX_OUTPUT_BYTES:
                    raise CoreError("limit_exceeded", "Inventory output size limit exceeded")
                filename = action_id + ".json"
                artifact = {"schema_version": "1.0.0", "artifact_id": "artifact_" + action_id[4:],
                            "task_id": task_id, "action_id": action_id, "path": filename,
                            "digest": digest(output), "media_type": "application/json", "size_bytes": len(output)}
                # This short transaction is the final local admission boundary.
                # Independent STOP marks deny-all even during a short write.
                # If it races with the effect, the result remains UNKNOWN.
                with self.ledger.effect_guard(task_id, expected_epoch=self._security_epoch) as connection:
                    policy.source_root(config)
                    safe_path(self.ledger.artifact_dir, directory=True)
                    destination = safe_path(self.ledger.artifact_dir / filename, must_exist=False)
                    write_attempted = True
                    with destination.open("xb") as artifact_file:
                        artifact_file.write(output)
                        artifact_file.flush()
                        os.fsync(artifact_file.fileno())
                    self._verify_artifact(artifact)
                    self.ledger.complete(connection, action_id, artifact)
            except (CoreError, OSError) as exc:
                code = exc.code if isinstance(exc, CoreError) else "filesystem_error"
                state = "UNKNOWN" if write_attempted or code == 'model_unknown' else ("CANCELLED" if code in {"stopped", "cancelled"} else "FAILED")
                self.ledger.finish_without_receipt(action_id, state, {"code": code, "message": str(exc)})
            return self.ledger.record(action_id)

    def cancel(self, task_id):
        self._recover()
        return self.ledger.cancel(task_id)

    def stop(self, reason="Requested through the local CLI"):
        reconciliation = self.ledger.stop(reason)
        # Do not call status(): orphan recovery and task scanning depend on the
        # business DB. The existing degraded status shape stays compatible.
        safety = reconciliation.pop("safety")
        result = {"initialized": True, "stopped": safety["stopped"], "stop_reason": reason,
                  "diagnostic_error": "Business status deliberately not queried on independent stop path",
                  "limitations": LIMITATIONS}
        result.update(reconciliation)
        return result
