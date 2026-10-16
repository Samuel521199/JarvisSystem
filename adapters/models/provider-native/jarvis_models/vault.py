"""Windows current-user DPAPI storage. Never serialize secrets into source files."""
from __future__ import annotations

import base64
import ctypes
from ctypes import wintypes
import json
import os
from pathlib import Path
import tempfile


class VaultError(RuntimeError):
    pass


def default_path() -> Path:
    base = os.environ.get("LOCALAPPDATA")
    if not base:
        raise VaultError("LOCALAPPDATA unavailable")
    return Path(base) / "Jarvis" / "private" / "credentials.dpapi"


def _crypt(payload: bytes, decrypt: bool = False) -> bytes:
    if os.name != "nt":
        raise VaultError("This credential backend requires Windows DPAPI")

    class Blob(ctypes.Structure):
        _fields_ = [("size", wintypes.DWORD), ("data", ctypes.POINTER(ctypes.c_ubyte))]

    storage = (ctypes.c_ubyte * len(payload)).from_buffer_copy(payload)
    source = Blob(len(payload), storage)
    output = Blob()
    crypt32 = ctypes.WinDLL("crypt32", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.LocalFree.argtypes = [ctypes.c_void_p]
    kernel32.LocalFree.restype = ctypes.c_void_p
    function = crypt32.CryptUnprotectData if decrypt else crypt32.CryptProtectData
    function.argtypes = [ctypes.POINTER(Blob), ctypes.c_void_p, ctypes.POINTER(Blob),
                         ctypes.c_void_p, ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(Blob)]
    function.restype = wintypes.BOOL
    if not function(ctypes.byref(source), None, None, None, None, 1, ctypes.byref(output)):
        raise VaultError("DPAPI operation failed")
    try:
        return ctypes.string_at(output.data, output.size)
    finally:
        kernel32.LocalFree(output.data)
        ctypes.memset(storage, 0, len(payload))


def save(credentials: dict, path: Path | None = None) -> Path:
    target = path or default_path()
    target.parent.mkdir(parents=True, exist_ok=True)
    encrypted = _crypt(json.dumps(credentials).encode("utf-8"))
    envelope = {"schema_version": 1, "format": "windows-dpapi-current-user",
                "payload": base64.b64encode(encrypted).decode("ascii")}
    fd, name = tempfile.mkstemp(prefix="vault-", suffix=".tmp", dir=target.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(envelope, stream)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(name, target)
    finally:
        Path(name).unlink(missing_ok=True)
    return target


def load(path: Path | None = None) -> dict:
    try:
        envelope = json.loads((path or default_path()).read_text(encoding="utf-8"))
        if envelope.get("schema_version") != 1 or envelope.get("format") != "windows-dpapi-current-user":
            raise ValueError()
        return json.loads(_crypt(base64.b64decode(envelope["payload"], validate=True), decrypt=True))
    except Exception:
        raise VaultError("Credential vault unavailable or invalid") from None
