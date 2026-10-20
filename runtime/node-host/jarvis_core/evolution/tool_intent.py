"""Local, bounded tool requests and durable gap handoff; never invent an oracle.

Exact named calls with explicit JSON can be admitted. Lexical suggestions are
reviewable proposals only, not semantic certainty or authority to run code.
"""
import copy
import json
import re

from .. import policy
from ..coding_demand import CodingDemands
from ..conversation_tasks import conversation_id
from .catalog import encoded, fail, runtime_binding

CALL = re.compile(r'^(?:请帮我|帮我|请)?\s*(?:使用|调用|运行|用)\s*(.{2,96}?)\s*(?:处理|计算|转换|输入(?:为|是)?|参数(?:为|是)?|[:：])\s*([\s\S]+)$')
NON_ACTION = re.compile(r'^(?:不要|别|不需要|如果|假如|假设|以后|将来|等到|怎么|如何|为什么|解释|介绍|他说|她说|你说|示例|例如|["“‘`])|[?？]|(?:是什么意思|怎么用|如何用)$')


def normalize(value):
    return re.sub(r'\s+','',value).casefold()


def terms(text):
    out=set(re.findall(r'[a-z0-9][a-z0-9_-]+',text.casefold()))
    for part in re.findall(r'[\u4e00-\u9fff]+',text):
        out.update(part[n:n+2] for n in range(len(part)-1))
    return out-{'工具','使用','处理','数据','帮我','请用'}


def parse(message):
    text=re.sub(r'^/工具(?:\s+|$)','',message).strip()
    match=CALL.fullmatch(text)
    goal=match[1].strip() if match else text
    if NON_ACTION.search(goal):return {'goal':goal,'discussed':True}
    result={'goal':goal,'direct':bool(match)}
    if match:
        def obj(pairs):
            value={}
            for key,item in pairs:
                if key in value:raise ValueError('duplicate JSON key')
                value[key]=item
            return value
        try:
            value=json.loads(match[2],object_pairs_hook=obj,parse_constant=lambda _:(_ for _ in ()).throw(ValueError()))
            encoded(value);result['input']=value
        except (ValueError,RecursionError,policy.CoreError):result['input_error']='请输入完整、有效且不超过 8 KiB 的 JSON；没有猜测输入。'
    return result


