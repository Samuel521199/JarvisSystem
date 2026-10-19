"""Synthetic, real-provider K2 conversational review; never owner-state mutation.

Functional checks inspect exact dispatched context and durable-state digests.
Answer quality must be reviewed separately against the frozen case rubric.
"""
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import time
from unittest.mock import patch
import uuid

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / 'runtime/node-host'), str(ROOT / 'tools')]
from jarvis_core import __version__
from jarvis_core.chat import ChatService, gateway
from jarvis_core.memory import MemoryStore
from jarvis_core.memory_policy import SUBJECTS
from jarvis_core.persona import PersonaStore
from jarvis_core.service import CoreService
from jarvis_core.workspace import WorkspaceService
from k2_state_fingerprint import fingerprint


def uid():
    return uuid.uuid4().hex


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--live', action='store_true')
    parser.add_argument('--route', default='vertex::gemini-3.8-flash')
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        parser.error('Retain prior evidence; use a fresh output')
    provider, model = args.route.split('::', 1)
    corpus = ROOT / 'evals/cases/k2-delegated-review-v1.json'
    cases = json.loads(corpus.read_text(encoding='utf-8'))['cases']
    paths = list((ROOT / 'runtime/node-host/jarvis_core').rglob('*.py'))
    paths += list((ROOT / 'adapters/models/provider-native').rglob('*.py'))
    paths += [corpus, Path(__file__), ROOT / 'tools/k2_state_fingerprint.py', ROOT / 'config/model-profiles/providers.json']
    def hashes():
        return {p.relative_to(ROOT).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}
    report = {'version': __version__, 'captured_at': datetime.now(timezone.utc).isoformat(),
              'status': 'running', 'live': args.live, 'route': args.route, 'source_sha256': hashes(),
              'corpus': corpus.relative_to(ROOT).as_posix(), 'rows': [],
              'limits': ['Synthetic temporary stores only; no owner data read or altered.',
                         'Direct ChatService transport checks supplement, not replace, HTTP/UI/queue tests.',
                         'No owner satisfaction inferred. Functional pass is not conversational quality pass.',
                         'Visible author-created cases, one answer per case per route; not a blind or large-sample benchmark.']}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    def save():
        args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    real = gateway.probe
    try:
        for case in cases:
            if hashes() != report['source_sha256']:
                raise RuntimeError('Bound source changed; no further paid dispatch')
            with tempfile.TemporaryDirectory(prefix='jarvis-k2-review-') as temp:
                base = Path(temp); folder = base / 'sample'; folder.mkdir()
                core = CoreService(base / 'data'); core.initialize(folder)
                memory = MemoryStore(core)
                PersonaStore(core).change('profile', {'style': '温暖', 'relationship': '伙伴', 'preferred_name': '小岚'},
                                          request_id=uid(), revision=0)
                ctx = {'enabled': True, 'project_id': None}
                history, refs, included, excluded = [], [], [], []
                def put(title, body, *, providers=None, kind='preference', uses=None, project=None, label='', expires=None):
                    return memory.put(uid(), {'revision': 0, 'document': {
                        'title': title, 'content': body, 'project_id': project,
                        'providers': [provider] if providers is None else providers,
                        'classification': {'kind': kind, 'subject': SUBJECTS[kind], 'subject_label': label,
                                           'uses': ['personal_chat'] if uses is None else uses, 'expires_at': expires}}})
                tea = '下午喜欢淡一点的茉莉花茶'
                setup = case['setup']
                if setup in {'allowed', 'local_only', 'temporary', 'corrected', 'forgotten', 'revoked'}:
                    row = put('饮品偏好', tea, providers=[] if setup == 'local_only' else None)
                    included.append(tea) if setup == 'allowed' else excluded.append(tea)
                    if setup in {'corrected', 'forgotten', 'revoked'}:
                        history = [{'role': 'user', 'content': '我平时喜欢喝什么？'},
                                   {'role': 'assistant', 'content': '你下午喜欢淡一点的茉莉花茶。'}]
                        refs = [[], [{'id': row['id'], 'revision': row['revision']}]]
                        if setup == 'forgotten':
                            memory.delete(row['id'], {'revision': row['revision']})
                        else:
                            doc = dict(row['document'])
                            if setup == 'corrected':
                                doc['content'] = '现在改为温热的薄荷茶'; included.append(doc['content'])
                            else:
                                doc['providers'] = []
                            memory.put(row['id'], {'revision': row['revision'], 'document': doc})
                if setup == 'work':
                    second = base / 'other'; second.mkdir()
                    project = WorkspaceService(core).open_project({'path': str(folder)})['id']
                    other = WorkspaceService(core).open_project({'path': str(second)})['id']
                    ctx.update(project_id=project, purpose='work_assist')
                    put('登录方案', '本项目采用琥珀会话票据', kind='project_fact', uses=['work_assist'], project=project)
                    put('登录方案', '另一项目采用紫杉通行证', kind='project_fact', uses=['work_assist'], project=other)
                    put('登录私事', '私人登录暗号是测试山雀')
                    put('回复偏好', '优先简短中文', uses=['personal_chat', 'work_assist'])
                    included += ['本项目采用琥珀会话票据', '优先简短中文']
                    excluded += ['另一项目采用紫杉通行证', '私人登录暗号是测试山雀']
                if setup == 'excluded':
                    put('茶偏好', '只存不使用的测试乌龙', uses=[])
                    put('茶偏好', '已过期的测试红茶', kind='temporary_state', expires='2000-01-01T00:00:00Z')
                    put('茶偏好', '虚构NPC喜欢测试龙井', kind='fiction', uses=[], label='NPC小兔')
                    excluded += ['只存不使用的测试乌龙', '已过期的测试红茶', '虚构NPC喜欢测试龙井']
                if setup == 'conflict':
                    put('饮品偏好', '喜欢每天喝咖啡'); put('饮品偏好备注', '不喜欢咖啡并且要避开咖啡')
                    included += ['喜欢每天喝咖啡', '不喜欢咖啡并且要避开咖啡']
                if setup == 'allowed':
                    put('旅行记录', '曾在测试石榴岛旅行'); excluded.append('曾在测试石榴岛旅行')
                # Freeze after the store's normal empty-schema initialization,
                # so first read is not mistaken for a newly remembered fact.
                memory.list()
                chat = ChatService(core); before = fingerprint(core.data_dir); traces = []
                def transport(config, selected, message, *a, **kw):
                    traces.append({'message': message, 'provider': selected, 'instructions': kw.get('instructions', ''),
                                   'history': kw.get('history', [])})
                    return real(config, selected, message, *a, **kw) if args.live else {
                        'status': 'SUCCEEDED', 'text': 'fixture response', 'provider': selected, 'model': model}
                start = time.monotonic()
                with patch('jarvis_core.chat.gateway.probe', side_effect=transport):
                    result = chat.reply(case['query'], provider=provider, model=model, reasoning='low',
                                        history=history, history_memory=refs, memory_context=ctx,
                                        personal_context={'temporary': setup == 'temporary'}, _route_attempt_limit=1)
                wire = json.dumps(traces, ensure_ascii=False)
                after = fingerprint(core.data_dir)
                checks = {'successful': result.get('status') == 'SUCCEEDED', 'one_dispatch': len(traces) == 1,
                          'included_context': all(value in wire for value in included),
                          'excluded_context': all(value not in wire for value in excluded),
                          'profile_boundary': ('小岚' in wire) == (setup != 'temporary'),
                          'existing_business_rows_unchanged': all(after[name] == value for name, value in before.items())}
                if setup in {'corrected', 'forgotten', 'revoked'}:
                    checks['stale_history_removed'] = all(not t['history'] for t in traces)
                report['rows'].append({'id': case['id'], 'query': case['query'], 'expect': case['expect'],
                                       'checks': checks, 'result': result, 'transport': traces,
                                       'changed_stores': [name for name, value in before.items() if after[name] != value],
                                       'elapsed_seconds': round(time.monotonic() - start, 3)})
                save(); print(json.dumps({'id': case['id'], 'status': result.get('status'), 'checks': checks}), flush=True)
                if result.get('status') != 'SUCCEEDED':
                    raise RuntimeError('Provider failed or uncertain; no automatic paid retry')
        report['source_unchanged'] = hashes() == report['source_sha256']
        report['status'] = 'functional_pass_answer_review_pending' if report['source_unchanged'] and all(
            all(row['checks'].values()) for row in report['rows']) else 'failed'
    except Exception as error:
        report.update(status='failed', error=repr(error)); raise
    finally:
        report['cost'] = {'dispatches': sum(len(r['transport']) for r in report['rows']) if args.live else 0,
                          'estimated_usd': sum((r['result'].get('billing') or {}).get('amount', 0) or 0 for r in report['rows'])}
        save()
    return 0 if report['status'] == 'functional_pass_answer_review_pending' else 1


if __name__ == '__main__':
    raise SystemExit(main())
