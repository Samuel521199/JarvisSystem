/* Independent growth panel. Opening settings never starts a paid coding job. */
(()=>{'use strict';
const view=document.getElementById('modules-view');if(!view)return;
const nonce=document.querySelector('meta[name="jarvis-nonce"]').content;
const panel=document.createElement('section');panel.className='panel module-upgrades';panel.id='evolution-panel';
panel.innerHTML=`<div class="panel-heading"><div><h2>自主成长 · 代码与技能</h2><p>自动发现缺失或退化 → 生成代码 → 隔离验收 → 启用 → 自检与回退。</p></div></div>
<p id="evolution-summary" role="status">正在读取成长状态…</p>
<p class="module-note">当前对象：文件清单导出工具。v1 支持 CSV / Markdown，v2 增加 TSV。生成的 Python 与技能说明独立成包，可查看源码；核心宿主和任意软件尚不自动改写。</p>
<form id="evolution-policy"><label>编码模型<select id="evolution-route" required></select></label>
<label>期望能力<select id="evolution-target"><option value="1">v1 · CSV / Markdown</option><option value="2">v2 · 增加 TSV，保留旧能力</option></select></label>
<label><input id="evolution-enabled" type="checkbox"> 自动检查并修复</label>
<p class="muted">启用后每 5 分钟检查一次；缺失、低于期望版本或退化时自动研发。每次最多 2 个候选，每天最多 4 个自动事件。健康检查不调用模型，编码使用所选账户额度。</p>
<button class="secondary" type="submit">保存成长设置</button></form>
<div class="module-release-actions"><button class="primary" id="evolution-start" type="button">生成 / 升级到期望版本</button><button class="secondary" id="evolution-check" type="button">立即自检</button><button class="secondary" id="evolution-rollback" type="button">回退上个版本</button><button class="secondary" id="evolution-stop" type="button">停止本次</button></div>
<p id="evolution-error" class="error" role="alert" hidden></p>
<details><summary>调用已发布技能</summary><p>输入已有的文件清单；工具不扫描磁盘。结果经过独立核验后显示。</p><label>JSON 数据<textarea id="evolution-input" rows="5" spellcheck="false">{"format":"csv","entries":[{"path":"hello.txt","size":12},{"path":"readme.md","size":48}]}</textarea></label><button class="secondary" id="evolution-execute" type="button">执行已发布工具</button><pre id="evolution-output" tabindex="0"></pre></details>
<h3>改进记录与证据</h3><div id="evolution-jobs"></div><details id="evolution-detail-box"><summary>任务详情 / 候选源码</summary><pre id="evolution-detail" tabindex="0"></pre></details>`;
view.prepend(panel);
const skillsView=document.getElementById('skill-view');
if(skillsView){const note=document.createElement('p');note.className='module-note';const link=document.createElement('a');link.href='#modules';link.textContent='生成工具技能与自动升级 → 模块与升级';note.append(link);skillsView.prepend(note);}
const $=id=>document.getElementById('evolution-'+id);
let data=null,timer=null,loading=false,visible=false,loadedPolicy=false,dirty=false,submitting=false,selectedJob=null;
const statuses={QUEUED:'排队',RUNNING:'执行中',OBSERVING:'发布后观察',SUCCEEDED:'已完成',FAILED:'失败',UNKNOWN:'结果待核对',CANCELLED:'已停止',INTERRUPTED:'进程中断'};
async function api(path,body){const response=await fetch(path,{method:body===undefined?'GET':'POST',headers:{'X-Jarvis-Nonce':nonce,...(body===undefined?{}:{'Content-Type':'application/json'})},body:body===undefined?undefined:JSON.stringify(body)});const result=await response.json();if(!response.ok)throw Error(result.user_message||result.error?.message||result.error||'成长服务暂不可用');return result;}
function error(text){$('error').textContent=text;$('error').hidden=!text;}
function showJob(detail){$('detail').textContent=JSON.stringify(detail,null,2);if(detail.result?.text!==undefined)$('output').textContent=detail.result.text;}
function render(){
 const active=data.packages.find(x=>x.id===data.selection.active),busy=data.busy||submitting;
 $('summary').textContent=`${active?'已启用 v'+active.revision+' · '+active.id.slice(0,12):'尚无已启用的生成技能'} · ${data.busy?'正在处理':'待命'} · ${data.settings.enabled?'自动检查已启用':'自动检查未启用'}`;
 for(const id of ['start','check','rollback','execute'])$(id).disabled=busy||(id==='start'&&dirty)||(id==='rollback'&&!data.selection.previous)||(id==='execute'&&!active);
 $('stop').disabled=!data.busy||submitting;
 $('policy').querySelector('button').disabled=busy;
 if(!dirty){$('enabled').checked=data.settings.enabled;$('target').value=String(data.settings.target_revision);$('route').value=data.settings.route;}
 $('jobs').replaceChildren();
 for(const job of data.jobs.slice(0,8)){
  const row=document.createElement('div');row.className='module-job';
  const button=document.createElement('button');button.className='text-button';button.type='button';button.textContent=`${statuses[job.status]||job.status} · ${job.action} · ${new Date(job.created_at).toLocaleString()}${job.error?' · '+job.error:''}`;
  button.onclick=async()=>{try{selectedJob=job.id;showJob(await api('/api/evolution/jobs/'+job.id));$('detail-box').open=true;}catch(e){error(e.message);}};row.append(button);$('jobs').append(row);
 }
 if(active){const button=document.createElement('button');button.type='button';button.className='secondary';button.textContent='查看当前技能源码与清单';button.onclick=async()=>{try{selectedJob=null;$('detail').textContent=JSON.stringify(await api('/api/evolution/packages/'+active.id),null,2);$('detail-box').open=true;}catch(e){error(e.message);}};$('jobs').append(button);}
}
async function load(){if(!visible||loading)return;loading=true;try{
 data=await api('/api/evolution');
 if(!loadedPolicy){const models=await api('/api/models');for(const m of models.models||[]){const option=document.createElement('option');option.value=m.provider+'::'+m.model;option.textContent=m.label+' · '+m.provider;$('route').append(option);}loadedPolicy=true;}
 render();
 if(selectedJob)showJob(await api('/api/evolution/jobs/'+selectedJob));
 if(data.monitor_error)error(data.monitor_error);
}catch(e){error(e.message);}finally{loading=false;clearTimeout(timer);if(visible)timer=setTimeout(load,data?.busy?1500:10000);}}
async function act(payload){if(submitting)return;submitting=true;error('');if(data)render();try{const job=await api('/api/evolution/jobs',{...payload,request_id:'ui-'+crypto.randomUUID().replaceAll('-','')});selectedJob=job.id;showJob(job);$('detail-box').open=true;}catch(e){error(e.message);}finally{submitting=false;await load();if(data)render();}}
for(const el of [$('route'),$('enabled'),$('target')])el.addEventListener('change',()=>{dirty=true;if(data)render();});
$('policy').onsubmit=async event=>{event.preventDefault();if(submitting)return;submitting=true;error('');try{data=await api('/api/evolution/policy',{enabled:$('enabled').checked,route:$('route').value,target_revision:Number($('target').value)});dirty=false;}catch(e){error(e.message);}finally{submitting=false;if(data)render();}};
$('start').onclick=()=>act({action:'ensure',target_revision:Number($('target').value)});
$('check').onclick=()=>act({action:'check'});
$('rollback').onclick=()=>act({action:'rollback'});
$('execute').onclick=()=>{try{const input=JSON.parse($('input').value);act({action:'execute',input});}catch{error('请填写有效 JSON。');}};
$('stop').onclick=async()=>{const job=data?.jobs.find(x=>['QUEUED','RUNNING','OBSERVING'].includes(x.status));if(!job)return;try{await api('/api/evolution/cancel',{job_id:job.id});await load();}catch(e){error(e.message);}};
function sync(){const next=!document.hidden&&!view.hidden;if(next===visible)return;visible=next;if(visible)load();else clearTimeout(timer);}
document.addEventListener('jarvis:settings-view',sync);document.addEventListener('visibilitychange',sync);sync();
})();
