"""Legacy control-state compatibility, independent of the business/model DB.

This same-user implementation is not a protected OS supervisor. Pending stop
files deny admission before attempting SQLite, including when SQLite is busy.
Ordinary chat cancellation never latches this state. Personal use has no
recovery credentials; the explicit migration retains old events and epochs.
"""
from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import sqlite3
import stat
import uuid


class SafetyError(RuntimeError):
    def __init__(self, code, message):
        super().__init__(message)
        self.code = code


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def timestamp():
    return datetime.now(timezone.utc).isoformat()


def safe_path(value, *, exists=True):
    path = Path(os.path.abspath(value))
    if path.drive.startswith("\\\\"):
        raise SafetyError("safety_path", "Network paths are not supported")
    for current in (*reversed(path.parents), path):
        try:
            info = current.lstat()
        except FileNotFoundError:
            if exists:
                raise SafetyError("safety_missing", "Safety storage is missing; no automatic reset")
            continue
        if stat.S_ISLNK(info.st_mode) or getattr(info, "st_file_attributes", 0) & 0x400:
            raise SafetyError("safety_path", "Links/reparse points are forbidden")
    return path


def read_json(path, maximum=65536):
    path = safe_path(path)
    if not path.is_file() or path.stat().st_size > maximum:
        raise SafetyError("invalid_message", "Invalid or oversized JSON file")
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ValueError("duplicate key")
            result[key] = value
        return result
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"), object_pairs_hook=pairs)
    except (ValueError, UnicodeError) as exc:
        raise SafetyError("invalid_message", "Malformed JSON message") from exc


def validate_recovery(value):
    """Validate a legacy-state migration snapshot, not an authentication proof."""
    import re
    fields = {"schema_version", "kind", "node_id", "security_epoch", "incident_ids", "reason"}
    if not isinstance(value, dict) or set(value) != fields or value["schema_version"] != "1.1.0" or value["kind"] != "jarvis.local-maintenance":
        raise SafetyError("invalid_recovery", "Unknown local maintenance request")
    try:
        valid = (str(uuid.UUID(value["node_id"])) == value["node_id"]
                 and type(value["security_epoch"]) is int and value["security_epoch"] > 0
                 and isinstance(value["reason"], str) and 1 <= len(value["reason"]) <= 512 and bool(value["reason"].strip())
                 and isinstance(value["incident_ids"], list) and 0 < len(value["incident_ids"]) <= 10000
                 and all(isinstance(item, str) and re.fullmatch(r"incident_[0-9a-f]{32}", item) for item in value["incident_ids"])
                 and value["incident_ids"] == sorted(set(value["incident_ids"])))
    except (ValueError, TypeError, AttributeError):
        valid = False
    if not valid:
        raise SafetyError("invalid_recovery", "Invalid local maintenance snapshot")


