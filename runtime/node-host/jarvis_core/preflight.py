"""Read-only K1 readiness observations, never an authorization decision.

No live ledger is opened (even a read-only SQLite connection can need WAL
sidecars). No credentials, model calls, permission changes or service starts.
"""
from __future__ import annotations

from datetime import datetime, timezone
from contextlib import closing
import csv
import errno
from importlib import metadata
import io
import json
import locale
import os
from pathlib import Path
import platform
import re
import socket
import sqlite3
import subprocess
import sys
import tomllib

from . import __version__, policy

BOUNDARIES = "config/runtime-boundaries.json"
SCHEMA = "contracts/schemas/preflight.schema.json"


def check(identifier, status, message, **evidence):
    return {"id": identifier, "status": status, "message": message, "evidence": evidence}


def system_query(executable, arguments):
    """Only fixed, display-only Windows commands; do not search the project PATH."""
    if executable not in {"whoami.exe", "icacls.exe"}:
        raise ValueError("Unsupported diagnostic command")
    if executable == "whoami.exe" and arguments != ["/user", "/fo", "csv", "/nh"]:
        raise ValueError("Only the fixed identity query is supported")
    if executable == "icacls.exe" and (len(arguments) != 1 or not Path(arguments[0]).is_absolute()):
        raise ValueError("Only one absolute path may be passed to the ACL display command")
    command = Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32" / executable
    try:
        result = subprocess.run([str(command), *arguments], capture_output=True, timeout=3,
                                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                                check=False)
        # Windows console tools use the OEM codepage when redirecting output.
        encoding = "oem" if os.name == "nt" else locale.getpreferredencoding(False)
        return {"exit_code": result.returncode,
                "stdout": result.stdout.decode(encoding, errors="replace")[:16384],
                "stderr": result.stderr.decode(encoding, errors="replace")[:4096]}
    except (OSError, subprocess.TimeoutExpired) as exc:
        return {"error": type(exc).__name__}


def identity_check():
    evidence = {"pid": os.getpid(), "role": "preflight_cli", "executable": sys.executable,
                "scope": "This diagnostic process only; other service identities are not inferred."}
    if os.name == "nt":
        result = system_query("whoami.exe", ["/user", "/fo", "csv", "/nh"])
        if result.get("exit_code") == 0:
            rows = list(csv.reader(io.StringIO(result["stdout"].strip())))
            if len(rows) == 1 and len(rows[0]) == 2 and re.fullmatch(r"S-\d+(?:-\d+)+", rows[0][1]):
                evidence.update(account=rows[0][0], sid=rows[0][1])
                return check("process.identity", "pass", "已读取本次预检进程的 Windows 身份。", **evidence)
        return check("process.identity", "unknown", "无法确认本次进程身份。", **evidence, query=result)
    evidence.update(uid=os.getuid(), effective_uid=os.geteuid(), groups=os.getgroups())
    return check("process.identity", "pass", "已读取本次预检进程的 POSIX 身份。", **evidence)


def path_check(identifier, path, *, directory=True):
    path = Path(path).absolute()
    evidence = {"path": str(path), "effective_permissions": "not_verified"}
    try:
        policy.safe_path(path, directory=directory)
        info = path.stat()
        evidence.update(mode=oct(info.st_mode), uid=info.st_uid, gid=info.st_gid)
        if os.name == "nt":
            evidence["acl"] = system_query("icacls.exe", [str(path)])
            if evidence["acl"].get("exit_code") != 0:
                return check(identifier, "unknown", "路径存在，但 ACL 证据不可读。", **evidence)
        else:
            evidence["acl"] = {"scope": "POSIX mode only; extended ACLs were not queried"}
        return check(identifier, "pass", "路径类型与权限元数据已读取；未验证隔离身份的有效访问权。", **evidence)
    except policy.CoreError as exc:
        return check(identifier, "fail", "路径缺失、类型不符或含链接/重解析点。", **evidence, error=exc.code)
    except OSError as exc:
        return check(identifier, "fail", "无法读取路径权限元数据。", **evidence, error=type(exc).__name__)


def port_check(port):
    if type(port) is not int or not 1 <= port <= 65535:
        raise ValueError("Port must be an integer from 1 to 65535")
    # Bind and immediately close; never connect to or send requests to a server.
    # Exclusive bind is necessary on Windows to avoid a false 'free' with reuse.
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
            if os.name == "nt":
                probe.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
            probe.bind(("127.0.0.1", port))
        return check(f"port.{port}", "pass", "本次可绑定；启动服务前仍须重新检查。",
                     host="127.0.0.1", port=port, observation="bindable_now")
    except OSError as exc:
        busy = exc.errno == errno.EADDRINUSE or getattr(exc, "winerror", None) == 10048
        return check(f"port.{port}", "warn" if busy else "unknown",
                     "端口已占用，可能是已启动的服务；未认定服务身份。" if busy else "端口不可绑定，未将原因猜测为已占用。",
                     host="127.0.0.1", port=port, observation="occupied" if busy else "unavailable",
                     error=type(exc).__name__, errno=exc.errno)


