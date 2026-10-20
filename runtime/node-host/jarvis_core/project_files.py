"""On-demand project explorer/editor. No recursive index, watcher or execution."""
from __future__ import annotations

import fnmatch
import json
import os
from pathlib import Path, PureWindowsPath
import re
import stat
import tempfile
import threading
import time

from .policy import CoreError, safe_path, digest
from .workspace import WorkspaceService, fields, fail, RESERVED, identity

MAX_FILE = 1024 * 1024
MAX_ENTRIES = 500
EXCLUDED = {'.git', '.hg', '.svn', 'node_modules', '__pycache__', '.venv', 'venv',
            '.cache', 'dist', 'build', 'target', '.next'}
TEXT_TYPES = {'.md', '.txt', '.rst', '.py', '.js', '.ts', '.tsx', '.jsx', '.json',
              '.yaml', '.yml', '.toml', '.ini', '.cfg', '.css', '.html', '.svg',
              '.xml', '.sql', '.sh', '.ps1', '.bat', '.cmd', '.c', '.h', '.cpp',
              '.cs', '.rs', '.go', '.java', '.kt', '.lua', '.r', '.rb', '.php',
              '.mmd', '.csv', '.gitignore', '.jarvis-workspace'}


def relative(value, *, empty=False):
    if not isinstance(value, str) or len(value) > 4096:
        fail('invalid_path', '项目路径必须是文本。')
    if not value and empty:
        return ''
    value = value.replace('\\', '/')
    if not value or PureWindowsPath(value).drive or value.startswith('/') or any(
        not part or part in {'.', '..'} or part.endswith((' ', '.')) or RESERVED.match(part)
        or any(c in part for c in '<>:"|?*') or any(ord(c) < 32 for c in part)
        for part in value.split('/')
    ):
        fail('path_denied', '请使用项目内的相对路径，不支持父目录跳转或特殊路径。')
    return value


def excluded(value, patterns=(), *, allow_dirs=()):
    parts = value.casefold().split('/')
    name = parts[-1]
    return (any(p in EXCLUDED - set(allow_dirs) for p in parts)
            or name == '.env' or name.startswith('.env.')
            or name in {'id_rsa', 'id_ed25519', 'credentials.json', 'secrets.json'}
            or Path(name).suffix in {'.pem', '.key', '.p12', '.pfx'}
            or any(fnmatch.fnmatchcase(value, p) or fnmatch.fnmatchcase(name, p)
                   or value.startswith(p.rstrip('/') + '/') for p in patterns))


def text_type(path):
    return path.suffix.lower() in TEXT_TYPES or path.name.lower() in {
        'dockerfile', 'makefile', 'license', '.gitignore', '.gitattributes', '.editorconfig'}


def read_text(path):
    path = safe_path(path, directory=False)
    before = path.stat()
    if before.st_nlink != 1 or before.st_size > MAX_FILE:
        fail('file_unsupported', '不支持硬链接或超过 1 MiB 的文本文件。')
    with path.open('rb') as stream:
        opened = os.fstat(stream.fileno())
        body = stream.read(MAX_FILE + 1)
    after = safe_path(path, directory=False).stat()
    signature = lambda s: (s.st_dev, s.st_ino, s.st_size, s.st_mtime_ns, s.st_nlink)
    if signature(before) != signature(opened) or signature(before) != signature(after):
        fail('file_conflict', '读取期间文件发生变化，请刷新。')
    if len(body) > MAX_FILE or b'\x00' in body:
        fail('file_unsupported', '此文件过大或不是可编辑文本。')
    try:
        content = body.decode('utf-8-sig')
    except UnicodeError:
        fail('file_unsupported', '本版本编辑器支持 UTF-8 文本；原文件未改动。')
    return {'content': content, 'digest': digest(body), 'size_bytes': len(body),
            'bom': body.startswith(b'\xef\xbb\xbf')}


