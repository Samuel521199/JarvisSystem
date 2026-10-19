"use strict";
(() => {
  const el=id=>document.getElementById(id);
  let projects=[],project=null,operationBusy=true,activeId=crypto.randomUUID().replaceAll("-",""),sessions=new Map(),saving=null,temporary=false,archiveWarning="";
  const stateNames={PREPARED:"等待文件内容",SAVED:"已保存",FAILED:"保存失败",UNKNOWN:"结果待核对"};
  const newId=()=>crypto.randomUUID().replaceAll("-","");
  const collapsed=new Set();
  try{const saved=JSON.parse(localStorage.getItem("jarvis.sidebar.collapsed.v1")||"[]");if(Array.isArray(saved))for(const id of saved)if(typeof id==="string")collapsed.add(id);}catch{}
  function saveCollapsed(){try{localStorage.setItem("jarvis.sidebar.collapsed.v1",JSON.stringify([...collapsed]));}catch{}}
  function revealCurrent(){collapsed.delete(project?.id||"general");saveCollapsed();}
  function icon(path){const svg=document.createElementNS("http://www.w3.org/2000/svg","svg"),shape=document.createElementNS("http://www.w3.org/2000/svg","path");svg.setAttribute("class","icon");svg.setAttribute("viewBox","0 0 24 24");svg.setAttribute("aria-hidden","true");shape.setAttribute("d",path);svg.append(shape);return svg;}
  function sidebarState(){
    const current=el("current-chat"),title=el("session-title").textContent;
    current.classList.toggle("is-running",busy);current.classList.toggle("is-temporary",temporary);
    current.classList.toggle("save-failed",sessions.get(activeId)?.archiveState==="failed");
    current.title=title+(busy?" · 正在回复":temporary?" · 临时会话":"")+(sessions.get(activeId)?.archiveState==="failed"?" · 保存失败":"");
    current.setAttribute("aria-label",current.title);current.dataset.sessionId=activeId;
  }
  async function api(path,payload,timeout=20000){
    const controller=new AbortController(),timer=setTimeout(()=>controller.abort(),timeout);
    try{
      const response=await fetch(path,{method:payload===undefined?"GET":"POST",credentials:"omit",cache:"no-store",headers:{"X-Jarvis-Nonce":NONCE,...(payload===undefined?{}:{"Content-Type":"application/json"})},body:payload===undefined?undefined:JSON.stringify(payload),signal:controller.signal});
      const result=await response.json();
      if(!response.ok)throw new Error(result.user_message||"项目操作未完成。");
      return result;
    }catch(error){if(error.name==="AbortError")throw new Error("等待超时，结果尚未确定。请检查保存记录，不要更换请求重复保存。");throw error;}
    finally{clearTimeout(timer);}
  }
  function controls(){
    const locked=busy||Boolean(window.Dialogue?.hasPending())||operationBusy||Boolean(window.ProjectMenu?.isBusy());
    for(const id of ["open-project","context-project","no-project","file-mode","output-path","project-open","project-pick","project-create"]){el(id).disabled=locked;}
    for(const button of document.querySelectorAll(".project-new-chat,.project-more,.session-row:not(#current-chat)"))button.disabled=locked;
    sidebarState();
    el("file-options").hidden=!project;
    el("file-options-label").textContent=el("file-mode").checked?"文件输出 · 开":"文件输出";
    for(const id of ["conversation-delete","conversation-temporary","conversation-retry"])el(id).disabled=locked;
    window.ProjectKnowledge?.controls();
    window.ProjectExplorer?.controls();
    el("output-location").hidden=!el("file-mode").checked;
    el("file-mode").disabled=locked||!project;
  }
  function busyOperation(value){operationBusy=value;setControls();controls();}
  function render(){
    el("context-project").textContent=project?project.name+" · "+project.path:"选择项目文件夹";
    el("context-project").title=project?"项目根目录："+project.path:"打开文件夹作为项目根目录";
    el('context-project').setAttribute('aria-haspopup',project?'menu':'dialog');el('context-project').setAttribute('aria-controls',project?'project-menu':'project-dialog');
    el("project-root-note").textContent=project?"默认保存到 "+project.path+"；可在输出位置填写相对路径或明确的绝对路径。":"选择项目后可导出文件；会话归档独立保存。";
    el("no-project").hidden=!project;
    // Move the existing active button so its listeners and live title stay intact.
    const current=el("current-chat"),focus=document.activeElement,focusSession=focus?.dataset.sessionId,focusProject=focus?.dataset.projectId;
    current.hidden=false;
    el("project-list").replaceChildren();el("session-list").replaceChildren();
    if(!projects.length){const p=document.createElement("p");p.className="project-empty";p.textContent="打开文件夹，开始一个项目";el("project-list").append(p);}
    const rows=[...sessions].reverse();
    // Also show a new empty conversation before it has anything to archive.
    if(!sessions.has(activeId))rows.unshift([activeId,{project,title:current.querySelector(".session-name").textContent}]);
    function group(p,host){
      const key=p?.id||"general",items=rows.filter(([id,s])=>(id===activeId?project?.id:s.project?.id)===(p?.id)&&(id===activeId||!window.ProjectMenu?.isArchived(id)));
      if(!p&&!items.length){host.hidden=true;return;}host.hidden=false;
      const section=document.createElement("section"),header=document.createElement("div"),toggle=document.createElement("button"),name=document.createElement("span"),add=document.createElement("button"),list=document.createElement("div");
      section.className="project-group";section.setAttribute("aria-label",p?.name||"独立会话");header.className="project-heading";
      toggle.type="button";toggle.className="project-toggle";toggle.dataset.projectId=key;toggle.title=p?"项目根目录："+p.path:"未绑定项目文件夹的会话";
      toggle.setAttribute("aria-expanded",String(!collapsed.has(key)));toggle.setAttribute("aria-controls","project-chats-"+key);
      toggle.append(icon(p?"M3 7V5a2 2 0 0 1 2-2h5l3 3h6a2 2 0 0 1 2 2v2M3 7h16a2 2 0 0 1 2 2l-2 10H4L2 9a2 2 0 0 1 1-2Z":"M4 4h16v13H9l-5 4V4Z"));
      name.className="project-name";name.textContent=p?p.name+(p.available?"":" · 不可用"):"独立会话";toggle.append(name,icon("m9 6 6 6-6 6"));
      if(p&&window.ProjectMenu?.profile(p).pinned){const pin=icon('m9 3 6 0-1 6 4 4H6l4-4-1-6M12 13v8');pin.classList.add('project-pin');pin.setAttribute('aria-hidden','true');toggle.append(pin);}
      add.type="button";add.className="project-new-chat icon-button";add.dataset.projectId=key;add.title=p?"在 "+p.name+" 中新建对话":"新建独立对话";add.setAttribute("aria-label",add.title);add.append(icon("M12 5v14M5 12h14"));add.addEventListener("click",()=>newSession(p));
      list.className="project-conversations";list.id="project-chats-"+key;list.hidden=collapsed.has(key);
      toggle.addEventListener("click",()=>{list.hidden=!list.hidden;toggle.setAttribute("aria-expanded",String(!list.hidden));list.hidden?collapsed.add(key):collapsed.delete(key);saveCollapsed();});
      for(const [id,s] of items){
        if(id===activeId){list.append(current);continue;}
        const button=document.createElement("button"),label=document.createElement("span"),indicator=document.createElement("span");
        button.type="button";button.className="session-row";button.dataset.sessionId=id;button.title=s.title+(s.temporary?" · 临时会话":"")+(s.archiveState==="failed"?" · 保存失败":"");button.setAttribute("aria-label",button.title);
        button.classList.toggle("is-temporary",Boolean(s.temporary));button.classList.toggle("save-failed",s.archiveState==="failed");
        label.className="session-name";label.textContent=s.title;indicator.className="session-indicator";indicator.setAttribute("aria-hidden","true");button.append(label,indicator);button.addEventListener("click",()=>restore(id));list.append(button);
      }
      if(!items.length){const empty=document.createElement("p");empty.className="project-empty";empty.textContent="暂无会话";list.append(empty);}
      header.append(toggle);if(p){const more=document.createElement('button');more.type='button';more.className='project-more';more.dataset.projectId=p.id;more.textContent='…';more.setAttribute('aria-label',p.name+' · 项目操作');more.setAttribute('aria-haspopup','menu');more.setAttribute('aria-expanded','false');more.setAttribute('aria-controls','project-menu');more.title='项目详情与操作';more.onclick=()=>window.ProjectMenu.show(p,more);header.addEventListener('contextmenu',event=>{event.preventDefault();window.ProjectMenu.show(p,more);});header.append(more);}
      header.append(add);section.append(header,list);if(p&&window.ProjectMenu?.archiveCount(p)){const archive=document.createElement('button');archive.type='button';archive.className='project-archive-entry';archive.textContent='已归档聊天 · '+ProjectMenu.archiveCount(p);archive.onclick=()=>ProjectMenu.showArchives(p);list.append(archive);}host.append(section);
    }
    const visible=projects.filter(p=>!window.ProjectMenu?.profile(p).removed),pinned=visible.filter(p=>window.ProjectMenu?.profile(p).pinned),normal=visible.filter(p=>!window.ProjectMenu?.profile(p).pinned),host=el('project-list');
    function sectionLabel(text){const label=document.createElement('p');label.className='project-section-label';label.textContent=text;host.append(label);}
    if(pinned.length){sectionLabel('置顶');for(const p of pinned)group(p,host);}
    const sectionNames=[...new Set(normal.map(p=>window.ProjectMenu?.profile(p).section||''))];
    for(const name of sectionNames){if(name||pinned.length||sectionNames.length>1)sectionLabel(name||'未分区');for(const p of normal.filter(p=>(window.ProjectMenu?.profile(p).section||'')===name))group(p,host);}
    const removed=projects.length-visible.length;if(removed){const button=document.createElement('button');button.type='button';button.className='project-recovery-entry';button.textContent='已移除项目 · '+removed;button.onclick=()=>ProjectMenu.showRemoved();host.append(button);}group(null,el("session-list"));
    // Keep the active control addressable while a removed project is detached.
    if(!current.isConnected){current.hidden=true;el('session-list').append(current);}
    controls();archiveStatus();
    window.ConversationTasks?.sessionChanged();window.ConversationGrowth?.sessionChanged();window.Dialogue?.sessionChanged();
    // Autosave may rebuild the list; keep keyboard navigation on the same row.
    if(focusSession)document.querySelector('[data-session-id="'+focusSession+'"]')?.focus({preventScroll:true});
    else if(focusProject)document.querySelector('.'+(focus.classList.contains("project-new-chat")?"project-new-chat":focus.classList.contains('project-more')?'project-more':"project-toggle")+'[data-project-id="'+focusProject+'"]')?.focus({preventScroll:true});
  }
  function snapshot(){
    if(!history.length&&!el("message").value.trim()&&!el("messages").querySelector(".message")&&!Attachments.hasDraft()&&!window.SessionContext?.wire())return;
    sessions.set(activeId,{project,nodes:Array.from(el("messages").childNodes),history:history.map(x=>({...x})),draft:el("message").value,attachments:Attachments.snapshot(),context:window.SessionContext?.snapshot(),continuity:window.Continuity?.snapshot()||[],title:el("session-title").textContent,mode:el("file-mode").checked,path:el("output-path").value,temporary,archiveState:sessions.get(activeId)?.archiveState,archiveError:sessions.get(activeId)?.archiveError,archiveJSON:sessions.get(activeId)?.archiveJSON});
  }
  function archiveStatus(){
    const s=sessions.get(activeId),state=s?.archiveState;
    const label=temporary?"临时会话":state==="saving"?"保存中…":state==="failed"?"保存失败":state==="saved"?"已存本机":"自动保存";
    el("archive-tooltip").textContent=label+" · 会话管理";el("conversation-status").setAttribute("aria-label",label+" · 会话管理");el("conversation-status").dataset.state=temporary?"temporary":state||"auto";
    el("conversation-status").classList.toggle("archive-error",state==="failed"||Boolean(archiveWarning));
    el("conversation-note").textContent=temporary?"此会话只在当前页面保留，刷新或关闭后消失。":s?.archiveError||archiveWarning||(state==="saved"?"聊天文字已保存在本机，刷新后可从左侧继续。":"发送后自动保存聊天文字，无需逐条点击保存。");
    el("conversation-retry").hidden=state!=="failed";
    el("conversation-delete").disabled=busy||Boolean(window.Dialogue?.hasPending())||operationBusy||!s;
    sidebarState();
  }
  function remember(force=false){
    snapshot();const id=activeId,s=sessions.get(id);if(!s||s.temporary)return;
    const messages=Conversations.capture();if(!messages.length)return;
    const document={title:s.title,project_id:s.project?.id||null,messages,context_note:window.SessionContext?.wire()||"",continuity_ids:window.Continuity?.snapshot()||[]},encoded=JSON.stringify(document);
    if(!force&&encoded===s.archiveJSON)return;
    s.archiveJSON=encoded;s.archiveState="saving";s.archiveError="";locationForProject();render();
    Conversations.save(id,document).then(()=>{s.archiveState="saved";s.archiveError="";archiveWarning="";}).catch(error=>{s.archiveState="failed";s.archiveError=error.message;}).finally(()=>{const current=sessions.get(id);if(current&&current.archiveJSON===encoded){current.archiveState=s.archiveState;current.archiveError=s.archiveError;}if(id===activeId)archiveStatus();else if(current?.archiveJSON===encoded&&current.archiveState==="failed"){render();notify("会话“"+current.title+"”保存失败："+current.archiveError);}});
  }
  function locationForProject(){window.history.replaceState(null,"",sessions.has(activeId)&&!temporary?"#chat="+activeId:project?"#project="+project.id:location.pathname);}
  function newSession(next=project,isTemporary=false){
    if(busy||Boolean(window.Dialogue?.hasPending())||operationBusy)return;
    remember();activeId=newId();project=next;temporary=isTemporary;resetConversation();el("file-mode").checked=false;el("output-path").value="";el("file-options").open=false;
    revealCurrent();locationForProject();render();el("current-chat").click();
    const heading=el("welcome")?.querySelector("h2");if(heading&&project)heading.textContent="在 "+project.name+" 中做点什么？";
  }
  async function restore(id){
    if(busy||Boolean(window.Dialogue?.hasPending())||operationBusy||id===activeId)return;
    remember();let s=sessions.get(id);if(!s)return;
    busyOperation(true);
    try{
      if(!s.nodes){
        const doc=await Conversations.load(id);project=projects.find(p=>p.id===doc.project_id)||null;resetConversation();
        let pending=null,lastInput=null;history=[];
        for(const row of doc.messages){
          const article=addMessage(row.role,row.content,row.meta,row.short_meta);if(row.reply_ref)article.dataset.replyRef=row.reply_ref;
          if(row.personal_control){article.dataset.personalControl='true';if(row.growth_ref)article.dataset.growthRef=row.growth_ref;if(row.growth_request_id)article.dataset.growthRequestId=row.growth_request_id;pending=null;continue;}
          if(row.task_control){article.dataset.taskControl='true';if(row.task_ref)article.dataset.taskRef=row.task_ref;if(row.task_request_id)article.dataset.taskRequestId=row.task_request_id;pending=null;continue;}
          window.ProjectKnowledge?.restore(article,row);
          if(row.continuity_refs?.length)article.dataset.continuityRefs=JSON.stringify(row.continuity_refs);
          if(row.memory_refs?.length)article.dataset.memoryRefs=JSON.stringify(row.memory_refs);
          if(row.attachments_omitted){article.dataset.attachmentsOmitted="true";const note=document.createElement("p");note.className="meta";note.textContent="此消息的附件未归档；需要时请重新添加。";article.append(note);}
          if(row.incomplete){article.classList.add("incomplete");const note=document.createElement("p");note.className="meta";note.textContent="这条回答未完整结束。";article.append(note);}
          if(row.role==="assistant")attachAnswer(article,row.content,{project});
          if(row.role==="user"){pending=row;lastInput=row;}
          else if(row.role==="assistant"){if(row.reply_ref)pending=lastInput?.reply_ref===row.reply_ref?lastInput:null;if(pending&&!pending.attachments_omitted&&!row.incomplete)history.push({role:"user",content:pending.content},{role:"assistant",content:row.content,_memory_refs:row.memory_refs||[],_knowledge_refs:row.knowledge_refs||[],_continuity_refs:row.continuity_refs||[]});pending=null;}
          else pending=null;
        }
        trimHistory();window.SessionContext?.restore({note:doc.context_note});window.Continuity?.restore(doc.continuity_ids||[]);
        s={...s,project,nodes:Array.from(el("messages").childNodes),history:history.map(x=>({...x})),draft:"",attachments:[],context:window.SessionContext?.snapshot(),continuity:window.Continuity?.snapshot()||[],title:doc.title,mode:false,path:"",archiveState:"saved"};sessions.set(id,s);
      }
      activeId=id;temporary=Boolean(s.temporary);project=s.project;history=s.history.map(x=>({...x}));el("messages").replaceChildren(...s.nodes);el("message").value=s.draft;Attachments.restore(s.attachments);window.SessionContext?.restore(s.context);window.Continuity?.restore(s.continuity||[]);el("session-title").textContent=s.title;el("file-mode").checked=s.mode;el("output-path").value=s.path;el("file-options").open=false;notify("");providerHint();revealCurrent();locationForProject();render();el("current-chat").click();
    }catch(error){notify(error.message);}finally{busyOperation(false);archiveStatus();window.Dialogue?.sessionChanged();}
  }
  async function deleteConversation(){
    if(busy||Boolean(window.Dialogue?.hasPending())||operationBusy)return;const id=activeId;busyOperation(true);
    try{if(!temporary)await Conversations.remove(id);sessions.delete(id);activeId=newId();temporary=false;resetConversation();el("file-mode").checked=false;el("output-path").value="";locationForProject();render();el("conversation-menu").open=false;}
    catch(error){notify(error.message);}finally{busyOperation(false);archiveStatus();}
  }
  async function refreshProjects(){const data=await api("/api/workspace/projects");projects=data.projects.map(p=>window.ProjectMenu?.decorate(p)||p);render();}
  let preparedProject=null;
  function prepareProject(path,text,game){preparedProject={text,game};openDialog(true);el("folder-path").value=path||"";}
  function openDialog(fromRequest=false){if(fromRequest!==true)preparedProject=null;if(busy||Boolean(window.Dialogue?.hasPending())||operationBusy)return;el("project-error").textContent="";el("folder-path").value=project?.path||"";el("project-dialog").showModal();el("folder-path").focus();}
  async function openProject(usePicker,create=false){
    if(busy||Boolean(window.Dialogue?.hasPending())||operationBusy)return;el("project-error").textContent="";busyOperation(true);
    let chosen=null,engineering=null;
    try{
      if(usePicker){const result=await api("/api/workspace/pick-folder",{},125000);if(!result.cancelled)chosen=result.project;}
      else {const path=el("folder-path").value.trim();if(path.endsWith(".jarvis-workspace")){engineering=await api("/api/project-files/open-project",{path});chosen=engineering.project;}else chosen=await api(create?"/api/workspace/create-project":"/api/workspace/projects",{path});}
      if(chosen){await window.ProjectMenu?.reopen(chosen);chosen=window.ProjectMenu?.decorate(chosen)||chosen;await refreshProjects();el("project-dialog").close();}
    }catch(error){el("project-error").textContent=error.message;}
    finally{busyOperation(false);}
    if(chosen&&!el('project-error').textContent){newSession(chosen);const prepared=preparedProject;preparedProject=null;if(prepared){el("message").value=prepared.text;if(prepared.game)window.Creation?.prepareGame(prepared.text);notify("项目已打开，原需求已保留；核对当前任务范围后发送。");}if(engineering)await window.ProjectExplorer?.restoreProject(engineering);else window.ProjectExplorer?.show(true);}
  }
  async function beforeSend(){
    if(operationBusy)throw new Error("请先完成当前项目操作。");
    const context={project:project?{...project}:null,ticket:null};
    if(!el("file-mode").checked)return context;
    if(!project)throw new Error("请先打开项目文件夹。");
    context.ticket=await api("/api/workspace/outputs/prepare",{project_id:project.id,request_id:newId(),path:el("output-path").value.trim()});
    return context;
  }
  async function saveContent(ticket,content){return api("/api/workspace/outputs/"+ticket.request_id,{content});}
  function receiptText(receipt){return (stateNames[receipt.status]||receipt.status)+" · "+receipt.path+(receipt.size_bytes===null?"":" · "+receipt.size_bytes+" 字节");}
  function attachAnswer(article,text,context){
    const actions=document.createElement("div"),menu=document.createElement("details"),summary=document.createElement("summary"),items=document.createElement("div"),copy=document.createElement("button"),button=document.createElement("button"),note=document.createElement("div");actions.className="file-actions";menu.className="answer-menu";summary.textContent="···";summary.setAttribute("aria-label","回答操作");items.className="answer-menu-body";copy.type="button";copy.textContent="复制回答";copy.addEventListener("click",async()=>{try{await navigator.clipboard.writeText(text);menu.open=false;}catch{notify("未能复制，请选择正文手动复制。");}});note.className="file-receipt";note.setAttribute("role","status");button.type="button";button.textContent="导出为文件…";items.append(copy);if(context?.project)items.append(button);menu.append(summary,items);actions.append(menu,note);article.append(actions);
    const answer={text,project:context?.project||null,ticket:context?.ticket||null,note,button,saved:false};
    button.addEventListener("click",()=>{
      menu.open=false;
      if(busy||Boolean(window.Dialogue?.hasPending())||operationBusy)return;
      if(!answer.project){notify("此回答未绑定项目。请打开文件夹，在项目会话中生成并保存文件。");return;}
      saving=answer;el("save-project").textContent="项目根目录："+answer.project.path;el("save-path").value=answer.ticket?.path||"";el("save-path").disabled=Boolean(answer.ticket);el("save-note").textContent=answer.ticket?"重试会使用原请求和原路径；不会覆盖已有文件。":"留空时生成文件名并保存在项目根目录。也可以明确输入其他位置。";el("save-error").textContent="";el("save-dialog").showModal();el("save-confirm").focus();
      el("save-new").hidden=!answer.ticket;
    });
    return answer;
  }
  async function saveAnswer(answer){
    if(!answer.ticket)throw new Error("尚未选择保存位置。");
    answer.button.disabled=true;answer.note.textContent="正在保存到 "+answer.ticket.path;
    try{
      const receipt=await saveContent(answer.ticket,answer.text);answer.saved=true;answer.note.textContent=receiptText(receipt);answer.button.textContent="复制文件路径";
      const replacement=answer.button.cloneNode(true);replacement.disabled=false;answer.button.replaceWith(replacement);answer.button=replacement;
      replacement.addEventListener("click",async()=>{try{await navigator.clipboard.writeText(receipt.path);answer.note.textContent="已复制路径 · "+receipt.path;}catch{answer.note.textContent="请复制路径："+receipt.path;}});
      return receipt;
    }catch(error){answer.note.textContent=error.message+"\n目标："+answer.ticket.path;answer.button.textContent="检查并重试保存…";throw error;}
    finally{answer.button.disabled=false;}
  }
  async function confirmSave(){
    if(!saving||operationBusy)return;busyOperation(true);el("save-confirm").disabled=true;
    try{
      if(!saving.ticket)saving.ticket=await api("/api/workspace/outputs/prepare",{project_id:saving.project.id,request_id:newId(),path:el("save-path").value.trim()});
      await saveAnswer(saving);el("save-dialog").close();
    }catch(error){el("save-error").textContent=error.message;el("save-path").disabled=Boolean(saving.ticket);}
    finally{busyOperation(false);el("save-confirm").disabled=false;el("save-new").hidden=!saving.ticket;}
  }
  async function showOutputs(){
    el("exports-dialog").showModal();el("export-list").textContent="正在读取…";
    try{const data=await api("/api/workspace/outputs");el("export-list").replaceChildren();
      for(const row of data.outputs.filter(x=>!project||x.project_id===project.id)){const div=document.createElement("div"),title=document.createElement("strong"),path=document.createElement("span");div.className="export-row";title.textContent=(stateNames[row.status]||row.status)+" · "+new Date(row.created_at).toLocaleString();path.textContent=row.path;div.append(title,path);el("export-list").append(div);}
      if(!el("export-list").childNodes.length)el("export-list").textContent="还没有保存记录。";
    }catch(error){el("export-list").textContent=error.message;}
  }
  window.Workspace={currentConversation:()=>({id:activeId,temporary}),currentProject:()=>project,memoryContext:()=>({project_id:project?.id||null,temporary}),controls,isBusy:()=>operationBusy||Boolean(window.ProjectMenu?.isBusy()),newSession,prepareProject,beforeSend,attachAnswer,saveAnswer,remember,
    allProjects:()=>projects,projectSessions:id=>{const rows=[...sessions].filter(([_,s])=>s.project?.id===id).map(([key,s])=>({id:key,...s}));if(project?.id===id&&!sessions.has(activeId))rows.push({id:activeId,title:el('session-title').textContent});return rows;},
    async flushConversation(){remember();await Conversations.flush();if(sessions.get(activeId)?.archiveState==='failed')throw new Error('当前聊天尚未保存成功，请先重试保存，再归档；页面内容已保留。');},
    afterProjectArchive(p){if(project?.id===p.id)newSession(p);},afterProjectRemoved(p){if(project?.id===p.id)newSession(null);},
    projectOrganizationChanged(){projects=projects.map(p=>ProjectMenu.decorate(p));const byId=new Map(projects.map(p=>[p.id,p]));if(project)project=byId.get(project.id)||project;for(const s of sessions.values())if(s.project)s.project=byId.get(s.project.id)||s.project;render();},
    fileContent:text=>{const match=text.match(/^\s*```[^\n]*\n([\s\S]*?)\n```\s*$/);return match&&!match[1].includes("```")?match[1]+"\n":text;}};
  el("open-project").addEventListener("click",openDialog);el("context-project").addEventListener("click",()=>project?ProjectMenu.show(project,el('context-project')):openDialog());
  el("project-create").addEventListener("click",()=>openProject(false,true));
  el("project-form").addEventListener("submit",event=>{event.preventDefault();openProject(false);});el("project-pick").addEventListener("click",()=>openProject(true));
  el("no-project").addEventListener("click",()=>newSession(null));el("file-mode").addEventListener("change",controls);
  el("save-form").addEventListener("submit",event=>{event.preventDefault();confirmSave();});el("show-exports").addEventListener("click",showOutputs);
  el("save-new").addEventListener("click",()=>{if(operationBusy||!saving)return;saving.ticket=null;el("save-path").disabled=false;el("save-path").value="";el("save-new").hidden=true;el("save-error").textContent="";el("save-note").textContent="已开始新的另存请求。原保存记录保留；若原结果不确定，请先核对原文件，避免产生两份内容。";el("save-path").focus();});
  for(const button of document.querySelectorAll("[data-close-dialog]"))button.addEventListener("click",()=>el(button.dataset.closeDialog).close());
  el("conversation-temporary").addEventListener("click",()=>{newSession(project,true);el("conversation-menu").open=false;});
  el("conversation-delete").addEventListener("click",deleteConversation);
  el("conversation-retry").addEventListener("click",()=>remember(true));
  document.addEventListener("click",event=>{for(const menu of document.querySelectorAll('.answer-menu[open],#conversation-menu[open],#file-options[open]'))if(!menu.contains(event.target))menu.open=false;});
  document.addEventListener("keydown",event=>{if(event.key==="Escape")for(const menu of document.querySelectorAll('.answer-menu[open],#conversation-menu[open],#file-options[open]')){menu.open=false;menu.querySelector('summary').focus();}});
  (async()=>{
    try{if(window.ProjectMenu){try{await ProjectMenu.load();}catch(e){notify('项目管理暂不可用：'+e.message);}}await refreshProjects();const rows=await Conversations.list();for(const row of [...rows].reverse())sessions.set(row.id,{title:row.title,project:projects.find(p=>p.id===row.project_id)||null,archiveState:"saved"});
      const projectId=location.hash.match(/^#project=([a-f0-9]{32})$/)?.[1],chatId=location.hash.match(/^#chat=([a-f0-9]{32})$/)?.[1];
      if(projectId)project=projects.find(p=>p.id===projectId)||null;revealCurrent();
      busyOperation(false);if(chatId&&sessions.has(chatId))await restore(chatId);render();
    }catch(error){archiveWarning="未能读取本机会话："+error.message;notify(archiveWarning);}finally{busyOperation(false);archiveStatus();}
  })();
})();
