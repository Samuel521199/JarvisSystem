/* Drafting, review and code execution have separate receipts and authority. */
(()=>{'use strict';
const current=()=>window.Workspace?.currentConversation(),pending=new Map();let origin=null;
const active=s=>['QUEUED','RUNNING','OBSERVING'].includes(s),states={QUEUED:'等待生成',RUNNING:'正在拟定草案',SUCCEEDED:'草案待审阅',FAILED:'生成失败',UNKNOWN:'响应未确认',INTERRUPTED:'生成中断',CANCELLED:'已取消'};
const base=(cid,pid)=>'/api/project-tools/'+cid+'/plans/'+pid+'/contracts';
function el(tag,text){const n=document.createElement(tag);if(text!==undefined)n.textContent=text;return n;}
function button(p,text,fn){const n=el('button',text);n.type='button';n.onclick=fn;p.append(n);return n;}
async function api(path,payload){const r=await fetch(path,{method:payload===undefined?'GET':'POST',credentials:'omit',cache:'no-store',headers:{'X-Jarvis-Nonce':NONCE,...(payload===undefined?{}:{'Content-Type':'application/json'})},body:payload===undefined?undefined:JSON.stringify(payload),signal:AbortSignal.timeout(15000)});const value=await r.json();if(!r.ok){const e=new Error(value.user_message||'验收草案请求未确认。');e.status=r.status;throw e;}return value;}
async function open(plan){
 const cid=current()?.id;if(!cid||current().temporary||!Workspace.currentProject()){notify('请先打开已保存的项目会话。');return;}
 const pane=el('section');pane.id='tool-contracts-view';pane.className='project-tools-view';const header=el('header');header.append(el('h2','验收草案与审阅'));const close=button(header,'×',()=>ProjectExplorer.closeView('tool-contracts'));close.setAttribute('aria-label','关闭验收草案');close.title='关闭验收草案';
 const state=el('p');state.setAttribute('role','status');const actions=el('div'),list=el('div');pane.append(header,el('p',plan.message),el('p','先把“做成什么、怎样算对”说清楚。模型建议需要核对；独立留出案例由你补充，随后使用原编程通道。'),actions,state,list);
 const valid=()=>pane.isConnected&&current()?.id===cid,drafts=new Map();let acting=false,timer=null;
 function controls(value){for(const b of pane.querySelectorAll('button'))if(b!==close)b.disabled=value;}
 async function action(work){if(acting)return;acting=true;controls(true);try{await work();await load();}catch(e){state.textContent=e.message;}finally{acting=false;controls(false);}}
 button(actions,'生成验收草案（调用进化模型）',()=>action(async()=>{let key=pending.get(plan.id);if(!key){key=crypto.randomUUID().replaceAll('-','');pending.set(plan.id,key);}try{await api(base(cid,plan.id),{request_id:key});pending.delete(plan.id);}catch(e){if(e.status&&e.status<500)pending.delete(plan.id);throw e;}}));
 button(actions,'刷新与核对草案',()=>action(async()=>{}));
 button(actions,'模型与备选设置',()=>window.open('/settings#growth','_blank','noopener'));
 function field(p,title,value){const l=el('label',title),t=el('textarea');t.value=value;l.append(t);p.append(l);return t;}
 function render(job){
  const card=el('article');card.dataset.contractId=job.id;card.append(el('h3',job.review?'审阅已接受':states[job.status]||job.status));
  const selections=job.attempts.map(a=>a.selection.route+(a.selection.reasoning?' · '+a.selection.reasoning:''));card.append(el('small',job.id+' · '+(selections.join(' → ')||job.policy.models.evolve.primary.route)));
  if(job.error)card.append(el('p','诊断：'+job.error+'。未自动重发或开始编码。'));
  if(active(job.status))button(card,'取消本次草案生成',()=>action(()=>api(base(cid,plan.id)+'/'+job.id+'/cancel',{})));
  if(!job.result?.draft)return card;
  card.append(el('p','模型建议 · 尚未由系统验证预期是否正确。审阅后仍需独立运行候选。'));
  const saved=drafts.get(job.id),review=job.review?.payload,source=saved?.contract||review?.contract||job.result.draft;
  const input=field(card,'输入格式',source.input_contract),output=field(card,'输出规则',source.output_contract),exclusions=field(card,'不包含的能力（每行一项）',source.non_goals.join('\n')),examples=field(card,'公开案例 JSON',saved?.examples??JSON.stringify(source.public_cases,null,2));
  const answers=job.result.draft.questions.map((q,i)=>field(card,'待澄清：'+q,saved?.answers[i]??review?.answers[i]??''));
  const heldout=field(card,'独立留出案例 JSON',saved?.heldout??(review?JSON.stringify(review.coding.heldout_cases,null,2):'')),note=field(card,'独立预期依据',saved?.note??review?.oracle_note??'');
  heldout.placeholder='填写 2—24 条新输入与预期；不发送给草案模型或编码模型。';note.placeholder='例如：依据已确认公式手算，或从独立参考实现取得；不要用候选自身输出充当预期。';
  const label=el('label','我已核对需求、公开案例和留出预期的依据'),checked=el('input');checked.type='checkbox';checked.checked=saved?.checked??Boolean(review);checked.style.cssText='width:auto;display:inline-block;margin-right:8px';label.prepend(checked);card.append(label);
  const remember=()=>drafts.set(job.id,{contract:{input_contract:input.value,output_contract:output.value,non_goals:exclusions.value.split('\n').map(s=>s.trim()).filter(Boolean),public_cases:source.public_cases,questions:job.result.draft.questions},examples:examples.value,answers:answers.map(a=>a.value),heldout:heldout.value,note:note.value,checked:checked.checked});
  for(const n of [input,output,exclusions,examples,...answers,heldout,note])n.oninput=remember;checked.onchange=remember;
  if(review){for(const n of card.querySelectorAll('textarea,input'))n.disabled=true;card.append(el('p','审阅已冻结。可按原内容核对或重试交接；修改目标需要重新分析需求。'));button(card,'核对或继续原编码交接',()=>action(async()=>{await api(base(cid,plan.id)+'/'+job.id+'/review',review);await ToolIntents.open(plan.id);}));return card;}
  button(card,review?'核对或继续原编码交接':'使用已核对草案准备编码',()=>{
   try{
    if(!checked.checked)throw new Error('请先核对需求与独立预期，再勾选审阅。');
    if($('message').value.trim()&&$('message').value.trim()!==plan.message)throw new Error('输入框已有草稿，请先保留，再准备编码。');
    remember();const d=drafts.get(job.id),contract={...d.contract,public_cases:JSON.parse(d.examples)},privateCases=JSON.parse(d.heldout);
    if(d.answers.some(a=>!a.trim())||d.note.trim().length<5)throw new Error('请回答待澄清问题，并填写独立预期依据。');
    if(SkillWorkbench.prepareImprovement(plan.message)){
     ToolIntents.clearOrigin();origin={cid,planId:plan.id,id:job.id,message:plan.message,review:{draft_digest:job.result.digest,contract,answers:d.answers,oracle_note:d.note,reviewed:true}};
     $('skill-coding-cases').value=JSON.stringify(contract.public_cases,null,2);$('skill-coding-heldout').value=JSON.stringify(privateCases,null,2);$('skill-coding-recipe').value=review?.coding.build_recipe||'python-zipapp-v1';
     if(review){$('skill-paths').value=review.coding.paths.join('\n');$('skill-coding-provider').value=review.coding.coding_provider;}
     SkillWorkbench.controls();state.textContent='已准备编程表单。核对源码路径、模型与构建方式，发送后保存审阅并建立待开始编码单。';
    }
   }catch(e){state.textContent=e instanceof SyntaxError?'请填写有效的公开与独立留出案例 JSON。':e.message;}
  });return card;
 }
 async function load(){if(!valid()||document.hidden)return;clearTimeout(timer);try{const jobs=await api(base(cid,plan.id));if(!valid())return;const key=pending.get(plan.id);if(key&&jobs.some(j=>j.request.request_id==='tool-contract-'+key))pending.delete(plan.id);list.replaceChildren(...jobs.map(render));if(!jobs.length)list.append(el('p','还没有验收草案。生成前仅发送原需求，不读取项目源码、聊天历史或私人记忆。'));if(jobs.some(j=>active(j.status))&&pane.offsetParent!==null)timer=setTimeout(load,1000);}catch(e){state.textContent=e.message;}}
 if(!ProjectExplorer.openView({id:'tool-contracts',title:'验收草案',element:pane}))return;await load();
}
window.ToolContracts={open,clearOrigin(){origin=null;},codingOrigin(prompt){return origin?.cid===current()?.id&&origin.message===prompt?origin:null;}};
})();