def dependency_checks(project):
    checks = []
    for requirement in project["dependencies"]:
        match = re.fullmatch(r"([A-Za-z0-9_-]+)(?:\[[A-Za-z0-9_,.-]+\])?==([A-Za-z0-9.+_-]+)", requirement)
        if match is None:
            checks.append(check("dependency.specification", "unknown", "预检只接受核心依赖的精确版本锁。"))
            continue
        name, expected = match.groups()
        try:
            actual = metadata.version(name)
        except metadata.PackageNotFoundError:
            actual = None
        checks.append(check(f"dependency.{name}", "pass" if actual == expected else "fail",
                            "核心依赖元数据版本匹配。" if actual == expected else "核心依赖缺失或版本不匹配。",
                            package=name, expected=expected, installed=actual,
                            scope="Package metadata only; optional extras and import health not tested"))
    return checks


def source_check(root):
    """Hash a bounded allowlist of runtime inputs, never user data or credentials."""
    paths = ["pyproject.toml", "uv.lock", "apps/cli/main.py", BOUNDARIES, SCHEMA,
             "runtime/sovereignty-supervisor/jarvis_safety/store.py", "runtime/recovery-cli/main.py",
             "config/worker-profile.json", "runtime/worker-host/worker.py", "runtime/worker-host/jarvis_worker/windows.py"]
    paths.extend(f"runtime/node-host/jarvis_core/{name}.py"
                 for name in ("__init__", "policy", "ledger", "service", "chat", "preflight", "control", "worker", "task_queue", "worker_recovery"))
    paths.extend(["apps/computer-use/main.py", "jarvis-computer.ps1", "apps/web/server.py", "apps/web/index.html", "apps/web/computer.js",
                  "contracts/schemas/computer-task.schema.json", "contracts/schemas/computer-action.schema.json",
                  "config/computer-use/demo-task.json", "apps/computer-use/demo.html"])
    paths.extend(f"adapters/computer-use/jarvis_computer/{name}.py"
                 for name in ("__init__", "protocol", "browser", "planner", "service", "web", "task_queue"))
    paths.extend(["apps/web/admin.html", "apps/web/admin.css", "apps/web/admin.js",
                  "contracts/schemas/model-admin.schema.json"])
    paths.extend(f"adapters/models/provider-native/jarvis_models/{name}.py"
                 for name in ("gateway", "catalog", "registry", "billing", "vault"))
    hashes, errors = {}, {}
    for relative in paths:
        try:
            path = policy.safe_path(root / relative, directory=False)
            if path.stat().st_size > 4 * 1024 * 1024:
                raise ValueError("Source file exceeds diagnostic size limit")
            hashes[relative] = policy.digest(path.read_bytes())
        except (OSError, ValueError, policy.CoreError) as exc:
            errors[relative] = getattr(exc, "code", type(exc).__name__)
    return check("source.fingerprint", "fail" if errors else "pass",
                 "源码与配置摘要；不是签名发布包或完整依赖闭包。", digests=hashes, errors=errors)


