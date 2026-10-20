"""Exact loopback routes for personal plans; reuse the owner's page token."""
import re
from urllib.parse import urlsplit, parse_qs

from jarvis_core.policy import CoreError
from jarvis_core.runtime_admission import coordinator


def handle(handler, *, post=False):
    url=urlsplit(handler.path)
    if not post and url.path in {'/assistant-plans.js','/assistant-plans.css'}:
        name=url.path[1:]
        mime='application/javascript' if name.endswith('.js') else 'text/css'
        handler._send(200,handler.server.ui_assets.optional(name),mime+'; charset=utf-8')
        return True
    match=re.fullmatch(r'/api/assistant-plans(?:/([a-f0-9]{32}))?',url.path)
    if not match:return False
    if not handler._conversation_token():return True
    service=getattr(handler.server,'assistant_plans',None)
    if service is None:
        handler._error(503,'plan_unavailable','个人计划模块暂不可用。')
        return True
    try:
        if post:
            lengths=handler.headers.get_all('Content-Length',[])
            if (handler.headers.get_all('Transfer-Encoding') or len(lengths)!=1
                    or not lengths[0].isdigit() or not 0<int(lengths[0])<=64000
                    or handler.headers.get('Content-Type','').split(';')[0]!='application/json'):
                raise CoreError('invalid_plan','请求格式或长度无效。')
            from server import strict_json
            value=strict_json(handler.rfile.read(int(lengths[0])))
            if not isinstance(value,dict):raise CoreError('invalid_plan','请求必须为对象。')
            if value.get('action') not in {'cancel','pause','withdraw','ack'} and not handler._guard():return True
            if match[1]:result=service.change(match[1],value)
            else:
                cid=value.pop('conversation_id',None)
                result=service.create(cid,value)
        else:
            query=parse_qs(url.query,keep_blank_values=True)
            if set(query)-{'conversation_id'} or any(len(v)!=1 for v in query.values()):
                raise CoreError('invalid_plan','查询字段无效。')
            result=service.view(match[1]) if match[1] else service.list(query.get('conversation_id',[None])[0])
            result['resource_admission']=coordinator(handler.server.core).snapshot()
        handler._send(200,result)
    except (ValueError,CoreError) as exc:
        handler._error(409 if getattr(exc,'code','')=='plan_conflict' else 400,
                       getattr(exc,'code','invalid_plan'),str(exc))
    except Exception:
        handler._error(503,'plan_unavailable','计划操作结果未确认，请重新读取；没有重新执行任务。')
    return True
