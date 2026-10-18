"""Bounded ASAR acquisition into REA's existing filtered directory snapshot.

Only the documented pickle header and member ranges are decoded here; semantic
analysis remains in the pinned REA parser. No archive member is executed.
"""
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import struct

from . import policy
from .project_files import ProjectFiles, excluded, relative

MAX_ARCHIVE = 128 * 1024 * 1024
MAX_HEADER = 4 * 1024 * 1024


def signature(info):
    return info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_nlink


def unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result: raise ValueError('Duplicate ASAR metadata key')
        result[key] = value
    return result


def entries(stream, size, checkpoint):
    prefix = stream.read(16)
    if len(prefix) != 16: raise ValueError('Truncated ASAR header')
    marker, header_size, payload_size, json_size = struct.unpack('<4I', prefix)
    if (marker != 4 or header_size < 8 or header_size > MAX_HEADER or header_size > size - 8
            or payload_size != header_size - 4 or json_size > payload_size - 4):
        raise ValueError('Invalid ASAR header bounds')
    header = json.loads(stream.read(json_size).decode('utf-8'), object_pairs_hook=unique_object)
    if not isinstance(header, dict) or not isinstance(header.get('files'), dict):
        raise ValueError('ASAR has no file table')
    pending = [('', header['files'], 0)]
    rows, seen, scanned, path_bytes = [], set(), 0, 0
    while pending:
        parent, children, depth = pending.pop()
        if depth > 24: raise ValueError('ASAR nesting exceeds 24 levels')
        for name, node in children.items():
            checkpoint(); scanned += 1
            if scanned > 4096: raise ValueError('ASAR exceeds 4096 entries')
            if not isinstance(node, dict) or '/' in name or '\\' in name:
                raise ValueError('Invalid ASAR member')
            path = relative(parent + name)
            path_bytes += len(path.encode('utf-8'))
            if path.casefold() in seen or path_bytes > 1024 * 1024:
                raise ValueError('Ambiguous or oversized ASAR paths')
            seen.add(path.casefold())
            if 'link' in node: raise ValueError('ASAR links are unsupported')
            if 'files' in node:
                if not isinstance(node['files'], dict) or any(k in node for k in ('size', 'offset')):
                    raise ValueError('Invalid ASAR directory')
                pending.append((path+'/', node['files'], depth+1)); continue
            count = node.get('size')
            if type(count) is not int or count < 0 or count > MAX_ARCHIVE:
                raise ValueError('Invalid ASAR member size')
            if type(node.get('unpacked', False)) is not bool:
                raise ValueError('Invalid ASAR unpacked flag')
            offset = None
            if not node.get('unpacked', False):
                value = node.get('offset')
                if not isinstance(value, str) or not re.fullmatch(r'[0-9]{1,16}', value):
                    raise ValueError('Invalid ASAR offset')
                offset = 8 + header_size + int(value)
                if offset > size or count > size - offset: raise ValueError('ASAR member leaves container')
            rows.append((path, node, offset))
    return sorted(rows, key=lambda row:row[0])


def snapshot(core, args, checkpoint, target, destination=None):
    from .rea import SUFFIXES, PUBLISHED_DIRS, MAX_FILE, MAX_FILES, MAX_TOTAL
    target = policy.safe_path(target, directory=False)
    before = target.stat()
    if before.st_nlink != 1 or not stat.S_ISREG(before.st_mode):
        raise policy.CoreError('rea_input_unsafe', 'ASAR 必须为普通文件，不支持链接。')
    if before.st_size > MAX_ARCHIVE:
        raise policy.CoreError('rea_input_limit', 'ASAR 容器最多 128 MiB，请选择较小的发布包或源码目录。')
    rows, omitted, total = [], [], 0
    try:
        with target.open('rb') as archive:
            opened = os.fstat(archive.fileno())
            listing = entries(archive, before.st_size, checkpoint)
            archive.seek(0); digest = hashlib.sha256()
            while block := archive.read(1024 * 1024):
                checkpoint(); digest.update(block)
                if archive.tell() > MAX_ARCHIVE: raise ValueError('ASAR changed size')
            for path, node, offset in listing:
                checkpoint()
                # Check each component so excluded directories remain excluded in a flat index.
                if any(excluded('/'.join(path.split('/')[:i]), allow_dirs=PUBLISHED_DIRS) for i in range(1, len(path.split('/'))+1)):
                    omitted.append({'path':path, 'reason':'排除目录或凭据名称'}); continue
                if Path(path).suffix.lower() not in SUFFIXES:
                    omitted.append({'path':path, 'reason':'当前静态解析不支持此格式'}); continue
                count = node['size']
                if len(rows) >= MAX_FILES or count > MAX_FILE or total + count > MAX_TOTAL:
                    raise policy.CoreError('rea_input_limit', 'ASAR 最多选入 128 个文本文件、单文件 16 MiB、合计 32 MiB。')
                if offset is None:
                    companion = policy.safe_path(Path(str(target)+'.unpacked') / path, directory=False)
                    info = companion.stat()
                    if info.st_nlink != 1 or info.st_size != count:
                        raise ValueError('ASAR companion size or links changed')
                    with companion.open('rb') as source:
                        source_info = os.fstat(source.fileno()); raw = source.read(MAX_FILE + 1)
                    if signature(info) != signature(source_info) or signature(info) != signature(policy.safe_path(companion).stat()):
                        raise ValueError('ASAR companion changed while reading')
                else:
                    archive.seek(offset); raw = archive.read(count)
                if len(raw) != count: raise ValueError('Truncated ASAR member')
                raw.decode('utf-8-sig')
                if b'\0' in raw: raise ValueError('Binary bytes in ASAR text member')
                member_digest = policy.digest(raw)
                integrity = node.get('integrity')
                if integrity is not None:
                    if (not isinstance(integrity, dict) or integrity.get('algorithm') != 'SHA256'
                            or integrity.get('hash') != member_digest.removeprefix('sha256:')):
                        raise ValueError('ASAR declared integrity mismatch')
                rows.append({'path':path, 'bytes':count, 'digest':member_digest,
                             'origin':{'container':args['target_path'], 'member':path, 'byte_offset':offset,
                                       'unpacked':offset is None, 'declared_hash_checked':integrity is not None}})
                total += count
                if destination:
                    output = destination / path; output.parent.mkdir(parents=True, exist_ok=True); output.write_bytes(raw)
        if signature(before) != signature(opened) or signature(before) != signature(policy.safe_path(target).stat()):
            raise policy.CoreError('rea_source_changed', 'ASAR 在读取期间发生变化，请重试。')
    except (OSError, ValueError, UnicodeError, RecursionError, TypeError, OverflowError) as exc:
        raise policy.CoreError('rea_asar_invalid', 'ASAR 索引、成员路径、内容或随包 .unpacked 文件未通过核对。') from exc
    if not any(Path(row['path']).suffix.lower() in {'.js', '.mjs', '.cjs'} for row in rows):
        raise policy.CoreError('rea_input_unsupported', 'ASAR 中没有可解析的 UTF-8 JavaScript 文件。')
    ProjectFiles(core).root(args['project_id'])
    container = {'path':args['target_path'], 'digest':'sha256:'+digest.hexdigest(), 'bytes':before.st_size}
    return {'target_path':args['target_path'], 'format':'asar', 'parser_input_format':'directory',
            'container':container, 'files':rows, 'omitted':omitted, 'total_bytes':total,
            'digest':policy.digest(policy.canonical_json({'container':container,'files':rows}).encode('utf-8'))}
