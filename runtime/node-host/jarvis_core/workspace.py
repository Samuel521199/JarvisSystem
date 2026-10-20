"""User-selected projects and explicit text exports, not an agent filesystem tool.

All mutations use the existing core effect guard. Paths and receipts are bound
before generation. Same-user filesystem races are outside the prototype's
protection boundary, as with the existing fixed file capability.
"""
from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path, PureWindowsPath
import re
import sqlite3
import subprocess
import sys
import threading
import uuid

from .policy import CoreError, safe_path

MAX_TEXT_BYTES = 1024 * 1024
MAX_PROJECTS = 200
ID = r"[a-f0-9]{32}"
RESERVED = re.compile(r"^(CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])(?:\.|$)", re.I)


def timestamp():
    return datetime.now(timezone.utc).isoformat()


def fail(code, message):
    raise CoreError(code, message)


def fields(payload, required, optional=()):
    if not isinstance(payload, dict) or not set(required) <= set(payload) or set(payload) - set(required) - set(optional):
        fail("invalid_request", "请求字段不完整或含有不支持的字段。")


def identifier(value):
    if not isinstance(value, str) or not re.fullmatch(ID, value):
        fail("invalid_request", "项目或保存请求标识无效。")
    return value


def identity(path):
    info = safe_path(path, directory=True).stat()
    return [info.st_dev, info.st_ino]


