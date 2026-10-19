"""Project tools share the existing workbench authentication and growth lane."""
import re
from jarvis_core.evolution.catalog import ProjectTools
from jarvis_core.evolution.tool_intent import ToolIntents
from jarvis_core.policy import CoreError
from evolution_routes import failure


def service(handler):
    host=handler.server
    if host.evolution is None or host.conversation_tasks is None:
        raise CoreError('evolution_unavailable','成长或会话任务模块暂不可用。')
    return ProjectTools(host.evolution,host.conversation_tasks)


def get(handler):
    if handler.path=='/tool-intents.js':
        handler._send(200,handler.server.tool_intents_script,'application/javascript; charset=utf-8');return True
    if handler.path=='/project-tools.js':
        handler._send(200,handler.server.project_tools_script,'application/javascript; charset=utf-8');return True
    plan=re.fullmatch(r'/api/project-tools/([a-f0-9]{32})/plans(?:/(requests/)?([a-f0-9]{32}))?',handler.path)
    if plan:
        if not handler._workspace_token() or not handler._guard():return True
        try:
            intents=ToolIntents(service(handler))
            handler._send(200,intents.lookup(plan[1],plan[3]) if plan[2] else intents.view(plan[1],plan[3]) if plan[3] else intents.listing(plan[1]))
        except Exception as exc:failure(handler,exc)
        return True
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
        plan=re.fullmatch(r'/api/project-tools/([a-f0-9]{32})/plans(?:/([a-f0-9]{32})/(start|coding|cancel))?',handler.path)
        if plan:
            intents=ToolIntents(service(handler))
            if plan[3]=='cancel':
                if payload!={}:raise CoreError('invalid_request','取消只接受空对象。')
                value=intents.cancel(plan[1],plan[2])
            elif plan[3]:value=getattr(intents,plan[3])(plan[1],plan[2],payload)
            else:value=intents.propose(plan[1],payload)
            handler._send(202,value);return
        match=re.fullmatch(r'/api/project-tools/([a-f0-9]{32})(?:/jobs/([a-f0-9]{32})/cancel)?',handler.path)
        if not match:raise CoreError('not_found','未找到工具入口。')
        tools=service(handler)
        if match[2]:
            if payload!={}:raise CoreError('invalid_request','取消只接受空对象。')
            tools.bound_job(match[1],match[2]);value=tools.manager.cancel(match[2])
        else:value=tools.submit(match[1],payload)
        handler._send(202,value)
    except Exception as exc:failure(handler,exc)
