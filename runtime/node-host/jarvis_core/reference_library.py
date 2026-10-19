"""Local, cited answers over the verified seed and current Host boundaries.

The index is disposable; source bodies and capability decisions are always
loaded afresh. It never grants execution authority or enters model history.
"""
import hashlib
import json
import os
from pathlib import Path
import tempfile

from . import __version__
from .knowledge import normalized, terms
from .policy import CoreError, safe_path
from .runtime_catalog import RuntimeCatalog, ASSETS

MAX_INDEX_BYTES = 262144
MAX_RESULTS = 8
MAX_ANSWER_BYTES = 12288


class ReferenceLibrary:
    def __init__(self, core, *, catalog=None):
        self.core = core
        self.catalog = catalog or RuntimeCatalog(core)
        self.path = Path(core.data_dir) / 'reference-index.json'

    def records(self, state):
        rows = []
        for item in state['knowledge']:
            rows.append(dict(id=item['record_id'], kind='knowledge', content=item['content'],
                source=item['source'], version=item['version'], status='design_baseline', asset=ASSETS[0]))
        for item in state['rules']:
            rows.append(dict(id=item['rule_id'], kind='rule', content=item['statement'],
                source=item['source_ref'], version=state['seed_version'], status='historical_K0_K1', asset=ASSETS[1]))
        for item in state['skills'] + state['capabilities']:
            rows.append(dict(id=item['id'], kind='skill' if 'capability_refs' in item else 'capability',
                content=item['description'] + (' ' + item['reason'] if 'reason' in item else ''),
                source=ASSETS[2], version=item['version'], status=item['status'], asset=ASSETS[2]))
        # Implementation boundary, not a claim that a worker/model is currently ready.
        rows.append(dict(id='host.bounded_growth', kind='runtime', version=__version__,
            status='implemented_bounded', source='runtime/node-host/jarvis_core/evolution/demand.py',
            content='当前宿主已有受限需求、候选构建、验证、启用与回退链路；执行前仍检查模型、Worker、资源和策略。'
                    '种子中“候选构建 planned / 后续 K3”是旧 K0/K1 基线；不能据此否认现有受限成长，也不能把它扩大为任意源码自改或自主发布。'))
        return rows

    def index(self, rows):
        # The source-derived checksum also authenticates the expected postings.
        # Small seed: validate everything; never trust a writable cache's hash.
        postings = {row['id']: terms(row['id']+' '+row['content']) for row in rows}
        source = hashlib.sha256(json.dumps(rows, ensure_ascii=False, sort_keys=True).encode()).hexdigest()
        expected = {'schema_version': 1, 'source_digest': source, 'postings': postings}
        try:
            path = safe_path(self.path, must_exist=False)
            if path.exists() and path.stat().st_nlink != 1:
                raise ValueError('linked index')
            if path.exists() and path.stat().st_size <= MAX_INDEX_BYTES:
                with path.open('rb') as stream:
                    cached = json.loads(stream.read(MAX_INDEX_BYTES+1))
                if cached == expected:
                    return postings, 'ready'
        except (OSError, ValueError, TypeError, RecursionError, CoreError):
            pass
        # Fixed single cache file, atomic replacement. Never remove directories,
        # authoritative stores, or a rejected link. Read-only storage still works.
        temporary = None
        try:
            path = safe_path(self.path, must_exist=False)
            if path.exists() and path.stat().st_nlink != 1:
                raise ValueError('linked index')
            with tempfile.NamedTemporaryFile(dir=path.parent, prefix='reference-index-', suffix='.tmp', delete=False) as out:
                temporary = Path(out.name)
                out.write(json.dumps(expected, ensure_ascii=False).encode())
                out.flush()
                os.fsync(out.fileno())
            os.replace(temporary, path)
            return postings, 'rebuilt'
        except (OSError, ValueError, CoreError):
            return postings, 'memory_only'
        finally:
            if temporary is not None and temporary.exists():
                try:
                    temporary.unlink(missing_ok=True)
                except OSError:
                    pass

    def query(self, query='', *, capabilities=False):
        state = self.catalog.snapshot()
        receipt = dict(kind='reference', action='view', committed=False, version=__version__,
                       seed_version=state['seed_version'], references=[], privacy='local_only', index='unused')
        if state['status'] != 'ready':
            return state['message']+' 本次没有采用旧索引或调用模型。', dict(receipt, status='unavailable')
        rows = self.records(state)
        postings, receipt['index'] = self.index(rows)
        words = set(terms(query))
        ranked = []
        for row in rows:
            score = len(words.intersection(postings[row['id']]))
            if normalized(query) in normalized(row['id']+' '+row['content']) and query:
                score += 4
            category={'知识':'knowledge','规则':'rule','技能':'skill'}.get(query.strip())
            if capabilities and row['kind'] in {'skill','capability','runtime'} or not capabilities and (score or category==row['kind']):
                ranked.append((score, row))
        ranked.sort(key=lambda value: -value[0])
        header = (f"本机三库查询 · 宿主 v{__version__} · 种子 v{state['seed_version']}\n"
                  '来源正文仅供说明，当前权限由宿主逐次核验。历史 K0/K1 规则不等于所有模块当前状态。\n')
        # Always explain the stale construction claim beside it, not off-screen.
        if any(row['id'] in {'skills.limit','R_PLANNED','build.candidate.v1','candidate_build'} for _, row in ranked):
            header += rows[-1]['content']+'\n'
        text = header
        for _, row in ranked[:MAX_RESULTS]:
            block = f"\n{row['id']} · {row['status']}\n{row['content']}\n来源：{row['source']} · v{row['version']}\n"
            if len((text+block).encode()) > MAX_ANSWER_BYTES:
                break
            text += block
            receipt['references'].append(row)
        if not receipt['references']:
            text += '\n没有匹配的已校验资料。可尝试“UNKNOWN”“候选构建”“规则”，或发送“查看能力”。'
        receipt.update(status='ready', omitted=max(0,len(ranked)-len(receipt['references'])))
        return text, receipt
