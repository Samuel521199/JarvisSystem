/* Personal plans stay tied to their conversation. No implicit model submission. */
(()=>{
'use strict';
const $=id=>document.getElementById(id),el=(tag,text)=>{const n=document.createElement(tag);if(text!==undefined)n.textContent=text;return n;};
const labels={DRAFT:'待配置',ACTIVE:'执行中',PAUSED:'已暂停',BLOCKED:'需要核对',COMPLETE:'已交付',CANCELLING:'正在取消',CANCELLED:'已取消',SUBMITTING:'正在交接',RUNNING:'原任务执行中',SUCCEEDED:'交付已核验',FAILED:'失败',UNKNOWN:'结果未知',NEEDS_EDIT:'需要补充'};
const button=el('button');button.id='open-personal-plans';button.type='button';button.className='icon-button topbar-action';
button.setAttribute('aria-label','个人计划与主动跟进');button.title='个人计划与主动跟进';
button.innerHTML='<svg class="icon" viewBox="0 0 24 24" aria-hidden="true"><path d="M9 5h11M9 12h11M9 19h11M3 5l1 1 2-3M3 12l1 1 2-3M3 19l1 1 2-3"/></svg>';
const tip=el('span','个人计划与主动跟进');tip.className='topbar-tooltip';tip.id='personal-plans-tip';tip.setAttribute('role','tooltip');button.setAttribute('aria-describedby',tip.id);button.append(tip);
$('open-explorer').before(button);
const dialog=el('dialog');dialog.className='personal-plans';dialog.setAttribute('aria-label','个人计划与主动跟进');
document.body.append(dialog);let selected=null,rows=[],cid=null,dirty=false,busy=false,defaults=null,unfinished=[];
const status=el('p');status.setAttribute('role','status');
function btn(parent,title,work){const b=el('button',title);b.type='button';b.onclick=async()=>{if(busy){status.textContent='上一项操作仍在保存，请稍候。';return;}busy=true;dialog.setAttribute('aria-busy','true');b.disabled=true;status.textContent='';try{await work();}catch(e){status.textContent=e.message;status.className='plan-error';}finally{busy=false;dialog.setAttribute('aria-busy','false');b.disabled=false;}};parent.append(b);return b;}
function field(parent,label,tag='input',value=''){const wrap=el('label',label),input=el(tag);input.value=value;input.setAttribute('aria-label',label);wrap.append(input);parent.append(wrap);return input;}
function select(parent,label,choices,value){const n=field(parent,label,'select');for(const [v,t] of choices){const o=el('option',t);o.value=v;n.append(o);}n.value=value;return n;}
function id(){return crypto.randomUUID().replaceAll('-','');}
async function api(path='',payload){const r=await fetch('/api/assistant-plans'+path,{method:payload===undefined?'GET':'POST',cache:'no-store',credentials:'omit',headers:{'X-Jarvis-Nonce':NONCE,...(payload===undefined?{}:{'Content-Type':'application/json'})},body:payload===undefined?undefined:JSON.stringify(payload),signal:AbortSignal.timeout(12000)});const d=await r.json();if(!r.ok)throw new Error(d.user_message||'计划操作未确认，请重新读取。');return d;}
function current(){const c=window.Workspace?.currentConversation();return c&&!c.temporary?c.id:null;}
async function load(render=true){
 const c=current();if(!c){cid=null;rows=[];unfinished=[];if(render&&!dirty)draw();return;}
 const result=await api('?conversation_id='+c);
 if(c!==current())return;
 rows=result.plans;defaults=result.policy_defaults;unfinished=result.unfinished||[];cid=c;
 button.dataset.unread=String(rows.some(r=>r.state==='DRAFT'||r.notifications.some(n=>!n.read)));
 if(render&&!dirty)draw();
}
async function change(row,action,extra={}){const result=await api('/'+row.id,{action,revision:row.revision,...extra});dirty=false;selected=result.id;await load();return result;}
function draw(){
 const header=el('header'),title=el('h2','个人计划'),body=el('div');
 header.append(title);btn(header,'关闭',()=>{if(dirty&&!confirm('关闭将丢弃未保存的编辑，继续？'))return;dialog.close();});dialog.replaceChildren(header,status,body);
 status.className='';status.textContent='';
 if(!cid){body.append(el('p','先发送一条消息，保存当前会话后即可整理计划。'));return;}
 const top=el('div');top.className='plan-actions';body.append(top);
 btn(top,'所有计划',()=>{if(dirty&&!confirm('放弃当前未保存的计划编辑？'))return;dirty=false;selected=null;draw();});
 btn(top,'重新读取',async()=>{if(dirty&&!confirm('重新读取会丢弃未保存的编辑，继续？'))return;dirty=false;await load();});
 btn(top,'新建 / 从聊天整理',()=>createForm(body));
 const row=rows.find(r=>r.id===selected);
 if(!row){
  body.append(el('p','这里保存目标、分步进度和待办。草案不会自动执行；原任务结果未知时不会重跑。'));
  for(const r of rows){const card=el('section');card.className='plan-entry';card.append(el('strong',r.goal),el('p',(labels[r.state]||r.state)+' · '+r.steps.filter(s=>s.state==='SUCCEEDED').length+'/'+r.steps.length+' 步'));btn(card,'查看与调整',()=>{selected=r.id;draw();});body.append(card);}
  if(!rows.length)createForm(body);return;
 }
 title.textContent='个人计划 · '+(labels[row.state]||row.state);
 body.append(el('h3',row.goal));
 if(!row.scope_valid)body.append(el('p','原会话或未结事项已变更。此计划不能继续执行或纳入记忆，请核对来源后重新整理。'));
 if(row.reason)body.append(el('p',row.reason));
 for(const n of row.notifications.filter(n=>!n.read)){const p=el('p',n.message);p.className='plan-notice';body.append(p);}
 if(row.notifications.some(n=>!n.read))btn(body,'已查看跟进',()=>change(row,'ack'));
 body.append(el('p','模型调用 '+row.usage.calls+'/'+row.policy.max_calls+' · 已预留 $'+row.usage.reserved.USD+' / ¥'+row.usage.reserved.CNY+'。按配置价表保守预留，未知价格不自动派发；实际账单以供应商为准。'));
 const actions=el('div');actions.className='plan-actions';body.append(actions);
 if(['DRAFT','PAUSED','BLOCKED'].includes(row.state))btn(actions,'确认计划并继续',()=>{if(dirty)throw new Error('请先保存修改，再确认执行。');return change(row,'start',{policy:readPolicy()});});
 if(row.state==='ACTIVE')btn(actions,'暂停后续步骤',()=>change(row,'pause'));
 if(!['COMPLETE','CANCELLED','CANCELLING'].includes(row.state))btn(actions,'取消计划',()=>change(row,'cancel'));
 if(['BLOCKED','PAUSED','CANCELLED','COMPLETE'].includes(row.state))btn(actions,'重新分析为新草案',()=>change(row,'replan'));
 const policyBox=el('details');policyBox.open=['DRAFT','PAUSED','BLOCKED'].includes(row.state);policyBox.append(el('summary','主动跟进与预算授权'));body.append(policyBox);
 const pgrid=el('div');pgrid.className='plan-policy';policyBox.append(pgrid);const inputs={};
 inputs.followup=select(pgrid,'主动跟进',[['false','关闭'],['true','启用站内跟进']],String(row.policy.followup));
 for(const [key,label] of [['interval_minutes','最短间隔（分钟）'],['daily_limit','每日最多提醒'],['quiet_start','安静开始（小时）'],['quiet_end','安静结束（小时）'],['max_calls','计划模型调用上限'],['usd','美元预留上限'],['cny','人民币预留上限']]){inputs[key]=field(pgrid,label,'input',row.policy[key]);inputs[key].type='number';inputs[key].min=0;inputs[key].step=['usd','cny'].includes(key)?'0.01':'1';}
 policyBox.append(el('p','跟进为本机站内提示，不调用模型。安静时间使用保存的 UTC 偏移；不会重新执行已完成或未知任务。'));
 function readPolicy(){return {...row.policy,utc_offset_minutes:-new Date().getTimezoneOffset(),...Object.fromEntries(Object.entries(inputs).map(([k,n])=>[k,k==='followup'?n.value==='true':Number(n.value)]))};}
 const editors=[];
 const editable=row.state!=='ACTIVE'&&row.state!=='CANCELLED';
 function addStep(step){
  const card=el('section');card.className='plan-step';card.dataset.state=step.state||'DRAFT';body.append(card);
  card.append(el('small',(labels[step.state]||'待配置')+(step.task_id?' · '+step.task_id:'')));
  const name=field(card,'步骤目标','input',step.title),prompt=field(card,'发送给执行器的要求','textarea',step.payload?.prompt||step.title);
  const grid=el('div');grid.className='plan-grid';card.append(grid);
  const mode=select(grid,'执行能力',[['','尚未配置'],['mcp','研究文档（Context7）'],['team','多 Agent 分析'],['natural','样例目录报告'],['skill','技能 / 编码']],step.payload?.mode||'');
  const models=(typeof modelCatalog!=='undefined'?modelCatalog:[]).map(m=>[m.provider+'::'+m.model,m.label||m.model]);
  const route=select(grid,'模型',[['','请选择'],['auto','自动路由（须有有效价表）'],...models],step.payload?.planner_model||step.payload?.model||'');
  const library=field(grid,'研究库名 / 文档库 ID','input',step.payload?.library||''),relative=field(grid,'样例根内相对目录','input',step.payload?.relative_path||'.');
  const deps=select(grid,'等待哪个步骤完成',[['','无依赖'],...row.steps.filter(s=>s.ordinal<step.ordinal).map(s=>[s.id,s.title])],step.depends_on?.[0]||'');
  const include=select(grid,'将前序结果交给下一步',[['false','不传递'],['true','明确允许传递摘要']],String(step.include_results||false));
  const advanced=el('details');advanced.append(el('summary','技能 / 编码参数与完整依赖'));const json=field(advanced,'沿用现有任务参数（不含 request_id）','textarea',JSON.stringify(step.payload||{},null,2));card.append(advanced);
  btn(advanced,'导入当前技能 / 编码设置',()=>{const p=window.SkillWorkbench.planPayload(prompt.value);json.value=JSON.stringify(p,null,2);mode.value='skill';dirty=true;});
  const stateLocked=!editable||!['DRAFT','NEEDS_EDIT'].includes(step.state||'DRAFT');
  function relevant(){library.parentElement.hidden=mode.value!=='mcp';relative.parentElement.hidden=mode.value!=='natural';route.parentElement.hidden=!['natural','team'].includes(mode.value);advanced.hidden=mode.value!=='skill';}
  mode.addEventListener('change',relevant);relevant();
  if(stateLocked){
   const summary=el('h3',step.title),settings=el('details');settings.append(el('summary','查看已提交的步骤设置'));
   for(const part of [name.parentElement,prompt.parentElement,grid,advanced])settings.append(part);
   card.append(summary,settings);
  }
  for(const n of [name,prompt,mode,route,library,relative,deps,include,json]){n.disabled=stateLocked;n.addEventListener('input',()=>{dirty=true;});}
  for(const n of advanced.querySelectorAll('button'))n.disabled=stateLocked;
  editors.push(()=>{if(stateLocked)return Object.fromEntries(['id','title','payload','depends_on','include_results'].map(k=>[k,step[k]]));
   let payload=null;
   if(mode.value==='mcp')payload={mode:'mcp',prompt:prompt.value,library:library.value,...(row.project_id?{project_id:row.project_id}:{})};
   if(mode.value==='team')payload={mode:'team',prompt:prompt.value,criteria:['满足本步骤目标','指出不确定性与需要验证的内容'],planner_model:route.value,reviewer_model:route.value,auto_team:true,max_agents:2};
   if(mode.value==='natural')payload={mode:'natural',prompt:prompt.value,model:route.value,relative_path:relative.value};
   if(mode.value==='skill')payload={...JSON.parse(json.value),mode:'skill',prompt:prompt.value,project_id:row.project_id};
   return {id:step.id,title:name.value,payload,depends_on:deps.value?[deps.value]:[],include_results:include.value==='true'};});
  if(step.reason)card.append(el('p',step.reason));
  if(step.task_id)btn(card,'查看原任务与产物',()=>{dialog.close();return window.ConversationTasks?.openTask?.(step.task_id);});
  if(step.result){const details=el('details');details.append(el('summary','原始交付摘要'+(step.result.truncated?'（已截取）':'')),el('pre',step.result.text));card.append(details);}
  if(!stateLocked){const existing=el('details');existing.append(el('summary','或关联已经独立执行的任务'));card.append(existing);const link=field(existing,'本会话已有任务 ID');existing.append(el('small','已有任务的费用属于原任务，不计入本计划新增调用预算。'));btn(existing,'关联已有任务',()=>change(row,'link',{step_id:step.id,task_id:link.value.trim()}));}
 }
 row.steps.forEach(addStep);
 if(editable){const edits=el('div');edits.className='plan-actions';body.append(edits);
  btn(edits,'补充一步',()=>{if(editors.length>=8)throw new Error('每计划最多八步。');addStep({id:id(),title:'补充任务',state:'DRAFT',ordinal:editors.length,payload:null,depends_on:[],include_results:false});dirty=true;});
  btn(edits,'保存修改与授权',()=>change(row,'edit',{steps:editors.map(f=>f()),policy:readPolicy()}));
 }
 for(const n of Object.values(inputs)){n.disabled=!editable;n.addEventListener('input',()=>{dirty=true;});}
 if(row.candidate){
  const c=row.candidate,section=el('section');section.className='plan-entry';body.append(section);section.append(el('h3','结果候选 · '+({pending:'待确认',accepted:'已纳入',withdrawn:'已撤回'}[c.state]||c.state)));
  if(c.state!=='withdrawn'){
   const content=field(section,'可纠正的结果笔记','textarea',c.content);content.oninput=()=>{dirty=true;};
   btn(section,'保存纠正（旧引用立即失效）',()=>change(row,'candidate',{content:content.value}));
   const kind=select(section,'纳入范围',[['knowledge','工作用途知识笔记（不进入个人闲聊）'],[row.project_id?'project':'personal',row.project_id?'当前项目工作结果':'明确确认为我的经历']],c.kind||'knowledge');
   btn(section,'确认纳入',()=>{if(content.value!==c.content)throw new Error('请先保存纠正后的内容。');return change(row,'accept',{kind:kind.value,providers:[]});});
   section.append(el('small','记忆默认不向云端模型开放。确认后可在记忆面板选择供应商；工作结果不会自动推断成个人喜好。'));
   btn(section,'撤回此结果候选',()=>change(row,'withdraw'));
  }
 }
}
function createForm(body){
 if(body.querySelector('#plan-create-form'))return;
 const form=el('section');form.id='plan-create-form';form.className='plan-entry';body.prepend(form);
 const goal=field(form,'这次想完成什么？','textarea',$('message').value.trim());
 const steps=field(form,'行动或未结事项（每行一步，可先不配置执行能力）','textarea','');
 if(unfinished.length){
  const choice=select(form,'已有未结事项',unfinished.map(n=>[n.id,n.title]),unfinished[0].id);
  btn(form,'从未结事项创建草案',async()=>{const note=unfinished.find(n=>n.id===choice.value);
   const r=await api('',{id:id(),conversation_id:cid,goal:note.title,source:note.next_step,
    continuity_source:{id:note.id,revision:note.revision},steps:[{id:id(),title:note.next_step.slice(0,150),payload:null,depends_on:[]}]});
   selected=r.id;dirty=false;await load();});
 }
 btn(form,'保存可编辑草案',async()=>{await window.Conversations?.flush();const parts=(steps.value||goal.value).split(/\n|[；;]/).map(s=>s.trim()).filter(Boolean);
  let previous=null;const items=parts.map(title=>{const item={id:id(),title,payload:null,depends_on:previous?[previous]:[]};previous=item.id;return item;});
  const r=await api('',{id:id(),conversation_id:cid,goal:goal.value,source:goal.value,steps:items});selected=r.id;dirty=false;await load();});
}
button.onclick=async()=>{cid=current();if(!dialog.open)dialog.show();try{if(cid)await load();else draw();}catch(e){draw();status.textContent=e.message;}};
dialog.addEventListener('keydown',e=>{if(e.key==='Escape'){if(!dirty||confirm('关闭将丢弃未保存的编辑，继续？'))dialog.close();e.preventDefault();}});
dialog.addEventListener('cancel',e=>{if(dirty&&!confirm('保留编辑请取消关闭；确认关闭将丢弃未保存的编辑。'))e.preventDefault();});
dialog.addEventListener('close',()=>{dirty=false;});
window.addEventListener('jarvis:conversation-context',()=>{if(dialog.open&&dirty){status.textContent='会话已切换。此处仍显示原计划；关闭后重新打开查看新会话。';return;}selected=null;cid=current();load(dialog.open).catch(()=>{});});
const timer=setInterval(()=>{if(document.visibilityState==='visible'&&!busy&&!dirty)load(dialog.open).catch(()=>{});},15000);
window.addEventListener('pagehide',()=>clearInterval(timer));
window.PersonalPlans={open:(ident)=>{if(ident)selected=ident;button.click();},refresh:()=>load(dialog.open)};
})();
