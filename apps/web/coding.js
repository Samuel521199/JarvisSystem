/* Optional coding executor settings; no polling or model calls on page load. */
(()=>{'use strict';
const $=id=>document.getElementById(id),nonce=document.querySelector('meta[name="jarvis-nonce"]').content;
let state=null,busy=false;
async function request(body){const r=await fetch('/api/coding',{method:body?'POST':'GET',credentials:'omit',cache:'no-store',headers:{'X-Jarvis-Nonce':nonce,...(body?{'Content-Type':'application/json'}:{})},body:body?JSON.stringify(body):undefined,signal:AbortSignal.timeout(10000)});const v=await r.json();if(!r.ok)throw new Error(v.user_message||'编码设置暂不可用。');return v;}
function render(){if(!state)return;$('coding-enabled').checked=state.settings.enabled;$('coding-model').value=state.settings.model;$('coding-reasoning').value=state.settings.reasoning;$('coding-state').textContent=state.offline?'软件离线 · 外部编码暂停':state.available?'Codex CLI '+state.version+' · 已核对':'执行器未就绪';$('coding-detail').textContent=state.reason+' '+state.authentication;$('coding-scope').textContent=state.scope;$('coding-billing').textContent=state.billing;$('coding-save').disabled=busy;}
async function load(){if(busy)return;busy=true;try{state=await request();render();$('coding-message').textContent='';}catch(e){$('coding-message').textContent=e.message;}finally{busy=false;render();}}
$('coding-form').addEventListener('submit',async e=>{e.preventDefault();if(busy||!state)return;const body={revision:state.settings.revision,enabled:$('coding-enabled').checked,model:$('coding-model').value.trim(),reasoning:$('coding-reasoning').value};busy=true;$('coding-save').disabled=true;try{state=await request(body);$('coding-message').textContent='已保存。任务中选择外部 Codex 才会调用；保存设置不产生模型请求。';}catch(e){$('coding-message').textContent=e.message;}finally{busy=false;render();}});
$('coding-refresh').onclick=load;document.addEventListener('jarvis:settings-view',e=>{if(e.detail==='coding')load();});if(location.hash==='#coding')load();
})();
