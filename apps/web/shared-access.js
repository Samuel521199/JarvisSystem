(() => {
  'use strict';
  const root = document.getElementById('shared-access-root');
  if (!root) return;
  root.innerHTML = `<h2>模型使用授权 · 仅本机</h2>
    <p>配对只同步资料。这里另外选择哪些卡可用于个人或指定项目聊天，以及允许发给哪些模型接入方。另一设备须独立设置；修改或撤销后，旧引用立即失效。</p>
    <p data-status role="status"></p><div data-form hidden>
    <label>用途<select data-project aria-label="共享资料聊天用途"></select></label>
    <fieldset><legend>允许引用的资料卡</legend><div data-cards></div></fieldset>
    <fieldset><legend>允许接收资料的模型接入方</legend><div data-providers></div></fieldset>
    <p>授权绑定当前接入地址与凭据版本；配置变化需要重新检查。已经发送或手动导出的资料无法撤回。</p>
    <div class="shared-row"><button data-save>保存用途授权</button><button data-revoke>撤销全部模型使用</button></div></div>`;
  const q = s => root.querySelector(s), nonce = document.querySelector('meta[name="jarvis-nonce"]').content;
  let current = null, options = null, key = '', ticket = 0, busy = false, dirty = false;
  const status = message => q('[data-status]').textContent = message;
  async function api(body) {
    const response = await fetch('/api/federation', {method:'POST', cache:'no-store', credentials:'omit',
      headers:{'X-Jarvis-Nonce':nonce,'Content-Type':'application/json'},body:JSON.stringify(body),
      signal:AbortSignal.timeout(8000)});
    const value = await response.json();
    if (!response.ok) throw new Error(value.user_message || value.message || '授权操作未确认，请刷新检查。');
    return value;
  }
  function boxes(selector, rows, selected) {
    q(selector).replaceChildren(...rows.map(row => {
      const label=document.createElement('label'), input=document.createElement('input'), text=document.createElement('span');
      input.type='checkbox';input.value=row.id;input.checked=selected(row);
      text.textContent=row.label||row.title;label.className='shared-choice';
      label.append(input,text);return label;
    }));
  }
  function render() {
    const policy=options.policy, select=q('[data-project]');
    select.replaceChildren(...[{id:'',name:'个人聊天（不带项目）'},...options.projects].map(row=>{
      const option=document.createElement('option');option.value=row.id;option.textContent=row.name;return option;
    }));
    select.value=policy.project_id||'';
    boxes('[data-cards]',options.cards,row=>policy.cards.includes(row.id));
    boxes('[data-providers]',options.providers,row=>policy.providers[row.id]===row.destination);
    q('[data-form]').hidden=false;dirty=false;
    status(`授权版本 ${policy.revision}；新空间默认不向任何模型开放。`);
  }
  async function load(space) {
    const id=++ticket;
    current=space;options=null;q('[data-form]').hidden=true;
    if (!space || space.state!=='active') {status('选择已配对空间后可设置模型用途。');return;}
    status('正在读取用途设置…');
    try {const value=await api({action:'access_options',space:space.id});if(id!==ticket)return;options=value;render();}
    catch(error){if(id===ticket)status(error.message);}
  }
  root.addEventListener('change',()=>{dirty=true;});
  window.addEventListener('jarvis:shared-space',event=>{
    const space=event.detail, next=space?space.id+':'+space.state+':'+space.access_revision+':'+space.scoped_revision+':'+space.scoped_seq:'';
    if(next===key)return;
    if(dirty && space?.id===current?.id){status('授权已在另一处改变；当前选择保留，保存将重新检查版本。');return;}
    key=next;load(space);
  });
  async function save(revoke) {
    if(busy||!options||!current)return;
    busy=true;root.querySelectorAll('button,input,select').forEach(b=>b.disabled=true);
    const selected=selector=>[...q(selector).querySelectorAll('input:checked')].map(e=>e.value);
    const cards=revoke?[]:selected('[data-cards]'), providers={};
    if(!revoke)for(const id of selected('[data-providers]'))providers[id]=options.providers.find(row=>row.id===id).destination;
    const space=current.id, id=++ticket;
    try {
      const value=await api({action:'access_change',space,revision:options.policy.revision,
        cards,providers,project_id:q('[data-project]').value||null});
      if(id!==ticket||space!==current?.id)return;
      options=value;render();status(revoke?'本机模型使用已撤销；旧引用和派生历史将停止使用。':'用途授权已保存；旧引用失效，请重新选择资料。');
      key='';document.getElementById('shared-refresh').click();
    }catch(error){if(id===ticket)status(error.message);}
    finally{busy=false;root.querySelectorAll('button,input,select').forEach(b=>b.disabled=false);}
  }
  window.SharedAccess={canSwitch:()=>{if(busy)return false;if(dirty&&!confirm('用途授权尚未保存，是否放弃本次选择？'))return false;dirty=false;return true;}};
  q('[data-save]').onclick=()=>save(false);
  q('[data-revoke]').onclick=()=>save(true);
  window.addEventListener('beforeunload',e=>{if(dirty){e.preventDefault();e.returnValue='';}});
})();
