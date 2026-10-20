/* Receipt-driven finite growth; no generated code is executed by the page. */
(()=>{
'use strict';
const nonce=document.querySelector('meta[name="jarvis-nonce"]')?.content||NONCE;
const labels={CODING:'生成与独立验收',BASELINE:'正常模型对照',STAGING:'准备灰度',CANARY:'新输入灰度',OBSERVING:'启用后观察',STOPPING:'停止与恢复',COMPLETE:'本轮达标',PAUSED:'暂停待分析',CANCELLED:'已取消',INTERRUPTED:'中断待分析'};
const reasons={owner_cancelled:'你已停止本轮成长',restart_requires_reanalysis:'服务重启，需要核对原回执并重新分析',growth_authorization_changed:'授权已变更、过期或达到周期预算',growth_validator_changed:'验收器已更新，需要重新冻结条件',working_baseline_not_verified:'正常模型对照未通过独立验算，不能据此宣称改进有效',memory_evidence_missing_or_over_budget:'内存证据缺失或超过预定预算',benefit_not_established:'收益或资源条件未满足，本轮活动能力已停用并保留恢复包',growth_coding_failed:'候选编码未通过独立验收',growth_coding_unknown:'编码结果未知，未重新派发',growth_child_unknown:'子任务结果未知，未重发',growth_child_failed:'子任务失败，请查看原始回执'};
const terminal=new Set(['COMPLETE','PAUSED','CANCELLED','INTERRUPTED']);
const pending=new Map();
function el(t,text){const x=document.createElement(t);if(text!==undefined)x.textContent=text;return x;}
async function api(path,value){const r=await fetch(path,{method:value===undefined?'GET':'POST',credentials:'omit',cache:'no-store',headers:{'X-Jarvis-Nonce':nonce,...(value===undefined?{}:{'Content-Type':'application/json'})},body:value===undefined?undefined:JSON.stringify(value),signal:AbortSignal.timeout(15000)});const d=await r.json();if(!r.ok){const e=Error(d.user_message||'请求未确认，请刷新原记录');e.status=r.status;throw e;}return d;}
async function open(goal=''){
 const context=window.Workspace?.currentConversation(),cid=context?.id;
 if(!cid||context.temporary||!window.SkillWorkbench?.context().project_id){notify('请先选择已保存的项目会话。');return;}
 const base='/api/project-tools/'+cid+'/growth',pane=el('section');pane.className='project-tools-view';pane.id='growth-cycles-view';
 const header=el('header'),close=el('button','×');close.title='关闭成长进度';close.setAttribute('aria-label','关闭成长进度');close.onclick=()=>window.ProjectExplorer.closeView('growth-cycles');
 header.append(el('h2','可持续成长'),close);pane.append(header,el('p','为反复需要的能力建立一次有界成长：独立验收 → 灰度 → 启用 → 收益观察。不满足条件会暂停；新任务仍需你明确提出。'));
 const state=el('p');state.className='project-tools-status';state.setAttribute('role','status');
 const refresh=el('button','刷新原记录'),policyBox=el('details'),policyForm=el('div'),request=el('article'),cards=el('div');
 policyBox.append(el('summary','此项目的成长策略与预算'),policyForm);
 pane.append(state,refresh,policyBox,request,cards);
 let data,dirty=false,editing=false;
 const valid=()=>pane.isConnected&&window.Workspace?.currentConversation()?.id===cid;
 function field(parent,name,value,type='text'){const l=el('label',name),i=el(type==='textarea'?'textarea':'input');if(type!=='textarea')i.type=type;if(type==='checkbox'){i.checked=Boolean(value);i.style.cssText='display:inline-block;width:auto;margin:0 8px 0 0';l.prepend(i);}else{i.value=value;l.append(i);}parent.append(l);return i;}
 function renderPolicy(){
  if(dirty)return;policyForm.replaceChildren();const p=data.policy;
  const enabled=field(policyForm,'允许按此策略自动推进',p.enabled,'checkbox');
  const modelLabel=el('label','编码与对照模型'),model=el('select');modelLabel.append(model);policyForm.append(modelLabel);
  for(const m of modelCatalog)model.add(new Option((m.label||m.model)+' · '+m.provider,m.provider+'::'+m.model));
  const selectedModel=p.model||'vertex::gemini-3.8-flash';
  if(![...model.options].some(o=>o.value===selectedModel))model.add(new Option(selectedModel+'（请核对可用性）',selectedModel));
  model.value=selectedModel;
  const days=field(policyForm,'授权有效天数（1–31）',Math.max(1,Math.min(31,Math.ceil((p.expires_at-Date.now()/1000)/86400))),'number');
  const count=field(policyForm,'本次修订最多启动几轮（1–10）',p.maximum_cycles,'number');
  const window=field(policyForm,'灰度及启用后的各自观察秒数（30–3600）',p.window_seconds,'number');
  const maxTime=field(policyForm,'一次工具调用最长秒数（1–30）',p.maximum_seconds,'number');
  const domainChecks=data.domains.map(d=>({id:d.id,input:field(policyForm,d.name,p.domains.includes(d.id),'checkbox')}));
  const note=field(policyForm,'授权说明','仅处理我明确选择的契约；不满足质量和预算时停止。','textarea');
  const reviewed=field(policyForm,'已核对范围及预算：每轮最多 8 次模型调用、6 份独立对照样本',false,'checkbox');
  policyForm.append(el('small','自动执行不等于无限授权。生成物不能改写策略和验证器；修改或关闭策略会停止在途自动准入。已有达标工具可在工具库停用。'));
  const save=el('button','保存成长策略');
  policyForm.oninput=()=>dirty=true;
  save.onclick=async()=>{if(!reviewed.checked){state.textContent='请先核对范围和调用预算。';return;}save.disabled=true;
   try{const fields=['revision','maximum_cycle_seconds','maximum_model_calls','minimum_calls_saved','maximum_memory_bytes'];const value=Object.fromEntries(fields.map(k=>[k,p[k]]));
    await api(base+'/policy',{...value,enabled:enabled.checked,domains:domainChecks.filter(d=>d.input.checked).map(d=>d.id),model:model.value.trim(),expires_at:Date.now()/1000+Number(days.value)*86400,maximum_cycles:Number(count.value),window_seconds:Number(window.value),maximum_seconds:Number(maxTime.value),reviewed:true,review_note:note.value});
    dirty=false;policyBox.open=false;await load();state.textContent='策略已保存。';}catch(e){state.textContent=e.message;}finally{save.disabled=false;}};
  policyForm.append(save);
 }
 const demand=field(request,'你希望反复处理的需求',goal,'textarea'),domain=el('select'),contract=el('p');
 domain.setAttribute('aria-label','明确选择本轮验收契约');domain.append(new Option('先选择契约，未覆盖的需求继续人工审阅',''));
 const start=el('button','按策略开始本轮成长');request.append(domain,contract,start);
 domain.onchange=()=>contract.textContent=data.domains.find(d=>d.id===domain.value)?.contract||'';
 start.onclick=async()=>{if(editing)return;if(!domain.value){state.textContent='请先选择明确契约；系统不会替你猜测业务标准。';return;}editing=true;start.disabled=true;
  const old=pending.get(cid),payload={request_id:old?.request_id||crypto.randomUUID().replaceAll('-',''),goal:demand.value,domain:domain.value,policy_revision:data.policy.revision};
  if(old&&JSON.stringify(old)!==JSON.stringify(payload)){state.textContent='上次请求尚未确认，请先刷新原记录。';editing=false;start.disabled=false;return;}
  pending.set(cid,payload);
  try{await api(base,payload);pending.delete(cid);state.textContent='已冻结需求和验证器，可继续聊天或关闭此面板。';await load();}catch(e){if(e.status&&e.status<500)pending.delete(cid);state.textContent=e.message+(pending.has(cid)?'；请刷新核对，未自动重发。':'');}finally{editing=false;start.disabled=false;}};
 function render(){
  renderPolicy();if(domain.options.length===1)for(const d of data.domains)domain.append(new Option(d.name,d.id));
  cards.replaceChildren();for(const c of data.cycles){
   const a=el('article');a.append(el('h3',c.domain.name+' · '+(labels[c.status]||c.status)),el('p',c.submission.goal),
    el('small','策略 #'+c.policy.revision+' · 对照 '+c.baseline.length+'/6 · 灰度 '+c.trials.length+'/3 · 启用后 '+c.uses.length+'/3'));
   if(c.stop_reason)a.append(el('p','停止原因：'+(reasons[c.stop_reason]||c.stop_reason)+'。原回执已保留；重新分析需要新的明确请求。'));
   if(c.assessment){const q=c.assessment;a.append(el('p','已核验 '+q.samples+' 次 · 相对重复模型调用减少 '+q.calls_saved+' 次'),el('p','实验实际模型调用 '+q.experiment_model_calls+' 次 · token 差额 '+(q.token_delta_baseline_minus_coding??'未知')+' · 费用差额 '+(q.amount_delta_baseline_minus_coding??'未知')),el('small',q.limits));}
   if(!terminal.has(c.status)){const cancel=el('button','停止此轮成长');cancel.onclick=async()=>{cancel.disabled=true;try{await api(base+'/'+c.id+'/cancel',{});await load();}catch(e){state.textContent=e.message;}finally{cancel.disabled=false;}};a.append(cancel);}
   const detail=el('details');detail.append(el('summary','阶段与原始回执'),el('pre',JSON.stringify({id:c.id,events:c.events,assessment:c.assessment||null},null,2)));a.append(detail);cards.append(a);
  }
 }
 async function load(){if(!valid())return;try{data=await api(base);if(!valid())return;const old=pending.get(cid);if(old&&data.cycles.some(c=>c.id===old.request_id)){pending.delete(cid);state.textContent='已找到原请求，没有重复启动。';}render();}catch(e){state.textContent=e.message;}}
 refresh.onclick=load;
 if(!window.ProjectExplorer?.openView({id:'growth-cycles',title:'可持续成长',element:pane}))return;
 await load();
 async function poll(){if(!valid())return;if(!document.hidden&&pane.offsetParent!==null&&(pending.has(cid)||data?.cycles.some(c=>!terminal.has(c.status))))await load();if(valid())setTimeout(poll,3000);}
 setTimeout(poll,3000);
}
window.GrowthCyclesUI={open};
})();