class SafetyStore:
    def __init__(self, data_dir):
        self.directory = Path(data_dir).absolute() / "safety"
        self.db_path = self.directory / "control.db"
        self.pending_dir = self.directory / "pending"

    @contextmanager
    def connection(self, *, write=False):
        safe_path(self.db_path)
        safe_path(self.pending_dir)
        for suffix in ("-wal", "-shm", "-journal"):
            safe_path(str(self.db_path) + suffix, exists=False)
        db = None
        try:
            db = sqlite3.connect(self.db_path.as_uri() + "?mode=rw", uri=True, timeout=.25, isolation_level=None)
            db.row_factory = sqlite3.Row
            db.execute("PRAGMA synchronous=FULL")
            if db.execute("PRAGMA user_version").fetchone()[0] != 1:
                raise SafetyError("safety_invalid", "Unsupported safety storage version")
            if write:
                db.execute("BEGIN IMMEDIATE")
            yield db
            if write:
                db.execute("COMMIT")
        except sqlite3.Error as exc:
            raise SafetyError("safety_unavailable", "Safety storage unavailable; admission denied") from exc
        finally:
            if db is not None:
                if db.in_transaction:
                    db.rollback()
                db.close()

    def initialize(self, node_id, *, stopped=False, reason="Imported legacy stop"):
        uuid.UUID(node_id)
        safe_path(self.directory, exists=False)
        if self.directory.exists():
            current = self.status()
            if current["node_id"] != node_id:
                raise SafetyError("safety_binding", "Existing safety store belongs to another node")
            if stopped and not current["stopped"]:
                self.stop(reason)
            return
        self.directory.mkdir(mode=0o700)
        self.pending_dir.mkdir(mode=0o700)
        with self.db_path.open("xb"):
            pass
        db = sqlite3.connect(self.db_path, isolation_level=None)
        try:
            db.execute("PRAGMA journal_mode=WAL")
            db.execute("PRAGMA synchronous=FULL")
            db.execute("BEGIN IMMEDIATE")
            db.execute("CREATE TABLE state (id INTEGER PRIMARY KEY CHECK(id=1), node_id TEXT NOT NULL, epoch INTEGER NOT NULL CHECK(epoch>0), stopped INTEGER NOT NULL CHECK(stopped IN(0,1)), public_key TEXT)")
            db.execute("CREATE TABLE incidents (incident_id TEXT PRIMARY KEY, reason TEXT NOT NULL, created_at TEXT NOT NULL, resolved_epoch INTEGER)")
            db.execute("CREATE TABLE challenges (nonce TEXT PRIMARY KEY, document TEXT NOT NULL, used INTEGER NOT NULL CHECK(used IN(0,1)))")
            db.execute("CREATE TABLE audit (sequence INTEGER PRIMARY KEY, kind TEXT NOT NULL, created_at TEXT NOT NULL, details TEXT NOT NULL)")
            db.execute("INSERT INTO state VALUES (1,?,1,0,NULL)", (node_id,))
            db.execute("PRAGMA user_version=1")
            if stopped:
                self._record_stop(db, {"incident_id": "incident_" + uuid.uuid4().hex, "reason": reason, "created_at": timestamp()})
            db.commit()
        finally:
            db.close()

    def _pending(self):
        safe_path(self.pending_dir)
        return sorted(self.pending_dir.iterdir())

    def _state(self, db):
        row = db.execute("SELECT * FROM state WHERE id=1").fetchone()
        if row is None or row["stopped"] not in (0, 1) or type(row["epoch"]) is not int or row["epoch"] < 1:
            raise SafetyError("safety_invalid", "Invalid safety state")
        try:
            uuid.UUID(row["node_id"])
        except (ValueError, TypeError, AttributeError) as exc:
            raise SafetyError("safety_invalid", "Invalid node binding") from exc
        incidents = [dict(item) for item in db.execute("SELECT incident_id,reason,created_at FROM incidents WHERE resolved_epoch IS NULL ORDER BY incident_id")]
        if bool(incidents) != bool(row["stopped"]):
            raise SafetyError("safety_invalid", "Latch and incident set disagree")
        pending = [path.name for path in self._pending()]
        return {"node_id": row["node_id"], "security_epoch": row["epoch"],
                "stopped": bool(row["stopped"] or pending), "incidents": incidents,
                "pending_stops": pending, "recovery_mode": "local-manual-legacy-only"}

    def status(self):
        with self.connection() as db:
            return self._state(db)

    def _admit(self, db, node_id=None, epoch=None):
        state = self._state(db)
        if node_id is not None and node_id != state["node_id"]:
            raise SafetyError("safety_binding", "Safety node differs from task node")
        if state["stopped"]:
            raise SafetyError("stopped", "Independent stop latch is active")
        if epoch is not None and epoch != state["security_epoch"]:
            raise SafetyError("stale_authorization", "Old security generation; explicit new admission required")
        return state

    def assert_running(self, node_id=None, epoch=None):
        # Pending marker still denies admission if the SQL store is damaged.
        if self._pending():
            raise SafetyError("stopped", "Pending stop denies admission")
        with self.connection() as db:
            return self._admit(db, node_id, epoch)

    @contextmanager
    def effect_guard(self, node_id=None, epoch=None):
        with self.connection(write=True) as db:
            self._admit(db, node_id, epoch)
            yield
            # STOP can create a marker while this short effect is in flight.
            # A caller which may have written an effect must record UNKNOWN.
            self._admit(db, node_id, epoch)

    def _audit(self, db, kind, details):
        db.execute("INSERT INTO audit(kind,created_at,details) VALUES (?,?,?)", (kind, timestamp(), canonical(details)))

    def _record_stop(self, db, event):
        existing = db.execute("SELECT reason,created_at FROM incidents WHERE incident_id=?", (event["incident_id"],)).fetchone()
        if existing is not None:
            if dict(existing) != {"reason": event["reason"], "created_at": event["created_at"]}:
                raise SafetyError("safety_invalid", "Stop identifier collision")
            return
        db.execute("INSERT INTO incidents VALUES (?,?,?,NULL)", (event["incident_id"], event["reason"], event["created_at"]))
        db.execute("UPDATE state SET stopped=1, epoch=epoch+1 WHERE id=1")
        self._audit(db, "STOP", event)

    def reconcile_pending(self):
        # Process each independently; never delete an uncommitted marker.
        for path in self._pending():
            event = read_json(path, 4096)
            if (not isinstance(event, dict) or set(event) != {"incident_id", "reason", "created_at"}
                    or event["incident_id"] + ".json" != path.name
                    or not isinstance(event["reason"], str) or not 1 <= len(event["reason"]) <= 512
                    or not isinstance(event["created_at"], str)):
                raise SafetyError("safety_invalid", "Invalid pending stop; maintenance required")
            with self.connection(write=True) as db:
                self._state(db)
                self._record_stop(db, event)
            # A parallel reconciler may have removed this exact committed marker.
            try:
                path.unlink()
            except FileNotFoundError:
                pass

    def stop(self, reason):
        if not isinstance(reason, str) or not 1 <= len(reason) <= 512:
            raise SafetyError("invalid_arguments", "Stop reason must have 1 to 512 characters")
        safe_path(self.pending_dir)
        event = {"incident_id": "incident_" + uuid.uuid4().hex, "reason": reason, "created_at": timestamp()}
        marker = self.pending_dir / (event["incident_id"] + ".json")
        # File existence is deny-all, including a partial marker after a crash.
        with marker.open("xb") as output:
            output.write(canonical(event).encode("utf-8"))
            output.flush()
            os.fsync(output.fileno())
        try:
            self.reconcile_pending()
            return self.status()
        except (SafetyError, OSError) as exc:
            return {"stopped": True, "incident_id": event["incident_id"], "pending_stop": True,
                    "error": getattr(exc, "code", type(exc).__name__),
                    "message": "Stop marker retained; database reconciliation incomplete; no automatic resume"}

    def prepare_recovery(self, reason="Switch legacy stopped instance to personal use"):
        """Only for explicit migration of a historical latch; no credentials."""
        self.reconcile_pending()
        with self.connection() as db:
            state = self._state(db)
            if not state["stopped"] or state["pending_stops"]:
                raise SafetyError("recovery_unavailable", "No reconciled legacy stop to migrate")
            value = {"schema_version": "1.1.0", "kind": "jarvis.local-maintenance", "node_id": state["node_id"],
                     "security_epoch": state["security_epoch"],
                     "incident_ids": sorted(item["incident_id"] for item in state["incidents"]), "reason": reason}
            validate_recovery(value)
            return value

    def recover(self, value):
        """Migrate a historical stop without keys/passwords; never replay work."""
        validate_recovery(value)
        with self.connection(write=True) as db:
            state = self._state(db)
            if (value["node_id"] != state["node_id"] or value["security_epoch"] != state["security_epoch"]
                    or not state["stopped"] or state["pending_stops"]
                    or value["incident_ids"] != sorted(item["incident_id"] for item in state["incidents"])):
                raise SafetyError("recovery_stale", "Legacy state changed; inspect it again")
            next_epoch = state["security_epoch"] + 1
            db.execute("UPDATE state SET stopped=0,epoch=? WHERE id=1", (next_epoch,))
            db.execute("UPDATE incidents SET resolved_epoch=? WHERE resolved_epoch IS NULL", (next_epoch,))
            # Retain legacy tables/columns and audit, but retire outstanding v1 challenges.
            db.execute("UPDATE challenges SET used=1 WHERE used=0")
            self._audit(db, "RECOVER", {"mode": "local-manual-legacy-only", "security_epoch": next_epoch,
                                        "reason": value["reason"], "incident_ids": value["incident_ids"]})
        return self.status()