def native_folder_picker():
    """Tk runs in its own short-lived UI process; no paths become shell code."""
    script = '''import json, tkinter as tk
from tkinter import filedialog
root=tk.Tk()
root.withdraw()
root.attributes('-topmost', True)
try:
    path=filedialog.askdirectory(parent=root, title='选择 Jarvis 项目根文件夹', mustexist=True)
    print(json.dumps({'path':path}, ensure_ascii=True), flush=True)
finally:
    root.destroy()
'''
    try:
        result = subprocess.run([sys.executable, "-c", script], capture_output=True, text=True,
                                timeout=120, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        if result.returncode:
            raise ValueError("picker unavailable")
        return json.loads(result.stdout)["path"]
    except (OSError, ValueError, KeyError, subprocess.TimeoutExpired):
        fail("picker_unavailable", "系统目录选择器不可用或已超时，请输入文件夹的完整路径。")


class WorkspaceService:
    def __init__(self, core, *, picker=native_folder_picker):
        self.core = core
        self.data_dir = Path(core.data_dir).absolute()
        self.db_path = self.data_dir / "workspace.db"
        self.picker = picker
        self.picker_lock = threading.Lock()

    @contextmanager
    def connection(self):
        safe_path(self.data_dir, directory=True)
        for suffix in ("", "-journal", "-wal", "-shm"):
            safe_path(str(self.db_path) + suffix, must_exist=False)
        from .storage_budget import timeout as bounded_timeout
        db = sqlite3.connect(self.db_path, timeout=bounded_timeout(5), isolation_level=None)
        db.row_factory = sqlite3.Row
        try:
            db.execute("PRAGMA synchronous=FULL")
            db.execute("PRAGMA foreign_keys=ON")
            yield db
        finally:
            db.close()

    def initialize(self):
        with self.core.effect_guard(), self.connection() as db:
            version = db.execute("PRAGMA user_version").fetchone()[0]
            if version not in (0, 1):
                fail("workspace_unavailable", "项目数据版本不兼容。")
            db.execute("BEGIN IMMEDIATE")
            try:
                db.execute("CREATE TABLE IF NOT EXISTS projects (id TEXT PRIMARY KEY, path TEXT NOT NULL, path_key TEXT UNIQUE NOT NULL, identity TEXT NOT NULL, name TEXT NOT NULL, opened_at TEXT NOT NULL)")
                db.execute("CREATE TABLE IF NOT EXISTS outputs (id TEXT PRIMARY KEY, project_id TEXT NOT NULL REFERENCES projects(id), requested_path TEXT NOT NULL, destination TEXT NOT NULL, binding TEXT NOT NULL, state TEXT NOT NULL, digest TEXT, size_bytes INTEGER, created_at TEXT NOT NULL, completed_at TEXT, error TEXT)")
                db.execute("PRAGMA user_version=1")
                db.execute("COMMIT")
            except BaseException:
                db.execute("ROLLBACK")
                raise

    def _ready(self):
        self.core.assert_running()
        self.initialize()

    def _allowed_destination(self, path):
        # Runtime/control/credential trees are not user deliverable directories.
        protected = [self.data_dir]
        if os.environ.get("LOCALAPPDATA"):
            protected.append(Path(os.environ["LOCALAPPDATA"]) / "Jarvis" / "private")
        for private in protected:
            if path == private or path.is_relative_to(private):
                fail("path_denied", "请选择项目文件夹，不能向 Jarvis 的运行数据或凭据目录保存。")
        if any(part.lower() == ".git" for part in path.parts):
            fail("path_denied", "不能将交付物写入 Git 内部目录。")

    def _directory(self, value):
        if not isinstance(value, str) or not value or len(value) > 4096 or "\x00" in value:
            fail("invalid_path", "请输入现有文件夹的完整路径。")
        path = Path(value)
        if not path.is_absolute():
            fail("invalid_path", "项目文件夹必须使用绝对路径。")
        path = safe_path(path, directory=True)
        self._allowed_destination(path)
        if path == Path(path.anchor):
            fail("path_denied", "请选择具体项目文件夹，不能使用整个磁盘作为项目。")
        return path

    @staticmethod
    def _public_project(row):
        result = {key: row[key] for key in ("id", "name", "path", "opened_at")}
        try:
            result["available"] = identity(Path(row["path"])) == json.loads(row["identity"])
        except (CoreError, OSError):
            result["available"] = False
        return result

    def projects(self):
        self._ready()
        with self.connection() as db:
            return {"projects": [self._public_project(row) for row in db.execute("SELECT * FROM projects ORDER BY opened_at DESC")],
                    "max_text_bytes": MAX_TEXT_BYTES}

    def open_project(self, payload):
        fields(payload, {"path"})
        self._ready()
        path = self._directory(payload["path"])
        key = os.path.normcase(str(path))
        with self.core.effect_guard(), self.connection() as db:
            db.execute("BEGIN IMMEDIATE")
            existing = db.execute("SELECT * FROM projects WHERE path_key=?", (key,)).fetchone()
            current = identity(path)
            if existing and json.loads(existing["identity"]) != current:
                fail("project_replaced", "该位置的原项目目录已被替换，请先恢复原目录；不会自动重新绑定。")
            if not existing and db.execute("SELECT COUNT(*) FROM projects").fetchone()[0] >= MAX_PROJECTS:
                fail("project_limit", "项目数量已达本版本上限。")
            project_id = existing["id"] if existing else uuid.uuid4().hex
            db.execute("INSERT INTO projects VALUES (?,?,?,?,?,?) ON CONFLICT(path_key) DO UPDATE SET opened_at=excluded.opened_at",
                       (project_id, str(path), key, json.dumps(current), path.name, timestamp()))
            row = db.execute("SELECT * FROM projects WHERE id=?", (project_id,)).fetchone()
            db.execute("COMMIT")
        return self._public_project(row)

    def choose_project(self, payload):
        fields(payload, set())
        self.core.assert_running()
        if not self.picker_lock.acquire(blocking=False):
            fail("picker_busy", "目录选择器已经打开。")
        try:
            path = self.picker()
            return {"cancelled": True} if not path else {"cancelled": False, "project": self.open_project({"path": path})}
        finally:
            self.picker_lock.release()

    def create_project(self, payload):
        """Explicit single-directory creation, shared by browser and desktop UI."""
        fields(payload, {'path'})
        self._ready()
        value = payload['path']
        if not isinstance(value, str) or not value or len(value) > 4096 or '\0' in value:
            fail('invalid_path', '请输入新文件夹的完整路径。')
        path = Path(value)
        if not path.is_absolute() or not path.name:
            fail('invalid_path', '请指定完整路径和新文件夹名称。')
        from .project_files import relative
        relative(path.name)
        with self.core.effect_guard():
            parent = safe_path(path.parent, directory=True)
            target = safe_path(parent / path.name, must_exist=False)
            self._allowed_destination(target)
            if target.exists():
                # A repeated request may observe the directory already created.
                # Opening never replaces files or changes an existing directory.
                safe_path(target, directory=True)
                created = False
            else:
                target.mkdir(exist_ok=False)
                created = True
        # Registration owns its own control transaction. Never nest effect
        # guards: that would acquire the same SQLite write lock twice.
        return {**self.open_project({'path': str(target)}), 'created': created}

    def _project(self, db, project_id):
        row = db.execute("SELECT * FROM projects WHERE id=?", (identifier(project_id),)).fetchone()
        if row is None:
            fail("not_found", "未找到所选项目，请重新打开文件夹。")
        if not self._public_project(row)["available"]:
            fail("project_unavailable", "项目根目录已丢失、离线或被替换；没有改存其他目录。")
        return row

    def _target(self, root, value):
        if not isinstance(value, str) or not value or len(value) > 4096 or "\x00" in value:
            fail("invalid_path", "请输入文件名、项目内相对路径或明确的绝对路径。")
        portable = value.replace("\\", "/")
        parts = portable.split("/")
        if ".." in parts or portable.endswith("/") or portable.startswith("//"):
            fail("path_denied", "不支持父目录跳转、网络路径或缺少文件名的路径。")
        windows = PureWindowsPath(value)
        path = Path(value)
        if (windows.drive or windows.root) and not path.is_absolute():
            fail("path_denied", "请使用完整绝对路径，不能使用驱动器相对路径。")
        target = path if path.is_absolute() else root / path
        for part in target.parts[1:]:
            if part.endswith((" ", ".")) or RESERVED.match(part) or any(c in part for c in '<>:"|?*') or any(ord(c) < 32 for c in part):
                fail("invalid_path", "路径含不支持的名称、设备名或字符。")
        target = safe_path(target, must_exist=False)
        self._allowed_destination(target)
        if target.exists():
            fail("file_exists", "目标已存在；请换一个文件名，本版本不会覆盖原文件。")
        parent = target.parent
        while not parent.exists():
            parent = parent.parent
        return target, {"anchor": str(parent), "identity": identity(parent)}

    @staticmethod
    def _output(row):
        return {"request_id": row["id"], "project_id": row["project_id"], "path": row["destination"],
                "status": "UNKNOWN" if row["state"] == "WRITING" else row["state"],
                "digest": row["digest"], "size_bytes": row["size_bytes"], "created_at": row["created_at"],
                "completed_at": row["completed_at"], "error_category": row["error"]}

    def prepare(self, payload):
        fields(payload, {"project_id", "request_id"}, {"path"})
        self._ready()
        request_id = identifier(payload["request_id"])
        project_id = identifier(payload["project_id"])
        supplied = payload.get("path", "")
        if not isinstance(supplied, str):
            fail("invalid_path", "输出位置必须是文本路径。")
        name = supplied or ("回答-" + request_id[:12] + ".md")
        with self.core.effect_guard(), self.connection() as db:
            db.execute("BEGIN IMMEDIATE")
            project = self._project(db, project_id)
            existing = db.execute("SELECT * FROM outputs WHERE id=?", (request_id,)).fetchone()
            if existing:
                if existing["project_id"] != project_id or existing["requested_path"] != name:
                    fail("idempotency_conflict", "同一保存请求不能更换项目或文件路径。")
                return self._output(existing)
            target, binding = self._target(Path(project["path"]), name)
            db.execute("INSERT INTO outputs(id,project_id,requested_path,destination,binding,state,created_at) VALUES (?,?,?,?,?,'PREPARED',?)",
                       (request_id, project_id, name, str(target), json.dumps(binding), timestamp()))
            row = db.execute("SELECT * FROM outputs WHERE id=?", (request_id,)).fetchone()
            db.execute("COMMIT")
        return self._output(row)

    def outputs(self):
        self._ready()
        with self.connection() as db:
            return {"outputs": [self._output(row) for row in db.execute("SELECT * FROM outputs ORDER BY created_at DESC LIMIT 50")]}

    def save(self, request_id, payload):
        fields(payload, {"content"})
        request_id = identifier(request_id)
        text = payload["content"]
        if not isinstance(text, str) or not text or "\x00" in text:
            fail("invalid_content", "只支持非空文本内容。")
        body = text.encode("utf-8")
        if len(body) > MAX_TEXT_BYTES:
            fail("output_too_large", "文本文件超过 1 MiB，请缩短后另存。")
        digest = "sha256:" + hashlib.sha256(body).hexdigest()
        self._ready()
        # Persist intent before touching the destination. WRITING is never replayed.
        with self.core.effect_guard(), self.connection() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT * FROM outputs WHERE id=?", (request_id,)).fetchone()
            if row is None:
                fail("not_found", "保存请求不存在，请重新指定输出位置。")
            self._project(db, row["project_id"])
            if row["digest"] and row["digest"] != digest:
                fail("idempotency_conflict", "同一保存请求不能更改内容。")
            if row["state"] == "SAVED":
                self._verify(row)
                return self._output(row)
            if row["state"] != "PREPARED":
                fail("output_unresolved", "此保存请求已结束或结果待核对；不会重复写入，请检查文件后另存。")
            self._validate_binding(row)
            db.execute("UPDATE outputs SET state='WRITING',digest=?,size_bytes=? WHERE id=?", (digest, len(body), request_id))
            db.execute("COMMIT")
        opened = False
        try:
            with self.core.effect_guard(), self.connection() as db:
                self._project(db, row["project_id"])
                self._validate_binding(row)
                target = safe_path(row["destination"], must_exist=False)
                target.parent.mkdir(parents=True, exist_ok=True)
                safe_path(target.parent, directory=True)
                with target.open("xb") as output:
                    opened = True
                    output.write(body)
                    output.flush()
                    os.fsync(output.fileno())
                self.core.assert_running()
                verified = {**dict(row), "digest": digest, "size_bytes": len(body)}
                self._verify(verified)
                db.execute("UPDATE outputs SET state='SAVED',completed_at=? WHERE id=?", (timestamp(), request_id))
        except (OSError, CoreError, sqlite3.Error) as exc:
            code = getattr(exc, "code", "file_exists" if isinstance(exc, FileExistsError) else "save_failed")
            with self.connection() as db:
                db.execute("UPDATE outputs SET state=?,error=? WHERE id=?", ("UNKNOWN" if opened else "FAILED", code, request_id))
            fail("output_unknown" if opened else code, "保存结果待核对，请查看目标文件；不会自动重写。" if opened else "文件未保存，请检查目录、文件名和核心状态；没有改存其他位置。")
        with self.connection() as db:
            return self._output(db.execute("SELECT * FROM outputs WHERE id=?", (request_id,)).fetchone())

    def _validate_binding(self, row):
        binding = json.loads(row["binding"])
        if identity(Path(binding["anchor"])) != binding["identity"]:
            fail("path_denied", "输出位置的原目录已被替换；没有重新绑定。")
        safe_path(row["destination"], must_exist=False)
        self._allowed_destination(Path(row["destination"]))

    @staticmethod
    def _verify(row):
        path = safe_path(row["destination"], directory=False)
        if path.stat().st_size != row["size_bytes"] or path.stat().st_size > MAX_TEXT_BYTES or "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest() != row["digest"]:
            fail("output_changed", "已保存文件已被修改或不完整；不会覆盖。")
