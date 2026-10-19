/* Conversation controls read the ledger; automatic receipts come from Host admission. */
(()=>{'use strict';
const $=id=>document.getElementById(id),states={READY:'已受理',RUNNING:'执行中',CANCELLING:'取消中',SUCCEEDED:'已完成',FAILED:'失败',CANCELLED:'已取消',UNKNOWN:'结果待核对'};
const active=s=>['READY','RUNNING','CANCELLING'].includes(s),validTask=x=>/^task_[a-f0-9]{32}$/.test(x||''),validRequest=x=>/^web-[a-f0-9]{32}$/.test(x||'');
const details=new Map(),recoveryAttempts=new Map(),pending=new Map();
let currentId=null,rows=[],snapshot=null,timer=null,loading=false,submitting=false,generation=0,selected=null;
const current=()=>window.Workspace?.currentConversation();
const mcpControls=document.createElement('div');mcpControls.className='skill-controls';mcpControls.id='mcp-task-controls';mcpControls.hidden=true;
const mcpLabel=document.createElement('label'),mcpLibrary=document.createElement('input'),mcpHint=document.createElement('small');
mcpLabel.textContent='文档库';mcpLabel.htmlFor='mcp-library';mcpLibrary.id='mcp-library';mcpLibrary.placeholder='例如 Electron 或 /electron/electron';mcpLibrary.maxLength=160;
mcpHint.textContent='只发送库名与当前问题到 Context7；库名先查候选，库 ID 直接查文档。零模型调用。';mcpControls.append(mcpLabel,mcpLibrary,mcpHint);$('conversation-task-note').after(mcpControls);
const same=id=>current()?.id===id;
const prefix=id=>'/api/conversation-tasks/'+id;
function bounded(map,key,value){map.set(key,value);while(map.size>64)map.delete(map.keys().next().value);}
async function api(path,payload,{blob=false}={}){
 const r=await fetch(path,{method:payload===undefined?'GET':'POST',cache:'no-store',credentials:'omit',headers:{'X-Jarvis-Nonce':NONCE,...(payload===undefined?{}:{'Content-Type':'application/json'})},body:payload===undefined?undefined:JSON.stringify(payload),signal:AbortSignal.timeout(10000)});
 if(!r.ok){const d=await r.json(),e=new Error(d.user_message||'任务接口暂不可用。');e.status=r.status;if(r.status===403)window.Workbench?.sessionExpired();throw e;}
 return blob?r.blob():r.json();
}
function controlMessage(role,text,fields={}){const article=addMessage(role,text);article.dataset.taskControl='true';for(const [key,value] of Object.entries(fields))article.dataset[key]=value;return article;}
function receiptLinks(){
 for(const article of document.querySelectorAll('#messages>.message[data-task-control="true"]')){
  const task=article.dataset.taskRef,request=article.dataset.taskRequestId;
  if(!validTask(task)&&!validRequest(request)||article.querySelector('.conversation-task-link'))continue;
  const b=document.createElement('button');b.type='button';b.className='conversation-task-link';b.textContent=task?'查看真实任务':'核对任务请求';
  b.onclick=async()=>{show();if(task)await openTask(task);else{recoveryAttempts.delete(currentId+':'+request);await load(true);}};article.append(b);
 }
}
function controls(){
 const temp=current()?.temporary;
 $('composer-mode').disabled=busy||Boolean(window.Workspace?.isBusy())||submitting;
 mcpControls.hidden=$('composer-mode').value!=='mcp';
 $('conversation-task-note').hidden=$('composer-mode').value!=='task';
 $('conversation-task-note').textContent='任务模式：当前执行样例目录统计报告；使用当前选择的模型，任务和回执保存在本机。'+(snapshot?.inventory_root?' 样例根：'+snapshot.inventory_root+'，当前项目不会改变此范围。':'')+(temp?'临时会话只是不归档聊天，任务仍写入本机账本。':'可用 /任务 要求、/进度、/取消。');
}
function render(){
 const host=$('conversation-task-list');host.replaceChildren();
 $('conversation-tasks-toggle').textContent='本会话任务'+(rows.length?' · '+rows.length:'');
 const note=$('conversation-task-summary');
 note.textContent=snapshot?(snapshot.queue.paused?'队列暂停；核对后可在后台任务页继续。':snapshot.queue.resources?.waiting?'后台任务等待资源。':'任务状态来自本机账本。')+' 当前显示 '+rows.length+' 项（最多 30 项，未完成优先），关闭会话不会取消任务。':'尚未读取本会话任务。';
 for(const row of rows){
  const card=document.createElement('article'),title=document.createElement('strong'),state=document.createElement('span'),meta=document.createElement('small'),actions=document.createElement('div');
  card.className='conversation-task-card';card.dataset.taskId=row.task_id;title.textContent=row.goal||'样例目录报告';state.className='conversation-task-state';state.textContent=states[row.status]||row.status;meta.textContent=row.task_id+(row.queue_position?' · 排队第 '+row.queue_position+' 位':'');actions.className='conversation-task-actions';
  function button(text,work){const b=document.createElement('button');b.type='button';b.textContent=text;b.onclick=async()=>{b.disabled=true;try{await work();}catch(e){notify(e.message);}finally{b.disabled=false;}};actions.append(b);return b;}
  button('查看详情',()=>openTask(row.task_id));
  if(['READY','RUNNING'].includes(row.status))button('取消任务',()=>cancelTask(row.task_id));
  if(row.kind==='natural'&&row.status==='READY')button('修改目录…',()=>{
   if(busy||submitting||$('message').value.trim()||Attachments.hasDraft()||$('file-mode').checked){notify('请先处理当前回复、草稿或附件；已有输入已保留。');return;}
   $('composer-mode').value='chat';$('message').value='把报告 '+row.task_id+' 的目录改为 ';
   controls();setControls();$('message').focus();notify('填写样例根内的相对目录后发送；只有尚未开始的报告可以替换。');
  });
  const link=document.createElement('a');link.textContent='后台记录 ↗';link.href='/settings?task='+row.task_id+'#tasks';link.target='_blank';link.rel='noopener';actions.append(link);
  card.append(title,state,meta);
  const detail=details.get(currentId+':'+row.task_id);
  if(detail){
   if(detail.report_control){const scope=document.createElement('small'),control=detail.report_control;
    scope.textContent='样例根内目录：'+control.relative_path+(control.admission?.replacement?' · 替换原报告：'+control.admission.replacement.task_id:'');card.append(scope);}
   const text=document.createElement('p');
   if(detail.report&&detail.action_status==='CONFIRMED'){
    if(detail.report.kind==='jarvis.skill-report'){
     text.textContent='技能已完成：'+detail.report.skill_id+'。'+((detail.report.evidence||detail.report.evidence_ref)?(detail.report.explanation?.model_calls?'静态解析与中文解释已交付；引用已核对，模型结论尚需验证；未运行目标软件。':'本地静态解析与证据交付完成；未运行目标软件，未调用模型。'):detail.report.html?'数值、页面交互及交付摘要检查通过。':'只读模型分析已交付；源码未修改，分析结论尚需人工或测试验证。');
     if(detail.report.html)button(detail.report.skill_id==='jarvis.tank-game'?'试玩游戏':'预览交互图',()=>window.SkillWorkbench.preview(row.task_id));
     if(detail.report.coding){text.textContent=detail.report.coding.passed?'编程副本通过所提供案例；交付时原文件未修改。':'编程验收未通过；交付时原文件未修改。';button('查看差异与验收',()=>window.SkillWorkbench.codingPreview(detail.report,row.task_id));}
     button('下载产物',()=>window.SkillWorkbench.download(row.task_id,detail.report));
     if(detail.report.evidence||detail.report.evidence_ref)button('查看分析报告',()=>window.SkillWorkbench.reportPreview(detail.report,row.task_id));
     if(detail.report.evidence||detail.report.evidence_ref)button('下载完整证据',()=>window.SkillWorkbench.evidence(row.task_id,detail.report));
    }else if(detail.report.kind==='jarvis.mcp-report'){
     text.textContent='Context7 已返回'+(detail.report.tool==='query-docs'?'文档资料':'候选文档库')+' · 1 次只读工具调用 · 未调用模型。内容来自外部服务，使用前核对来源及版本。';
     button('查看文档结果',()=>mcpPreview(detail.report));button('下载调用回执',()=>download(row.task_id));
    }else{text.textContent='已核验：'+detail.report.total_files+' 个文件 · '+detail.report.total_bytes+' 字节。'+(detail.report.by_type||[]).map(g=>g.type+'：'+g.file_count+' 个').join('；');button('下载已核验报告',()=>download(row.task_id));}
    const path=document.createElement('small');path.textContent='本机产物：'+(detail.report.output?.path||detail.artifact_path);card.append(path);
   }else text.textContent=detail.task.status==='CANCELLED'?'已取消；未确认产物不会作为完成结果提供。':detail.error?.message||'当前状态：'+(states[detail.task.status]||detail.task.status);
   card.append(text);
   if(selected===row.task_id){
    const info=document.createElement('small');info.textContent=(detail.steps||[]).map(s=>'规划 '+(s.ordinal+1)+'：'+s.state).join(' · ');card.append(info);
   }
  }
  card.append(actions);host.append(card);
 }
 if(!rows.length){const p=document.createElement('p');p.textContent='本会话暂无已查询到的任务。切换“执行任务”后输入要求，或使用 /任务。';host.append(p);}
 receiptLinks();
}
function schedule(delay=4000){clearTimeout(timer);if(!document.hidden&&currentId)timer=setTimeout(()=>load(),delay);}
async function recoverRequests(id){
 const articles=[...document.querySelectorAll('#messages>.message[data-task-request-id]')].filter(a=>!a.dataset.taskRef).slice(-10);
 for(const article of articles){
  const request=article.dataset.taskRequestId,key=id+':'+request;
  if(!validRequest(request)||(recoveryAttempts.get(key)||0)>=3)continue;
  bounded(recoveryAttempts,key,(recoveryAttempts.get(key)||0)+1);
  try{const data=await api(prefix(id)+'/requests/'+request);if(!same(id))return;
   article.dataset.taskRef=data.task.task_id;article.querySelector('.conversation-task-link')?.remove();bounded(details,id+':'+data.task.task_id,data);
   const submitted=pending.get(id);if(submitted?.payload.request_id===request){if($('message').value===submitted.original)$('message').value='';notify('已按原请求编号找回任务，未重复创建。');pending.delete(id);}
   article.querySelector('.bubble').textContent='任务已持久受理：'+data.task.task_id+'。进度及结果以任务记录为准。';window.Workspace?.remember();
  }catch(e){if(e.status!==404)throw e;}
 }
}
async function load(force=false){
 const id=current()?.id;if(!id||loading||document.hidden)return;
 loading=true;const mine=generation;
 try{
  if(force)for(const key of recoveryAttempts.keys())if(key.startsWith(id+':'))recoveryAttempts.delete(key);
  const data=await api(prefix(id));if(!same(id)||mine!==generation)return;
  rows=data.tasks;snapshot=data;
  await recoverRequests(id);if(!same(id)||mine!==generation)return;
  if(selected&&validTask(selected)){
   const d=await api(prefix(id)+'/'+selected);if(!same(id)||mine!==generation)return;bounded(details,id+':'+selected,d);
  }
  $('conversation-task-error').textContent='';render();controls();return data;
 }catch(e){if(same(id)&&mine===generation)$('conversation-task-error').textContent=e.name==='TimeoutError'?'状态读取超时，未重新提交任务。':e.message;}
 finally{
  loading=false;
  if(!same(id))schedule(0);
  else if(!document.hidden&&(!$('conversation-task-panel').hidden||rows.some(r=>active(r.status))))schedule();
 }
}
function show(read=true){
 $('conversation-task-panel').hidden=false;$('conversation-tasks-toggle').setAttribute('aria-expanded','true');if(read)load();
}
async function openTask(task){
 if(!validTask(task))return;selected=task;show(false);const id=currentId;
 try{const d=await api(prefix(id)+'/'+task);if(!same(id))return;bounded(details,id+':'+task,d);
  if(!rows.some(r=>r.task_id===task))rows.unshift({task_id:task,status:d.task.status,goal:'关联任务'});
  else rows=rows.map(r=>r.task_id===task?{...r,status:d.task.status}:r);render();return d;
 }catch(e){if(same(id))$('conversation-task-error').textContent=e.message;}
}
async function download(task){
 const id=currentId,blob=await api(prefix(id)+'/'+task+'/artifact',undefined,{blob:true});if(!same(id))return;
 const url=URL.createObjectURL(blob),a=document.createElement('a');a.href=url;a.download=task+'.json';a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);
}
async function cancelTask(task){
 const id=currentId;
 try{const d=await api(prefix(id)+'/'+task+'/cancel',{});if(!same(id))return;
  bounded(details,id+':'+task,d);rows=rows.map(r=>r.task_id===task?{...r,status:d.task.status}:r);render();notify('取消请求已记录；已发生的效果以实际回执为准。');await load();return d;
 }catch(e){notify(e.message+' 取消回执未确认时请先查询，不会自动重复请求。');}
}
function sessionChanged(){
 const id=current()?.id;if(!id)return;
 if(id!==currentId){$('mcp-result-dialog')?.remove();currentId=id;rows=[];snapshot=null;selected=null;generation++;clearTimeout(timer);$('composer-mode').value='chat';$('conversation-task-error').textContent='';render();
  if(!$('conversation-task-panel').hidden||document.querySelector('#messages [data-task-control="true"]'))schedule(0);
 }else receiptLinks();
 controls();
}
function mcpPreview(report){
 $('mcp-result-dialog')?.remove();const dialog=document.createElement('dialog');dialog.id='mcp-result-dialog';dialog.className='skill-preview';dialog.style.cssText='width:min(880px,94vw);max-height:85vh;overflow:auto;padding:24px';
 const title=document.createElement('h2'),close=document.createElement('button'),description=document.createElement('p'),body=document.createElement('pre');title.textContent='Context7 文档结果';close.textContent='关闭';close.onclick=()=>dialog.close();description.textContent=report.library+' · '+report.query;body.textContent=report.text;body.style.cssText='white-space:pre-wrap;overflow-wrap:anywhere;font:13px/1.8 ui-monospace,monospace';dialog.append(title,close,description);
 for(const id of report.candidates||[]){const button=document.createElement('button');button.textContent='选择 '+id;button.style.margin='4px';button.onclick=()=>{if($('message').value.trim()){notify('当前草稿仍在，请先处理草稿再选库。');return;}$('composer-mode').value='mcp';mcpLibrary.value=id;$('message').value=report.query;controls();window.SkillWorkbench?.controls();dialog.close();$('message').focus();};dialog.append(button);}
 dialog.append(body);document.body.append(dialog);dialog.showModal();
}
async function prepareDocumentation(candidate,conversationId,text){
 if(current()?.id!==conversationId){notify('会话已切换，请在原会话重新准备文档草稿。');return false;}
 if(busy||submitting||window.Workspace?.isBusy()||$('message').value.trim()||Attachments.hasDraft()||$('file-mode').checked){
  notify('请先处理当前回复、草稿或附件，再准备文档查询。');return false;
 }
 const project=window.Workspace?.currentProject()?.id,mode=$('composer-mode').value,mine=generation,libraryBefore=mcpLibrary.value;
 let checked;
 try{checked=await api(prefix(conversationId)+'/documentation-candidate',{candidate,text,...(project?{project_id:project}:{})});}
 catch(error){notify(error.message);return false;}
 if(!checked.eligible){notify(checked.reason||'文档候选尚未通过条件检查。');return false;}
 if(mine!==generation||current()?.id!==conversationId||checked.context?.project_id!==(window.Workspace?.currentProject()?.id||undefined)){
  notify('会话项目已变化，请重新核对文档候选。');return false;
 }
 if(busy||submitting||window.Workspace?.isBusy()||$('message').value.trim()||Attachments.hasDraft()||$('file-mode').checked||$('composer-mode').value!==mode||mcpLibrary.value!==libraryBefore){
  notify('输入状态已变化，已保留当前草稿。');return false;
 }
 $('composer-mode').value='mcp';mcpLibrary.value=checked.library;$('message').value=checked.query;
 controls();window.SkillWorkbench?.controls();setControls();$('message').focus();
 notify('文档草稿已准备；检查库名与查询后发送。只会外发这些内容。');return true;
}
async function submit(prompt,original,extra=null){
 const context=current(),id=context.id,item=chosenModel(),model=item?item.provider+'::'+item.model:'auto';
 if(submitting){notify('上个任务提交仍在核对中，草稿保留。');return;}
 if(Attachments.hasDraft()||$('file-mode').checked){notify('此任务不使用附件或回答文件输出，请先移除附件并关闭该选项。');return;}
 if(!prompt.trim()||encoder.encode(prompt).length>(extra?2048:1024)){notify('请输入单个有界任务要求。');return;}
 if(extra&&!extra.library.trim()){notify('请填写文档库名称或 ID。');return;}
 const old=pending.get(id),payload={request_id:old?.payload.request_id||'web-'+crypto.randomUUID().replaceAll('-',''),prompt:prompt.trim(),...(extra||{model,relative_path:'.'})};
 if(old&&JSON.stringify(payload)!==JSON.stringify(old.payload)){notify('此前任务提交结果尚未确认，请先核对本会话任务；当前草稿保留。');show();return;}
 let article=old?.article;
 if(!article){
  controlMessage('user',original);article=controlMessage('assistant','正在提交任务；受理与执行结果尚未确认。',{taskRequestId:payload.request_id});
  if(!history.length&&!$('messages').querySelector('.message.user:not([data-task-control]):not([data-personal-control])'))$('session-title').textContent=prompt.slice(0,22);
  bounded(pending,id,{payload,article,original});
 }
 $('message').value='';window.Workspace?.remember();submitting=true;controls();show();
 try{
  const result=await api(prefix(id),payload);article.dataset.taskRef=result.task_id;article.querySelector('.conversation-task-link')?.remove();article.querySelector('.bubble').textContent='任务已持久受理：'+result.task_id+'。进度及结果以任务记录为准。';pending.delete(id);
  if(same(id)){receiptLinks();selected=result.task_id;window.Workspace?.remember();await load();}
 }catch(e){
  article.querySelector('.bubble').textContent='任务提交回执尚未确认；先核对请求，重试时使用原编号。';
  if(e.status&&e.status<500){pending.delete(id);article.querySelector('.bubble').textContent='任务未受理：'+e.message;delete article.dataset.taskRequestId;}
  if(same(id)){if(!$('message').value)$('message').value=original;window.Workspace?.remember();notify(e.message);await load();}
 }finally{submitting=false;controls();}
}
async function query(command,task){
 const id=currentId;controlMessage('user',command);window.Workspace?.remember();let result;
 if(task)result=await openTask(task);else{show(false);result=await load(true);}
 if(!same(id))return;
 controlMessage('assistant',result?'任务状态已从本机账本查询；请查看“本会话任务”。':'任务状态暂未确认；请查看提示并刷新状态。');window.Workspace?.remember();
}
async function cancelCommand(command,task){
 const id=currentId;show(false);await load(true);if(!same(id))return;
 const candidates=rows.filter(r=>['READY','RUNNING'].includes(r.status));
 const chosen=task||(candidates.length===1?candidates[0].task_id:null);
 controlMessage('user',command);
 if(chosen){const result=await cancelTask(chosen);if(!same(id))return;controlMessage('assistant',result?'取消请求已记录；请以本会话任务中的实际状态为准。':'取消结果暂未确认；请先查询状态。',result?{taskRef:chosen}:{});}
 else controlMessage('assistant',candidates.length?'有多个可取消任务，请使用对应任务的取消按钮或 /取消 任务编号。':'当前查询范围内没有可取消任务。');
 window.Workspace?.remember();
}
function handleSubmit(){
 const docs=$('message').value.trim().match(/^\/文档\s+(\S+)\s+([\s\S]+)$/);
 if(docs||$('composer-mode').value==='mcp'){
  if(!current()){notify('会话尚未就绪，草稿保留。');return true;}
  const original=$('message').value,project=window.Workspace?.currentProject()?.id;
  submit(docs?docs[2]:original,original,{mode:'mcp',library:docs?docs[1]:mcpLibrary.value.trim(),...(project?{project_id:project}:{})});return true;
 }
 const text=$('message').value.trim(),match=text.match(/^\/(任务|进度|取消)(?:\s+([\s\S]*))?$/),queryText=/^(查看任务进度|查询任务进度|任务进度)$/.test(text),cancelText=text==='取消当前任务';
 if(!match&&!queryText&&!cancelText&&$('composer-mode').value!=='task')return false;
 if(!current()){notify('会话尚未就绪，草稿保留。');return true;}
 const verb=match?.[1]||(queryText?'进度':cancelText?'取消':'任务'),arg=match?match[2]||'':verb==='任务'?text:'';
 if(verb!=='任务'&&arg&&!validTask(arg)){notify('请使用真实 task_ 任务编号，或打开本会话任务选择。');return true;}
 if(verb==='任务'){submit(arg,text);return true;}
 $('message').value='';(verb==='进度'?query(text,arg):cancelCommand(text,arg)).catch(e=>notify(e.message));return true;
}
$('composer-mode').onchange=()=>{controls();setControls();};
$('conversation-tasks-toggle').onclick=()=>{const panel=$('conversation-task-panel');panel.hidden=!panel.hidden;$('conversation-tasks-toggle').setAttribute('aria-expanded',String(!panel.hidden));if(!panel.hidden)load(true);else{clearTimeout(timer);if(rows.some(r=>active(r.status)))schedule();}};
$('conversation-task-refresh').onclick=()=>load(true);
document.addEventListener('visibilitychange',()=>{clearTimeout(timer);if(!document.hidden&&(!$('conversation-task-panel').hidden||rows.some(r=>active(r.status))))load();});
window.addEventListener('pagehide',()=>clearTimeout(timer));
function automaticReceipt(receipt){
 if(!['submitted','controlled'].includes(receipt?.status)||!validTask(receipt.task_id)||!validRequest(receipt.request_id))return;
 if(!$('messages').querySelector('.message[data-task-control][data-task-request-id="'+receipt.request_id+'"]')){
  controlMessage('assistant',receipt.reason||'任务操作已受理，进度与结果请查看本会话任务。',{taskRef:receipt.task_id,taskRequestId:receipt.request_id});
  window.Workspace?.remember();
 }
 selected=receipt.task_id;show(false);load(true);
}
window.ConversationTasks={sessionChanged,controls,handleSubmit,openTask,load,prepareDocumentation,automaticReceipt};sessionChanged();
})();
