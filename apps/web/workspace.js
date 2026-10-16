"use strict";
(() => {
  const el=id=>document.getElementById(id);
  let projects=[],project=null,operationBusy=false,activeId=crypto.randomUUID(),sessions=new Map(),saving=null;
  const stateNames={PREPARED:"等待文件内容",SAVED:"已保存",FAILED:"保存失败",UNKNOWN:"结果待核对"};
  const newId=()=>crypto.randomUUID().replaceAll("-","");
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
    const locked=busy||operationBusy;
    for(const id of ["open-project","context-project","no-project","file-mode","output-path","project-open","project-pick"]){el(id).disabled=locked;}
    for(const button of document.querySelectorAll(".project-row"))button.disabled=locked;
    el("output-location").hidden=!el("file-mode").checked;
    el("file-mode").disabled=locked||!project;
  }
  function busyOperation(value){operationBusy=value;setControls();controls();}
  function render(){
    el("context-project").textContent=project?project.name+" · "+project.path:"选择项目文件夹";
    el("context-project").title=project?"项目根目录："+project.path:"打开文件夹作为项目根目录";
    el("project-root-note").textContent=project?"默认保存到 "+project.path+"；可在输出位置填写相对路径或明确的绝对路径。":"打开项目后，可将回答生成为文件。会话仅保留在本页面。";
    el("no-project").hidden=!project;
    el("project-list").replaceChildren();
    if(!projects.length){const p=document.createElement("p");p.className="project-empty";p.textContent="打开文件夹，开始一个项目";el("project-list").append(p);}
    for(const p of projects){
      const button=document.createElement("button"),title=document.createElement("strong"),path=document.createElement("small");
      button.type="button";button.className="project-row";button.setAttribute("aria-pressed",String(p.id===project?.id));button.title=p.path;
      title.textContent=p.name+(p.available?"":" · 不可用");path.textContent=p.path;button.append(title,path);
      button.addEventListener("click",()=>{if(!busy&&!operationBusy)newSession(p);});el("project-list").append(button);
    }
    el("session-list").replaceChildren();
    for(const [id,s] of [...sessions].reverse()){
      const button=document.createElement("button");button.className="project-row";button.type="button";button.textContent=(s.project?.name||"无项目")+" · "+s.title;button.setAttribute("aria-pressed",String(id===activeId));button.addEventListener("click",()=>restore(id));el("session-list").append(button);
    }
    controls();
  }
  function snapshot(){
    if(!history.length&&!el("message").value.trim()&&!el("messages").querySelector(".message")&&!Attachments.hasDraft())return;
    sessions.set(activeId,{project,nodes:Array.from(el("messages").childNodes),history:history.map(x=>({...x})),draft:el("message").value,attachments:Attachments.snapshot(),title:el("session-title").textContent,mode:el("file-mode").checked,path:el("output-path").value});
  }
  function locationForProject(){window.history.replaceState(null,"",project?"#project="+project.id:location.pathname);}
  function newSession(next=project){
    if(busy||operationBusy)return;
    snapshot();activeId=crypto.randomUUID();project=next;resetConversation();el("file-mode").checked=false;el("output-path").value="";
    locationForProject();render();el("current-chat").click();
    const heading=el("welcome")?.querySelector("h2");if(heading&&project)heading.textContent="在 "+project.name+" 中做点什么？";
  }
  function restore(id){
    if(busy||operationBusy||id===activeId)return;
    snapshot();const s=sessions.get(id);if(!s)return;
    activeId=id;project=s.project;history=s.history.map(x=>({...x}));el("messages").replaceChildren(...s.nodes);el("message").value=s.draft;Attachments.restore(s.attachments);el("session-title").textContent=s.title;el("file-mode").checked=s.mode;el("output-path").value=s.path;notify("");providerHint();locationForProject();render();el("current-chat").click();
  }
  async function refreshProjects(){const data=await api("/api/workspace/projects");projects=data.projects;render();}
  function openDialog(){if(busy||operationBusy)return;el("project-error").textContent="";el("folder-path").value=project?.path||"";el("project-dialog").showModal();el("folder-path").focus();}
  async function openProject(usePicker){
    if(busy||operationBusy)return;el("project-error").textContent="";busyOperation(true);
    let chosen=null;
    try{
      if(usePicker){const result=await api("/api/workspace/pick-folder",{},125000);if(!result.cancelled)chosen=result.project;}
      else chosen=await api("/api/workspace/projects",{path:el("folder-path").value.trim()});
      if(chosen){await refreshProjects();el("project-dialog").close();}
    }catch(error){el("project-error").textContent=error.message;}
    finally{busyOperation(false);}
    if(chosen)newSession(chosen);
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
    const actions=document.createElement("div"),button=document.createElement("button"),note=document.createElement("div");actions.className="file-actions";note.className="file-receipt";note.setAttribute("role","status");button.type="button";button.textContent="保存回答…";actions.append(button,note);article.append(actions);
    const answer={text,project:context?.project||null,ticket:context?.ticket||null,note,button,saved:false};
    button.addEventListener("click",()=>{
      if(busy||operationBusy)return;
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
  window.Workspace={controls,isBusy:()=>operationBusy,newSession,beforeSend,attachAnswer,saveAnswer,
    fileContent:text=>{const match=text.match(/^\s*```[^\n]*\n([\s\S]*?)\n```\s*$/);return match&&!match[1].includes("```")?match[1]+"\n":text;}};
  el("open-project").addEventListener("click",openDialog);el("context-project").addEventListener("click",openDialog);
  el("project-form").addEventListener("submit",event=>{event.preventDefault();openProject(false);});el("project-pick").addEventListener("click",()=>openProject(true));
  el("no-project").addEventListener("click",()=>newSession(null));el("file-mode").addEventListener("change",controls);
  el("save-form").addEventListener("submit",event=>{event.preventDefault();confirmSave();});el("show-exports").addEventListener("click",showOutputs);
  el("save-new").addEventListener("click",()=>{if(operationBusy||!saving)return;saving.ticket=null;el("save-path").disabled=false;el("save-path").value="";el("save-new").hidden=true;el("save-error").textContent="";el("save-note").textContent="已开始新的另存请求。原保存记录保留；若原结果不确定，请先核对原文件，避免产生两份内容。";el("save-path").focus();});
  for(const button of document.querySelectorAll("[data-close-dialog]"))button.addEventListener("click",()=>el(button.dataset.closeDialog).close());
  (async()=>{try{await refreshProjects();const id=location.hash.match(/^#project=([a-f0-9]{32})$/)?.[1];if(id){project=projects.find(p=>p.id===id)||null;render();}}catch(error){el("project-root-note").textContent=error.message;}})();
})();
