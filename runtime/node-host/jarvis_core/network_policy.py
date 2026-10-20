"""Per-data-directory offline control. Application policy, not an OS firewall."""
from contextlib import closing
from datetime import datetime, timezone
import ipaddress
from pathlib import Path
import sqlite3
import sys
from urllib.parse import urlsplit

from . import policy

MESSAGE = 'Jarvis 已启用仅此软件离线；请使用本地能力，或在设置 → 网络与离线恢复联网。'
_process_policy = None


class NetworkDenied(policy.CoreError):
    def __init__(self, code='network_offline', message=MESSAGE):
        super().__init__(code, message)


def loopback(host):
    if host is None or host == 'localhost':
        return True
    try:
        address = ipaddress.ip_address(host)
        return address.is_loopback or bool(getattr(address, 'ipv4_mapped', None) and address.ipv4_mapped.is_loopback)
    except ValueError:
        return False


class NetworkPolicy:
    def __init__(self, data_dir):
        self.root = Path(data_dir).absolute()
        self.path = self.root / 'network-policy.db'

    def _path(self):
        for suffix in ('', '-wal', '-shm', '-journal'):
            policy.safe_path(str(self.path) + suffix, must_exist=False)
        return self.path

    def snapshot(self):
        value = {'offline': False, 'revision': 0, 'updated_at': None, 'valid': True}
        try:
            path = self._path()
            if path.exists():
                with closing(sqlite3.connect(path.as_uri() + '?mode=ro', uri=True, timeout=.05)) as db:
                    db.execute('PRAGMA query_only=ON')
                    if db.execute('PRAGMA user_version').fetchone()[0] != 1:
                        raise ValueError('Unknown network policy schema')
                    row = db.execute('SELECT offline,revision,updated_at FROM settings WHERE singleton=1').fetchone()
                    if not row or row[0] not in (0, 1) or type(row[1]) is not int or row[1] < 1:
                        raise ValueError('Invalid network policy')
                    value.update(offline=bool(row[0]), revision=row[1], updated_at=row[2])
        except (OSError, sqlite3.Error, ValueError, policy.CoreError):
            value.update(offline=True, revision=None, valid=False, error='network_policy_unavailable')
        return {**value, 'scope': 'application', 'process_guard': bool(_process_policy and _process_policy.root == self.root),
                'local_available': ['本地模型', '记忆与交流设置', '文件与确定性任务'],
                'blocked': ['云模型及认证', '远程 MCP', '在线余额查询', '受控浏览器', '设备资料同步'],
                'notice': '只限制此 Jarvis 数据目录对应的运行实例；不改变其他软件或系统网络。已外发请求无法撤回。应用级限制不等于系统防火墙。'}

    def change(self, offline, revision):
        if type(offline) is not bool or type(revision) is not int or revision < 0:
            raise policy.CoreError('network_request_invalid', '离线开关和修订号格式无效。')
        self.root.mkdir(parents=True, exist_ok=True)
        path = self._path()
        current = self.snapshot()
        if not current['valid']:
            raise NetworkDenied('network_policy_unavailable', '网络限制配置损坏或暂不可读，保持禁止外联；请检查本机存储。')
        with closing(sqlite3.connect(path, timeout=.1)) as db:
            with db:
                db.execute('BEGIN IMMEDIATE')
                version = db.execute('PRAGMA user_version').fetchone()[0]
                if version not in (0, 1):
                    raise NetworkDenied('network_policy_unavailable')
                db.execute('CREATE TABLE IF NOT EXISTS settings(singleton INTEGER PRIMARY KEY CHECK(singleton=1), offline INTEGER NOT NULL CHECK(offline IN(0,1)), revision INTEGER NOT NULL, updated_at TEXT NOT NULL)')
                row = db.execute('SELECT revision FROM settings WHERE singleton=1').fetchone()
                actual = row[0] if row else 0
                if actual != revision:
                    raise policy.CoreError('network_conflict', '网络设置已被另一页面修改，请刷新后重试。')
                db.execute('INSERT OR REPLACE INTO settings VALUES(1,?,?,?)',
                           (int(offline), actual + 1, datetime.now(timezone.utc).isoformat()))
                db.execute('PRAGMA user_version=1')
        return self.snapshot()

    def require_online(self, revision=None):
        value = self.snapshot()
        if value['offline']:
            raise NetworkDenied()
        if revision is not None and revision != value['revision']:
            raise NetworkDenied('network_policy_changed', '网络模式已切换，本轮联网请求结束；请核对结果后重新发起。')
        return value['revision']

    def check_model(self, item, provider, revision=None):
        if item.get('adapter', provider) == 'local':
            # A local label cannot smuggle a remote endpoint or a local proxy.
            value = urlsplit(item.get('endpoint', ''))
            if value.scheme != 'http' or value.hostname != '127.0.0.1' or value.port != 18180 or value.username or value.password:
                raise NetworkDenied('network_local_endpoint_invalid', '本地模型仅使用固定的 127.0.0.1:18180 入口。')
            return None
        return self.require_online(revision)


def activate_process(data_dir):
    """Install once in the real Host/transport child, never the caller's browser.

    Socket audit blocks new external connects, UDP sends and external DNS while
    offline. Managed HTTP paths separately guard existing requests and credentials.
    Native engines use pinned offline inputs; this is not hostile-code containment.
    """
    global _process_policy
    current = NetworkPolicy(data_dir)
    if _process_policy is not None:
        if _process_policy.root != current.root:
            raise RuntimeError('One process cannot own multiple network policies')
        return
    _process_policy = current

    def audit(event, args):
        if event not in {'socket.connect', 'socket.getaddrinfo', 'socket.gethostbyname', 'socket.gethostbyaddr', 'socket.getnameinfo', 'socket.sendto', 'subprocess.Popen'}:
            return
        if not current.snapshot()['offline']:
            return
        if event == 'subprocess.Popen':
            # Playwright's native driver has networking outside Python audit.
            if Path(str(args[0])).name.lower() in {'node.exe', 'node', 'msedge.exe', 'chrome.exe', 'chromium'}:
                raise NetworkDenied()
            return
        address = args[0] if event.startswith('socket.get') else args[-1] if event == 'socket.sendto' else args[1]
        host = address[0] if isinstance(address, tuple) else address
        if not loopback(host):
            raise NetworkDenied()

    sys.addaudithook(audit)
