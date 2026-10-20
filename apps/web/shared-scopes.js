(() => {
  'use strict';
  const root=document.getElementById('shared-scopes-root');if(!root)return;
  root.innerHTML=`<h2>分域共享 · 发送与接收</h2>
    <p>双方分别选择发送条目和接收许可。个人记忆保留在个人范围，项目记忆需映射到本机项目；接收内容放在独立共享层，不覆盖原记忆。</p>
    <p data-status role="status" aria-live="polite"></p>
    <button data-enable>启用分域接收控制</button>
    <div data-form hidden>
    <details open><summary>1 · 选择本机可共享的来源</summary>
      <p>仅分享勾选条目；目录会包含标题、类别和项目编号，正文等对端许可后再发送。原文修订随下次同步更新，遗忘或取消发布随下次同步移除对端共享副本。</p>
      <div class="shared-row"><label>来源类型<select data-kind><option value="personal">个人记忆</option><option value="project">项目记忆</option><option value="card">普通共享卡</option></select></label>
      <label data-project-label hidden>本机来源项目<select data-project></select></label><button data-load>读取来源</button></div>
      <div data-sources class="scoped-choices"></div><p data-count></p><button data-clear>取消全部发送选择</button>
    </details>
    <details open><summary>2 · 许可对端条目进入本机</summary>
      <p>先保存两端发送选择，再由加入端交换目录。未勾选不会接收正文；撤销或修改映射会立即清除本机对应共享内容。已导出的副本无法撤回。</p>
      <div data-grants class="scoped-choices"></div>
    </details>
    <div class="shared-row"><button data-save class="primary">保存发送与接收许可</button><button data-catalog>只交换候选目录</button><button data-sync>按许可同步正文</button></div>
    <p data-role></p><details open><summary>3 · 本机已接收内容</summary><div data-inbox></div></details>
    <p>模型使用还需在下方单独授权，并受来源模型许可限制。对端离线时，尚未送达的纠正或撤回无法即时获知。旧整空间同步在启用后停用。</p>
    </div>`;
  const q=s=>root.querySelector(s),nonce=document.querySelector('meta[name="jarvis-nonce"]').content;
  let space=null,options=null,selected=new Map(),dirty=false,busy=false,key='',epoch=0;
  const status=text=>q('[data-status]').textContent=text;
  const selectionKey=r=>JSON.stringify([r.kind,r.source,r.source_project]);
  function controls(){
    const locked=busy||document.getElementById('federation-root').dataset.operationBusy==='true';
    root.querySelectorAll('button,input,select').forEach(e=>e.disabled=locked);
    for(const action of ['catalog','sync'])q(`[data-${action}]`).disabled=locked||space?.role!=='client'||dirty;
  }
  async function api(body){
    const r=await fetch('/api/federation',{method:'POST',cache:'no-store',credentials:'omit',
      headers:{'X-Jarvis-Nonce':nonce,'Content-Type':'application/json'},body:JSON.stringify(body),signal:AbortSignal.timeout(55000)});
    const value=await r.json();if(!r.ok)throw new Error(value.user_message||value.message||'操作未确认，请重新读取状态。');return value;
  }
  const currentSource=()=>({kind:q('[data-kind]').value==='card'?'card':'memory',project_id:q('[data-kind]').value==='project'?q('[data-project]').value:null});
  function count(){q('[data-count]').textContent=`共选择 ${selected.size} 项（含其他来源页），最多 32 项。`;controls();}
  function sourceList(rows){
    const {kind,project_id}=currentSource();
    q('[data-sources]').replaceChildren(...rows.map(row=>{
      const value={kind,source:row.id,source_project:project_id,expected:row.expected},id=selectionKey(value);
      const label=document.createElement('label'),input=document.createElement('input'),text=document.createElement('span');
      label.className='shared-choice';input.type='checkbox';input.checked=selected.has(id);input.dataset.source=row.id;text.textContent=row.title;
      if(input.checked)selected.set(id,value);
      input.onchange=()=>{if(input.checked)selected.set(id,value);else selected.delete(id);dirty=true;count();};
      label.append(input,text);return label;
    }));count();
  }
  function render(value){
    options=value;dirty=false;selected=new Map(Object.values(value.selected).map(r=>[selectionKey(r),{kind:r.kind,source:r.source,source_project:r.source_project,expected:r.expected}]));
    q('[data-enable]').hidden=value.enabled;q('[data-form]').hidden=!value.enabled;
    q('[data-project]').replaceChildren(...value.projects.map(row=>{const e=document.createElement('option');e.value=row.id;e.textContent=row.name;return e;}));
    q('[data-kind]').value='personal';q('[data-project-label]').hidden=true;sourceList(value.sources);
    q('[data-grants]').replaceChildren(...Object.entries(value.catalog).map(([id,row])=>{
      const wrap=document.createElement('div'),label=document.createElement('label'),input=document.createElement('input'),text=document.createElement('span');
      wrap.dataset.offer=id;input.type='checkbox';input.checked=!!value.grants[id];label.className='shared-choice';
      text.textContent=`${row.domain==='project'?'项目记忆':row.domain==='personal'?'个人记忆':'普通资料'} · ${row.title}`;
      label.append(input,text);wrap.append(label);
      if(row.domain==='project'){
        const target=document.createElement('select');target.setAttribute('aria-label','接收项目：'+row.title);
        const blank=document.createElement('option');blank.value='';blank.textContent='选择本机对应项目';target.append(blank);
        for(const project of value.projects){const e=document.createElement('option');e.value=project.id;e.textContent=project.name;target.append(e);}
        target.value=value.grants[id]?.project_id||'';wrap.append(target);
      }
      wrap.onchange=()=>{dirty=true;controls();};return wrap;
    }));
    if(!Object.keys(value.catalog).length)q('[data-grants]').textContent='尚无对端候选目录。两端启用并保存选择后，由加入端交换目录。';
    q('[data-inbox]').replaceChildren(...value.received.map(card=>{
      const details=document.createElement('details'),title=document.createElement('summary'),text=document.createElement('p');
      const project=value.projects.find(p=>p.id===card.project_id);
      title.textContent=(card.domain==='project'?`项目 · ${project?.name||'项目当前不可用'}`:'个人范围')+' · '+card.versions[0].title;
      text.textContent=card.versions[0].text;text.className='shared-wrap';details.append(title,text);return details;
    }));
    if(!value.received.length)q('[data-inbox]').textContent='尚无获准的接收内容。';
    q('[data-role]').textContent=space?.role==='client'?'在此交换两端目录与正文；每次发送都会重新取得对端许可。':'本机是共享端。保存许可后，等待加入端点击目录交换或同步。';
    controls();
  }
  async function run(action){
    if(busy||!space||space.state!=='active')return;
    busy=true;const ticket=++epoch,sid=space.id;controls();status('正在处理…');
    try{
      if(action==='enable'||action==='save'){
        const grants={};
        if(action==='save')for(const wrap of q('[data-grants]').children){
          if(!wrap.querySelector('input:checked'))continue;
          const id=wrap.dataset.offer,row=options.catalog[id],project=wrap.querySelector('select')?.value||null;
          if(row.domain==='project'&&!project)throw new Error('请为每项获准的项目记忆选择本机项目。');
          grants[id]={domain:row.domain,source_project:row.source_project,project_id:project};
        }
        await api({action:'scope_change',space:sid,revision:options.revision,selected:action==='enable'?[]:[...selected.values()],grants});
      }else if(action==='catalog'||action==='sync'){
        await api({action:action==='sync'?'scope_sync':'scope_catalog',space:sid});
      }
      const value=await api({action:'scope_options',space:sid,...(action==='sources'?currentSource():{kind:'memory',project_id:null})});
      if(ticket!==epoch||sid!==space?.id)return;
      if(action==='sources'){sourceList(value.sources);status('本机来源已读取；勾选后保存。');}
      else{render(value);status(action==='sync'?'分域同步完成。':action==='catalog'?'目录已更新，尚未发送正文。':action==='load'?'发送、接收和模型使用分别授权。':'设置已保存。');}
      if(!['sources','load'].includes(action)){key='';document.getElementById('shared-refresh').click();}
    }catch(error){if(ticket===epoch)status(error.message);}
    finally{busy=false;controls();}
  }
  window.addEventListener('jarvis:shared-space',event=>{
    const next=event.detail,nextKey=next?`${next.id}:${next.state}:${next.scoped_revision}:${next.scoped_seq}`:'';
    if(nextKey!==key){
      if(dirty&&next?.id===space?.id){status('共享状态已变化；当前选择保留，保存会核验版本。');controls();return;}
      key=nextKey;space=next;root.hidden=!next||next.state!=='active';if(!root.hidden&&!busy)run('load');
    }controls();
  });
  q('[data-kind]').onchange=()=>{q('[data-project-label]').hidden=q('[data-kind]').value!=='project';q('[data-sources]').replaceChildren();status('选择来源后点击读取来源；其他范围的已选条目会保留。');};
  q('[data-project]').onchange=()=>q('[data-sources]').replaceChildren();
  q('[data-load]').onclick=()=>run('sources');
  q('[data-clear]').onclick=()=>{selected.clear();dirty=true;q('[data-sources]').querySelectorAll('input').forEach(e=>e.checked=false);count();};
  for(const action of ['enable','save','catalog','sync'])q(`[data-${action}]`).onclick=()=>run(action);
  window.SharedScopes={canSwitch:()=>{if(busy)return false;if(dirty&&!confirm('分域共享选择尚未保存，是否放弃并切换？'))return false;dirty=false;return true;}};
  window.addEventListener('beforeunload',event=>{if(dirty){event.preventDefault();event.returnValue='';}});
  root.hidden=true;
})();
