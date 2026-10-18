"""Reviewed REA JavaScript static adapter. Targets are data, never programs to run."""
from __future__ import annotations
import json
import os
from pathlib import Path
import stat
import tempfile
from . import policy
from .project_files import ProjectFiles, excluded

PROFILE = policy.REPOSITORY_ROOT / 'config/skills/rea-runtime.json'
SUFFIXES = {'.js', '.mjs', '.cjs', '.json', '.html', '.htm'}
MAX_FILE, MAX_TOTAL, MAX_FILES = 16 * 1024 * 1024, 32 * 1024 * 1024, 128
MAX_EVIDENCE = 8 * 1024 * 1024
PUBLISHED_DIRS = {'dist', 'build', 'target', '.next'}


def runtime(*, verify=False, checkpoint=lambda: None):
    try:
        profile = json.loads(policy.safe_path(PROFILE, directory=False).read_text(encoding='utf-8'))
        root = policy.safe_path(Path(profile['root']), directory=True)
        manifest = policy.safe_path(root / 'bundle.json', directory=False).read_bytes()
        if os.name != 'nt' or profile['version'] != '6.5.0' or policy.digest(manifest) != profile['manifest_digest']:
            raise ValueError('Unverified REA bundle')
        data = json.loads(manifest)
        for name in ('node.exe', 'node_modules/rea-agents/scripts/rea.mjs'):
            policy.safe_path(root / name, directory=False)
        if verify:
            for index, (name, expected) in enumerate(data['files'].items()):
                if index % 128 == 0: checkpoint()
                path = policy.safe_path(root / name, directory=False)
                if not path.is_relative_to(root) or path.stat().st_nlink != 1 or policy.digest(path.read_bytes()) != expected:
                    raise ValueError('REA runtime changed')
            # Additional code could change Node resolution even if existing files match.
            actual = {p.relative_to(root).as_posix() for p in root.rglob('*') if p.is_file()}
            if actual != set(data['files']) | {'bundle.json'}: raise ValueError('Unexpected REA runtime file')
            checkpoint()
        return root, profile['manifest_digest']
    except policy.CoreError as exc:
        if exc.code in {'cancelled', 'stopped', 'limit_exceeded'}: raise
        raise policy.CoreError('rea_unavailable', 'REA 固定版本环境缺失或内容已变化，需要重新准备并验证。') from None
    except (OSError, ValueError, KeyError, TypeError):
        raise policy.CoreError('rea_unavailable', 'REA 固定版本环境缺失或内容已变化，需要重新准备并验证。') from None


def snapshot(core, args, checkpoint, destination=None):
    """Bounded, explicit project subtree; reject unsafe links and retain omissions."""
    files = ProjectFiles(core); root = files.root(args['project_id'])
    target = files.target(root, args.get('target_path', ''), empty=True, allow_dirs=PUBLISHED_DIRS)
    if target.suffix.lower() == '.asar' and target.is_file():
        from .rea_asar import snapshot as asar_snapshot
        return asar_snapshot(core, args, checkpoint, target, destination)
    policy.safe_path(target, directory=True)
    rows, omitted, total, scanned = [], [], 0, 0
    def walk(parent, depth):
        nonlocal total, scanned
        checkpoint()
        if depth > 24: raise policy.CoreError('rea_input_limit', '应用目录层级超过 24 层。')
        with os.scandir(parent) as entries:
            for entry in entries:
                checkpoint(); scanned += 1
                if scanned > 4096: raise policy.CoreError('rea_input_limit', '应用目录超过 4,096 个条目，请缩小范围。')
                path = parent / entry.name; rel = path.relative_to(target).as_posix()
                if excluded(rel, allow_dirs=PUBLISHED_DIRS): omitted.append({'path': rel, 'reason': '排除目录或凭据名称'}); continue
                path = policy.safe_path(path)
                info = path.stat()
                if stat.S_ISDIR(info.st_mode): walk(path, depth + 1); continue
                if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
                    raise policy.CoreError('rea_input_unsafe', '应用目录含有不支持的链接或非普通文件。')
                if path.suffix.lower() not in SUFFIXES:
                    omitted.append({'path': rel, 'reason': '当前静态解析不支持此格式'}); continue
                if len(rows) >= MAX_FILES or info.st_size > MAX_FILE or total + info.st_size > MAX_TOTAL:
                    raise policy.CoreError('rea_input_limit', '最多 128 个文本文件、单文件 16 MiB、合计 32 MiB；请缩小范围。')
                with path.open('rb') as stream:
                    opened = os.fstat(stream.fileno()); raw = stream.read(MAX_FILE + 1)
                after = policy.safe_path(path).stat()
                signature = lambda s: (s.st_dev, s.st_ino, s.st_size, s.st_mtime_ns, s.st_nlink)
                if signature(info) != signature(opened) or signature(info) != signature(after) or len(raw) != info.st_size:
                    raise policy.CoreError('rea_source_changed', '应用文件在读取时发生变化，请重试。')
                try: raw.decode('utf-8-sig')
                except UnicodeError: raise policy.CoreError('rea_input_encoding', '应用目录中的解析文本必须为 UTF-8。') from None
                if b'\0' in raw: raise policy.CoreError('rea_input_encoding', '解析文件包含二进制内容。')
                total += len(raw); rows.append({'path': rel, 'digest': policy.digest(raw), 'bytes': len(raw)})
                if destination:
                    output = destination / rel; output.parent.mkdir(parents=True, exist_ok=True); output.write_bytes(raw)
    walk(target, 0)
    if not any(Path(r['path']).suffix.lower() in {'.js', '.mjs', '.cjs'} for r in rows):
        raise policy.CoreError('rea_input_unsupported', '请指定含 JavaScript 的应用目录或 .asar 文件；EXE、APK 尚未开放。')
    rows.sort(key=lambda r: r['path']); omitted.sort(key=lambda r: r['path'])
    files.root(args['project_id'])
    return {'target_path': args.get('target_path', ''), 'format':'directory', 'parser_input_format':'directory', 'files': rows, 'omitted': omitted,
            'total_bytes': total, 'digest': policy.digest(policy.canonical_json(rows).encode('utf-8'))}


