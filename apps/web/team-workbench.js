/* Explicit two-role collaboration; no automatic submit, memory or tool grants. */
(()=>{
'use strict';
const $=id=>document.getElementById(id),box=document.createElement('details');
box.id='team-controls';box.className='team-controls';box.hidden=true;
const summary=document.createElement('summary');summary.textContent='协作分工与检查要求 · 可按需分配角色';box.append(summary);
const allocation=document.createElement('label'),maximum=document.createElement('select');
allocation.textContent='团队预算 ';maximum.id='team-maximum';maximum.setAttribute('aria-label','团队最大模型调用次数');
for(const [value,text] of [['2','固定 2 个角色'],['3','自动分工 · 最多 3 次调用'],['4','自动分工 · 最多 4 次调用']]){
 const option=document.createElement('option');option.value=value;option.textContent=text;maximum.append(option);
}allocation.append(maximum);box.append(allocation);
const grid=document.createElement('div');grid.className='team-role-grid';box.append(grid);
const selectors={};
for(const [role,label] of [['planner','方案 Agent'],['reviewer','审阅 Agent']]){
 const field=document.createElement('div'),name=document.createElement('label'),model=document.createElement('select'),level=document.createElement('select');
 name.textContent=label;name.htmlFor='team-'+role;model.id=name.htmlFor;level.id=model.id+'-reasoning';level.setAttribute('aria-label',label+'推理级别');
 field.append(name,model,level);grid.append(field);selectors[role]={model,level};model.onchange=()=>levels(role);
}
const label=document.createElement('label'),criteria=document.createElement('textarea'),hint=document.createElement('p');
label.htmlFor='team-criteria';label.textContent='检查要求（每行一条，最多 6 条）';criteria.id=label.htmlFor;criteria.rows=2;criteria.placeholder='例如：不新增常驻服务\n分阶段实施且可以撤回';
hint.textContent='根据检查要求与可用资源分配方案、专项分析和独立审阅角色；专项分析沿用方案模型。后台顺序执行，可继续聊天。同一父任务合计预算；未知结果不重试，不写入个人记忆。';
box.append(label,criteria,hint);$('conversation-task-note').after(box);
let signature='',conversationId=null;
function levels(role){
 const {model,level}=selectors[role],old=level.value,item=modelCatalog.find(m=>m.provider+'::'+m.model===model.value);
 level.replaceChildren();const defaults=document.createElement('option');defaults.value='';defaults.textContent='模型默认级别';level.append(defaults);
 for(const value of item?.reasoning_levels||[]){const option=document.createElement('option');option.value=value;option.textContent=levelNames[value]||value;level.append(option);}
 level.value=(item?.reasoning_levels||[]).includes(old)?old:'';
 level.disabled=!(item?.reasoning_levels?.length);
}
function controls(){
 const id=window.Workspace?.currentConversation()?.id;
 if(id&&id!==conversationId){conversationId=id;criteria.value='';box.open=false;}
 box.hidden=$('composer-mode').value!=='team';if(box.hidden)return;
 const key=JSON.stringify(modelCatalog.map(m=>[m.provider,m.model,m.label,m.reasoning_levels]));
 if(key!==signature){signature=key;
  for(const role of ['planner','reviewer']){
   const {model}=selectors[role],old=model.value;model.replaceChildren();
   for(const item of modelCatalog){const option=document.createElement('option');option.value=item.provider+'::'+item.model;option.textContent=(names[item.provider]||item.provider)+' · '+(item.label||item.model);model.append(option);}
   if([...model.options].some(o=>o.value===old))model.value=old;else if(chosenModel())model.value=chosenModel().provider+'::'+chosenModel().model;
   levels(role);
  }
 }
}
function payload(){
 controls();const requirements=criteria.value.split(/\r?\n/).map(s=>s.trim()).filter(Boolean);
 if(!requirements.length||requirements.length>6)throw new Error('请展开“协作分工与检查要求”，填写 1—6 条检查要求。');
 if(!selectors.planner.model.value||!selectors.reviewer.model.value)throw new Error('请选择两个角色的模型。');
 const value={mode:'team',criteria:requirements,auto_team:Number(maximum.value)>2,max_agents:Number(maximum.value)};
 for(const role of ['planner','reviewer']){value[role+'_model']=selectors[role].model.value;if(selectors[role].level.value)value[role+'_reasoning']=selectors[role].level.value;}
 return value;
}
function preview(report){
 $('team-result-dialog')?.remove();const dialog=document.createElement('dialog');dialog.id='team-result-dialog';dialog.className='team-result';
 const heading=document.createElement('h2'),close=document.createElement('button');heading.id='team-result-title';dialog.setAttribute('aria-labelledby',heading.id);heading.textContent='协作报告 · '+(report.decision==='needs_revision'?'需要修改':'待你审阅');close.textContent='关闭';close.onclick=()=>dialog.close();dialog.append(heading,close);
 const section=(title,text)=>{const h=document.createElement('h3'),body=document.createElement('p');h.textContent=title;body.textContent=text;dialog.append(h,body);};
 section('任务与边界',report.goal+'\n'+report.limits);
 section('候选方案',report.proposal.summary+'\n'+report.proposal.steps.map(s=>s.id+' · '+s.title+'\n'+s.detail).join('\n\n'));
 section('假设与风险',[...report.proposal.assumptions,...report.proposal.risks].join('\n')||'方案未列出；不代表不存在。');
 section('独立审阅意见',report.review.summary+'\n'+report.review.findings.map(f=>f.step_id+' · '+f.severity+' · '+f.issue).join('\n'));
 const labels={addressed:'审阅认为已覆盖',uncertain:'尚不确定',missing:'缺失'};
 section('逐项要求',report.review.criteria.map(c=>(report.criteria.find(r=>r.id===c.criterion_id)?.text||c.criterion_id)+'：'+labels[c.status]+'\n'+c.reason).join('\n\n'));
 section('调用与预算',report.roles.map(r=>r.role+' · '+r.model+' · '+r.state+' · 用量 '+JSON.stringify(r.receipt?.usage||'未返回')).join('\n')+'\n'+(report.allocation?.reason||'固定双角色')+'\n最多 '+report.budget.max_model_calls+' 次调用，每次最多 2,048 输出 tokens；不构成货币费用的精确上限。');
 for(const s of report.specialists||[])section('专项建议 · '+s.role,s.proposal.summary);
 section('程序已核验', '输出结构、引用编号、要求逐项覆盖及状态一致性。模型结论和事实正确性尚未验收。');
 dialog.addEventListener('close',()=>dialog.remove());document.body.append(dialog);dialog.showModal();
}
window.TeamWorkbench={controls,payload,preview};controls();
})();
