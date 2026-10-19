"""Explicit personal commands, parsed only from the current owner's input.

No inference/extraction model, transcript scan, background job or task dispatch.
The whole input must use an anchored command; quotations and examples are data.
"""
import re
import uuid

from .memory import MemoryError, normalized
from .persona import PersonaStore
from . import continuity

ENGINE = 'personal-core-v1'
COMMAND = re.compile(r'^(?:请)?(记住本项目|修改本项目记忆|忘记本项目|查看本项目记忆|记住|修改记忆|忘记|查看记忆|设置交流风格|设置相处方式|设置称呼|查询三库)\s*[：:]\s*([^\r\n]+)$')
BARE = {'查看记忆', '查看本项目记忆', '查看交流设置', '恢复默认交流设置', '撤销交流设置', '查看能力'}


def validate_context(value):
    if value is None:
        return None
    if not isinstance(value, dict) or not {'temporary'} <= set(value) or set(value)-{'temporary','source'} or type(value['temporary']) is not bool:
        raise ValueError('Invalid personal context')
    if 'source' in value:
        continuity.validate_source(value['source'])
    return value


def parse(message):
    value = message.strip()
    checkpoint = continuity.parse(value)
    if checkpoint:
        return checkpoint
    if value in BARE:
        return value, ''
    match = COMMAND.fullmatch(value)
    return (match[1], match[2].strip()) if match else None


def execute(command, *, core, memory, memory_context, personal_context, request_id=None, cancel_event=None, message=None):
    name, body = command
    if name in {'查询三库', '查看能力'}:
        from .reference_library import ReferenceLibrary
        return ReferenceLibrary(core).query(body, capabilities=name == '查看能力')
    if personal_context is None or personal_context['temporary']:
        raise MemoryError('personal_disabled', '临时会话或未声明的会话模式不读取或修改个人记忆、交流设置；请使用普通会话。')
    request_id = request_id or uuid.uuid4().hex
    if '交流' in name or '相处' in name or name == '设置称呼':
        store = PersonaStore(core)
        if name == '查看交流设置':
            row = store.snapshot()
            return f"当前称呼：{row['preferred_name'] or '未设置'}；交流风格：{row['style']}；相处方式：{row['relationship']}；修订 {row['revision']}。", {'kind': 'persona', 'action': 'view', 'committed': False, **row}
        field = {'设置交流风格': 'style', '设置相处方式': 'relationship', '设置称呼': 'preferred_name', '恢复默认交流设置': 'reset', '撤销交流设置': 'undo'}[name]
        receipt = store.change(field, body if field in ('style', 'relationship', 'preferred_name') else None, request_id=request_id, cancel_event=cancel_event)
        text = ('此请求已处理，未重复修改。可发送“查看交流设置”核对当前状态。' if receipt['replayed'] else
                f"已保存交流设置：{receipt['preferred_name'] or '未设置称呼'} · {receipt['style']} · {receipt['relationship']}（修订 {receipt['revision']}）。从下一轮普通对话开始生效，新会话和切换模型后继续使用，包括所选云端模型；临时会话不使用。可发送“撤销交流设置”恢复上一版。")
        return text, receipt
    if not memory_context or not memory_context['enabled']:
        raise MemoryError('personal_disabled', '当前未启用记忆；请先在记忆面板开启普通会话记忆。')
    if name in {'保存接续','更新接续','查看接续','继续话题','完成接续','重新打开接续','忘记接续'}:
        memory._project(memory_context['project_id'])
        return continuity.execute(command, core=core, project_id=memory_context['project_id'], source=personal_context.get('source'),
                                  message=message, request_id=request_id, cancel_event=cancel_event)
    project_id = memory_context['project_id'] if '本项目' in name else None
    if '本项目' in name and not project_id:
        raise MemoryError('invalid_memory', '请先选择项目；未把项目记忆存成通用记忆。')
    if name.startswith('查看'):
        rows = [r for r in memory.list(project_id=project_id)['facts'] if r['document']['project_id'] == project_id
                and normalized(body) in normalized(r['document']['title']+'\n'+r['document']['content'])]
        text = '当前范围没有匹配的记忆。' if not rows else '\n\n'.join(
            f"{r['document']['title']}：{r['document']['content']}\n标识 {r['id']} · 修订 {r['revision']} · "
            + ('仅本地使用' if not r['document']['providers'] else '允许接入方：本地、'+'、'.join(r['document']['providers']))
            + (' · 来源尚未核实，暂停用于回答；请在记忆面板核对' if r.get('provenance',{}).get('state') in {'unchecked','source_changed_or_missing'} else '') for r in rows[:20])
        if len(rows) > 20:
            text += '\n\n这里只显示前 20 条，请缩小关键词或打开记忆面板。'
        return text, {'kind': 'memory', 'action': 'view', 'committed': False}
    action = 'remember' if name.startswith('记住') else 'correct' if name.startswith('修改') else 'forget'
    if action in ('remember', 'correct'):
        parts = re.split('[=＝]', body, maxsplit=1)
        if len(parts) == 1 and action == 'correct':
            raise MemoryError('invalid_memory', '请使用“修改记忆：完整名称=新内容”。')
        title, content = (parts[0].strip(), parts[1].strip()) if len(parts) == 2 else (body[:60], body)
    else:
        title, content = body, None
    receipt = memory.command(action, title, content, project_id=project_id, request_id=request_id, cancel_event=cancel_event)
    if receipt['replayed']:
        return '此请求已处理，未重复写入或恢复旧内容。可发送“查看记忆”核对当前状态。', receipt
    if action == 'forget':
        text = '已忘记这条长期记忆，后续不再作为记忆使用。原聊天记录和已有导出未删除。'
    else:
        text = ('已记住' if action == 'remember' else '已纠正') + f"：{title}。已存入{'本项目' if project_id else '通用'}记忆（修订 {receipt['revision']}）。"
        text += ' 新记忆默认仅本地使用；需要云端模型记住时，可在记忆面板勾选允许的接入方。' if action == 'remember' else ' 原使用范围与接入方授权保持不变。'
    return text, receipt
