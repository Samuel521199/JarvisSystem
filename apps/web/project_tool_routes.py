"""Project tools share the existing workbench authentication and growth lane."""
import re
from jarvis_core.evolution.catalog import ProjectTools
from jarvis_core.policy import CoreError
from evolution_routes import failure


def service(handler):
    host=handler.server
    if host.evolution is None or host.conversation_tasks is None:
        raise CoreError('evolution_unavailable','成长或会话任务模块暂不可用。')
    return ProjectTools(host.evolution,host.conversation_tasks)


def get(handler):
    if handler.path=='/project-tools.js':
        handler._send(200,handler.server.project_tools_script,'application/javascript; charset=utf-8');return True
    match=re.fullmatch(r'/api/project-tools/([a-f0-9]{32})(?:/jobs/([a-f0-9]{32}))?',handler.path)
    if not match:return False
    if not handler._workspace_token() or not handler._guard():return True
    try:
        tools=service(handler)
        handler._send(200,tools.bound_job(*match.groups()) if match[2] else tools.snapshot(match[1]))
    except Exception as exc:failure(handler,exc)
    return True


def post(handler,payload):
    try:
        match=re.fullmatch(r'/api/project-tools/([a-f0-9]{32})(?:/jobs/([a-f0-9]{32})/cancel)?',handler.path)
        if not match:raise CoreError('not_found','未找到工具入口。')
        tools=service(handler)
        if match[2]:
            if payload!={}:raise CoreError('invalid_request','取消只接受空对象。')
            tools.bound_job(match[1],match[2]);value=tools.manager.cancel(match[2])
        else:value=tools.submit(match[1],payload)
        handler._send(202,value)
    except Exception as exc:failure(handler,exc)