class ToolIntents:
    def __init__(self,tools):
        self.tools,self.store,self.core=tools,tools.store,tools.core

    def catalog(self,cid):
        scope=self.tools.scope(cid);result=[]
        with self.store.connection() as db:
            rows=db.execute('SELECT * FROM project_tools WHERE project_id=? ORDER BY tool_id',(scope['project_id'],)).fetchall()
        for raw in rows:
            row=dict(raw);meta=None;issue=None
            from .lifecycle import ToolLifecycle
            life=ToolLifecycle(self.tools).state(scope['project_id'],row['tool_id'])
            if life['phase']=='STORED':continue
            try:
                ident=row['active'] or row['previous'] or life.get('candidate') or life.get('retired_version')
                if ident:meta=self.tools.package(ident,row)[0]['metadata']
            except policy.CoreError as exc:issue=exc.code
            result.append({**{k:row[k] for k in ('tool_id','active','previous','generation')},'metadata':meta,'issue':issue,'lifecycle_phase':life['phase'],'lifecycle_revision':life['revision']})
        return result

    @staticmethod
    def binding(rows):return policy.digest(policy.canonical_json(rows).encode())

    def decide(self,parsed,rows):
        if parsed.get('discussed'):return {'decision':'discussed','candidates':[],'reason':'这是说明、假设、否定或问题，没有作为执行指令。'}
        goal=normalize(parsed['goal']);matches=[]
        for row in rows:
            meta=row['metadata'] or {};exact=goal in {normalize(row['tool_id']),normalize(meta.get('name',''))}
            overlap=terms(parsed['goal']) & terms(row['tool_id']+' '+meta.get('name','')+' '+meta.get('when_to_use',''))
            if exact or overlap:
                matches.append({**row,'exact':exact,'matched_terms':sorted(overlap)[:12]})
        exact=[x for x in matches if x['exact']]
        candidates=exact or sorted(matches,key=lambda x:(-len(x['matched_terms']),x['tool_id']))[:5]
        decision='gap'
        if len(exact)==1:
            row=exact[0]
            decision='unavailable' if not row['active'] or row['issue'] else 'ready' if parsed.get('direct') and 'input' in parsed else 'input_needed'
        elif candidates:decision='choose'
        return {'decision':decision,'candidates':candidates,'reason':{
            'gap':'本项目目录中没有匹配的已登记工具；可继续提出编码需求，不能据此认定全系统都不会。',
            'choose':'有多个名称或用途候选；词法相关性不等于适用性，请选择并核对输入。',
            'unavailable':'指定工具已停用或完整性异常，请先到工具库核对恢复。',
            'ready':'唯一明确指定的已启用工具，输入来自本次完整 JSON。',
            'input_needed':parsed.get('input_error','已找到工具，请提供本次 JSON 输入。')}[decision]}

    def propose(self,cid,payload):
        scope=self.tools.scope(cid)
        if not isinstance(payload,dict) or set(payload)!={'request_id','message'}:fail('工具需求需要请求编号和原话。')
        conversation_id(payload['request_id']);message=payload['message']
        if not isinstance(message,str) or not message.strip() or '\0' in message or len(message.encode())>12288:fail('工具需求文本无效或超过 12 KiB。')
        submission=copy.deepcopy(payload);key='tool-plan-'+payload['request_id'];old=self.store.existing_job(key)
        if old:
            if old['request']['scope']!=scope or old['request']['submission']!=submission:fail('请求编号已用于不同需求。','evolution_conflict')
            return self.view(cid,old['id'])
        rows=self.catalog(cid);parsed=parse(message);proposal=self.decide(parsed,rows)
        request={'action':'project-tool-plan','request_id':key,'scope':scope,'submission':submission,
            'parsed':parsed,'catalog_binding':self.binding(rows),'runtime_binding':runtime_binding()}
        job,_=self.store.create_job(request,proposal=proposal)
        return self.view(cid,job['id'])

    def bound(self,cid,ident):
        conversation_id(ident);job=self.store.job(ident)
        if job['request'].get('action')!='project-tool-plan' or job['request']['scope']!=self.tools.scope(cid):fail('未找到本会话的工具需求。','not_found')
        return job

    def view(self,cid,ident):
        job=self.bound(cid,ident);child=self.store.existing_job('project-tool-'+ident)
        if child:child=self.tools.bound_job(cid,child['id'])
        result={k:job[k] for k in ('id','status','created_at','proposal')}
        result['request']={'action':'project-tool-plan','origin':{'goal':job['request']['submission']['message']}}
        result.update(message=job['request']['submission']['message'],parsed=job['request']['parsed'],coding_request_id=ident,
                      invocation=child,coding=None)
        if self.tools.tasks:
            try:result['coding']=CodingDemands(self.core,self.tools.tasks).lookup(cid,ident)
            except policy.CoreError as exc:
                if exc.code!='not_found':raise
        return result

    def lookup(self,cid,request_id):
        conversation_id(request_id);self.tools.scope(cid);job=self.store.existing_job('tool-plan-'+request_id)
        if not job:fail('没有找到原需求回执；没有重新提交。','not_found')
        return self.view(cid,job['id'])

    def listing(self,cid):
        scope=self.tools.scope(cid)
        with self.store.connection() as db:
            ids=[r[0] for r in db.execute("SELECT id FROM jobs WHERE json_extract(document,'$.request.action')='project-tool-plan' AND json_extract(document,'$.request.scope.conversation_id')=? ORDER BY rowid DESC LIMIT 30",(cid,))]
        return [self.view(cid,x) for x in ids if self.store.job(x)['request']['scope']==scope]

    def fresh(self,job,cid):
        if job['status']!='PROPOSED':fail('需求已取消，请重新分析。','evolution_conflict')
        if job['request']['catalog_binding']!=self.binding(self.catalog(cid)) or job['request']['runtime_binding']!=runtime_binding():
            fail('工具目录或执行器已变化，请重新分析；没有替换原选择。','evolution_conflict')

    def start(self,cid,ident,payload):
        job=self.bound(cid,ident);decision=job['proposal'];parsed=job['request']['parsed']
        if not isinstance(payload,dict):fail('工具选择必须是对象。')
        if decision['decision']=='ready' and not payload:
            selected=decision['candidates'][0];value=parsed['input'];extra={}
        else:
            if decision['decision'] not in {'ready','choose','input_needed'} or not {'tool_id','input'}<=set(payload) or set(payload)-{'tool_id','input','expected'}:fail('此需求还不能执行；请选择候选并提供输入。')
            selected=next((x for x in decision['candidates'] if x['tool_id']==payload['tool_id'] and x['active'] and not x['issue']),None)
            if not selected:fail('所选工具不在本次可用候选中。')
            value=payload['input'];extra={'expected':payload['expected']} if 'expected' in payload else {}
        request={'operation':'run','request_id':ident,'tool_id':selected['tool_id'],'generation':selected['generation'],'input':value,**extra}
        # Reconcile an admitted call even if the directory changed afterward.
        if not self.store.existing_job('project-tool-'+ident):self.fresh(job,cid)
        return self.tools.submit(cid,request)

    def coding(self,cid,ident,payload):
        job=self.bound(cid,ident)
        if job['proposal']['decision']!='gap':fail('已有候选的需求不能绕过选择直接变成新代码。')
        if not isinstance(payload,dict) or set(payload)!={'request_id','prompt','coding'} or payload['request_id']!=ident or payload['prompt']!=job['request']['submission']['message']:
            fail('编码改进单必须保留原需求和请求编号。')
        demands=CodingDemands(self.core,self.tools.tasks)
        try:demands.lookup(cid,ident)
        except policy.CoreError as exc:
            if exc.code!='not_found':raise
            self.fresh(job,cid)
        return demands.propose(cid,payload)

    def cancel(self,cid,ident):
        job=self.view(cid,ident)
        if job['invocation']:return self.tools.manager.cancel(job['invocation']['id'])
        if job['coding']:return CodingDemands(self.core,self.tools.tasks).cancel(cid,job['coding']['id'],{})
        from .tool_contract import ToolContracts
        for draft in ToolContracts(self.tools).listing(cid,ident):
            if draft['status'] in {'QUEUED','RUNNING','OBSERVING'}:self.tools.manager.cancel(draft['id'])
        return self.tools.manager.cancel(ident)