def collect_report(data_dir=None, *, root=None, ports=(18180, 18181)):
    root = Path(root or policy.REPOSITORY_ROOT).absolute()
    data = Path(data_dir or policy.default_data_dir()).absolute()
    checks = [identity_check(), source_check(root)]
    try:
        project = tomllib.loads(policy.safe_path(root / "pyproject.toml", directory=False).read_text(encoding="utf-8"))["project"]
        lock = tomllib.loads(policy.safe_path(root / "uv.lock", directory=False).read_text(encoding="utf-8"))
        locked = [item["version"] for item in lock["package"] if item["name"] == project["name"]]
        matches = project["version"] == __version__ and locked == [__version__]
        checks.append(check("runtime.version", "pass" if matches else "fail", "核对模块、项目与锁文件版本。",
                            module=__version__, project=project["version"], locked=locked))
        supported = (3, 11) <= sys.version_info[:2] < (3, 14) and project["requires-python"] == ">=3.11,<3.14"
        checks.append(check("runtime.python", "pass" if supported else "fail", "核对已支持的 Python 版本范围。",
                            installed=platform.python_version(), required=project["requires-python"]))
        checks.extend(dependency_checks(project))
    except (OSError, ValueError, KeyError, TypeError, policy.CoreError) as exc:
        checks.append(check("runtime.configuration", "fail", "项目或锁文件不可读取/解析。", error=type(exc).__name__))

    try:
        # A separate in-memory connection cannot recover or mutate live tasks.
        with closing(sqlite3.connect(":memory:")) as db:
            db.execute("SELECT 1").fetchone()
        checks.append(check("runtime.sqlite", "pass", "SQLite 内存连接可用；未打开运行账本。",
                            version=sqlite3.sqlite_version, threadsafety=sqlite3.threadsafety))
    except sqlite3.Error as exc:
        checks.append(check("runtime.sqlite", "fail", "SQLite 内存连接不可用。", error=type(exc).__name__))

    checks.extend([path_check("path.source", root), path_check("path.data", data),
                   path_check("path.artifacts", data / "artifacts"),
                   path_check("path.control", data / "control.db", directory=False)])
    # Do not read the private directory or vault contents, even for readiness.
    checks.append(check("control.live_state", "unknown", "预检不读取账本或恢复任务；锁存状态未评估。",
                        reason="No live SQLite connection or status() call"))
    checks.extend(port_check(port) for port in ports)
    from .worker import verify_bundle, require_acl_volume, WorkerError
    try:
        runtime, evidence = verify_bundle()
        checks.append(check('worker.bundle', 'pass', '固定 Worker 运行包摘要匹配；本次未启动 Worker 或修改 ACL。',
                            path=str(runtime), **evidence))
    except (WorkerError, policy.CoreError, OSError) as exc:
        checks.append(check('worker.bundle', 'fail', 'Worker 运行包不可用或摘要不匹配；禁止退回普通子进程。',
                            error=getattr(exc,'code',type(exc).__name__)))
    try:
        filesystem = require_acl_volume(root)
        checks.append(check('boundary.source_storage', 'warn', '源码卷支持 ACL；受保护部署身份仍未验证。',filesystem=filesystem))
    except (WorkerError, OSError) as exc:
        checks.append(check('boundary.source_storage', 'fail', '当前源码卷不能提供所需的 Windows ACL 保护。',
                            error=getattr(exc,'code',type(exc).__name__)))

    try:
        declarations = json.loads(policy.safe_path(root / BOUNDARIES, directory=False).read_text(encoding="utf-8"))
        # This file is descriptive evidence. It never grants capabilities and
        # cannot turn these unimplemented isolation gates green.
        checks.append(check("roles.declaration", "warn", "角色与资源矩阵是实现声明，不是部署或有效权限证明。",
                            declaration=declarations, source=BOUNDARIES))
    except (OSError, ValueError, policy.CoreError) as exc:
        checks.append(check("roles.declaration", "fail", "运行边界声明不可读取。", error=type(exc).__name__))
    for identifier, message in (
        ("boundary.supervisor", "历史控制存储保留兼容；受保护 OS 监督及全局强制停止尚未实现，当前个人使用延期。"),
        ("boundary.worker", "固定元数据 Worker 已实现 LPAC/Job；通用工具执行、受保护 Host 与全平台部署验收仍未完成。"),
    ):
        checks.append(check(identifier, "fail", message, evidence_level="implementation_gap"))
    checks.append(check("boundary.recovery", "warn",
                        "当前个人使用无需恢复密钥或密码；旧版状态可显式迁移，认证增强已由用户延期。",
                        evidence_level="deferred_by_owner"))
    status = "blocked" if any(c["status"] == "fail" for c in checks) else "incomplete"
    return {"schema_version": "1.0.0", "report_kind": "jarvis.preflight", "version": __version__,
            "captured_at": datetime.now(timezone.utc).isoformat(),
            "environment": {"platform": platform.platform(), "python": platform.python_version()},
            "readiness": status, "checks": checks,
            "limitations": ["Point-in-time diagnostic; not an admission token or a full K1 gate pass.",
                            "Protected-deployment gaps are retained as unverified; owner-deferred authentication is not a personal-use prerequisite.",
                            "ACL metadata is not an effective-access test by an isolated worker.",
                            "Live stop/task state and existing service ownership were not inspected.",
                            "No file writes, model calls, service starts or permission changes; ports are briefly bound and closed."]}


def format_report(report):
    labels = {"pass": "已核对", "fail": "未满足", "warn": "提示", "unknown": "未确认"}
    lines = [f"Jarvis {report['version']} · K1 运行预检", "K1 就绪状态：条件未满足（不是执行授权）"]
    lines.extend(f"[{labels[item['status']]}] {item['id']}：{item['message']}" for item in report["checks"])
    lines.append("使用 --json 查看身份、权限元数据、版本与源码摘要。预检不初始化、不停止、不解锁。")
    return "\n".join(lines)
