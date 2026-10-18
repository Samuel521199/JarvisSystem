"use strict";
(() => {
  const el=id=>document.getElementById(id),dialog=el('knowledge-dialog'),preview=el('knowledge-excerpt-dialog');
  let rows=[],editing=null,pending=null,working=false,generation=0;
  const state=()=>window.Workspace?.memoryContext?.()||{project_id:null,temporary:false};
  let scopeKey=null,extraProjects=[];
  function projectIds(){
    const s=state(),key=(window.Workspace?.currentConversation?.().id||'')+':'+s.project_id+':'+s.temporary;
    if(key!==scopeKey){scopeKey=key;extraProjects=[];}
    return s.temporary?[]:[...new Set([...(s.project_id?[s.project_id]:[]),...extraProjects])];
  }
  const context=()=>({enabled:el('knowledge-enabled').checked&&!state().temporary&&Boolean(state().project_id),project_id:state().project_id,...(!state().temporary?{project_ids:projectIds()}:{})});
  const status=(text,error=false)=>{el('knowledge-status').textContent=text;el('knowledge-status').dataset.error=String(error);};
  async function api(path,payload){
    const controller=new AbortController(),timer=setTimeout(()=>controller.abort(),12000);
    try{
      const response=await fetch('/api/knowledge'+path,{method:payload===undefined?'GET':'POST',credentials:'omit',cache:'no-store',headers:{'X-Jarvis-Nonce':NONCE,...(payload===undefined?{}:{'Content-Type':'application/json'})},body:payload===undefined?undefined:JSON.stringify(payload),signal:controller.signal});
      const data=await response.json();if(!response.ok)throw new Error(data.user_message||'项目资料操作未完成。');return data;
    }catch(error){if(error.name==='AbortError')throw new Error('操作结果未确认，输入保留；可刷新检查或用同一登记重试。');throw error;}
    finally{clearTimeout(timer);}
  }
  function controls(){
    const s=state(),blocked=busy||Boolean(window.Workspace?.isBusy());
    el('open-knowledge').hidden=!s.project_id;el('open-knowledge').disabled=blocked;
    const selected=projectIds(),hint='AI 资料范围 · '+(s.temporary?'临时会话不检索项目资料':'本会话查询 '+selected.length+' 个项目');el('knowledge-tooltip').textContent=hint;el('open-knowledge').setAttribute('aria-label',hint);
    for(const input of dialog.querySelectorAll('input,button'))input.disabled=working;
    el('knowledge-save').disabled=working||s.temporary||!s.project_id;
    el('knowledge-enabled').disabled=working||s.temporary;
    el('knowledge-path').disabled=working||Boolean(editing);
    for(const button of dialog.querySelectorAll('[data-source-mutate]'))button.disabled=working||s.temporary;
    for(const input of el('knowledge-projects').querySelectorAll('input'))input.disabled=working||s.temporary||input.value===s.project_id||(!input.checked&&selected.length>=4);
  }
  async function loadProjects(){
    const key=scopeKey;
    const response=await fetch('/api/workspace/projects',{credentials:'omit',cache:'no-store',headers:{'X-Jarvis-Nonce':NONCE}});
    const result=await response.json();if(!response.ok)throw new Error(result.user_message||'未能读取项目目录。');
    projectIds();if(key!==scopeKey)return;
    el('knowledge-projects').replaceChildren();
    for(const project of result.projects){
      const label=document.createElement('label'),input=document.createElement('input');input.type='checkbox';input.value=project.id;input.checked=projectIds().includes(project.id);
      label.append(input,document.createTextNode(project.name+(project.id===state().project_id?'（当前项目）':'')));label.title=project.path;
      input.onchange=()=>{extraProjects=Array.from(el('knowledge-projects').querySelectorAll('input:checked'),i=>i.value).filter(id=>id!==state().project_id);controls();el('knowledge-results').replaceChildren();status('查询范围已更新，下次提问生效；没有更改永久分享权限。');};el('knowledge-projects').append(label);
    }controls();
  }
  function edit(row=null){
    editing=row;pending=null;el('knowledge-path').value=row?.document.path||'';
    el('knowledge-editor-title').textContent=row?'修改使用范围':'纳入项目资料';
    el('knowledge-save').textContent=row?'保存设置':'纳入资料';el('knowledge-providers').replaceChildren();
    const selected=row?.document.providers||[];
    for(const id of [...new Set([...modelCatalog.map(m=>m.provider),...selected])].filter(id=>id!=='local')){
      const label=document.createElement('label'),input=document.createElement('input');input.type='checkbox';input.value=id;input.checked=selected.includes(id);label.append(input,document.createTextNode(names[id]||id));el('knowledge-providers').append(label);
    }
    controls();
  }
  async function load(){
    const stamp=++generation,id=state().project_id;const data=await api('?project_id='+encodeURIComponent(id));
    if(stamp!==generation||id!==state().project_id)return;
    rows=data.sources;el('knowledge-list').replaceChildren();
    if(!rows.length)el('knowledge-list').textContent='尚未纳入资料。打开文件夹不会自动扫描内容。';
    for(const row of rows){
      const card=document.createElement('article'),title=document.createElement('strong'),meta=document.createElement('small'),change=document.createElement('button'),remove=document.createElement('button');
      card.className='knowledge-source';title.textContent=row.document.path;meta.textContent='登记修订 '+row.revision+' · '+(row.document.providers.length?'本地、'+row.document.providers.map(p=>names[p]||p).join('、'):'仅本地模型');
      change.type=remove.type='button';change.textContent='使用范围';remove.textContent='撤出';change.dataset.sourceMutate=remove.dataset.sourceMutate='true';
      change.onclick=()=>{edit(row);status('可以修改允许处理此文件的接入方。');};
      remove.onclick=async()=>{if(working)return;working=true;controls();try{await api('/'+row.id+'/delete',{revision:row.revision});if(editing?.id===row.id)edit();await load();status('已撤出资料，原文件未改动。');}catch(error){status(error.message,true);}finally{working=false;controls();}};
      card.append(title,meta,change,remove);el('knowledge-list').append(card);
    }
    controls();
  }
  async function read(citation){
    preview.showModal();el('knowledge-excerpt-title').textContent=citation.path+' · '+citation.start_line+'–'+citation.end_line+' 行';el('knowledge-excerpt').textContent='正在核对来源…';
    try{const result=await api('/read',{project_id:citation.project_id||state().project_id,reference:citation.reference,start_line:citation.start_line,end_line:citation.end_line});el('knowledge-excerpt').textContent=result.text;}
    catch(error){el('knowledge-excerpt').textContent=error.message;}
  }
  function citations(container,items){
    if(!items?.length)return;const group=document.createElement('div');group.className='knowledge-citations';
    const caption=document.createElement('span');caption.textContent='本轮提供的来源：';group.append(caption);
    for(const item of items){const button=document.createElement('button');button.type='button';button.textContent='['+item.label+'] '+(item.project_name?item.project_name+' / ':'')+item.path+':'+item.start_line+'–'+item.end_line;button.title=item.title||item.path;button.onclick=()=>read(item);group.append(button);}
    container.append(group);
  }
  el('open-knowledge').onclick=async()=>{if(busy||!state().project_id)return;dialog.showModal();edit();el('knowledge-results').replaceChildren();status('正在读取登记…');try{await load();await loadProjects();status(state().temporary?'临时会话不使用或修改项目资料登记。':'只读取明确登记的文件；每次检索重新核对内容。');}catch(error){status(error.message,true);}};
  el('knowledge-close').onclick=()=>{if(!working)dialog.close();};dialog.addEventListener('cancel',event=>{if(working)event.preventDefault();});
  el('knowledge-excerpt-close').onclick=()=>preview.close();
  el('knowledge-new').onclick=()=>{edit();status('填写当前项目内的相对路径。');};
  el('knowledge-reload').onclick=async()=>{try{await load();status('登记已刷新，编辑内容保留。');}catch(error){status(error.message,true);}};
  el('knowledge-form').onsubmit=async event=>{
    event.preventDefault();if(working||state().temporary)return;
    const document={project_id:state().project_id,path:el('knowledge-path').value.trim(),providers:Array.from(el('knowledge-providers').querySelectorAll('input:checked'),input=>input.value)},encoded=JSON.stringify(document);
    if(!pending||pending.encoded!==encoded)pending={id:editing?.id||crypto.randomUUID().replaceAll('-',''),revision:editing?.revision||0,encoded};
    working=true;controls();try{const row=await api('/'+pending.id,{revision:pending.revision,document});editing=row;pending=null;await load();edit(row);status('资料已纳入，下次提问按项目和接入方检索。');}catch(error){status(error.message,true);}finally{working=false;controls();}
  };
  el('knowledge-search-form').onsubmit=async event=>{
    event.preventDefault();if(working)return;working=true;controls();el('knowledge-results').replaceChildren();status('正在检索当前文件…');
    try{const result=await api('/view',{project_id:state().project_id,project_ids:state().temporary?[state().project_id]:projectIds(),query:el('knowledge-query').value.trim(),memory_enabled:window.MemoryPanel?.context().enabled||false});
      for(const fact of result.facts){const card=document.createElement('article'),title=document.createElement('strong'),body=document.createElement('p');card.className='knowledge-source';title.textContent=(fact.project_name||'')+' / '+fact.document.title+' · 修订 '+fact.revision;body.textContent=fact.document.content;card.append(title,body);el('knowledge-results').append(card);}
      citations(el('knowledge-results'),result.knowledge.citations);
      const missing=result.view.coverage.filter(p=>p.status!=='matched').length;
      status('本机联合预览：'+result.facts.length+' 条记忆、'+result.knowledge.citations.length+' 段资料。'+(missing?missing+' 个项目没有完整的匹配摘录。':'')+'实际发送时会按模型权限和预算重新筛选。'+(result.knowledge.issues.length?'部分资料不可用或超出读取预算：'+result.knowledge.issues.map(i=>i.path+' ('+i.code+')').join('；'):''));
    }catch(error){status(error.message,true);}finally{working=false;controls();}
  };
  window.ProjectKnowledge={context,controls,projectIds,
    mark(article,report){const refs=report?.references||[],items=report?.citations||[];if(refs.length)article.dataset.knowledgeRefs=JSON.stringify(refs);if(items.length)article.dataset.knowledgeCitations=JSON.stringify(items);citations(article,items);return refs;},
    restore(article,row){if(row.knowledge_refs?.length)article.dataset.knowledgeRefs=JSON.stringify(row.knowledge_refs);if(row.knowledge_citations?.length)article.dataset.knowledgeCitations=JSON.stringify(row.knowledge_citations);citations(article,row.knowledge_citations);}
  };
})();
