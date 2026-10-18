"use strict";
(() => {
  const dialog=$('growth-dialog'),pending=new Map();
  const states={PROPOSED:'待开始',QUEUED:'已受理',RUNNING:'进行中',OBSERVING:'观察中',SUCCEEDED:'已完成',FAILED:'失败',UNKNOWN:'结果未知',INTERRUPTED:'运行中断',CANCELLED:'已取消'};
  let currentId=null,timer=null,loading=false,acting=false,selected=null;
  const current=()=>window.Workspace?.currentConversation(),active=s=>['QUEUED','RUNNING','OBSERVING'].includes(s),prefix=id=>'/api/conversation-growth/'+id;
  function error(text){$('growth-error').textContent=text;}
  async function api(path,payload,blob=false){
    const r=await fetch(path,{method:payload===undefined?'GET':'POST',credentials:'omit',cache:'no-store',headers:{'X-Jarvis-Nonce':NONCE,...(payload===undefined?{}:{'Content-Type':'application/json'})},body:payload===undefined?undefined:JSON.stringify(payload),signal:AbortSignal.timeout(12000)});
    if(!r.ok){const d=await r.json(),e=new Error(d.user_message||'成长状态未确认。');e.status=r.status;throw e;}return blob?r.blob():r.json();
  }
  function message(role,text,fields={}){const node=addMessage(role,text);node.dataset.personalControl='true';Object.assign(node.dataset,fields);return node;}
  function linkReceipts(){
    for(const node of document.querySelectorAll('#messages>[data-growth-ref],#messages>[data-growth-request-id]')){
      if(node.querySelector('.growth-link'))continue;
      const button=document.createElement('button');button.type='button';button.className='growth-link';button.textContent='查看改进与结果';
      button.addEventListener('click',()=>show(node));node.append(button);
    }
  }
  function controls(){for(const b of dialog.querySelectorAll('button'))b.disabled=acting;}
  async function act(job,action){
    if(acting)return;const id=currentId;acting=true;controls();error('');
    try{await api(prefix(id)+'/'+job.id+'/'+action,{});if(current()?.id===id)await load();}
    catch(e){error(e.message+' 可查询状态；重复点击同一改进单不会创建第二个作业。');}
    finally{acting=false;controls();}
  }
  async function download(job){
    try{const blob=await api(prefix(currentId)+'/'+job.id+'/artifact',undefined,true),url=URL.createObjectURL(blob),a=document.createElement('a');a.href=url;a.download='目录报告-'+job.id.slice(0,8)+'.'+({markdown:'md'}[job.request.input.format]||job.request.input.format);a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);}
    catch(e){error(e.message);}
  }
  async function reanalyse(job){
    if(acting||busy||pending.has(currentId)){error('请先核对正在处理或结果未确认的请求。');return;}
    const id=currentId;if(current()?.id!==id)return;
    acting=true;busy=true;controls();setControls();error('');
    const prompt=job.request.origin.goal;
    message('user','重新分析：'+prompt);
    const node=message('assistant','正在重新核对需求与来源；原单保留，尚未开始执行。',{growthRequestId:crypto.randomUUID().replaceAll('-','')});
    pending.set(id,{prompt,node});
    try{
      await Workspace.flushConversation();
      const next=await api(prefix(id)+'/'+job.id+'/reanalyse',{request_id:node.dataset.growthRequestId});
      node.dataset.growthRef=next.id;selected=next.id;pending.delete(id);
      node.querySelector('.bubble').textContent='已重新分析并建立待开始的新单。请核对新的来源、能力和模型后开始；原单状态保留。';
      linkReceipts();await load();
    }catch(e){error(e.message+' 请打开回执核对，不会自动重发。');node.querySelector('.bubble').textContent=e.message;
      if(e.status&&e.status<500){pending.delete(id);delete node.dataset.growthRequestId;}}
    finally{linkReceipts();acting=false;busy=false;Workspace.remember();controls();setControls();}
  }
  function render(rows){
    const list=$('growth-list');list.replaceChildren();
    if(!rows.length){list.textContent='本会话尚无改进单。先完成一份目录报告，再输入 /改进 把最近的目录报告导出为 TSV。';return;}
    for(const job of rows){
      const card=document.createElement('article'),title=document.createElement('strong'),steps=document.createElement('div'),copy=document.createElement('p'),scope=document.createElement('small'),actions=document.createElement('div');
      card.className='growth-card';card.dataset.growthId=job.id;card.dataset.active=String(active(job.status));title.textContent=(states[job.status]||job.status)+' · '+job.request.origin.goal;
      steps.className='growth-steps';const phases=job.events.map(e=>e.phase),reached=[true,phases.includes('GENERATING'),phases.includes('VALIDATING'),Boolean(job.activation_confirmed)||Boolean(job.result),Boolean(job.result)];
      ['需求与基线','生成候选','独立验收','能力可用','本次交付'].forEach((label,i)=>{const span=document.createElement('span');span.textContent=label;if(reached[i])span.className='reached';steps.append(span);});
      const p=job.proposal,decision={reuse:'现有能力已覆盖，健康核验后复用；若发现退化，将在本次预算内修复。',upgrade:'现有版本缺少所需格式，需要升级。',create:'当前没有已发布导出能力，需要补齐。',repair:'原能力包状态异常，需要修复或回退。'}[p.decision];
      copy.textContent='分析时：'+decision+' 输出 '+job.request.input.format.toUpperCase()+'，共 '+job.request.input.entries.length+' 条记录。'+(job.status==='SUCCEEDED'?' 已用本次真实输入核对输出。':job.error?' 本次未完成：'+job.error:'');
      scope.textContent='来源：'+job.request.origin.source_task+'。只使用已核验报告中的路径与大小；不重新扫描目录。编码模型：'+p.route+'；最多 '+p.max_coding_attempts+' 个候选。原会话和清单不发送给编码模型。';
      actions.className='growth-actions';const button=(text,fn)=>{const b=document.createElement('button');b.type='button';b.textContent=text;b.addEventListener('click',fn);actions.append(b);};
      if(job.status==='PROPOSED')button(p.decision==='reuse'?'使用现有能力导出':'补齐能力并导出',()=>act(job,'start'));
      if(job.status==='PROPOSED'||active(job.status))button('取消本次',()=>act(job,'cancel'));
      if(job.status==='SUCCEEDED')button('下载已核验结果',()=>download(job));
      if(['FAILED','INTERRUPTED','UNKNOWN','CANCELLED'].includes(job.status)){
        const recovery=document.createElement('p');recovery.className='growth-recovery';
        recovery.textContent=(job.status==='UNKNOWN'?'原单结果未知，请先核对远端用量和已有产物。':'原单已结束，记录将保留。')+' 重新分析只创建待开始的新单，不调用编码模型；可核对后再开始。';card.append(recovery);
        button('重新分析这项需求',()=>reanalyse(job));
      }
      if(job.request.origin.previous_job){const previous=document.createElement('small');previous.textContent='重新分析自：'+job.request.origin.previous_job+'；原记录未改写。';card.append(previous);}
      const details=document.createElement('details'),summary=document.createElement('summary'),pre=document.createElement('pre');summary.textContent=job.result?'查看输出与证据':'查看验收与记录';pre.textContent=job.result?.text||JSON.stringify({acceptance_digest:p.acceptance_digest,input_digest:p.input_digest,events:job.events,attempts:job.attempts},null,2);details.append(summary,pre);
      const settings=document.createElement('a');settings.href='/settings#modules';settings.target='_blank';settings.rel='noopener';settings.textContent='成长设置与回退 ↗';actions.append(settings);
      card.append(title,steps,copy,scope,actions,details);list.append(card);
    }controls();
  }
  async function load(){
    if(loading||!dialog.open||document.hidden||!currentId)return;loading=true;clearTimeout(timer);const id=currentId;
    try{const data=await api(prefix(id));if(current()?.id!==id)return;
      if(selected&&!data.jobs.some(j=>j.id===selected))data.jobs.unshift(await api(prefix(id)+'/'+selected));
      render(data.jobs);error('');
    }catch(e){error(e.message);}finally{loading=false;if(dialog.open&&!document.hidden)timer=setTimeout(load,4000);}
  }
  async function show(node=null){
    currentId=current()?.id;if(!currentId)return;selected=node?.dataset.growthRef||null;if(!dialog.open)dialog.showModal();error('');
    if(node?.dataset.growthRequestId&&!node.dataset.growthRef){
      try{const job=await api(prefix(currentId)+'/requests/'+node.dataset.growthRequestId);node.dataset.growthRef=job.id;selected=job.id;pending.delete(currentId);node.querySelector('.bubble').textContent='改进单已保存。开始与执行结果以实际记录为准。';window.Workspace?.remember();}
      catch(e){error(e.message);return;}
    }await load();
  }
  async function handleSubmit(){
    const original=$('message').value.trim(),match=original.match(/^\/改进(?:\s+([\s\S]+))?$/u),context=current();
    if(!match&&original!=='/成长进度'){notify('查询请使用完整的 /成长进度。');return;}
    if(!context||context.temporary){notify('请在普通会话中提出改进；临时会话不建立持久改进单。');return;}
    if(Attachments.hasDraft()||$('file-mode').checked){notify('改进使用本会话已完成的目录报告；请先移除附件并关闭文件输出。');return;}
    if(match&&!match[1]){notify('例如：/改进 把最近的目录报告导出为 TSV');return;}
    const prompt=match?.[1],old=pending.get(context.id);
    if(prompt&&old&&old.prompt!==prompt){notify('上次分析结果尚未确认，请先打开回执核对；没有重新生成。');return;}
    busy=true;setControls();let node;
    try{
      if(old){node=old.node;}else{
        message('user',original);node=message('assistant',match?'正在分析已有能力与来源；尚未启动生成。':'正在查询本会话成长记录。',match?{growthRequestId:crypto.randomUUID().replaceAll('-','')}:{});
        if(!history.length)$('session-title').textContent=(prompt||original).slice(0,22);
      }
      $('message').value='';await Workspace.flushConversation();
      if(match){
        pending.set(context.id,{prompt,node});const job=await api(prefix(context.id),{request_id:node.dataset.growthRequestId,prompt});node.dataset.growthRef=job.id;pending.delete(context.id);
        node.querySelector('.bubble').textContent='已形成改进单：'+prompt+'。已有能力、输入范围、模型和验收条件可查看；开始后可继续聊天。';
      }else node.querySelector('.bubble').textContent='成长状态来自本机记录。查看进度不调用模型。';
      window.Workspace?.remember();linkReceipts();await show(match?node:null);
    }catch(e){
      if(node){node.querySelector('.bubble').textContent=e.message;if(e.status&&e.status<500){pending.delete(context.id);delete node.dataset.growthRequestId;}}
      if(!$('message').value)$('message').value=original;notify(e.message);linkReceipts();
    }finally{busy=false;window.Workspace?.remember();setControls();}
  }
  $('growth-close').addEventListener('click',()=>{if(!acting)dialog.close();});$('growth-refresh').addEventListener('click',load);
  dialog.addEventListener('cancel',e=>{if(acting)e.preventDefault();});dialog.addEventListener('close',()=>clearTimeout(timer));
  document.addEventListener('visibilitychange',()=>{clearTimeout(timer);if(!document.hidden)load();});window.addEventListener('pagehide',()=>clearTimeout(timer));
  window.ConversationGrowth={handleSubmit,sessionChanged(){const id=current()?.id;if(id!==currentId){currentId=id;selected=null;clearTimeout(timer);if(dialog.open)dialog.close();}linkReceipts();}};
  window.ConversationGrowth.sessionChanged();
})();
