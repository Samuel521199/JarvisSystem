"use strict";
// Independent view; task truth remains in the server ledger, never browser storage.
(() => {
  const el = id => document.getElementById(id);
  const NONCE=document.querySelector('meta[name="jarvis-nonce"]').content;
  const stateNames = {READY:"已接纳",RUNNING:"执行中",CANCELLING:"正在取消",SUCCEEDED:"已完成",FAILED:"失败",CANCELLED:"已取消",UNKNOWN:"结果待核对",PREPARED:"已准备",DISPATCHING:"执行中"};
  const actionNames = {fill:"填写",select:"选择",check:"勾选状态",click:"点击"};
  let selected=/^task_[a-f0-9]{32}$/.test(new URLSearchParams(location.search).get('task')||'')?new URLSearchParams(location.search).get('task'):null, visible=false, timer=null, refreshingTasks=false, submitting=false, active=false, available=false, browserAvailable=false, queuePaused=false, queueWaiting=0, queueCapacity=20, queueOwned=false, queueChanging=false;
  let imageURL=null, imageTask=null, pending=null, generation=0;
  async function request(path, payload) {
    const response=await fetch(path,{method:payload===undefined?"GET":"POST",cache:"no-store",credentials:"omit",
      headers:{"X-Jarvis-Nonce":NONCE,...(payload===undefined?{}:{"Content-Type":"application/json"})},
      body:payload===undefined?undefined:JSON.stringify(payload),signal:AbortSignal.timeout(12000)});
    if(!response.ok){const error=await response.json();throw new Error(error.user_message||"请求未完成");}
    return response;
  }
  function controls() {
    const inventory=el("task-mode").value==="inventory",natural=el("task-mode").value==="natural",scripted=inventory||el("task-mode").value==="scripted";
    el("task-model").disabled=scripted||submitting||!el("task-model").value;
    el("task-start").disabled=submitting||queueWaiting>=queueCapacity||!available||(!inventory&&!natural&&!browserAvailable)||!queueOwned||(!scripted&&!el("task-model").value);
    el("task-start").textContent=active||queuePaused||queueWaiting?"加入队列":"启动任务";
    el("queue-toggle").textContent=queuePaused?"继续队列":"暂停队列";
    el("queue-toggle").disabled=queueChanging||!queueOwned||!available;
    el("task-mode").disabled=submitting;
    el("task-json").disabled=submitting;
    el("task-custom").hidden=el("task-mode").value!=="custom";
    el("inventory-options").hidden=!inventory&&!natural;
    el("natural-options").hidden=!natural;
    el("task-prompt").disabled=submitting;
    el("inventory-relative").disabled=submitting;
    el("task-privacy").textContent=natural?"任务要求和所选相对路径交给规划模型；文件名、文件正文、记忆和会话历史不会发送。规划通过后执行固定任务，结果保存在本机。自动路由可能切换供应商。":inventory?"仅列举初始化绑定目录的文件元数据，不读取文件正文、不调用模型。清单回执保存在本机运行数据区。":scripted?"固定动作仅检查浏览器通路，不调用模型，也不产生模型用量。":
      "页面文字和允许的输入值将发送至所选模型。自动路由可能使用其他供应商；截图只保存在本机。";
  }
  function clearImage() {
    if(imageURL)URL.revokeObjectURL(imageURL);
    imageURL=null;imageTask=null;el("task-image").hidden=true;el("task-image").removeAttribute("src");
  }
  async function detail(id) {
    const mine=++generation;
    const data=await (await request("/api/tasks/"+id)).json();
    if(mine!==generation||selected!==id)return;
    el("task-detail").hidden=false;
    const status=data.task.status;
    el("task-detail-title").textContent=(stateNames[status]||status)+" · 执行详情";
    el("task-result").textContent=status==="SUCCEEDED"?(["inventory","natural"].includes(data.kind)?(data.kind==="natural"?"统计报告已生成，数量、字节分组及产物摘要已核验。文件：":"目录清单已生成并核对回执。文件：")+data.artifact_path:"页面已满足任务的成功条件，结果截图已保存。"):status==="UNKNOWN"?
      "结果尚未确认，不会自动重试。请核对实际页面或业务结果，再决定是否新建任务。":status==="CANCELLED"?"任务已取消；已经发生的操作不会撤销。":data.cancel_requested?
      "已请求取消，正在等待执行器结束；已发生的操作无法撤销。":data.error?.message||"任务 "+id;
    el("task-cancel").hidden=!["READY","RUNNING"].includes(status);
    el("task-cancel").disabled=data.cancel_requested;
    el("task-steps").replaceChildren();
    for(const step of data.steps) {
      const item=document.createElement("li"),note=document.createElement("small");
      if(data.kind==="natural"){
        const labels={MODEL_REQUESTED:"模型请求已记录",MODEL_UNRESOLVED:"规划结果未确认",MODEL_FAILED:"模型返回不可用",PLAN_REJECTED:"计划未通过校验",PLAN_VALIDATED:"计划已通过校验"};
        item.textContent="规划 "+(step.ordinal+1)+" · "+(labels[step.state]||step.state);
        const metadata=JSON.parse(step.model_json||"{}");note.textContent=[metadata.provider,metadata.model].filter(Boolean).join(" / ")+(metadata.usage?" · 用量 "+JSON.stringify(metadata.usage):"");
        item.append(note);el("task-steps").append(item);continue;
      }
      const state=step.state==="CONFIRMED"?"已执行":step.state==="IN_FLIGHT"?"执行结果待确认":"结果待核对";
      item.textContent=(actionNames[step.action.op]||step.action.op)+" · "+step.action.target+" · "+state;
      note.textContent=(step.model.model||"固定动作测试")+(step.model.usage?" · 用量 "+JSON.stringify(step.model.usage):"");
      item.append(note);el("task-steps").append(item);
    }
    if(["inventory","natural"].includes(data.kind)&&data.report){
      const summary=document.createElement("li");summary.textContent="共 "+data.report.total_files+" 个文件，"+data.report.total_bytes+" 字节";el("task-steps").append(summary);
      for(const group of data.report.by_type||[]){const row=document.createElement("li");row.textContent=group.type+" · "+group.file_count+" 个文件 · "+group.total_bytes+" 字节";el("task-steps").append(row);}
      for(const file of data.report.files){const row=document.createElement("li");row.textContent=file.path+" · "+file.size_bytes+" 字节";el("task-steps").append(row);}
    }else if(!data.steps.length){const item=document.createElement("li");item.textContent=data.kind==="inventory"?"目录任务尚未产生已确认清单。":"尚无页面操作记录。";el("task-steps").append(item);}
    if(data.has_screenshot&&imageTask!==id) {
      const blob=await (await request("/api/tasks/"+id+"/screenshot")).blob();
      if(mine!==generation||selected!==id)return;
      clearImage();imageURL=URL.createObjectURL(blob);imageTask=id;el("task-image").src=imageURL;el("task-image").hidden=false;
    } else if(!data.has_screenshot)clearImage();
  }
  async function loadTasks() {
    if(refreshingTasks)return;
    refreshingTasks=true;
    try {
      const data=await (await request("/api/tasks")).json();
      active=data.active;available=data.ready;browserAvailable=data.available;
      el("inventory-scope").textContent="固定样例根目录："+data.inventory_root+"。当前项目选择不会改变此任务范围。";
      queuePaused=data.queue.paused;queueWaiting=data.queue.waiting;queueCapacity=data.queue.capacity;queueOwned=data.queue.owned;
      const reasons={restart_review:"服务已重启，请核对记录后继续。",service_closed:"服务已关闭过，请核对记录后继续。",result_unknown:"上个任务结果待核对；继续只会执行尚未开始的任务。",queue_version_changed:"存在旧版本任务，请取消后重新提交。",queue_content_changed:"演示页面已改变，请取消旧任务后重新提交。"};
      const resource=data.queue.resources;
      const resourceReasons={memory_pressure:"可用内存不足，后台任务等待；聊天仍可使用。",resource_recovering:"内存正在恢复，稳定后继续后台任务。",resource_unavailable:"暂时无法读取内存状态，后台任务等待。"};
      const resourceNote=resource?.waiting&&!queuePaused?(resourceReasons[resource.reason]||"后台任务等待资源。")+(resource.sample?" 可用 "+Math.round(resource.sample.available_bytes/1048576)+" MiB，启动需要 "+Math.round(resource.required_bytes/1048576)+" MiB。":""):"";
      el("queue-note").textContent=(queuePaused?"队列已暂停":resource?.waiting?"等待资源":"队列运行中")+" · 等待 "+queueWaiting+" / "+queueCapacity+" · 执行 "+data.queue.running.length+(resourceNote?"。"+resourceNote:"")+(data.queue.error?"。"+(reasons[data.queue.error]||"队列遇到问题："+data.queue.error):"");
      if(pending) {
        const recovered=data.tasks.find(t=>t.request_id===pending.request_id);
        if(recovered){selected=recovered.task_id;pending=null;el("task-submit-note").textContent="已找到刚才提交的任务。";}
      }
      el("task-list").replaceChildren();
      el("task-list-note").textContent=!data.ready?"核心未就绪或已停止；可以查看历史记录。":active?"后台任务正在执行，你可以切回对话。":data.tasks.length?"最近 "+data.tasks.length+" 个任务 · 记录保存在本机":"还没有后台任务，从左侧选择目录清单或浏览器任务。";
      if(!selected&&data.tasks.length)selected=data.tasks[0].task_id;
      for(const task of data.tasks) {
        const button=document.createElement("button"),title=document.createElement("strong"),meta=document.createElement("span");
        button.type="button";button.className="task-row";button.setAttribute("aria-pressed",String(task.task_id===selected));
        title.textContent=task.goal;meta.textContent=(task.queue_position?"排队第 "+task.queue_position+" 位":stateNames[task.status]||task.status)+" · "+task.model+" · "+new Date(task.created_at).toLocaleString();
        button.append(title,meta);button.addEventListener("click",()=>{selected=task.task_id;clearImage();loadTasks();});el("task-list").append(button);
      }
      if(selected)await detail(selected);
    } catch(error){el("task-list-note").textContent=error.message;}
    finally{refreshingTasks=false;controls();}
  }
  async function modelsForTasks() {
    try {
      const data=await (await request("/api/models")).json();
      const previous=el("task-model").value;el("task-model").replaceChildren();
      const options=[...(data.models||[]).map(m=>({...m,model:m.provider+"::"+m.model,label:(m.label||m.model)+" · "+(m.provider_label||m.provider)})),{model:"auto",label:"自动路由"}];
      for(const item of options){const option=document.createElement("option");option.value=item.model;option.textContent=item.label||item.model;el("task-model").append(option);}
      const preferred=previous||"auto";
      if(options.some(item=>item.model===preferred))el("task-model").value=preferred;
    } catch(error){el("task-submit-note").textContent=error.message;}
    controls();
  }
  function showTasks(show) {
    visible=show;
    clearInterval(timer);timer=null;
    if(show){modelsForTasks();loadTasks();timer=setInterval(()=>{if(!document.hidden)loadTasks();},2000);}
  }
  document.addEventListener("jarvis:settings-view",event=>showTasks(event.detail==="tasks"));
  el("task-mode").addEventListener("change",()=>{pending=null;el("task-submit-note").textContent="";controls();});
  el("task-model").addEventListener("change",()=>{pending=null;});
  el("inventory-relative").addEventListener("input",()=>{pending=null;});
  el("task-prompt").addEventListener("input",()=>{pending=null;});
  el("task-json").addEventListener("input",()=>{pending=null;});
  el("task-refresh").addEventListener("click",()=>{modelsForTasks();loadTasks();});
  el("task-form").addEventListener("submit",async event=>{
    event.preventDefault();if(submitting)return;
    try {
      if(!pending){pending={request_id:"web-"+crypto.randomUUID().replaceAll("-",""),mode:el("task-mode").value,model:el("task-mode").value==="scripted"?"auto":el("task-model").value};
        if(pending.mode==="inventory"){delete pending.model;pending.relative_path=el("inventory-relative").value;}
        if(pending.mode==="natural"){pending.prompt=el("task-prompt").value;pending.relative_path=el("inventory-relative").value;}
        if(pending.mode==="custom")pending.task=JSON.parse(el("task-json").value);}
      submitting=true;controls();el("task-submit-note").textContent="正在接纳任务…";
      const result=await (await request("/api/tasks",pending)).json();
      selected=result.task_id;pending=null;clearImage();el("task-submit-note").textContent="任务已保存到队列，可切回聊天。";
    } catch(error){if(error instanceof SyntaxError)pending=null;el("task-submit-note").textContent=error.message+" 请先刷新记录；再次提交会沿用当前请求 ID。";}
    finally{submitting=false;controls();await loadTasks();}
  });
  el("queue-toggle").addEventListener("click",async()=>{
    queueChanging=true;controls();
    try{await request("/api/tasks/queue",{paused:!queuePaused});await loadTasks();}
    catch(error){el("task-list-note").textContent=error.message;}
    finally{queueChanging=false;controls();}
  });
  el("task-cancel").addEventListener("click",async()=>{
    if(!selected)return;el("task-cancel").disabled=true;
    try{await request("/api/tasks/"+selected+"/cancel",{});await loadTasks();}
    catch(error){el("task-result").textContent=error.message;el("task-cancel").disabled=false;}
  });
  window.addEventListener("pagehide",()=>{clearInterval(timer);clearImage();});
})();