def projection(evidence):
    if (not isinstance(evidence, dict) or not str(evidence.get('evidence_id', '')).startswith('ev_')
            or evidence.get('operation') != 'analyze_javascript_application'
            or evidence.get('confidence') != 'derived' or evidence.get('authority') != 'shipped-artifact'):
        raise policy.CoreError('rea_evidence_invalid', '解析器未返回匹配的静态分析证据。')
    result = evidence.get('normalized_result', {})
    graph = result.get('graph', {})
    if not isinstance(result.get('summary'), dict) or not isinstance(graph.get('nodes'), list) or not isinstance(graph.get('edges'), list):
        raise policy.CoreError('rea_evidence_invalid', '解析器证据缺少结构图或概要。')
    if result.get('statistics', {}).get('parse_failures', 0) or result.get('integrity_contradictions'):
        raise policy.CoreError('rea_analysis_incomplete', '解析存在语法失败或完整性矛盾；未作为成功报告交付。')
    from .rea_focus import RELATIONS, project_link
    links = []
    for edge in graph['edges']:
        if edge.get('relation') in RELATIONS:
            links.append(project_link(edge))
    priority = {'invokes': 0, 'maps_to': 1, 'handles': 2, 'loads': 3, 'imports': 4}
    links.sort(key=lambda row: priority[row['relation']])
    components = [{'kind': n['kind'], 'labels': [o.get('label', '') for o in n.get('observations', [])]}
                  for n in graph['nodes'] if n.get('kind') in {'electron-main', 'context-bridge-api', 'ipc-handler', 'javascript-module', 'package'}]
    return {'summary': result['summary'], 'node_count': len(graph['nodes']), 'edge_count': len(graph['edges']), 'components': components[:128],
            'key_links': links[:40], 'key_links_omitted': max(0, len(links) - 40),
            'components_omitted': max(0, len(components) - 128),
            'limitations': evidence.get('limitations', []) + result.get('limitations', []),
            'statistics': result.get('statistics', {}), 'integrity_contradictions': result.get('integrity_contradictions', [])}