class ProjectFiles:
    def __init__(self, core):
        self.core = core
        self.workspace = WorkspaceService(core)
        self.lock = threading.RLock()

    def root(self, project_id, *, ready=True):
        if ready:
            self.workspace._ready()
        with self.workspace.connection() as db:
            return Path(self.workspace._project(db, project_id)['path'])

    def target(self, root, value, *, empty=False, patterns=(), allow_dirs=()):
        value = relative(value, empty=empty)
        if value and excluded(value, patterns, allow_dirs=allow_dirs):
            fail('path_denied', '该路径属于排除目录或凭据文件。')
        target = safe_path(root / value, must_exist=False)
        if not target.is_relative_to(root):
            fail('path_denied', '路径必须位于当前项目中。')
        self.workspace._allowed_destination(target)
        return target

    @staticmethod
    def patterns(value):
        if not isinstance(value, list) or len(value) > 32 or any(
            not isinstance(p, str) or not p or len(p) > 160 or '\x00' in p
            or p.startswith(('/', '\\')) or '..' in p.split('/') or ':' in p for p in value
        ):
            fail('invalid_request', '排除项最多 32 条，使用相对路径或简单通配符。')
        return value

    def tree(self, payload):
        fields(payload, {'project_id', 'path'}, {'exclude'})
        root = self.root(payload['project_id'])
        patterns = self.patterns(payload.get('exclude', []))
        parent = self.target(root, payload['path'], empty=True, patterns=patterns)
        safe_path(parent, directory=True)
        rows, skipped, scanned, truncated = [], 0, 0, False
        deadline = time.monotonic() + 2
        with os.scandir(parent) as entries:
            for entry in entries:
                scanned += 1
                if scanned > 5000 or len(rows) >= MAX_ENTRIES or time.monotonic() > deadline:
                    truncated = True
                    break
                rel = (parent / entry.name).relative_to(root).as_posix()
                try:
                    target = self.target(root, rel, patterns=patterns)
                    info = target.lstat()
                    directory = stat.S_ISDIR(info.st_mode)
                    if not directory and (not stat.S_ISREG(info.st_mode) or info.st_nlink != 1):
                        skipped += 1
                        continue
                    rows.append({'name': entry.name, 'path': rel, 'kind': 'directory' if directory else 'file',
                                 'editable': not directory and text_type(target) and info.st_size <= MAX_FILE,
                                 'size_bytes': None if directory else info.st_size})
                except (CoreError, OSError):
                    skipped += 1
        rows.sort(key=lambda x: (x['kind'] != 'directory', x['name'].casefold()))
        return {'entries': rows, 'path': payload['path'], 'excluded': skipped, 'truncated': truncated}

    def read(self, payload):
        fields(payload, {'project_id', 'path'})
        root = self.root(payload['project_id'])
        target = self.target(root, payload['path'])
        if not text_type(target):
            fail('file_unsupported', '此类型暂不支持文本编辑。')
        return {'path': payload['path'], **read_text(target)}

    def mkdir(self, payload):
        fields(payload, {'project_id', 'path'})
        self.workspace._ready()
        with self.lock, self.core.effect_guard():
            root = self.root(payload['project_id'], ready=False)
            target = self.target(root, payload['path'])
            safe_path(target.parent, directory=True)
            if target.exists():
                safe_path(target, directory=True)
                return {'path': payload['path'], 'created': False}
            target.mkdir(exist_ok=False)
            return {'path': payload['path'], 'created': True}

    def write(self, payload):
        fields(payload, {'project_id', 'path', 'content', 'digest', 'bom'})
        content, expected = payload['content'], payload['digest']
        if not isinstance(content, str) or '\x00' in content or type(payload['bom']) is not bool:
            fail('invalid_request', '仅支持有效的文本内容。')
        if expected is not None and (not isinstance(expected, str) or not re.fullmatch(r'sha256:[a-f0-9]{64}', expected)):
            fail('invalid_request', '缺少有效文件版本。')
        body = (b'\xef\xbb\xbf' if payload['bom'] else b'') + content.encode('utf-8')
        if len(body) > MAX_FILE:
            fail('file_unsupported', '文件超过 1 MiB，编辑内容仍保留在页面中。')
        self.workspace._ready()
        with self.lock, self.core.effect_guard():
            root = self.root(payload['project_id'], ready=False)
            target = self.target(root, payload['path'])
            if not text_type(target):
                fail('file_unsupported', '此类型暂不支持文本编辑。')
            safe_path(target.parent, directory=True)
            parent_identity = identity(target.parent)
            current = read_text(target) if target.exists() else None
            if current and current['digest'] == digest(body):
                return {'path': payload['path'], **current}
            if (current['digest'] if current else None) != expected:
                fail('file_conflict', '磁盘文件已经变化；草稿保留，请重新打开文件核对后再保存。')
            if expected is None:
                # Exclusive creation never replaces an existing file.
                with target.open('xb') as output:
                    output.write(body); output.flush(); os.fsync(output.fileno())
            else:
                temp = None
                try:
                    with tempfile.NamedTemporaryFile(dir=target.parent, prefix='.jarvis-edit-', delete=False) as output:
                        temp = Path(output.name)
                        output.write(body); output.flush(); os.fsync(output.fileno())
                    # Preserve permission bits; arbitrary OS ACL/metadata preservation is not promised.
                    os.chmod(temp, target.stat().st_mode)
                    self.root(payload['project_id'], ready=False)
                    safe_path(target, directory=False)
                    if identity(target.parent) != parent_identity or read_text(target)['digest'] != expected:
                        fail('file_conflict', '保存期间文件发生变化；未替换原文件。')
                    os.replace(temp, target)
                    temp = None
                finally:
                    if temp is not None and temp.parent == target.parent:
                        temp.unlink(missing_ok=True)
            result = read_text(target)
            if result['digest'] != digest(body):
                fail('file_conflict', '写入后的文件再次变化，请核对磁盘内容。')
            return {'path': payload['path'], **result}

    def project_document(self, value):
        fields(value, {'schema_version', 'folders', 'view'})
        if type(value['schema_version']) is not int or value['schema_version'] != 1 or value['folders'] != [{'path': '.'}]:
            fail('invalid_workspace', '当前支持单文件夹工程，folders 必须为 [{"path":"."}]。')
        view = value['view']
        fields(view, {'open_files', 'active_file', 'exclude'})
        if not isinstance(view['open_files'], list) or len(view['open_files']) > 8:
            fail('invalid_workspace', '工程最多保存 8 个打开的文件位置。')
        for path in view['open_files']:
            relative(path)
        if view['active_file'] is not None and view['active_file'] not in view['open_files']:
            fail('invalid_workspace', '活动文件必须属于打开列表。')
        self.patterns(view['exclude'])
        return value

    def save_project(self, payload):
        fields(payload, {'project_id', 'path', 'document', 'digest'})
        path = relative(payload['path'])
        if '/' in path or not path.endswith('.jarvis-workspace'):
            fail('invalid_workspace', '工程文件保存在项目根目录，扩展名为 .jarvis-workspace。')
        content = json.dumps(self.project_document(payload['document']), ensure_ascii=False, indent=2) + '\n'
        return self.write({'project_id': payload['project_id'], 'path': path, 'content': content,
                           'digest': payload['digest'], 'bom': False})

    def open_project(self, payload):
        fields(payload, {'path'})
        value = payload['path']
        if not isinstance(value, str) or not Path(value).is_absolute() or not value.endswith('.jarvis-workspace'):
            fail('invalid_workspace', '请输入工程文件的完整路径。')
        target = safe_path(value, directory=False)
        self.workspace._allowed_destination(target)
        result = read_text(target)
        try:
            from json import JSONDecodeError
            def pairs(items):
                d = {}
                for k, v in items:
                    if k in d: fail('invalid_workspace', '工程文件含重复字段。')
                    d[k] = v
                return d
            document = self.project_document(json.loads(result['content'], object_pairs_hook=pairs))
        except (JSONDecodeError, RecursionError):
            fail('invalid_workspace', '工程文件不是有效 JSON。')
        # Validation precedes registration; document data never supplies commands or cloud permissions.
        project = self.workspace.open_project({'path': str(target.parent)})
        return {'project': project, 'document': document, 'path': target.name, 'digest': result['digest']}
