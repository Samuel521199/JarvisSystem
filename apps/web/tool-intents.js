/* Exact named calls are local; fuzzy matches and missing contracts stay drafts. */
(()=>{'use strict';
const current=()=>window.Workspace?.currentConversation(),pending=new Map();let creating=false,origin=null;
const active=s=>['QUEUED','RUNNING','OBSERVING'].includes(s),labels={ready:'已明确工具与输入',choose:'待选择工具',input_needed:'待补输入',gap:'目录中未匹配',discussed:'没有执行指令',unavailable:'工具暂不可用'};
const command=text=>/^\/工具(?:\s|$)/u.test(text)||/^(?:请帮我|帮我|请)?\s*(?:使用|调用|运行|用)\s*.{2,96}?(?:处理|计算|转换|输入(?:为|是)?|参数(?:为|是)?|[:：])\s*(?:[\[{"\d-]|true\b|false\b|null\b)/u.test(text);
function el(tag,text){const node=document.createElement(tag);if(text!==undefined)node.textContent=text;return node;}
function button(parent,text,fn){const b=el('button',text);b.type='button';b.onclick=fn;parent.append(b);return b;}
async function api(path,body){const response=await fetch(path,{method:body===undefined?'GET':'POST',credentials:'omit',cache:'no-store',headers:{'X-Jarvis-Nonce':NONCE,...(body===undefined?{}:{'Content-Type':'application/json'})},body:body===undefined?undefined:JSON.stringify(body),signal:AbortSignal.timeout(15000)});const value=await response.json();if(!response.ok){const error=new Error(value.user_message||'工具需求请求未确认。');error.status=response.status;throw error;}return value;}
const prefix=cid=>'/api/project-tools/'+cid+'/plans';
function context(){const c=current();if(!c||c.temporary||!Workspace.currentProject())throw new Error('请先选择普通项目会话；工具需求不会跨项目查找。');return c.id;}
function receipt(plan){for(const node of document.querySelectorAll('#messages>[data-growth-ref]'))if(node.dataset.growthRef===plan.id){const job=plan.invocation;node.querySelector('.bubble').textContent=job?.status==='SUCCEEDED'?'工具执行完成 · '+(job.result.result_verified?'结果与独立预期一致':'本次结果尚无独立预期核验')+'\n'+job.result.text.slice(0,4000)+(job.result.text.length>4000?'\n（完整结果在工具需求面板中）':''):job?'工具任务状态：'+job.status+'。实际结果与失败记录可在面板中查看。':plan.coding?'已关联编码改进单；候选验收、发布与工具可用是不同阶段。':'工具需求已保存：'+labels[plan.proposal.decision]+'。'+plan.proposal.reason;Workspace.remember();}}
async function create(message,automatic=false){
 if(creating)return;const cid=context();let old=pending.get(cid);if(old&&old.message!==message)throw new Error('上个需求回执未确认，请先核对原请求。');
 creating=true;busy=true;setControls();
 try{
  if(!old){const user=addMessage('user',message);user.dataset.personalControl='true';const node=addMessage('assistant','正在查找本项目的已验证工具；尚未执行。');node.dataset.personalControl='true';node.dataset.growthRequestId=crypto.randomUUID().replaceAll('-','');old={message,node,key:node.dataset.growthRequestId};pending.set(cid,old);}
  await Workspace.flushConversation();const plan=await api(prefix(cid),{request_id:old.key,message});pending.delete(cid);old.node.dataset.growthRef=plan.id;
  if(current()?.id!==cid)return;
  if($('message').value.trim()===message)$('message').value='';receipt(plan);window.ConversationGrowth?.sessionChanged();
  if(automatic&&plan.proposal.decision==='ready'){
   try{await api(prefix(cid)+'/'+plan.id+'/start',{});}catch(e){notify(e.message+'；可打开原需求核对，不会新建第二次调用。');}
  }
  await open(plan.id);return plan;
 }catch(e){if(e.status&&e.status<500)pending.delete(cid);if(old)old.node.querySelector('.bubble').textContent=e.message+'；请在工具需求面板核对原请求，没有自动重发。';Workspace.remember();window.ConversationGrowth?.sessionChanged();throw e;}
 finally{creating=false;busy=false;setControls();}
}
async function handleSubmit(){
 const text=$('message').value.trim();if($('composer-mode').value!=='chat'||!command(text))return false;
 try{if(Attachments.hasDraft()||$('file-mode').checked)throw new Error('工具需求首期只读取本次文本 JSON；请移除附件并关闭文件输出。草稿保留。');await create(text,true);}catch(e){notify(e.message);}return true;
}
async function open(selected=null){
 let cid;try{cid=context();}catch(e){notify(e.message);return;}
 const pane=el('section');pane.className='project-tools-view';pane.id='tool-intents-view';const header=el('header');header.append(el('h2','工具需求'));button(header,'×',()=>ProjectExplorer.closeView('tool-intents')).setAttribute('aria-label','关闭工具需求');
 const label=el('label','描述工具需求'),prompt=el('textarea');prompt.placeholder='请用求和工具处理 [10,20]，或 /工具 把列表导出为 CSV';label.append(prompt);const actions=el('div'),status=el('p'),list=el('div');status.setAttribute('role','status');pane.append(header,el('p','明确名称和 JSON 可直接调用；用途候选需要选择。分析需求不调用模型。'),label,actions,status,list);
 const valid=()=>pane.isConnected&&current()?.id===cid;let timer=null,acting=false;const drafts=new Map();
 function controls(value){for(const b of pane.querySelectorAll('button'))if(b.getAttribute('aria-label')!=='关闭工具需求')b.disabled=value;}
 async function action(work){if(acting)return;acting=true;controls(true);try{await work();await load();}catch(e){status.textContent=e.message;}finally{acting=false;controls(false);}}
 button(actions,'分析需求',()=>action(async()=>{if(!prompt.value.trim())throw new Error('请描述需求。');await create(prompt.value.trim());}));
 button(actions,'刷新与核对请求',()=>action(async()=>{const old=pending.get(cid);if(old){const p=await api(prefix(cid)+'/requests/'+old.key);old.node.dataset.growthRef=p.id;pending.delete(cid);receipt(p);window.ConversationGrowth?.sessionChanged();}}));
 function field(parent,title,value=''){const l=el('label',title),n=el('textarea');n.value=value;l.append(n);parent.append(l);return n;}
 function render(plan){
  const card=el('article');card.dataset.toolPlan=plan.id;const job=plan.invocation,decision=plan.proposal;
  card.append(el('h3',plan.message),el('p',plan.status==='CANCELLED'?'需求已取消':labels[decision.decision]),el('p',decision.reason));
  if(job){card.append(el('p','实际任务：'+job.status+(job.error?' · '+job.error:'')));if(job.result?.text!==undefined)card.append(el('p',job.result.result_verified?'结果与独立预期一致':'执行完成；本次结果尚无独立预期核验'),el('pre',job.result.text));if(job.rollback)card.append(el('pre',JSON.stringify(job.rollback,null,2)));}
  else if(plan.coding){card.append(el('p','编码改进单：'+plan.coding.status+'；通过候选验收后仍需发布为工具。'));button(card,'查看编码改进进度',()=>{const node=[...document.querySelectorAll('[data-growth-ref]')].find(n=>n.dataset.growthRef===plan.coding.id);if(node)node.querySelector('.growth-link')?.click();else{if($('message').value.trim()){notify('请先保留输入框草稿，再打开成长进度。');return;}$('message').value='/成长进度';ConversationGrowth.handleSubmit();}});}
  else if(plan.status==='PROPOSED'){
   if(['ready','choose','input_needed'].includes(decision.decision)){
    const l=el('label','候选工具'),select=el('select');select.setAttribute('aria-label','候选工具');const blank=el('option','请选择工具');blank.value='';select.append(blank);
    for(const row of decision.candidates){const option=el('option',(row.metadata?.name||row.tool_id)+' · '+row.tool_id);option.value=row.tool_id;option.disabled=!row.active||!!row.issue;select.append(option);card.append(el('p',(row.metadata?.name||row.tool_id)+'：'+(row.metadata?.when_to_use||'待核对')+'；不适用：'+(row.metadata?.when_not_to_use||'待核对')));}
    const draft=drafts.get(plan.id);if(draft)select.value=draft.tool;else if(decision.candidates.length===1)select.value=decision.candidates[0].tool_id;l.append(select);card.append(l);
    const input=field(card,'本次 JSON 输入',draft?.input??('input' in plan.parsed?JSON.stringify(plan.parsed.input,null,2):'')),expected=field(card,'独立预期（可选）',draft?.expected??'');const verify=el('input');verify.type='checkbox';verify.checked=draft?.verify??false;const remember=()=>drafts.set(plan.id,{tool:select.value,input:input.value,expected:expected.value,verify:verify.checked});input.oninput=expected.oninput=select.onchange=verify.onchange=remember;verify.style.cssText='width:auto;display:inline-block;margin-right:8px';const v=el('label','核对独立预期');v.prepend(verify);card.append(v);
    button(card,'使用所选工具',()=>action(async()=>{if(!select.value)throw new Error('请选择本次工具。');let value;try{value=JSON.parse(input.value);}catch{throw new Error('请提供有效的 JSON 输入；没有使用示例代替。');}await api(prefix(cid)+'/'+plan.id+'/start',{tool_id:select.value,input:value,...(verify.checked?{expected:expected.value}:{})});}));
   }else if(decision.decision==='gap'){button(card,'按限定契约持续成长',()=>window.GrowthCyclesUI?.open(plan.message));button(card,'验收草案与审阅',()=>ToolContracts.open(plan));button(card,'补齐验收并建立编码改进单',()=>{if($('message').value.trim()&&$('message').value.trim()!==plan.message){notify('输入框已有草稿，请先保留后再补齐编码需求。');return;}if(SkillWorkbench.prepareImprovement(plan.message)){window.ToolContracts?.clearOrigin();origin={cid,id:plan.id,message:plan.message};}});}
   else if(decision.decision==='unavailable')button(card,'打开工具库核对',()=>ProjectTools.open());
  }
  if((!job&&!plan.coding&&plan.status==='PROPOSED')||active(job?.status))button(card,'取消此需求或调用',()=>action(()=>api(prefix(cid)+'/'+plan.id+'/cancel',{})));
  if(!active(job?.status))button(card,'按当前目录重新分析',()=>action(()=>create(plan.message,false)));
  receipt(plan);return card;
 }
 async function load(){if(!valid()||document.hidden)return;clearTimeout(timer);try{const plans=await api(prefix(cid));if(!valid())return;if(selected&&!plans.some(p=>p.id===selected))plans.unshift(await api(prefix(cid)+'/'+selected));list.replaceChildren(...plans.map(render));if(!plans.length)list.append(el('p','尚无工具需求。可在上方描述，或在聊天中使用 /工具。'));if(plans.some(p=>active(p.invocation?.status))&&pane.offsetParent!==null)timer=setTimeout(load,1000);}catch(e){status.textContent=e.message;}}
 if(!ProjectExplorer.openView({id:'tool-intents',title:'工具需求',element:pane}))return;await load();
}
window.ToolIntents={open,command,handleSubmit,clearOrigin(){origin=null;},codingOrigin(prompt){return origin?.cid===current()?.id&&origin.message===prompt?origin:null;}};
})();
