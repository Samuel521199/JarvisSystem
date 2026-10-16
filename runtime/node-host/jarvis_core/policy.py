"""Deterministic, fixed capability boundary for the K1 validation prototype.

Path checks are defense in depth, not protection against a hostile process with
this user's filesystem privileges. No source file contents are opened.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path, PurePosixPath, PureWindowsPath
import stat
import time

POLICY_VERSION = "1.0.0"
MAX_FILES = 1000
MAX_BYTES = 10 * 1024 * 1024
MAX_ENTRIES = 5000
MAX_OUTPUT_BYTES = 2 * 1024 * 1024
MAX_SECONDS = 10
CAPABILITIES = ("system.status.v1", "filesystem.read_sample.v1", "artifact.write.v1")
REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_ALLOWED_ROOT = REPOSITORY_ROOT / "tests" / "fixtures" / "workspace"


class CoreError(Exception):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


def canonical_json(value) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def digest(value: bytes) -> str:
    return "sha256:" + hashlib.sha256(value).hexdigest()


def safe_path(path, *, must_exist=True, directory=None) -> Path:
    """Reject links/reparse points in every existing path component."""
    path = Path(os.path.abspath(os.fspath(path)))
    if path.drive.startswith("\\\\"):
        raise CoreError("path_denied", "UNC/network roots are not supported")
    current = Path(path.anchor)
    for part in path.parts[1:]:
        current = current / part
        try:
            info = current.lstat()
        except FileNotFoundError:
            if must_exist:
                raise CoreError("path_missing", f"Required path does not exist: {current}")
            continue
        if stat.S_ISLNK(info.st_mode) or getattr(info, "st_file_attributes", 0) & 0x400:
            raise CoreError("path_denied", f"Links and reparse points are forbidden: {current}")
    if must_exist:
        info = path.lstat()
        if directory is True and not stat.S_ISDIR(info.st_mode):
            raise CoreError("path_denied", "Expected a directory")
        if directory is False and not stat.S_ISREG(info.st_mode):
            raise CoreError("path_denied", "Expected a regular file")
    return path


def default_data_dir() -> Path:
    base = os.environ.get("LOCALAPPDATA")
    if base:
        return Path(base) / "Jarvis" / "data"
    return Path.home() / ".local" / "share" / "Jarvis" / "data"


def validate_config(config: dict, data_dir: Path) -> None:
    expected = {"schema_version", "node_id", "allowed_root", "root_device", "root_inode", "max_files", "max_bytes", "policy_version"}
    if not isinstance(config, dict) or set(config) != expected:
        raise CoreError("control_invalid", "Invalid control configuration")
    if config["schema_version"] != 1 or config["policy_version"] != POLICY_VERSION:
        raise CoreError("control_invalid", "Unsupported control/policy version")
    import uuid
    try:
        uuid.UUID(config["node_id"])
    except (ValueError, TypeError, AttributeError):
        raise CoreError("control_invalid", "Invalid node identity")
    for key, maximum in (("max_files", MAX_FILES), ("max_bytes", MAX_BYTES)):
        if type(config[key]) is not int or not 1 <= config[key] <= maximum:
            raise CoreError("control_invalid", f"Invalid configured {key}")
    root = Path(config["allowed_root"])
    if not root.is_absolute() or root == data_dir or root.is_relative_to(data_dir) or data_dir.is_relative_to(root):
        raise CoreError("control_invalid", "Input and runtime data must be separate directory trees")
    if type(config["root_device"]) is not int or type(config["root_inode"]) is not int:
        raise CoreError("control_invalid", "Invalid root identity")


def source_root(config: dict) -> Path:
    root = safe_path(config["allowed_root"], directory=True)
    info = root.stat()
    if (info.st_dev, info.st_ino) != (config["root_device"], config["root_inode"]):
        raise CoreError("path_denied", "The configured root was replaced; reconfiguration is not automatic")
    return root


def arguments(relative_path=".", max_files=None, max_bytes=None, *, config) -> dict:
    if not isinstance(relative_path, str) or not relative_path or len(relative_path) > 4096:
        raise CoreError("invalid_arguments", "relative_path must be a bounded nonempty string")
    windows = PureWindowsPath(relative_path)
    portable = relative_path.replace("\\", "/")
    parts = PurePosixPath(portable)
    if windows.drive or windows.root or parts.is_absolute() or ".." in parts.parts or ":" in portable or "\x00" in portable:
        raise CoreError("path_denied", "Only relative paths without parent traversal are permitted")
    values = {"relative_path": parts.as_posix(), "max_files": config["max_files"] if max_files is None else max_files,
              "max_bytes": config["max_bytes"] if max_bytes is None else max_bytes}
    for key in ("max_files", "max_bytes"):
        if type(values[key]) is not int or not 1 <= values[key] <= config[key]:
            raise CoreError("limit_exceeded", f"{key} may only reduce the configured limit")
    return values


def collect_inventory(config: dict, args: dict, checkpoint) -> dict:
    started = time.monotonic()
    checkpoint()
    root = source_root(config)
    selected = safe_path(root / args["relative_path"], directory=True)
    if not selected.is_relative_to(root):
        raise CoreError("path_denied", "Input escaped configured root")
    files, total_bytes, visited = [], 0, 0
    pending = [(selected, 0)]
    while pending:
        checkpoint()
        if time.monotonic() - started > MAX_SECONDS:
            raise CoreError("limit_exceeded", "Inventory time limit exceeded")
        directory, depth = pending.pop()
        safe_path(directory, directory=True)
        if depth > 32:
            raise CoreError("limit_exceeded", "Directory depth exceeds 32")
        with os.scandir(directory) as entries:
            for entry in entries:
                visited += 1
                checkpoint()
                if visited > MAX_ENTRIES or time.monotonic() - started > MAX_SECONDS:
                    raise CoreError("limit_exceeded", "Inventory entry/time limit exceeded")
                entry_path = safe_path(entry.path)
                info = entry_path.lstat()
                if stat.S_ISDIR(info.st_mode):
                    pending.append((entry_path, depth + 1))
                elif stat.S_ISREG(info.st_mode):
                    total_bytes += info.st_size
                    if len(files) >= args["max_files"] or total_bytes > args["max_bytes"]:
                        raise CoreError("limit_exceeded", "Inventory file/byte limit exceeded")
                    relative = entry_path.relative_to(selected).as_posix()
                    files.append({"path": relative, "size_bytes": info.st_size,
                                  "type": entry_path.suffix.lower() or "file"})
                else:
                    raise CoreError("path_denied", "Only regular files and directories are supported")
    source_root(config)
    if time.monotonic() - started > MAX_SECONDS:
        raise CoreError("limit_exceeded", "Inventory time limit exceeded")
    files.sort(key=lambda item: item["path"])
    return {"schema_version": "1.0.0", "relative_path": args["relative_path"], "files": files,
            "total_files": len(files), "total_bytes": total_bytes}
