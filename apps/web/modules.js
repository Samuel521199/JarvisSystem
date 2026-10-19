/* Independent settings view: cached observations, no cloud/model probe on open. */
(()=>{'use strict';
const $=id=>document.getElementById(id), nonce=document.querySelector('meta[name="jarvis-nonce"]').content;
let data=null,timer=null,controller=null,visible=false,submitting=false;
const health={ready:'就绪',unavailable:'不可用',offline:'离线',unknown:'观察失败',not_implemented:'尚未实现'};
const activity={running:'运行中',busy:'正在使用',standby:'待命',unused:'近期未使用',on_demand:'按需执行',service_online:'服务在线',offline:'服务离线',not_integrated:'未接入',unknown:'未知'};
const modes={planned:'尚未实现',bundled:'随运行包更新',configuration:'配置即时生效',external:'外部组件 · 暂无页面升级入口'};
const actions={install:'导入候选包',health:'验证候选',select:'选择下次启动版本',rollback:'恢复上次选择','local-start':'启动本地模型','local-stop':'停止本地模型'};
const states={installed:'待验证',verified:'验证通过',failed:'验证失败'};
const jobStates={RUNNING:'处理中',SUCCEEDED:'已完成',FAILED:'失败',UNKNOWN:'结果待核对'};
const esc=x=>String(x??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const date=x=>x?new Date(x).toLocaleString('zh-CN',{hour12:false}):'暂无记录';
const busy=m=>m.active>0||m.activity==='running';
const attention=m=>m.health!=='ready'&&m.health!=='not_implemented';
function error(message){$('module-error').textContent=message;$('module-error').hidden=!message;}
function tag(label,kind='off'){return `<span class="tag ${kind}">${esc(label)}</span>`;}
function storeMetadata(m){
 if(m.record_count==null)return '';
 return `<dl><dt>${esc(m.records_label)}</dt><dd>${esc(m.record_count)} 项${m.record_count===1000?'（达到观察上限）':''}</dd><dt>存储状态</dt><dd>${m.storage_state==='not_created'?'首次使用时创建':'可读取 · 版本兼容'}</dd><dt>最近记录修改</dt><dd>${esc(date(m.last_changed))}</dd></dl>`;
}
function localControls(m){
 if(m.id!=='local-llm'||!m.runtime)return '';
 const locked=submitting||data?.maintenance_busy;
 return `<div class="module-release-actions"><button class="secondary" data-release-action="local-start" ${locked||m.runtime.owned||m.health==='ready'?'disabled':''}>启动本地模型</button><button class="secondary" data-release-action="local-stop" ${locked||!m.runtime.owned?'disabled':''}>停止本地模型</button><small>${m.runtime.state==='starting'?'正在校验 / 加载':m.runtime.owned?'本实例管理 · CPU 4 线程':m.health==='ready'?'外部服务 · 不接管':'未加载 · 按需启动'}</small></div>`;
}
function renderCatalog(){
 const c=data?.catalog,query=$('seed-query').value.trim().toLowerCase();
 $('seed-status').textContent=c?.status==='ready'?`已校验 · 种子 ${c.seed_version}`:c?'不可用':'采集中';
 $('seed-notice').textContent=(c?.message||'正在读取发布种子。')+' 此处展示本机资料；三库查询本身不执行工具。规则条文保留 K0/K1 基线，当前受限任务与成长能力以宿主入口及执行前检查为准。';
 const labels={available:'本机入口',conditional:'执行前检查',internal:'宿主内部',planned:'规划中',unavailable:'不可用'};
 const includes=x=>!query||x.toLowerCase().includes(query);
 const groups=[['能力',(c?.capabilities||[]).filter(x=>includes(x.id+' '+x.description)).map(x=>`<article><strong>${esc(x.id)} ${tag(labels[x.status]||'未知',x.status==='available'?'ok':'off')}</strong><p>${esc(x.description)}</p><small>${esc(x.reason)} · ${esc(x.version)}</small></article>`)],
 ['种子技能',(c?.skills||[]).filter(x=>includes(x.id+' '+x.description)).map(x=>`<article><strong>${esc(x.description)} ${tag(labels[x.status]||'未知')}</strong><small>${esc(x.id)} · ${esc(x.version)} · ${esc(x.capability_refs.join(', '))}</small></article>`)],
 ['种子知识',(c?.knowledge||[]).filter(x=>includes(x.record_id+' '+x.content)).map(x=>`<article><strong>${esc(x.record_id)}</strong><p>${esc(x.content)}</p><small>${esc(x.source)} · ${esc(x.version)} · ${esc(x.validity)} · 仅本机</small></article>`)],
 ['规则说明',(c?.rules||[]).filter(x=>includes(x.rule_id+' '+x.statement)).map(x=>`<article><strong>${esc(x.rule_id)}</strong><p>${esc(x.statement)}</p><small>${esc(x.source_ref)}</small></article>`)]];
 $('seed-content').innerHTML=groups.filter(([,rows])=>rows.length).map(([name,rows])=>`<section><h3>${esc(name)}</h3>${rows.join('')}</section>`).join('')||'<p class="muted">没有匹配条目；不会扩大搜索到其他文件。</p>';
}
function usageMetadata(m){
 const catalog=m.count_scope==='catalog',scope=m.count_scope==='host_lifetime'?'本次启动':catalog?'当前目录':'来源最近 1,000 条记录';
 return `<dt>${catalog?'完整用户技能':'使用次数'}</dt><dd>${m.recent_uses==null?'尚无使用计数':esc(m.recent_uses)+(catalog?' 项':' 次')+' · '+scope}</dd>${catalog?'':`<dt>最近使用</dt><dd>${esc(date(m.last_used))}</dd>`}`;
}
function renderModules(){
 const rows=data?.modules||[],filter=$('module-filter').value;
 const selected=rows.filter(m=>filter==='all'||filter==='busy'&&busy(m)||filter==='idle'&&['standby','unused','on_demand','service_online'].includes(m.activity)||filter==='attention'&&attention(m)||filter==='planned'&&m.health==='not_implemented');
 $('module-summary').innerHTML=[[rows.length,'已登记模块'],[rows.filter(busy).length,'正在使用 / 常驻'],[rows.filter(m=>m.installed===true).length,'已安装'],[rows.filter(attention).length,'需要关注']].map(([n,label])=>`<div class="module-stat"><strong>${n}</strong><span>${label}</span></div>`).join('');
 $('module-list').innerHTML=selected.map(m=>`<article class="module-card" data-module="${esc(m.id)}"><header><div><h2>${esc(m.name)}</h2><small>${esc(m.id)}</small></div>${tag(health[m.health]||'未知',m.health==='ready'?'ok':attention(m)?'warn':'off')}</header><div class="module-badges">${tag(m.installed===true?'已安装':m.installed===false?'未安装':'安装未知')}${tag(m.enabled===true?'已启用':m.enabled===false?'未启用':'启用未知')}${tag(activity[m.activity]||'未知',busy(m)?'ok':'off')}${m.active?tag('进行中 '+m.active,'ok'):''}</div><dl><dt>版本 / 引擎</dt><dd>${esc(m.version||'暂无版本')}</dd>${usageMetadata(m)}</dl>${storeMetadata(m)}${localControls(m)}<p>${esc(m.message)}</p><footer><span>${esc(modes[m.update_mode]||'暂未支持升级')}</span>${m.update_mode==='configuration'?'<a href="#connections">管理连接 →</a>':m.update_mode==='bundled'&&m.installed?'<a href="#module-import" data-module-upgrade>查看升级 ↓</a>':''}</footer></article>`).join('')||'<p class="empty">此分类暂无模块。</p>';
 renderCatalog();
}
function renderMaintenance(){
 const releases=data.releases||{},locked=submitting||data.maintenance_busy;
 // Preserve keyboard focus across polling. The path draft is outside rendered containers.
 const focus=document.activeElement?.dataset?.releaseAction,focusId=document.activeElement?.dataset?.release;
 $('module-selection').textContent=`当前服务 ${data.version} · 下次运行包启动：${releases.active||'尚未选择'}。${releases.error||''}`;
 if(releases.previous){const b=document.createElement('button');b.type='button';b.className='secondary';b.dataset.releaseAction='rollback';b.textContent='恢复上次选择';b.disabled=locked;$('module-selection').append(b);}
 $('module-releases').innerHTML=(releases.releases||[]).map(r=>`<div class="module-release"><div><strong>${esc(r.version)} ${tag(states[r.state]||r.state,r.state==='verified'?'ok':r.state==='failed'?'warn':'off')} ${r.id===releases.active?tag('下次启动','ok'):''}</strong><small>${esc(r.id)} · ${esc(date(r.created_at))}</small></div><div class="module-release-actions"><button class="secondary" data-release-action="health" data-release="${esc(r.id)}" ${locked?'disabled':''}>验证候选</button><button class="secondary" data-release-action="select" data-release="${esc(r.id)}" ${locked||r.state!=='verified'||r.id===releases.active?'disabled':''}>设为下次启动</button></div></div>`).join('')||'<p class="module-note">尚无候选运行包。导入和验证在独立维护通道执行。</p>';
 $('module-jobs').innerHTML=(data.maintenance||[]).map(j=>`<div class="module-job"><div><strong>${esc(actions[j.action]||j.action)} · ${esc(date(j.started_at))}</strong><p>${esc(j.message)}</p></div>${tag(jobStates[j.status]||j.status,j.status==='SUCCEEDED'?'ok':['FAILED','UNKNOWN'].includes(j.status)?'warn':'off')}</div>`).join('')||'<p class="module-note">还没有维护记录。</p>';
 $('module-import').querySelector('button').disabled=locked;
 if(focus){const el=[...document.querySelectorAll('[data-release-action]')].find(e=>e.dataset.releaseAction===focus&&e.dataset.release===focusId);if(el&&!el.disabled)el.focus({preventScroll:true});}
}
async function api(path,payload,signal){const response=await fetch(path,{method:payload===undefined?'GET':'POST',headers:{'X-Jarvis-Nonce':nonce,...(payload===undefined?{}:{'Content-Type':'application/json'})},body:payload===undefined?undefined:JSON.stringify(payload),signal});const value=await response.json();if(!response.ok)throw new Error(value.user_message||value.message||value.error?.message||'模块服务暂不可用');return value;}
function schedule(delay=8000){clearTimeout(timer);if(visible)timer=setTimeout(()=>load(),delay);}
async function load(force=false){
 if(!visible||controller)return;controller=new AbortController();const request=controller;const timeout=setTimeout(()=>request.abort(),5000);
 $('module-refresh').disabled=true;
 try{data=await api(force?'/api/modules/refresh':'/api/modules',force?{}:undefined,request.signal);error('');$('module-observed').textContent=(data.observed_at?'最近观察 '+date(data.observed_at):'首次采集中')+(data.refreshing?' · 正在更新':'')+(data.stale?' · 缓存待更新':'');renderModules();renderMaintenance();}
 catch(e){if(visible){error(e.name==='AbortError'?'读取超时，保留上次状态。稍后重试。':e.message);$('module-observed').textContent='状态可能过期 · '+(data?.observed_at?date(data.observed_at):'尚未读取');}}
 finally{clearTimeout(timeout);controller=null;$('module-refresh').disabled=false;schedule(data?.refreshing||data?.maintenance_busy?1200:8000);}
}
async function maintain(payload){
 if(submitting||data?.maintenance_busy)return;submitting=true;if(data){renderModules();renderMaintenance();}error('');
 try{await api('/api/modules/maintenance',payload);await load(true);}
 catch(e){error(e.message+'；若请求已发出但没有回执，请刷新维护记录，勿重复提交。');}
 finally{submitting=false;if(data){renderModules();renderMaintenance();}schedule(1200);}
}
function sync(){const next=!document.hidden&&!$('modules-view').hidden;if(next===visible)return;visible=next;if(visible)load();else{clearTimeout(timer);controller?.abort();}}
document.addEventListener('jarvis:settings-view',sync);document.addEventListener('visibilitychange',sync);
$('module-filter').addEventListener('change',renderModules);$('module-refresh').addEventListener('click',()=>load(true));
$('seed-query').addEventListener('input',renderCatalog);
$('module-import').addEventListener('submit',e=>{e.preventDefault();maintain({action:'install',archive:$('module-archive').value.trim()});});
$('modules-view').addEventListener('click',e=>{const link=e.target.closest('[data-module-upgrade]');if(link){e.preventDefault();$('module-import').scrollIntoView({behavior:'smooth',block:'center'});$('module-archive').focus({preventScroll:true});return;}const b=e.target.closest('[data-release-action]');if(!b||b.disabled)return;maintain({action:b.dataset.releaseAction,...(b.dataset.release?{release_id:b.dataset.release}:{})});});
sync();
})();
