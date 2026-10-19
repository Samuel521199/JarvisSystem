/* Instance-scoped receipts and a bounded, page-only text outbox. */
(() => {
'use strict';
const intentNames={chat:'闲聊',question:'问答',emotion:'情感交流',action:'任务请求',control:'控制请求',memory:'记忆/偏好',other:'其他'};
const dispositionNames={requested:'当前请求',discussed:'讨论/引述/假设',negated:'明确否定',uncertain:'需要澄清'};
function intentSummary(result){
 const d=result.intent_decision;if(!d)return '';
 const labels=d.state==='recognized'?[...new Set(d.intents.map(i=>intentNames[i.kind]||'其他'))].join(' + '):'暂未识别';
 return '意图参考：'+labels+' · '+(result.work_admission?.status==='submitted'?'任务已受理':result.work_admission?.status==='controlled'?'任务控制已受理':'未自动派发');
}
function markIntent(article,result){
 const d=result.intent_decision;if(!d||article.querySelector('.dialogue-intent'))return;
 const details=document.createElement('details');details.className='message-meta dialogue-intent';
 const summary=document.createElement('summary');summary.textContent=intentSummary(result);details.append(summary);
 const submitted=['submitted','controlled'].includes(result.work_admission?.status);
 const note=document.createElement('p');note.textContent=result.work_admission?.reason||(d.state==='recognized'?'以下是本轮输入的识别参考，可同时包含多种需求。尚未提交任务或改变记忆、播放与系统状态。':d.state==='not_evaluated'?'此模型尚未验证意图协议，当前保留普通对话；明确任务入口仍可使用。':d.state==='skipped_budget'?'当前模型输入预算较小，保留普通回答并跳过意图识别；未自动派发。':'识别格式未确认。本轮没有根据候选执行操作，也没有额外重试模型。');details.append(note);
 const conversationId=window.Workspace?.currentConversation().id;
 for(const item of d.intents||[]){
  const p=document.createElement('p');p.textContent=(intentNames[item.kind]||'其他')+' · '+(dispositionNames[item.disposition]||'待核对')+'：“'+item.quote.slice(0,512)+'”'+(item.missing_fields.length?' · 缺少：'+item.missing_fields.join('、'):'');details.append(p);
  if(!submitted&&item.kind==='action'&&item.disposition==='requested'&&item.capability==='mcp.documentation'&&!item.missing_fields.length&&window.ConversationTasks?.prepareDocumentation){
   const button=document.createElement('button');button.type='button';button.textContent='准备文档查询草稿';button.title='检查连接与范围后填写输入框，由你核对并发送';
   button.onclick=async()=>{button.disabled=true;try{await ConversationTasks.prepareDocumentation(item.arguments,conversationId,item.quote);}catch{notify('未能准备文档查询草稿，请查看连接和当前会话。');}finally{button.disabled=false;}};details.append(button);
  }
 }
 article.append(details);
 if(submitted)window.ConversationTasks?.automaticReceipt(result.work_admission);
}
const pending=[], limit=4;
let paused=false, pumping=false;
const panel=document.createElement('section');panel.id='dialogue-pending';panel.className='dialogue-pending';panel.hidden=true;panel.setAttribute('aria-label','待发送消息');
$('composer').before(panel);
const stop=document.createElement('button');stop.id='dialogue-stop';stop.type='button';stop.className='dialogue-stop';stop.hidden=true;
stop.textContent='停止回复';stop.title='停止当前回复，不取消后台任务';stop.setAttribute('aria-label',stop.title);
$('send').before(stop);stop.onclick=()=>stopGeneration();
function controls(){stop.hidden=!activeRun;stop.disabled=!activeRun||activeRun.cancelled||activeRun.personal||activeRun.phase==='saving';}
function render(){
 panel.replaceChildren();panel.hidden=!pending.length;
 if(pending.length){
  const label=document.createElement('p');label.textContent=(paused?'待发已暂停':'等待当前回复结束')+' · '+pending.length+'/'+limit+' · 仅保留在本页，尚未发送';panel.append(label);
  if(paused){const resume=document.createElement('button');resume.type='button';resume.textContent='继续发送待发消息';resume.onclick=()=>{paused=false;render();pump();};panel.append(resume);}
  pending.forEach((row,i)=>{const item=document.createElement('div'),text=document.createElement('span'),remove=document.createElement('button');text.textContent=(i+1)+'. '+row.text.slice(0,140);text.title=row.text;remove.type='button';remove.textContent='移回输入框';remove.disabled=Boolean($('message').value.trim())||Attachments.hasDraft();remove.onclick=()=>{if($('message').value.trim()||Attachments.hasDraft())return;$('message').value=row.text;pending.splice(i,1);render();setControls();$('message').focus();};item.append(text,remove);panel.append(item);});
 }
 controls();window.Workspace?.controls();
}
function enqueue(){
 const text=$('message').value.trim();if(!text)return;
 if(Attachments.hasDraft()||$('file-mode').checked||localPersonalCommand()||localGrowthCommand()||/^\//u.test(text)||$('composer-mode').value!=='chat'){
  notify('待发区目前支持普通文字；附件、个人指令和文件生成请等当前回复结束。/任务、/进度、/取消仍可独立使用。');return;
 }
 if(pending.length>=limit||encoder.encode(text).length>16384){notify('待发区最多 4 条，每条不超过 16 KiB；草稿已保留。');return;}
 pending.push({text,conversation:Workspace.currentConversation().id});$('message').value='';render();setControls();
}
async function pump(){
 if(pumping||busy||paused||!pending.length||!coreReady||Workspace.isBusy())return;
 const row=pending[0];
 if(row.conversation!==Workspace.currentConversation().id||Attachments.hasDraft()||$('file-mode').checked){paused=true;render();return;}
 pumping=true;pending.shift();render();
 let started=false;try{await send({preventDefault(){}},row.text,()=>{started=true;});if(!started){pending.unshift(row);paused=true;}}finally{pumping=false;render();if(!busy&&!paused&&pending.length)queueMicrotask(pump);}
}
function complete(run){if(!pending.length)paused=false;else if(!run.succeeded&&!(run.cancelled&&run.receiptFinished))paused=true;render();queueMicrotask(pump);sessionChanged();}
function scope(run){return {instance_id:instanceId,conversation_id:Workspace.currentConversation().id,request_id:run.id};}
async function rpc(path,body,signal){
 const control=new AbortController(),abort=()=>control.abort();
 if(signal?.aborted)throw new DOMException('Aborted','AbortError');
 signal?.addEventListener('abort',abort,{once:true});const timer=setTimeout(abort,8000);
 try{const response=await fetch(path,{method:body?'POST':'GET',credentials:'omit',cache:'no-store',headers:{'Content-Type':'application/json','X-Jarvis-Nonce':NONCE},...(body?{body:JSON.stringify(body)}:{}),signal:control.signal});return {ok:response.ok,status:response.status,data:await response.json()};}
 finally{clearTimeout(timer);signal?.removeEventListener('abort',abort);}
}
function reply(response){return {ok:response.ok,json:async()=>response.data};}
function delay(signal){return new Promise((resolve,reject)=>{const abort=()=>{clearTimeout(timer);reject(new DOMException('Aborted','AbortError'));};const timer=setTimeout(()=>{signal.removeEventListener('abort',abort);resolve();},500);signal.addEventListener('abort',abort,{once:true});if(signal.aborted)abort();});}
async function request(run,body){
 run.dialogue=scope(run);let state=null,missing=0;
 try{const response=await rpc('/api/dialogue/turns',{...run.dialogue,chat:body},run.controller.signal);if(!response.ok)return reply(response);state=response.data;}
 catch(error){if(run.controller.signal.aborted)throw error;/* A lost POST response is queried, never replayed. */}
 const query=new URLSearchParams({conversation_id:run.dialogue.conversation_id,instance_id:run.dialogue.instance_id});
 for(;;){
  if(state?.finished){run.receiptFinished=true;return reply({ok:true,data:state.expired?{status:'UNKNOWN',user_message:state.user_message}:state.result});}
  await delay(run.controller.signal);
  try{
   const response=await rpc('/api/dialogue/turns/'+run.id+'?'+query,null,run.controller.signal);
   if(response.ok){state=response.data;missing=0;}
   else if(response.status===404&&++missing<20)continue;
   else return reply(response);
  }catch(error){if(run.controller.signal.aborted)throw error;}
 }
}
function cancel(run){return rpc('/api/dialogue/cancel',run.dialogue).then(response=>{if(!response.ok)throw new Error('cancel_unconfirmed');return response.data;});}
// Recovered answers are offered explicitly. They never replay a model, personal
// command, file save, task, or speech playback, and never enter history silently.
const recovery=document.createElement('section');recovery.id='dialogue-recovery';recovery.className='dialogue-pending';recovery.hidden=true;recovery.setAttribute('aria-label','回复恢复');panel.before(recovery);
let recoveryTimer=null,recoveryEpoch=0,recoveryRequest=null,recoveryKey='';const dismissed=new Set();try{for(const id of JSON.parse(sessionStorage.getItem('jarvis.recovery.dismissed')||'[]'))if(typeof id==='string')dismissed.add(id);}catch{}
function candidates(){
 const answered=new Set([...$('messages').querySelectorAll('.assistant[data-reply-ref],.stopped[data-reply-ref],.error[data-reply-ref]')].map(e=>e.dataset.replyRef));
 return [...$('messages').querySelectorAll('.user[data-reply-ref]')].filter(e=>!answered.has(e.dataset.replyRef)&&!dismissed.has(e.dataset.replyRef)).slice(-8);
}
function sessionChanged(){
 const scope=window.Workspace?.currentConversation(),rows=candidates();
 const key=(scope?.id||'')+':'+rows.map(e=>e.dataset.replyRef).join(',');
 if(key!==recoveryKey){recoveryKey=key;recoveryEpoch++;recoveryRequest?.abort();recovery.replaceChildren();recovery.hidden=true;}
 clearTimeout(recoveryTimer);
 if(!scope||scope.temporary||busy||Workspace.isBusy()||document.hidden||!rows.length)return;
 recoveryTimer=setTimeout(checkRecovery,350);
}
async function checkRecovery(){
 if(recoveryRequest||busy||Workspace.isBusy()||document.hidden)return;
 const scope=Workspace.currentConversation();if(scope.temporary)return;
 const epoch=recoveryEpoch,control=new AbortController();recoveryRequest=control;
 const rows=candidates();let running=false;
 recovery.replaceChildren();recovery.hidden=!rows.length;
 const heading=document.createElement('p');heading.textContent='回复恢复 · 只查询原请求，不重新执行';recovery.append(heading);
 try{
  for(const user of rows){
   const id=user.dataset.replyRef,item=document.createElement('div'),label=document.createElement('span');label.textContent='查询中…';item.append(label);recovery.append(item);
   let response;
   try{response=await rpc('/api/dialogue/recover/'+id+'?conversation_id='+scope.id,null,control.signal);}
   catch{response={ok:false,data:{user_message:'暂时无法查询，可稍后重试；没有重发。'}};}
   if(epoch!==recoveryEpoch||scope.id!==Workspace.currentConversation().id||busy)return;
   const row=response.data;
   if(response.ok&&row.finished){const hide=document.createElement('button');hide.type='button';hide.textContent='收起此提示';hide.title='只收起恢复提示；原请求与费用记录仍保留';hide.onclick=()=>{dismissed.add(id);try{sessionStorage.setItem('jarvis.recovery.dismissed',JSON.stringify([...dismissed].slice(-200)));}catch{}sessionChanged();};item.append(hide);}
   label.textContent=user.querySelector('.bubble').textContent.slice(0,40)+' · '+(!response.ok?row.user_message:row.expired?'正文已过期':row.finished?row.status==='SUCCEEDED'?'回复已完成':row.result?.user_message||row.status:'仍在处理');
   if(response.ok&&!row.finished){
    running=true;const stop=document.createElement('button');stop.type='button';stop.textContent='停止此回复';
    stop.onclick=async()=>{stop.disabled=true;try{await cancel({dialogue:{instance_id:row.instance_id,conversation_id:scope.id,request_id:id}});sessionChanged();}catch{label.textContent='取消未确认，请重新查询；没有取消后台任务。';}finally{stop.disabled=false;}};item.append(stop);
   }
   if(response.ok&&row.finished&&row.result?.status==='SUCCEEDED'&&typeof row.result.text==='string'){
    const button=document.createElement('button');button.type='button';button.textContent='取回回复';button.disabled=busy;
    button.onclick=async()=>{
     if(busy||Workspace.isBusy()||scope.id!==Workspace.currentConversation().id||$('messages').querySelector('.assistant[data-reply-ref="'+id+'"]'))return;
     const result=row.result,article=addMessage('assistant',result.text,metadata(result)+' · 从原回执取回，未重新调用模型'+(intentSummary(result)?' · '+intentSummary(result):''),'恢复的回复');article.dataset.replyRef=id;markIntent(article,result);
     // Append without shifting existing source-message indices. Older recovered
     // pairs stay visible but do not enter the current model context.
     if(result.personal){article.dataset.personalControl='true';window.Continuity?.accept(result.personal);}
     if(result.output_incomplete)article.classList.add('incomplete');
     const cr=window.Continuity?.mark(article,result.history_info?.continuity)||[];
     const mr=window.MemoryPanel?.mark(article,result.history_info?.memory)||[];
     const kr=window.ProjectKnowledge?.mark(article,result.history_info?.knowledge)||[];
     if(!result.personal)Workspace.attachAnswer(article,result.text,{project:Workspace.currentProject()});
     // Only extend current model context when this is its latest unpaired input.
     const latest=[...$('messages').querySelectorAll('.user:not([data-task-control]):not([data-personal-control])')].at(-1);
     if(!result.personal&&!result.output_incomplete&&latest===user&&user.dataset.attachmentsOmitted!=='true'&&!user.querySelector('.message-attachments')){
      history.push({role:'user',content:user.querySelector('.bubble').textContent},{role:'assistant',content:result.text,_memory_refs:mr,_knowledge_refs:kr,_continuity_refs:cr});trimHistory();
     }
     Workspace.remember();sessionChanged();providerHint();notify('已取回原回复。没有重新调用模型、自动写文件或播放语音。');
    };item.append(button);
   }
  }
  if(epoch===recoveryEpoch){const refresh=document.createElement('button');refresh.type='button';refresh.textContent='重新查询';refresh.onclick=sessionChanged;recovery.append(refresh);}
 }finally{if(recoveryRequest===control)recoveryRequest=null;if(running&&epoch===recoveryEpoch&&!document.hidden)recoveryTimer=setTimeout(checkRecovery,2000);}
}
window.Dialogue={request,cancel,enqueue,complete,controls,sessionChanged,markIntent,intentSummary,hasPending:()=>pending.length>0};
$('message').addEventListener('input',render);
window.addEventListener('beforeunload',event=>{if(pending.length||activeRun?.dialogue){event.preventDefault();event.returnValue='';}});
document.addEventListener('visibilitychange',()=>{if(document.hidden){clearTimeout(recoveryTimer);recoveryRequest?.abort();}else sessionChanged();});
window.addEventListener('pagehide',()=>{clearTimeout(recoveryTimer);recoveryRequest?.abort();});
render();setControls();sessionChanged();
})();
