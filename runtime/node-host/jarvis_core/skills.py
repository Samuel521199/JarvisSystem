"""Versioned native skill discovery, scoped preferences and bounded guidance.

Third-party registrations remain dormant. Only reviewed native adapters can run;
metadata and skill text cannot create executors or confer filesystem access.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import re
import importlib.util

from . import policy
from .extensions import ExtensionCatalog
from .workspace import fields, identifier, timestamp

ROOT = policy.REPOSITORY_ROOT
CATALOG = ROOT / 'config/skills/catalog.json'
MODES = {'auto', 'manual', 'disabled'}
SCOPES = {'global', 'project', 'conversation'}
CORE_GUIDES = {'matt-pocock.diagnosing-bugs', 'matt-pocock.tdd',
               'matt-pocock.code-review', 'matt-pocock.codebase-design',
               'matt-pocock.to-spec', 'matt-pocock.handoff', 'matt-pocock.teach',
               'matt-pocock.to-questionnaire', 'matt-pocock.writing-for-agents'}
SOURCE_REQUIRED = {'matt-pocock.diagnosing-bugs', 'matt-pocock.tdd',
                   'matt-pocock.code-review', 'matt-pocock.codebase-design'}
GUIDE_LIMIT = 1800


def validate_document(document, schema_name):
    from jsonschema import Draft202012Validator, ValidationError
    schema = json.loads(policy.safe_path(ROOT / 'contracts/schemas' / schema_name, directory=False).read_text(encoding='utf-8'))
    try: Draft202012Validator(schema).validate(document)
    except ValidationError as exc:
        raise policy.CoreError('skill_document_invalid', '技能文档未通过正式契约检查。') from exc


def file_digest(path):
    value = hashlib.sha256()
    with policy.safe_path(path, directory=False).open('rb') as source:
        for block in iter(lambda: source.read(1024 * 1024), b''):
            value.update(block)
    return 'sha256:' + value.hexdigest()


def catalog():
    raw = policy.safe_path(CATALOG, directory=False).read_bytes()
    if len(raw) > 256 * 1024:
        raise policy.CoreError('skill_catalog_invalid', '技能目录超过大小限制。')
    data = json.loads(raw)
    validate_document(data, 'native-skills.schema.json')
    if data.get('schema_version') != 1 or not isinstance(data.get('skills'), list):
        raise policy.CoreError('skill_catalog_invalid', '技能目录格式无效。')
    seen = set()
    for item in data['skills']:
        if (not isinstance(item, dict) or not re.fullmatch(r'[a-zA-Z0-9_.-]{1,100}', item.get('id', ''))
                or item['id'] in seen or item.get('default_mode') not in MODES
                or any(not isinstance(item.get(k), str) or not item[k].strip() for k in ('use_when', 'do_not_use_when'))
                or any(not isinstance(item.get(k), list) or len(item[k]) < 2 for k in ('positive_examples', 'negative_examples'))):
            raise policy.CoreError('skill_catalog_invalid', '技能缺少唯一标识、使用规则或正反例。')
        seen.add(item['id'])
        if item['workflow'] != 'internal' and not item.get('presentation'):
            raise policy.CoreError('skill_catalog_invalid', '用户技能缺少能力说明。')
        if item['workflow'] == 'guidance' and (item['id'] not in CORE_GUIDES or not item['guide'].strip() or len(item['guide'].encode('utf-8')) > GUIDE_LIMIT):
            raise policy.CoreError('skill_catalog_invalid', '工作指导尚未准入或超过预算。')
    return data, policy.digest(raw)


def validate_context(value):
    if value is None:
        return {'enabled': True}
    fields(value, set(), {'enabled', 'explicit', 'project_id', 'conversation_id', 'excluded'})
    if type(value.get('enabled', True)) is not bool:
        raise policy.CoreError('invalid_skill_context', '技能使用开关无效。')
    for key in ('project_id', 'conversation_id'):
        if value.get(key) is not None:
            identifier(value[key])
    if value.get('explicit') is not None and (not isinstance(value['explicit'], str) or len(value['explicit']) > 100):
        raise policy.CoreError('invalid_skill_context', '技能标识无效。')
    excluded = value.get('excluded', [])
    if not isinstance(excluded, list) or len(excluded) > 8 or any(not isinstance(x, str) or len(x) > 100 for x in excluded):
        raise policy.CoreError('invalid_skill_context', '本轮禁用技能列表无效。')
    return {'enabled': True, **value}


def infer_skill(message):
    """Conservative native intent rules; a name mention alone is not a call."""
    text = message.lower()
    if not re.search(r'(不要|不用|禁止|如果|假如|例如|示例|翻译|解释|如何|怎么)',text) and re.search(r'^(?:请帮我|帮我|请)?\s*(?:制作|创建|生成|写|做).{0,25}(?:坦克|tank).{0,16}游戏',text):
        return 'jarvis.tank-game'
    if re.search(r'^(翻译|校对|转述).{0,50}|^(总结|概述).{0,30}(审阅|调试|排错|测试|技能|设计)', text):
        return None
    if re.search(r'(不要|不用|不需要).{0,8}(审阅|审查|排查|调试|测试先行|教学|讲课)', text):
        return None
    if re.search(r'(介绍|什么是|总结|找到|查找).{0,40}(skill|技能|仓库|anatomy|tdd)', text):
        return None
    if re.search(r'(介绍|什么是|解释|总结|了解).{0,30}(代码审阅|排错方法|测试先行|模块设计)|(?:代码审阅|模块设计|tdd).{0,15}(是什么|的含义|介绍|原理)', text):
        return None
    if re.search(r'(不要|不用|不使用|禁用).{0,12}(技能|skill)', text):
        return None
    # A concept question is not a request to execute a workflow.
    if re.search(r'^(介绍|什么是|解释一下|总结|搜索|查找).{0,35}(rea|逆向|软件解析)', text):
        return None
    if not re.search(r'(不要|不用).{0,12}(分析|解析|逆向)', text) and re.search(r'(分析|解析|拆解|逆向).{0,32}(electron|javascript|asar|应用目录|软件结构|软件包|客户端)|rea.{0,12}(分析|解析)', text):
        return 'rea.software-analysis'
    if re.search(r'^(什么是|介绍一下|解释一下).{0,25}(技能|问卷|交接|需求规格|测试先行)|(?:技能|问卷|交接|需求规格|测试先行).{0,8}(是什么|有什么用)', text):
        return None
    if re.search(r'(编写|改写|精简|设计|优化|创建|写).{0,16}(agent.?指令|agents\.md|skill\.md|技能说明|协作指令)', text):
        return 'matt-pocock.writing-for-agents'
    if re.search(r'(制作|生成|设计|起草|编写|写).{0,16}(调研问卷|调查问卷|需求问卷|问卷)', text):
        return 'matt-pocock.to-questionnaire'
    if re.search(r'(整理|生成|写|准备).{0,18}(交接|接手说明)|交接.{0,12}(工作|项目|记录)', text):
        return 'matt-pocock.handoff'
    if re.search(r'(整理|编写|拆分|拆解|转成|生成).{0,22}(需求|规格|任务计划|任务清单)|需求.{0,16}(规格|拆分|拆解|验收|任务)', text):
        return 'matt-pocock.to-spec'
    if re.search(r'(教我|带我学|讲解.{0,30}(练习|例子)|解释.{0,30}并.{0,8}练习)', text):
        return 'matt-pocock.teach'
    if re.search(r'(制作|生成|创建|绘制|画(?:一个|一张|出|齿轮)|做(?:一个|个|成|齿轮)|render|animate)', text) and re.search(r'(交互|动画|拆解|组装|剖面|可视化)', text) and re.search(r'(机械|齿轮|发动机|原理|anatomy)', text):
        return 'anatomy.explainer'
    if re.search(r'(模块.{0,10}(接口|边界|设计)|接口设计|去除重复|无必要抽象)', text):
        return 'matt-pocock.codebase-design'
    if re.search(r'(审阅|审查|review|检查.{0,8}(代码|补丁)|代码.{0,8}(缺陷|问题))', text):
        return 'matt-pocock.code-review'
    if re.search(r'(排查|诊断|debug|调试|修复.{0,8}(异常|错误|bug)|性能退化)', text):
        return 'matt-pocock.diagnosing-bugs'
    if re.search(r'(\btdd\b|测试先行|行为测试|red.green.refactor)', text):
        return 'matt-pocock.tdd'
    if re.search(r'(模块.{0,10}(接口|边界|设计)|接口设计|去除重复|无必要抽象)', text):
        return 'matt-pocock.codebase-design'
    return None


class SkillManager:
    def __init__(self, core):
        self.core = core
        self.extensions = ExtensionCatalog(core)

    def _tables(self, db):
        db.execute('CREATE TABLE IF NOT EXISTS skill_policies(scope TEXT NOT NULL,scope_id TEXT NOT NULL,skill_id TEXT NOT NULL,revision INTEGER NOT NULL,mode TEXT NOT NULL,updated_at TEXT NOT NULL,PRIMARY KEY(scope,scope_id,skill_id))')
        db.execute('CREATE TABLE IF NOT EXISTS skill_decisions(id INTEGER PRIMARY KEY,task_id TEXT,created_at TEXT NOT NULL,document TEXT NOT NULL)')

    @staticmethod
    def renderer_profile():
        try:
            profile = json.loads(policy.safe_path(ROOT / 'config/skills/runtime.json', directory=False).read_text(encoding='utf-8'))
            from .worker import verify_bundle
            source, _ = verify_bundle()
            if os.name != 'nt' or profile['runtime_kind'] != 'fixed-python-lpac':
                return None, '本机缺少已验证的 Windows 科普执行环境。'
            if importlib.util.find_spec('playwright') is None:
                return None, '科普产物的浏览器验收组件尚未准备。'
            if not any((Path(os.environ.get(key, 'C:/Program Files')) / 'Microsoft/Edge/Application/msedge.exe').is_file()
                       for key in ('PROGRAMFILES', 'PROGRAMFILES(X86)', 'LOCALAPPDATA')):
                return None, '尚未找到本机 Edge，科普浏览器验收不可用。'
            for name, expected in profile['files'].items():
                path = ROOT / name
                if not path.is_relative_to(ROOT) or file_digest(path) != expected:
                    return None, '科普绘图库或执行器内容已变化，尚未重新准入。'
            return str(Path(source).absolute()), None
        except (OSError, ValueError, KeyError, policy.CoreError, RuntimeError):
            return None, '科普执行环境尚未准备或检查失败。'

    @staticmethod
    def readiness(item, node=None):
        if item['workflow'] == 'game':
            from .web_game import TEMPLATE
            ready=(os.name=='nt' and (ROOT/TEMPLATE).is_file()
                   and importlib.util.find_spec('playwright') is not None
                   and any((Path(os.environ.get(key,'C:/Program Files'))/'Microsoft/Edge/Application/msedge.exe').is_file()
                           for key in ('PROGRAMFILES','PROGRAMFILES(X86)','LOCALAPPDATA')))
            return {'loadable':True,'executable':ready,'execution_kind':'fixed_offline_game',
                    'reason':'固定 2D 坦克引擎，模型设计关卡；保存前真实浏览器验收，不生成或执行自由脚本。' if ready else '游戏引擎、Windows/Edge 或已有浏览器验收组件未就绪。'}
        if item['workflow'] == 'rea':
            from .rea import runtime
            try:
                runtime()
                reason, ready = '可解析 JavaScript / Electron 目录与 ASAR；可选模型中文解释，执行时核对运行环境和输入版本。', True
            except policy.CoreError as exc:
                reason, ready = str(exc), False
            return {'loadable': True, 'executable': ready, 'execution_kind': 'static_software_analysis', 'reason': reason}
        if item['id'] in CORE_GUIDES:
            if item.get('evaluation', {}).get('guide_sha256') != hashlib.sha256(item['guide'].encode('utf-8')).hexdigest():
                return {'loadable': True, 'executable': False, 'execution_kind': 'model_guidance',
                        'reason': '指导正文缺少匹配的样例验证记录，需复测后启用。'}
            return {'loadable': True, 'executable': True, 'execution_kind': 'model_guidance',
                    'reason': '可在聊天中使用，或保存只读文本报告；模型输出仍需按任务核对。'}
        if item['workflow'] == 'anatomy':
            source, reason = node if node is not None else SkillManager.renderer_profile()
            return {'loadable': True, 'executable': bool(source), 'execution_kind': 'fixed_mechanical_renderer',
                    'reason': reason or '已准入固定齿轮教学模板；自由 JS、CAD 和视频出口未开放。'}
        return {'loadable': False, 'executable': False, 'execution_kind': 'internal' if item['workflow'] == 'internal' else 'not_admitted',
                'reason': '由已有固定流程内部调用。' if item['workflow'] == 'internal' else '候选技能尚未完成宿主适配和准入。'}

    def _mode(self, db, item, context):
        mode, source, revision = item['default_mode'], 'package_default', 0
        for scope, scope_id in [('global', ''), ('project', context.get('project_id')), ('conversation', context.get('conversation_id'))]:
            if scope_id is None:
                continue
            row = db.execute('SELECT * FROM skill_policies WHERE scope=? AND scope_id=? AND skill_id=?', (scope, scope_id, item['id'])).fetchone()
            if row and row['mode'] != 'inherit':
                mode, source, revision = row['mode'], scope, row['revision']
        if item['id'] in context.get('excluded', []):
            mode, source = 'disabled', 'turn'
        return {'mode': mode, 'source': source, 'revision': revision}

    def snapshot(self, context=None):
        context = validate_context(context)
        data, binding = catalog()
        node = self.renderer_profile()
        from .skill_validation import statuses
        validation=statuses(self.core,data['skills'])
        with self.core.effect_guard(), self.extensions.connection() as db:
            self._tables(db)
            entries = [{**item, **self.readiness(item, node), 'policy_editable': item['workflow'] != 'internal', 'policy': self._mode(db, item, context),
                        'overrides': [dict(r) for r in db.execute('SELECT scope,scope_id,revision,mode FROM skill_policies WHERE skill_id=?', (item['id'],))]}
                       for item in data['skills']]
            for item in entries:
                item['validation']=validation[item['id']]
                item.pop('guide', None)
            return {'schema_version': 1, 'bundle_digest': binding, 'entries': entries,
                    'inventory': data.get('inventory', []), 'selection_method': 'host_rules',
                    'sources': data['sources'], 'scope': {k: context[k] for k in ('project_id', 'conversation_id') if k in context}}

    def put_policy(self, payload):
        fields(payload, {'skill_id', 'scope', 'revision'}, {'scope_id', 'mode'})
        data, _ = catalog()
        if not isinstance(payload['skill_id'], str) or payload['skill_id'] not in {x['id'] for x in data['skills']} or not isinstance(payload['scope'], str) or payload['scope'] not in SCOPES:
            raise policy.CoreError('invalid_skill_policy', '技能或设置作用域无效。')
        if next(x for x in data['skills'] if x['id'] == payload['skill_id'])['workflow'] == 'internal':
            raise policy.CoreError('host_managed_skill', '内部种子按宿主固定流程规则运行；技能偏好不能改变状态、安全或固定任务接口。')
        scope_id = payload.get('scope_id', '')
        if payload['scope'] == 'global':
            if scope_id:
                raise policy.CoreError('invalid_skill_policy', '全局设置不能绑定其他作用域。')
        else:
            identifier(scope_id)
        if type(payload['revision']) is not int or payload['revision'] < 0 or (payload.get('mode') is not None and (not isinstance(payload['mode'], str) or payload['mode'] not in MODES)):
            raise policy.CoreError('invalid_skill_policy', '策略模式或修订号无效。')
        with self.core.effect_guard(), self.extensions.connection() as db:
            self._tables(db)
            db.execute('BEGIN IMMEDIATE')
            key = (payload['scope'], scope_id, payload['skill_id'])
            row = db.execute('SELECT * FROM skill_policies WHERE scope=? AND scope_id=? AND skill_id=?', key).fetchone()
            old_revision = row['revision'] if row else 0
            if old_revision != payload['revision']:
                raise policy.CoreError('skill_policy_conflict', '技能设置已变化，请刷新后重试；当前输入保留。')
            # A tombstone revision prevents stale writes after restoring inheritance.
            db.execute('INSERT INTO skill_policies VALUES(?,?,?,?,?,?) ON CONFLICT(scope,scope_id,skill_id) DO UPDATE SET revision=excluded.revision,mode=excluded.mode,updated_at=excluded.updated_at',
                       (*key, old_revision + 1, payload.get('mode') or 'inherit', timestamp()))
        return {'saved': True, 'revision': old_revision + 1, 'mode': payload.get('mode'), 'scope': payload['scope'], 'scope_id': scope_id}

    def select(self, message, context=None, *, purpose='chat', record=False, task_id=None):
        if not isinstance(message, str) or not message.strip() or len(message.encode('utf-8')) > 65536:
            raise policy.CoreError('invalid_skill_request', '技能需求必须是有界非空文本。')
        context = validate_context(context)
        data, binding = catalog()
        explicit = context.get('explicit')
        if explicit and explicit not in {x['id'] for x in data['skills']}:
            row = next((x for x in data.get('inventory', []) if x['id'] == explicit), None)
            raise policy.CoreError('skill_not_found', ('此组件已并入 '+row['capability']+'，请选用完整技能。') if row and row.get('capability') else '此项不在活跃技能目录中。')
        target = explicit or infer_skill(message)
        selected, excluded = [], []
        with self.core.effect_guard(), self.extensions.connection() as db:
            self._tables(db)
            item = next((x for x in data['skills'] if x['id'] == target), None)
            if item:
                mode = self._mode(db, item, context)
                ready = self.readiness(item)
                if target == 'anatomy.explainer' and purpose == 'scene-guidance':
                    from .coding_js import asset
                    asset()  # This purpose composes guidance; it never calls the gear renderer.
                    ready = {'executable': True}
                reason = None
                if not context['enabled']:
                    reason = '本轮已关闭技能。'
                elif re.search(r'(不要|不用|不使用|禁用).{0,12}(技能|skill)', message, re.I):
                    reason = '本次要求明确排除了技能。'
                elif mode['mode'] == 'disabled':
                    reason = '有效设置禁用了此技能。'
                elif not explicit and mode['mode'] != 'auto':
                    reason = '此技能仅允许显式指定。'
                elif not ready['executable']:
                    reason = ready['reason']
                elif target == 'anatomy.explainer' and purpose != 'scene-guidance' and re.search(r'(CAD|STEP|STL|公差|制造图|MP4|视频|发动机|机械手)', message, re.I):
                    reason = '当前已验证的是齿轮传动交互模板；自由结构、CAD 和视频任务尚未接通。'
                elif target == 'anatomy.explainer' and purpose != 'scene-guidance' and not re.search(r'(齿轮|gear)', message, re.I):
                    reason = '当前科普执行器只支持齿轮传动，请在要求中明确齿轮主题。'
                elif target == 'jarvis.tank-game' and purpose == 'chat':
                    reason = '游戏需要产物任务，请选择坦克游戏技能任务；普通聊天不会创建文件。'
                elif target == 'anatomy.explainer' and purpose == 'chat':
                    reason = '此技能需要真实产物任务，请使用科普技能任务入口。'
                elif target == 'rea.software-analysis' and purpose == 'chat':
                    reason = '此技能需要解析应用目录，请在技能任务中选择目标目录后运行。'
                if reason:
                    excluded.append({'id': target, 'reason': reason, 'policy': mode})
                else:
                    selected.append({'id': target, 'version': item['version'], 'workflow': item['workflow'],
                                     'policy': mode, 'reason': '用户明确指定。' if explicit else '当前目标与已准入工作流匹配。'})
            decision = {'schema_version': 1, 'bundle_digest': binding, 'selected': selected, 'excluded': excluded,
                        'direct': not selected, 'purpose': purpose, 'message_digest': policy.digest(message.encode('utf-8'))}
            if record:
                db.execute('INSERT INTO skill_decisions(task_id,created_at,document) VALUES(?,?,?)', (task_id, timestamp(), policy.canonical_json(decision)))
        return decision

    def guidance(self, decision):
        data, binding = catalog()
        if binding != decision['bundle_digest']:
            raise policy.CoreError('skill_content_changed', '技能内容在选择后变化，未加载旧正文。')
        guides = []
        for selected in decision['selected']:
            item = next(x for x in data['skills'] if x['id'] == selected['id'])
            if item['id'] in CORE_GUIDES:
                guides.append(item['guide'])
        text = '\n'.join(guides)
        if len(text.encode('utf-8')) > GUIDE_LIMIT:
            raise policy.CoreError('skill_context_limit', '技能正文超过本轮预算，未静默截断。')
        return text

    def decisions(self):
        with self.core.effect_guard(), self.extensions.connection() as db:
            self._tables(db)
            return {'decisions': [{'id': r['id'], 'task_id': r['task_id'], 'created_at': r['created_at'],
                                  **json.loads(r['document'])} for r in db.execute('SELECT * FROM skill_decisions ORDER BY id DESC LIMIT 30')]}
