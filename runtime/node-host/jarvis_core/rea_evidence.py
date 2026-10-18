"""Receipt-bound REA evidence storage and bounded pages; no parser execution."""
import json
import os

from . import policy
from .rea import MAX_EVIDENCE


def prepare(action_id, evidence):
    raw = (policy.canonical_json(evidence) + '\n').encode('utf-8')
    if len(raw) > MAX_EVIDENCE:
        raise policy.CoreError('rea_output_limit', '完整解析证据超过 8 MiB，未截断交付。')
    return raw, {'path': action_id + '-evidence.json', 'digest': policy.digest(raw),
                 'size_bytes': len(raw), 'media_type': 'application/json', 'evidence_id': evidence['evidence_id']}


def save(core, reference, raw):
    path = policy.safe_path(core.ledger.artifact_dir / reference['path'], must_exist=False)
    with path.open('xb') as stream:
        stream.write(raw); stream.flush(); os.fsync(stream.fileno())
    read(core, reference, reference['path'].removesuffix('-evidence.json'))


def read(core, reference, action_id):
    if (not isinstance(reference, dict) or reference.get('path') != action_id + '-evidence.json'
            or type(reference.get('size_bytes')) is not int or not 0 < reference['size_bytes'] <= MAX_EVIDENCE):
        raise policy.CoreError('artifact_unavailable', '解析证据引用无效。')
    path = policy.safe_path(core.ledger.artifact_dir / reference['path'], directory=False)
    before = path.stat()
    if before.st_nlink != 1 or before.st_size != reference['size_bytes']:
        raise policy.CoreError('artifact_unavailable', '完整解析证据已变化。')
    with path.open('rb') as stream:
        opened = os.fstat(stream.fileno()); raw = stream.read(MAX_EVIDENCE + 1)
    after = policy.safe_path(path, directory=False).stat()
    signature = lambda s: (s.st_dev, s.st_ino, s.st_nlink, s.st_size, s.st_mtime_ns)
    if (signature(before) != signature(opened) or signature(before) != signature(after)
            or len(raw) != reference['size_bytes'] or policy.digest(raw) != reference['digest']):
        raise policy.CoreError('artifact_unavailable', '完整解析证据已变化，未重新生成。')
    return raw


def load(core, report, action_id):
    if report.get('kind') != 'jarvis.skill-report' or report.get('skill_id') != 'rea.software-analysis':
        raise policy.CoreError('artifact_unavailable', '此任务没有软件解析证据。')
    if 'evidence_ref' in report:
        evidence = json.loads(read(core, report['evidence_ref'], action_id))
    else:
        # Existing 0.1.45 receipts remain readable without migration.
        evidence = report.get('evidence')
    if not isinstance(evidence, dict):
        raise policy.CoreError('artifact_unavailable', '此任务没有完整解析证据。')
    return evidence


def page(evidence, report, section, offset=0, limit=20, *, query=''):
    if type(offset) is not int or offset < 0 or type(limit) is not int or not 1 <= limit <= 50:
        raise policy.CoreError('invalid_request', '证据分页参数无效。')
    if not isinstance(query, str) or len(query.encode('utf-8'))>256 or any(ord(c)<32 for c in query):
        raise policy.CoreError('invalid_request', '证据筛选项最多 256 UTF-8 字节。')
    result = evidence.get('normalized_result', {})
    graph = result.get('graph', {})
    if section == 'links':
        from .rea_focus import RELATIONS
        rows = [e for e in graph.get('edges', []) if e.get('relation') in RELATIONS]
    elif section == 'components': rows = graph.get('nodes', [])
    elif section == 'files': rows = report['input_manifest']['files']
    elif section == 'omitted': rows = report['input_manifest']['omitted']
    else: raise policy.CoreError('invalid_request', '请选择关系、结构节点、文件或排除范围。')
    total_before_filter = len(rows)
    if query:
        from .rea_focus import matches
        rows = [row for row in rows if matches(row, query)]
    items, used = [], 0
    for index, row in enumerate(rows[offset:offset + limit], offset):
        encoded = policy.canonical_json(row)
        item = {'index': index, 'value': row, 'truncated': False}
        if len(encoded.encode('utf-8')) > 8192:
            item = {'index': index, 'preview': encoded.encode('utf-8')[:6000].decode('utf-8', errors='ignore'),
                    'truncated': True, 'note': '此条内容较长，完整字段见证据下载。'}
        size = len(policy.canonical_json(item).encode('utf-8'))
        if items and used + size > 64 * 1024: break
        used += size; items.append(item)
    end = offset + len(items)
    return {'evidence_id': evidence['evidence_id'], 'section': section, 'offset': offset, 'total': len(rows),
            'items': items, 'next_offset': end if end < len(rows) else None, 'query':query, 'total_before_filter':total_before_filter,
            'static_only': True, 'coverage_note': '仅包含本次输入文件的静态关系，不证明运行时可达性。'}
