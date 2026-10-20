/* K5 reviewed module selection. Idle UI never requests a model. */
(()=>{
'use strict';
const parent=document.getElementById('evolution-pane-evolve');if(!parent)return;
const box=document.createElement('details');box.id='ranking-module-panel';
box.innerHTML='<summary>自身模块改造 · 检索排序</summary><p>生成受限排序代码，隔离检查后查看独立对照，再选择试用。原文、资料权限和个人记忆保持由宿主管理。每次生成最多请求模型一次；未知结果不自动重发。</p><div class="growth-model-grid"><label>本次编码模型<select id="ranking-model"></select></label><label>审阅依据<textarea id="ranking-review" rows="2" placeholder="核对质量、耗时、已知失败及适用范围"></textarea></label></div><div class="growth-actions"><button type="button" class="primary" id="ranking-generate">生成候选并独立评估</button><button type="button" class="secondary" id="ranking-refresh">刷新原记录</button><button type="button" class="secondary" id="ranking-confirm">保留试用版本</button><button type="button" class="secondary" id="ranking-rollback">回退上一版本</button><button type="button" class="secondary" id="ranking-baseline">恢复内置排序</button><button type="button" class="secondary" id="ranking-cancel">停止生成</button></div><p id="ranking-state" role="status"></p><p id="ranking-message" role="status"></p><div id="ranking-versions"></div><details><summary>最近生成回执</summary><pre id="ranking-jobs" tabindex="0"></pre></details>';
parent.append(box);
const $=id=>document.getElementById('ranking-'+id);
const nonce=document.querySelector('meta[name="jarvis-nonce"]').content;
let state=null,models=null,busy=false,timer=null,pending=null,selectionPending=null;
const active=j=>['QUEUED','RUNNING','OBSERVING'].includes(j.status);
const events={initial:'尚未切换',reviewed_trial:'已审阅，开始试用',reviewed_confirmation:'已审阅保留',reviewed_rollback:'已回退上一版本',owner_baseline:'已恢复内置排序',unconfirmed_trial_restart_rollback:'未确认试用，重启后已回退',startup_incompatible_rollback:'启动核对不兼容，已回退',invalid_or_failed_module_rollback:'模块核对或执行失败，已回退',trial_latency_rollback:'试用耗时超限，已回退'};
function el(tag,text){const n=document.createElement(tag);n.textContent=text;return n;}
async function api(path,payload){
 const response=await fetch(path,{method:payload?'POST':'GET',headers:{'X-Jarvis-Nonce':nonce,'Content-Type':'application/json'},body:payload?JSON.stringify(payload):undefined,signal:AbortSignal.timeout(12000)});
 const value=await response.json();if(!response.ok){const e=new Error(value.user_message||value.message||'请求未完成');e.status=response.status;throw e;}return value;
}
function controls(){
 const run=state?.jobs.some(active),sel=state?.selection;
 $('generate').disabled=busy||!!run||!!state?.busy||!state||!!pending;
 $('confirm').disabled=busy||!sel?.trial||sel.samples.length<3;
 $('rollback').disabled=busy||!sel?.active;
 $('baseline').disabled=busy||!sel?.active;
 $('cancel').disabled=busy||!run;
 for(const n of $('versions').querySelectorAll('button'))n.disabled=busy||n.dataset.eligible!=='true'||!!sel?.trial;
}
function render(){
 const s=state.selection;
 $('state').textContent='当前：'+(s.active?s.active.slice(0,12):'内置 lexical-v1')+' · '+(s.trial?'试用中（未确认时重启回退）':'稳定')+' · 已观察 '+s.samples.length+' 个不同查询 · '+(events[s.last_event]||s.last_event);
 $('versions').replaceChildren();
 for(const v of state.versions){
  const card=el('article','');card.className='ranking-version';
  card.append(el('h4',v.id.slice(0,12)+' · '+(v.evaluation.passed?'通过限定准入':'未通过，继续保留原模块')));
  card.append(el('p','独立检索 Top-1：'+v.evaluation.baseline+' → '+v.evaluation.candidate+' / '+v.evaluation.total+'；2048 项排序最长 '+v.evaluation.timing.candidate.maximum_ms+' ms。'));
  card.append(el('p','这是固定词法来源选择评测，不代表回答质量或语义理解已通过。'));
  const b=el('button','审阅后试用');b.type='button';b.className='secondary';b.dataset.eligible=String(v.evaluation.passed&&v.binding===state.binding&&s.active!==v.id);b.onclick=()=>change('trial',v.id);card.append(b);
  const details=el('details','');details.append(el('summary','源码、对照与模型用量'),el('pre',JSON.stringify(v,null,2)));card.append(details);$('versions').append(card);
 }
 $('jobs').textContent=JSON.stringify(state.jobs,null,2);controls();
}
async function load(){
 if(busy)return;busy=true;controls();clearTimeout(timer);
 try{
  state=await api('/api/evolution/ranking');
  if(!models){models=(await api('/api/models')).models||[];$('model').replaceChildren();for(const m of models){const o=el('option',m.label+' · '+m.provider);o.value=m.provider+'::'+m.model;$('model').append(o);}$('model').value=state.default_model;if(!$('model').value&&$('model').options.length)$('model').selectedIndex=0;}
  if(pending){const found=state.jobs.find(j=>j.request.request_id===pending.request_id);if(found){pending=null;$('message').textContent='已找到原请求；没有再次请求模型。';}else{$('message').textContent='未查到回执。保留原请求编号，可点击“重查 / 重交原请求”核对。';}}
  selectionPending=null;render();
 }catch(e){$('message').textContent=e.message;}
 finally{busy=false;controls();if(box.open&&state?.jobs.some(active))timer=setTimeout(load,2000);$('retry').hidden=!pending;}
}
async function generate(retry=false){
 if(busy||(!retry&&pending))return;
 pending=pending||{request_id:crypto.randomUUID().replaceAll('-',''),model:$('model').value};
 busy=true;controls();$('message').textContent='正在受理候选生成…';
 try{await api('/api/evolution/ranking/generate',pending);pending=null;}
 catch(e){if(e.status&&e.status<500)pending=null;$('message').textContent=e.message+'；响应中断时先刷新核对原请求。';}
 finally{busy=false;await load();}
}
async function change(action,version){
 if(busy||!state)return;
 if($('review').value.trim().length<8){$('message').textContent='请填写至少 8 字的审阅依据。';return;}
 const payload={action,generation:state.selection.generation,version,review:$('review').value.trim()};
 // Never silently substitute a new action when an earlier result is unknown.
 if(selectionPending&&JSON.stringify(selectionPending)!==JSON.stringify(payload)){$('message').textContent='上次切换结果待核对，请先刷新原记录。';return;}
 selectionPending=payload;busy=true;controls();
 try{await api('/api/evolution/ranking/select',payload);selectionPending=null;$('message').textContent='版本选择已记录。';}
 catch(e){if(e.status&&e.status<500)selectionPending=null;$('message').textContent=e.message+'；先刷新核对当前版本。';}
 finally{busy=false;await load();if(selectionPending&&JSON.stringify(state?.selection.last_request)===JSON.stringify(selectionPending))selectionPending=null;}
}
const retry=el('button','重查 / 重交原请求');retry.id='ranking-retry';retry.type='button';retry.hidden=true;retry.onclick=()=>generate(true);$('message').after(retry);
$('generate').onclick=()=>generate();$('refresh').onclick=load;
$('confirm').onclick=()=>change('confirm',state.selection.active);
$('rollback').onclick=()=>change('rollback',state.selection.active);
$('baseline').onclick=()=>change('baseline',state.selection.active);
$('cancel').onclick=async()=>{const j=state?.jobs.find(active);if(!j)return;try{await api('/api/evolution/cancel',{job_id:j.id});await load();}catch(e){$('message').textContent=e.message;}};
box.addEventListener('toggle',()=>{clearTimeout(timer);if(box.open)load();});
})();
