"use strict";
(() => {
  const el=id=>document.getElementById(id),dialog=el('memory-dialog');
  let rows=[],editing=null,working=false,loadGeneration=0,pending=null,compatible=false;
  const newId=()=>crypto.randomUUID().replaceAll('-','');
  const kinds={personal_fact:['个人事实','owner','personal'],preference:['偏好','owner','personal'],episode:['共同经历','owner','personal'],temporary_state:['临时状态','owner','personal'],project_fact:['项目资料','project','work'],work_result:['工作结果描述','project','work'],shared_experience:['共用经验','owner','shared'],third_party:['他人资料','other','others'],fiction:['虚构角色资料','character','others']};
  const useNames={personal_chat:'日常交流',work_assist:'工作协助'};
  function context(){const state=window.Workspace?.memoryContext?.()||{project_id:null,temporary:false};return {enabled:el('memory-enabled').checked&&!state.temporary,project_id:state.project_id,...(compatible&&el('memory-purpose').value?{purpose:el('memory-purpose').value}:{}),...(!state.temporary&&window.ProjectKnowledge?{project_ids:window.ProjectKnowledge.projectIds()}:{})};}
  function status(message,error=false){el('memory-status').textContent=message;el('memory-status').dataset.error=String(error);}
  async function api(path,payload){
    const controller=new AbortController(),timer=setTimeout(()=>controller.abort(),10000);
    try{
      const response=await fetch('/api/memory'+path,{method:payload===undefined?'GET':'POST',credentials:'omit',cache:'no-store',headers:{'X-Jarvis-Nonce':NONCE,...(payload===undefined?{}:{'Content-Type':'application/json'})},body:payload===undefined?undefined:JSON.stringify(payload),signal:controller.signal});
      const data=await response.json();if(!response.ok)throw new Error(data.user_message||'记忆操作未完成。');return data;
    }catch(error){if(error.name==='AbortError')throw new Error('保存结果尚未确认，输入仍保留；重试会使用同一条记忆标识。');throw error;}
    finally{clearTimeout(timer);}
  }
  function controls(){
    const temporary=Boolean(window.Workspace?.memoryContext?.().temporary);
    el('open-memory').disabled=Boolean(window.Workspace?.isBusy());
    for(const control of dialog.querySelectorAll('#memory-facts input,#memory-facts textarea,#memory-facts select,#memory-facts button,#memory-close,#memory-enabled,[data-memory-tab]'))control.disabled=working;
    el('memory-save').disabled=working||temporary||!compatible;
    el('memory-enabled').disabled=working||temporary;
    el('memory-purpose').disabled=working||temporary||!compatible;
    for(const button of dialog.querySelectorAll('[data-memory-mutate]'))button.disabled=working||temporary||!compatible;
    window.Continuity?.controls();
    classificationControls();
  }
  function classificationControls(){
    const kind=el('memory-kind').value,enabled=Boolean(kind),subject=kinds[kind]?.[1];
    el('memory-classification-fields').hidden=!enabled;
    el('memory-subject-label').required=enabled&&['other','character'].includes(subject);
    el('memory-subject-label').hidden=!['other','character'].includes(subject);
    dialog.querySelector('label[for="memory-subject-label"]').hidden=el('memory-subject-label').hidden;
    el('memory-expires').required=kind==='temporary_state';
    for(const id of ['memory-use-personal','memory-use-work'])el(id).disabled=working||kind==='fiction';
  }
  function classificationDefaults(){
    const kind=el('memory-kind').value;
    if(!['third_party','fiction'].includes(kind))el('memory-subject-label').value='';
    el('memory-use-personal').checked=!['project_fact','work_result','fiction'].includes(kind);
    el('memory-use-work').checked=['project_fact','work_result','shared_experience'].includes(kind);
    if(['project_fact','work_result'].includes(kind))el('memory-scope').value=window.Workspace?.memoryContext?.().project_id||'';
    classificationControls();
  }
  function providers(selected=[]){
    const ids=[...new Set([...modelCatalog.map(m=>m.provider),...selected])].filter(id=>id!=='local');
    el('memory-providers').replaceChildren();
    for(const id of ids){const label=document.createElement('label'),input=document.createElement('input');input.type='checkbox';input.value=id;input.checked=selected.includes(id);label.append(input,document.createTextNode(names[id]||id));el('memory-providers').append(label);}
  }
  function edit(row=null){
    editing=row;pending=null;el('memory-title').value=row?.document.title||'';el('memory-content').value=row?.document.content||'';
    const state=window.Workspace?.memoryContext?.()||{};el('memory-scope').replaceChildren(new Option('通用：适用于我的普通会话',''));
    if(state.project_id)el('memory-scope').append(new Option('仅当前项目',state.project_id));
    el('memory-scope').value=row?.document.project_id||'';providers(row?.document.providers||[]);
    const meta=row?.document.classification;
    el('memory-kind').replaceChildren();
    if(row&&!meta)el('memory-kind').append(new Option('未分类：保留原兼容规则',''));
    for(const [key,value] of Object.entries(kinds))el('memory-kind').append(new Option(value[0],key));
    el('memory-kind').value=meta?.kind||(row?'':'personal_fact');
    el('memory-subject-label').value=meta?.subject_label||'';
    el('memory-use-personal').checked=meta?meta.uses.includes('personal_chat'):true;
    el('memory-use-work').checked=meta?meta.uses.includes('work_assist'):false;
    const until=meta?.expires_at?new Date(meta.expires_at):null;
    el('memory-expires').value=until?new Date(until.getTime()-until.getTimezoneOffset()*60000).toISOString().slice(0,19):'';
    el('memory-editor-heading').textContent=row?'修改记忆':'添加明确记忆';el('memory-save').textContent=row?'保存修改':'记住';controls();
  }
  function render(){
    el('memory-list').replaceChildren();
    const category=el('memory-category-filter').value;
    const visible=rows.filter(row=>category==='all'||(kinds[row.document.classification?.kind]?.[2]||'legacy')===category);
    if(!visible.length){el('memory-list').textContent='当前范围还没有匹配的记忆。';return;}
    for(const row of visible){
      const card=document.createElement('article'),title=document.createElement('strong'),body=document.createElement('p'),meta=document.createElement('small'),actions=document.createElement('div');
      card.className='memory-card';card.dataset.memoryId=row.id;title.textContent=row.document.title;body.textContent=row.document.content;
      meta.textContent=(row.document.project_id?'当前项目':'通用')+' · 你明确保存 · 修订 '+row.revision+' · '+(row.document.providers.length?'可用于：本地、'+row.document.providers.map(p=>names[p]||p).join('、'):'仅本地模型');
      const classification=row.document.classification,usage=document.createElement('small');usage.className='memory-usage';
      usage.textContent=classification?(kinds[classification.kind]?.[0]||classification.kind)+(classification.subject_label?' · '+classification.subject_label:'')+' · '+(classification.uses.map(use=>useNames[use]).join('、')||'仅保存')+(row.usage?.state==='expired'?' · 已到期，暂停使用':classification.expires_at?' · 到期 '+new Date(classification.expires_at).toLocaleString():''):'未分类 · 保留原项目/接入方规则，可点击修改细分用途';
      const provenance=row.provenance,state=provenance?.state;
      const sourceInfo=document.createElement('div');sourceInfo.className='memory-source';
      if(provenance?.source_ref){
        const label=document.createElement('p');label.className='memory-source-state';
        label.textContent=state==='current'?'聊天候选 · 来源已核对':state==='independent'?'你已独立确认 · 原聊天变化不再影响这条记忆':state==='unchecked'?'来源核对达到本次上限 · 暂停用于回答':'来源已变化或删除 · 暂停用于回答';
        sourceInfo.append(label);
        const details=document.createElement('details'),summary=document.createElement('summary'),locator=document.createElement('small');
        summary.textContent='查看来源';locator.textContent='会话 '+provenance.source_ref.conversation_id+' · 第 '+(provenance.source_ref.message_index+1)+' 条消息 · 保存时版本 '+provenance.source_ref.archive_revision;
        details.append(summary,locator);
        if(provenance.excerpt){const quote=document.createElement('blockquote');quote.textContent=provenance.excerpt;details.append(quote);}
        else{const note=document.createElement('p');note.textContent=state==='independent'?'保留来源定位，不将旧原文视为当前事实。':'当前没有可核对的原文。你可以修改后保存、确认独立保留，或忘记这条记忆。';details.append(note);}
        sourceInfo.append(details);
      }
      actions.className='memory-card-actions';const change=document.createElement('button'),forget=document.createElement('button');
      change.type=forget.type='button';change.dataset.memoryMutate=forget.dataset.memoryMutate='true';change.textContent='修改';forget.textContent='忘记';
      change.addEventListener('click',()=>{edit(row);status('修改会让旧修订退出后续记忆上下文。');el('memory-title').focus();});
      forget.addEventListener('click',async()=>{
        if(working)return;
        if(forget.dataset.confirm!=='true'){forget.dataset.confirm='true';forget.textContent='确认忘记';return;}
        working=true;controls();status('正在忘记…');
        try{await api('/'+row.id+'/delete',{revision:row.revision});if(editing?.id===row.id)edit();await load();status('已忘记。原聊天与导出文件未删除。');}
        catch(error){status(error.message,true);}finally{working=false;controls();}
      });
      actions.append(change,forget);
      if(state==='source_changed_or_missing'||state==='unchecked'){
        const retain=document.createElement('button');retain.type='button';retain.dataset.memoryMutate='true';retain.textContent='确认独立保留';
        retain.addEventListener('click',async()=>{
          if(working)return;working=true;controls();status('正在确认这条记忆…');
          try{await api('/'+row.id,{revision:row.revision,document:row.document,reaffirm_source:true});await load();if(editing?.id===row.id)edit();status('已按你的确认独立保留，不再依赖原聊天。旧候选不会覆盖它。');}
          catch(error){status(error.message,true);}finally{working=false;controls();}
        });actions.append(retain);
      }
      card.append(title,body,meta,usage,sourceInfo,actions);el('memory-list').append(card);
    }
    controls();
  }
  async function load(){
    const generation=++loadGeneration,state=context(),query=new URLSearchParams();
    if(state.project_id)query.set('project_id',state.project_id);if(el('memory-search').value.trim())query.set('q',el('memory-search').value.trim());
    const data=await api(query.size?'?'+query:'');if(generation!==loadGeneration)return;
    compatible=data.schema_version===3&&data.capabilities?.includes('owner_facing_purpose');rows=data.facts;render();controls();
    if(!compatible)throw new Error('记忆界面已更新，宿主仍为旧版；请重启 Jarvis 后刷新页面，分类修改暂不可用。');
  }
  el('open-memory').addEventListener('click',async()=>{
    if(window.Workspace?.isBusy())return;dialog.showModal();edit();el('memory-search').value='';status('正在读取…');
    try{await load();status(window.Workspace?.memoryContext?.().temporary?'临时会话不使用或修改长期记忆。':'记忆来自你的明确保存或聊天指令，不会自动提取普通闲聊。');}catch(error){status(error.message,true);}
  });
  el('memory-close').addEventListener('click',()=>{if(!working&&!window.Continuity?.isWorking())dialog.close();});
  dialog.addEventListener('cancel',event=>{if(working)event.preventDefault();});
  el('memory-new').addEventListener('click',()=>{edit();status('新记忆默认只允许本地模型使用。');});
  el('memory-kind').addEventListener('change',classificationDefaults);
  el('memory-category-filter').addEventListener('change',render);
  el('memory-purpose').addEventListener('change',()=>status('下次回答按所选用途筛选长期事实；已有聊天、附件和接续不会因此清除。'));
  el('memory-reload').addEventListener('click',async()=>{try{await load();status('列表已更新；编辑区输入保留。');}catch(error){status(error.message,true);}});
  el('memory-search').addEventListener('keydown',event=>{if(event.key==='Enter'){event.preventDefault();el('memory-reload').click();}});
  el('memory-form').addEventListener('submit',async event=>{
    event.preventDefault();if(working||!compatible||window.Workspace?.memoryContext?.().temporary)return;
    const document={title:el('memory-title').value.trim(),content:el('memory-content').value.trim(),project_id:el('memory-scope').value||null,providers:Array.from(el('memory-providers').querySelectorAll('input:checked'),i=>i.value)};
    const kind=el('memory-kind').value;
    if(kind){
      const uses=[];if(el('memory-use-personal').checked)uses.push('personal_chat');if(el('memory-use-work').checked)uses.push('work_assist');
      const raw=el('memory-expires').value,date=raw?new Date(raw):null;
      if(date&&!Number.isFinite(date.getTime())){status('到期时间无效，请重新填写。',true);return;}
      document.classification={kind,subject:kinds[kind][1],subject_label:el('memory-subject-label').value.trim(),uses:kind==='fiction'?[]:uses,expires_at:date?date.toISOString().replace('.000Z','Z'):null};
    }
    const encoded=JSON.stringify(document);
    if(!pending||pending.encoded!==encoded)pending={id:editing?.id||newId(),revision:editing?.revision||0,encoded};
    working=true;controls();status('正在保存…');
    try{const row=await api('/'+pending.id,{revision:pending.revision,document});editing=row;pending=null;await load();edit(row);status('已存入本机记忆，下次普通对话按范围使用。');}
    catch(error){status(error.message,true);}finally{working=false;controls();}
  });
  window.MemoryPanel={context,controls,isWorking:()=>working,
    mark(article,report){const refs=report?.references||[];if(refs.length)article.dataset.memoryRefs=JSON.stringify(refs);return refs;},
  };
})();