def analyze(core, args, checkpoint):
    runtime_root, binding = runtime(verify=True, checkpoint=checkpoint)
    from .rea_process import run
    # TemporaryDirectory only removes its freshly created, absolute stage.
    with tempfile.TemporaryDirectory(prefix='jarvis-rea-static-') as temporary:
        stage = policy.safe_path(Path(temporary), directory=True)
        target = stage / 'application'; target.mkdir()
        inputs = snapshot(core, args, checkpoint, target)
        argv = [str(runtime_root / 'node.exe'), '--max-old-space-size=384',
                str(runtime_root / 'node_modules/rea-agents/scripts/rea.mjs'),
                'analyze-javascript-application', str(target), '--artifact-format', 'directory',
                '--max-heap-mb', '256', '--analysis-timeout-ms', '15000', '--json']
        evidence_path = stage / 'evidence.json'
        result = run(argv, stage, checkpoint, output_limit=MAX_EVIDENCE, output_path=evidence_path)
        if result['exit_code'] != 0:
            raise policy.CoreError('rea_analysis_failed', 'REA 未完成静态解析；未交付成功报告。请缩小目录或检查 JavaScript 格式。')
        raw_evidence = evidence_path.read_bytes()
        try: evidence = json.loads(raw_evidence)
        except ValueError: raise policy.CoreError('rea_evidence_invalid', 'REA 返回的证据不是有效 JSON。') from None
        view = projection(evidence)
        from .rea_focus import inspect, lines
        view['focus'] = inspect(evidence, args)
        if snapshot(core, args, checkpoint) != inputs:
            raise policy.CoreError('rea_source_changed', '解析期间目标目录发生变化，未交付旧报告。')
        if runtime(verify=True, checkpoint=checkpoint) != (runtime_root, binding):
            raise policy.CoreError('rea_runtime_changed', '解析期间运行环境发生变化，未交付旧报告。')
        summary, ipc = view['summary'], view['summary'].get('ipc', {})
        text = '\n'.join([
            '# 软件结构与行为解析报告', '', '目标：' + (inputs['target_path'] or '项目根目录'),
            '任务：' + args['prompt'], '解析器：REA 6.5.0 · JavaScript / Electron 静态解析',
            '证据编号：' + evidence['evidence_id'], '输入版本：' + inputs['digest'], '',
            *(['ASAR 容器：'+inputs['container']['path'], '原包摘要：'+inputs['container']['digest'],
               '解析范围：从 ASAR 及所需 .unpacked 成员取得的文本快照；成员位置保存在输入清单。'] if inputs.get('container') else []),
            '## 解析结果',
            f"读取 {len(inputs['files'])} 个文件，{inputs['total_bytes']} 字节；排除 {len(inputs['omitted'])} 个条目。",
            f"结构图：{view['node_count']} 个节点、{view['edge_count']} 条关系。",
            f"Electron 桥接 API：{summary.get('context_bridge_apis', 0)}；暴露成员：{summary.get('exposed_api_members', 0)}。",
            f"IPC 主进程处理器：{ipc.get('main_handlers', 0)}；发送操作：{ipc.get('renderer_transmissions', 0)}；配对：{ipc.get('paired_renderer_transmissions', 0)}。",
            *lines(view['focus']),
            '', '## 应用组成', *[r['kind'] + '：' + '、'.join(r['labels']) for r in view['components']],
            '', '## 关键关系（完整图见证据 JSON）',
            f"本报告展示 {len(view['key_links'])} 条关键关系，另有 {view['key_links_omitted']} 条可在证据分页中读取。",
            *[r['relation'] + '：' + json.dumps(r['properties'], ensure_ascii=False) + '\n  来源：' + json.dumps(r['location'], ensure_ascii=False) + '\n  证据：' + str(r['edge_id']) for r in view['key_links']],
            '', '## 解释与边界',
            '这些关系来自语法和模块引用推导，表示可能的调用路径；没有运行目标软件，不能证明实际可达性或安全性。',
            '已验证的是解析、输入版本与产物交付；未执行软件功能测试。没有发现某项关系并不证明它不存在。',
            '客户端资料不能还原云端私有代码、模型权重或完整后端。动态字符串、混淆和未纳入文件可能使关系不完整。',
            '当前报告在本地生成，没有模型调用或云端上传。需要进一步解释时，可明确选择报告作为模型任务资料。',
            '', '## 排除范围', *[r['path'] + '：' + r['reason'] for r in inputs['omitted']],
            '', '## 解析器限制', *view['limitations'],
        ])
        return {'text': text, 'evidence': evidence, 'analysis': view, 'input_manifest': inputs,
                'runtime': {'version': '6.5.0', 'manifest_digest': binding, 'stdout_digest': policy.digest(raw_evidence),
                            'evidence_output_limit_bytes': MAX_EVIDENCE, 'stdout_bytes': len(raw_evidence),
                            'evidence_digest': policy.digest(policy.canonical_json(evidence).encode('utf-8')), **result['process']},
                'checks': {'sources_rechecked': True, 'runtime_rechecked': True, 'target_executed': False,
                           'model_calls': 0, 'evidence_validated': True, 'runtime_behavior_verified': False}}
