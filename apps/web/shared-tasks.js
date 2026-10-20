(() => {
  'use strict';
  const root=document.getElementById('shared-tasks-root'); if(!root)return;
  root.innerHTML=`<h2>共同任务 · 交接与接续</h2>
    <p>加入端委派，共享端逐项许可执行。当前支持明确文本的清单报告；不会读取磁盘、调用模型或写入个人记忆。</p>
    <p data-status role="status" aria-live="polite"></p>
    <div class="shared-row"><button data-policy>启用任务通道</button><button data-refresh>读取本机回执</button><button data-sync>交换任务与回执</button></div>
    <div data-create><label>任务名称<input data-title maxlength="80"></label>
    <label>明确发送的资料<textarea data-text rows="4" maxlength="5000"></textarea></label><button data-submit>登记委派任务</button></div>
    <p>关闭通道阻止后续接收；取消请求需送达对端才能确认。未知任务不会自动接管或重跑。每空间最多保留 32 个任务。</p>
    <div data-tasks></div><details><summary>助手接续摘要</summary><pre data-continuation></pre><button data-copy>复制状态摘要</button></details>`;
  const q=s=>root.querySelector(s), nonce=document.querySelector('meta[name="jarvis-nonce"]').content;
  let space=null,value=null,busy=false,epoch=0,draftId=null;
  const states={OFFERED:'待交接',WAITING_APPROVAL:'等待执行端许可',RUNNING:'执行中',SUCCEEDED:'已完成',CANCELLED:'已取消',UNKNOWN:'结果未知，须核对',FAILED:'失败'};
  async function api(action,extra={},sid=space.id){
    const r=await fetch('/api/federation',{method:'POST',cache:'no-store',credentials:'omit',
      headers:{'Content-Type':'application/json','X-Jarvis-Nonce':nonce},
      body:JSON.stringify({action,space:sid,...extra}),signal:AbortSignal.timeout(25000)});
    const data=await r.json();if(!r.ok)throw new Error(data.user_message||data.message||'任务通道暂不可用');
    return data;
  }
  function controls(){
    root.querySelectorAll('button,input,textarea').forEach(e=>e.disabled=busy||!space);
    q('[data-create]').hidden=value?.role!=='client';
    q('[data-policy]').textContent=value?.enabled?'关闭任务通道':'启用任务通道';
    q('[data-sync]').disabled=busy||!value?.enabled||value?.role!=='client'||!value?.active;
    q('[data-submit]').disabled=busy||!value?.enabled||!value?.active;
  }
  function render(){
    q('[data-tasks]').replaceChildren();
    for(const [id,row] of Object.entries(value?.tasks||{})){
      const section=document.createElement('section'),title=document.createElement('h3'),info=document.createElement('p'),details=document.createElement('details'),summary=document.createElement('summary'),text=document.createElement('pre');
      title.textContent=row.spec.title; info.textContent=`${states[row.state]||row.state} · ${id.slice(0,8)}${row.cancel?' · 已请求取消':''}`;
      summary.textContent='查看交接资料与结果';text.textContent=row.spec.text+'\n\n'+(row.result?JSON.stringify(row.result,null,2):'暂无完成回执');
      details.append(summary,text);section.append(title,info,details);
      if(value.node===row.spec.executor&&row.state==='WAITING_APPROVAL'){
        const run=document.createElement('button');run.textContent='许可并执行此任务';run.onclick=()=>act('task_run',{task:id});section.append(run);
      }
      if(!['SUCCEEDED','CANCELLED','UNKNOWN','FAILED'].includes(row.state)){
        const cancel=document.createElement('button');cancel.textContent='取消任务';cancel.onclick=()=>act('task_cancel',{task:id});section.append(cancel);
      }
      q('[data-tasks]').append(section);
    }
    controls();
  }
  async function act(action='task_view',extra={}){
    if(busy||!space)return; const token=epoch,sid=space.id;busy=true;controls();
    try{
      const result=await api(action,extra,sid);if(token!==epoch)return;
      value=result;render();
      const continuity=await api('task_continuation',{},sid);if(token!==epoch)return;
      q('[data-continuation]').textContent=continuity.notice+'\n'+continuity.items.map(r=>`${r.title}：${states[r.state]}${r.cancel_pending?'（取消等待送达）':''}${r.last_contact?'；回执 '+new Date(r.last_contact*1000).toLocaleString():''}`).join('\n');
      q('[data-status]').textContent='已读取可追溯回执。没有完成回执的任务不会显示为完成。';
      if(action==='task_create'){draftId=null;q('[data-title]').value='';q('[data-text]').value='';}
    }catch(e){if(token===epoch)q('[data-status]').textContent=e.message;}
    finally{busy=false;if(token===epoch)render();}
  }
  q('[data-refresh]').onclick=()=>act();
  q('[data-policy]').onclick=()=>act('task_policy',{revision:value.revision,enabled:!value.enabled});
  q('[data-sync]').onclick=()=>act('task_sync');
  q('[data-submit]').onclick=()=>{draftId ||= crypto.randomUUID().replaceAll('-','');act('task_create',{task:draftId,title:q('[data-title]').value,text:q('[data-text]').value});};
  for(const s of ['[data-title]','[data-text]'])q(s).oninput=()=>{draftId=null;};
  q('[data-copy]').onclick=async()=>{try{await navigator.clipboard.writeText(q('[data-continuation]').textContent);q('[data-status]').textContent='已复制。可明确粘贴到聊天；不会自动写入个人记忆。';}catch{q('[data-status]').textContent='请选中摘要手动复制。';}};
  window.SharedTasks={canSwitch:()=>!busy&&(!(q('[data-text]').value||q('[data-title]').value)||confirm('任务草稿尚未提交，放弃并切换？'))};
  window.addEventListener('jarvis:shared-space',event=>{
    const next=event.detail;if(next?.id===space?.id){space=next;return;}
    epoch++;space=next;value=null;root.hidden=!space;q('[data-title]').value='';q('[data-text]').value='';draftId=null;
    if(space)act();
  });
})();
