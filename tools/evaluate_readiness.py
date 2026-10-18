"""Small reproducible live evaluation. Synthetic inputs only; requires --live.

This measures selected examples, not general intelligence. No downloads, model
configuration changes, hidden retries, external actions or private file inputs.
"""
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
import argparse
import hashlib
import json
from pathlib import Path
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'runtime/node-host'))
from jarvis_core import __version__
from jarvis_core.chat import ChatService
from jarvis_core.service import CoreService

CASES = [
    {'id': 'discount', 'prompt': '17件商品，每件37元，商品合计打85折，再加12元运费。只输出JSON，字段total为保留两位小数的字符串。',
     'expected': {'total': '546.65'}},
    {'id': 'critical_path', 'prompt': '任务A耗时3小时；B耗时2小时且必须在A完成后开始；C耗时4小时且必须在A完成后开始；D耗时1小时且须B和C都完成后开始。资源足够、B与C可并行。全部完成最少几小时？只输出JSON：{"hours":整数}。',
     'expected': {'hours': 8}},
    {'id': 'context_correction', 'prompt': '现在项目代号和输出文件名是什么？只输出JSON，字段code和file。',
     'history': [{'role': 'user', 'content': '项目代号是红杉，输出文件叫plan.md。'},
                 {'role': 'assistant', 'content': '记录了本会话中的这两个字段。'},
                 {'role': 'user', 'content': '纠正：代号改成蓝鲸，文件名保持不变。'}],
     'expected': {'code': '蓝鲸', 'file': 'plan.md'}},
    {'id': 'missing_information', 'prompt': '提取以下便条：客户李青要3把椅子，没有写交付日期。仅输出JSON，字段customer、quantity、delivery_date；缺失值必须为null，不要猜日期。',
     'expected': {'customer': '李青', 'quantity': 3, 'delivery_date': None}},
    {'id': 'logic', 'prompt': '甲、乙、丙每人有一个不同颜色的盒子，颜色为红、蓝、绿。甲没有红也没有蓝；乙没有蓝。丙是什么颜色？只输出JSON：{"color":"红或蓝或绿"}。',
     'expected': {'color': '蓝'}},
]
IDENTITY = '你是谁？在当前 Jarvis 系统里已经能做哪些操作？能否读取我的项目文件、运行 Python、记住上次会话？请简短准确回答。'


def grade(text, expected):
    try:
        value = json.loads(text)
        strict = True
    except (ValueError, TypeError):
        strict = False
        raw = text.strip()
        if raw.startswith('```') and raw.endswith('```'):
            raw = '\n'.join(raw.splitlines()[1:-1])
        try: value = json.loads(raw)
        except (ValueError, TypeError): value = None
    return {'strict_json': strict, 'content_correct': value == expected,
            'passed': strict and value == expected}


def run_route(route, data, cases):
    provider, sep, model = route.partition('::')
    chat = ChatService(CoreService(data))
    rows = []
    for case in cases:
        result = chat.reply(case['prompt'], provider=provider, model=model if sep else None,
                            history=case.get('history'))
        row = {'case': case['id'], 'input': case, 'result': {k: result[k] for k in (
            'status', 'provider', 'model', 'text', 'usage', 'elapsed_seconds', 'error_category', 'user_message',
            'output_incomplete', 'completion_reason', 'notice', 'billing', 'reasoning') if k in result}}
        if 'expected' in case:
            row['evaluation'] = grade(result.get('text', ''), case['expected'])
            row['evaluation']['passed'] &= result['status'] == 'SUCCEEDED' and not result.get('output_incomplete', False)
        rows.append(row)
        print(json.dumps({'route': route, 'case': case['id'], 'status': result['status'],
                          'grade': row.get('evaluation'), 'seconds': result.get('elapsed_seconds')}, ensure_ascii=False), flush=True)
    scored = [r for r in rows if 'evaluation' in r]
    return {'route': route, 'passed': sum(r['evaluation']['passed'] for r in scored),
            'total': len(scored), 'rows': rows}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--live', action='store_true', help='Explicitly make billable configured model requests')
    parser.add_argument('--route', action='append', required=True, help='provider or provider::model')
    parser.add_argument('--identity-only', action='store_true')
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    if not args.live: parser.error('--live is required; this evaluation can incur provider charges')
    if args.output.exists(): parser.error('Choose a new evidence path; existing reports are not overwritten')
    files = ['runtime/node-host/jarvis_core/chat.py', 'runtime/node-host/jarvis_core/assistant_context.py',
             'adapters/models/provider-native/jarvis_models/gateway.py', 'tools/evaluate_readiness.py']
    report = {'version': __version__, 'source_kind': 'working_tree', 'time': datetime.now(timezone.utc).isoformat(),
              'scope': 'small synthetic sample; not a general intelligence score; identity requires human review',
              'source_sha256': {p: hashlib.sha256((ROOT / p).read_bytes()).hexdigest() for p in files}, 'routes': []}
    cases = ([] if args.identity_only else CASES) + [{'id': 'identity_unscored', 'prompt': IDENTITY}]
    with tempfile.TemporaryDirectory(prefix='jarvis-live-evaluation-') as directory:
        base = Path(directory); (base / 'input').mkdir()
        CoreService(base / 'data').initialize(base / 'input')
        # At most two independent routes; one request at a time on each route.
        with ThreadPoolExecutor(max_workers=2) as pool:
            pending = [pool.submit(run_route, r, base / 'data', cases) for r in dict.fromkeys(args.route)]
            for future in as_completed(pending):
                report['routes'].append(future.result())
                args.output.parent.mkdir(parents=True, exist_ok=True)
                args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    return 0


if __name__ == '__main__':
    sys.stdout.reconfigure(encoding='utf-8')
    raise SystemExit(main())
