"use strict";
(() => {
  const el=id=>document.getElementById(id),dialog=el('memory-dialog'),panel=el('continuity-panel');
  let selected=[],working=false,loading=false,generation=0;
  const state=()=>window.Workspace?.memoryContext?.()||{project_id:null,temporary:false};
  const status=(text,error=false)=>{el('continuity-status').textContent=text;el('continuity-status').dataset.error=String(error);};
  function controls(){
    const locked=working||loading||state().temporary;
    for(const control of panel.querySelectorAll('button,input'))control.disabled=locked;
    el('continuity-reload').disabled=working||loading;
    el('memory-close').disabled=working||Boolean(window.MemoryPanel?.isWorking());
    for(const tab of dialog.querySelectorAll('[data-memory-tab]'))tab.disabled=working||Boolean(window.MemoryPanel?.isWorking());
  }
  async function api(path,payload){
    const controller=new AbortController(),timer=setTimeout(()=>controller.abort(),10000);
    try{
      const response=await fetch('/api/continuity'+path,{method:payload===undefined?'GET':'POST',credentials:'omit',cache:'no-store',
        headers:{'X-Jarvis-Nonce':NONCE,...(payload===undefined?{}:{'Content-Type':'application/json'})},body:payload===undefined?undefined:JSON.stringify(payload),signal:controller.signal});
      const data=await response.json();if(!response.ok)throw new Error(data.user_message||'接续操作未完成。');return data;
    }catch(error){if(error.name==='AbortError')throw new Error('操作结果尚未确认；可原样重试或刷新核对。');throw error;}
    finally{clearTimeout(timer);}
  }
  function accept(receipt){
    if(receipt?.kind!=='continuity'||receipt.replayed)return;
    if(receipt.action==='resume')selected=[receipt.id];
    if(receipt.action==='forget')selected=selected.filter(id=>id!==receipt.id);
  }
  function workEditor(card,row){
    const box=document.createElement('div'),open=document.createElement('button'),content=document.createElement('div');
    box.className='continuity-work';open.type='button';open.textContent='关联任务与实际进展'+(row.document.work_refs?.length?' · '+row.document.work_refs.length:'');
    open.addEventListener('click',async()=>{
      if(working||loading||state().temporary)return;working=true;controls();status('正在核对关联记录…');
      try{
        const d=row.document,data=await api('/'+row.id+'/work'+(d.project_id?'?project_id='+d.project_id:''));
        if(data.revision!==row.revision){await load();status('接续已更新，请重新打开关联列表。');return;}
        content.replaceChildren();const note=document.createElement('p');note.textContent='最多关联三项。只读取实际状态，不会启动、重试或取消任务；模型使用时沿用此接续的云端许可。';content.append(note);
        const refs=new Map();for(const ref of [...(d.work_refs||[]),...data.choices])refs.set(ref.kind+':'+ref.id,ref);
        const inputs=[];
        for(const [key,ref] of refs){
          const label=document.createElement('label'),input=document.createElement('input'),link=document.createElement('a');input.type='checkbox';input.checked=(d.work_refs||[]).some(r=>r.kind===ref.kind&&r.id===ref.id);input.dataset.workId=ref.id;inputs.push({input,ref});
          const observation=data.observed.items.find(r=>r.kind===ref.kind&&r.id===ref.id);
          label.append(input,document.createTextNode((ref.kind==='task'?'任务 ':'成长单 ')+ref.id+(observation?' · '+observation.label:'')));
          link.href='/#chat='+ref.conversation_id;link.target='_blank';link.rel='noopener';link.textContent='打开来源会话 ↗';label.append(link);content.append(label);
        }
        if(!refs.size){const empty=document.createElement('p');empty.textContent='来源会话还没有可关联的任务或成长单。';content.append(empty);}
        const save=document.createElement('button');save.type='button';save.textContent='保存任务关联';let pending=null;
        save.addEventListener('click',async()=>{
          if(working||loading||state().temporary)return;
          const links=inputs.filter(x=>x.input.checked).map(x=>x.ref);if(links.length>3){status('每条接续最多关联三项。',true);return;}
          const encoded=JSON.stringify(links);if(!pending||pending.encoded!==encoded)pending={encoded,id:crypto.randomUUID().replaceAll('-','')};
          working=true;controls();
          try{await api('/'+row.id,{action:'link_work',revision:row.revision,project_id:d.project_id,request_id:pending.id,work_refs:links});await load();status('任务关联已保存；下一轮会核对实际进展，不会自动执行。');}
          catch(e){status(e.message,true);}finally{working=false;controls();}
        });content.append(save);status('已核对实际进展。状态改变后，下一轮会重新读取。');
      }catch(e){status(e.message,true);}finally{working=false;controls();}
    });box.append(open,content);card.append(box);
  }
  function render(rows){
    const list=el('continuity-list');list.replaceChildren();
    const absent=selected.filter(id=>!rows.some(row=>row.id===id));
    if(absent.length){const p=document.createElement('p'),clear=document.createElement('button');p.textContent='本会话有 '+absent.length+' 条接续已不可见。';clear.type='button';clear.textContent='取消不可用选择';clear.addEventListener('click',()=>{selected=selected.filter(id=>!absent.includes(id));window.Workspace?.remember();render(rows);});p.append(clear);list.append(p);}
    if(!rows.length){const p=document.createElement('p');p.textContent='当前范围还没有接续记录。用聊天指令保存进展后会出现在这里。';list.append(p);}
    for(const row of rows){
      const d=row.document,card=document.createElement('article'),title=document.createElement('strong'),body=document.createElement('p'),meta=document.createElement('small'),source=document.createElement('a'),label=document.createElement('label'),use=document.createElement('input'),providers=document.createElement('fieldset'),legend=document.createElement('legend'),actions=document.createElement('div');
      card.className='continuity-card';card.dataset.continuityId=row.id;title.textContent=d.title;
      body.textContent='进展：'+d.progress+'\n下一步：'+d.next_step;
      meta.textContent=(d.project_id?'当前项目':'普通会话')+' · '+(d.state==='open'?'待续':'主人标记完成')+' · 修订 '+row.revision;
      source.href='/#chat='+d.source.conversation_id;source.target='_blank';source.rel='noopener';source.textContent='查看原会话 · 第 '+(d.source.message_index+1)+' 条消息';
      use.type='checkbox';use.checked=selected.includes(row.id);use.dataset.continuitySelect='true';label.append(use,document.createTextNode('用于本会话'));
      use.addEventListener('change',()=>{if(use.checked&&selected.length>=3){use.checked=false;status('每个会话最多选择三条接续。',true);return;}selected=selected.filter(id=>id!==row.id);if(use.checked)selected.push(row.id);window.Workspace?.remember();status('选择已更新；下一轮按范围、来源和接入方许可使用。');});
      legend.textContent='允许的云端接入方（默认仅本地）';providers.append(legend);
      for(const id of [...new Set([...modelCatalog.map(m=>m.provider),...d.providers])].filter(p=>p!=='local')){
        const choice=document.createElement('label'),input=document.createElement('input');input.type='checkbox';input.value=id;input.checked=d.providers.includes(id);choice.append(input,document.createTextNode(names[id]||id));providers.append(choice);
      }
      actions.className='memory-card-actions';
      for(const [action,text] of [['permissions','保存许可'],[d.state==='open'?'close':'reopen',d.state==='open'?'标记完成':'重新打开'],['forget','忘记']]){
        const button=document.createElement('button');button.type='button';button.textContent=text;button.dataset.continuityAction=action;let pending=null;
        button.addEventListener('click',async()=>{
          if(working||state().temporary)return;
          if(action==='forget'&&button.dataset.confirm!=='true'){button.dataset.confirm='true';button.textContent='确认忘记';return;}
          const payload={action,revision:row.revision,project_id:d.project_id,...(action==='permissions'?{providers:Array.from(providers.querySelectorAll('input:checked'),i=>i.value)}:{})};
          const encoded=JSON.stringify(payload);if(!pending||pending.encoded!==encoded)pending={encoded,request_id:crypto.randomUUID().replaceAll('-','')};
          working=true;controls();status('正在处理…');
          try{const receipt=await api('/'+row.id,{...payload,request_id:pending.request_id});accept(receipt);window.Workspace?.remember();await load();status(action==='close'?'已标记完成；这不代表后台执行过工作。':action==='forget'?'已忘记；已有聊天和导出未删除。':'接续已更新。');}
          catch(error){status(error.message,true);}finally{working=false;controls();}
        });actions.append(button);
      }
      card.append(title,body,meta,source,label,providers,actions);workEditor(card,row);list.append(card);
    }controls();
  }
  async function load(){
    const current=++generation,project=state().project_id;loading=true;controls();
    try{const data=await api(project?'?project_id='+encodeURIComponent(project):'');if(current===generation)render(data.records);}
    finally{if(current===generation){loading=false;controls();}}
  }
  function tab(name){
    for(const button of dialog.querySelectorAll('[data-memory-tab]')){const on=button.dataset.memoryTab===name;button.setAttribute('aria-pressed',String(on));}
    el('memory-facts').hidden=name!=='facts';panel.hidden=name!=='continuity';el('persona-panel').hidden=name!=='persona';
    if(name==='persona')window.PersonaPanel?.open();
    if(name==='continuity'){status(state().temporary?'临时会话可查看列表，不使用或修改接续。':'最多选三条。普通会话和每个项目各有独立范围。');load().catch(e=>status(e.message,true));}
  }
  for(const button of dialog.querySelectorAll('[data-memory-tab]'))button.addEventListener('click',()=>tab(button.dataset.memoryTab));
  el('open-memory').addEventListener('click',()=>tab('facts'));
  el('continuity-reload').addEventListener('click',()=>load().then(()=>status('已刷新。')).catch(e=>status(e.message,true)));
  el('continuity-suggest').addEventListener('click',async()=>{
    if(working||loading||state().temporary)return;
    const q=el('continuity-query').value.trim();if(!q){status('先输入你想接着聊的话题。');return;}
    const query=new URLSearchParams({q,provider:chosenModel()?.provider||'local'});if(state().project_id)query.set('project_id',state().project_id);
    const current=++generation;loading=true;controls();status('正在核对相关话题与来源…');
    try{const data=await api('?'+query);if(current===generation){render(data.records);status(data.records.length?'这些是可用于当前模型的相关记录；选中后用于下一轮。':'没有符合当前范围、模型许可和有效来源的相关记录。');}}
    catch(error){if(current===generation)status(error.message,true);}finally{if(current===generation){loading=false;controls();}}
  });
  dialog.addEventListener('cancel',event=>{if(working)event.preventDefault();});
  window.Continuity={controls,isWorking:()=>working,accept,
    context:()=>({enabled:Boolean(window.MemoryPanel?.context().enabled)&&!state().temporary,ids:[...selected]}),
    snapshot:()=>[...selected],restore:ids=>{selected=Array.isArray(ids)?[...ids]:[];},clear:()=>{selected=[];loading=false;generation++;},
    mark(article,report){const refs=report?.references||[];if(refs.length)article.dataset.continuityRefs=JSON.stringify(refs);return refs;},
  };
})();
