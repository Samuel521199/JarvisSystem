/* Layout owns visibility and dimensions; it never owns chat or file content. */
(()=>{'use strict';
const $=id=>document.getElementById(id),app=$('app'),sidebar=$('sidebar'),main=document.querySelector('main.workspace');
const defaults={side:248,dock:520,hidden:false},storage='jarvis.workbench.layout.v1';
let prefs={...defaults},panel=null,opened=false,full=false;
try{const p=JSON.parse(localStorage.getItem(storage)||'null');if(p&&typeof p==='object'){for(const k of ['side','dock'])if(Number.isFinite(p[k]))prefs[k]=p[k];prefs.hidden=p.hidden===true;}}catch{}
const clamp=(v,min,max)=>Math.min(Math.max(v,min),max),persist=()=>{try{localStorage.setItem(storage,JSON.stringify(prefs));}catch{}};
const row=document.createElement('div');row.id='workbench-row';$('chat-panel').before(row);row.append($('chat-panel'));
const notice=document.createElement('div');notice.id='page-reconnect';notice.hidden=true;notice.innerHTML='<span role="status">连接已更新，页面草稿仍然保留。</span><button type="button">重新连接</button>';row.before(notice);
notice.querySelector('button').onclick=async()=>{
 const button=notice.querySelector('button'),message=notice.querySelector('span');button.disabled=true;
 try{const r=await fetch('/',{cache:'no-store',credentials:'same-origin',redirect:'error',signal:AbortSignal.timeout(10000)});if(!r.ok)throw new Error();
  // Read inert markup only. Never execute the fetched document or replay a write.
  const html=await r.text(),match=html.match(/<meta name="jarvis-page-session" content="([A-Za-z0-9_-]{32,128})">/);
  if(!match)throw new Error();NONCE=match[1];notice.hidden=true;window.ProjectExplorer?.reconnected();window.notify?.('已重新连接，草稿保留。需要保存的内容请再次点击保存。');
 }catch{message.textContent='连接暂不可用，草稿保留，请稍后重试。';}finally{button.disabled=false;}
};
function separator(id,label,controls){const e=document.createElement('div');e.id=id;e.className='workbench-separator';e.tabIndex=0;e.setAttribute('role','separator');e.setAttribute('aria-orientation','vertical');e.setAttribute('aria-label',label);e.setAttribute('aria-controls',controls);e.title='拖动调整宽度 · 方向键微调 · 双击恢复默认';return e;}
const sideGrip=separator('sidebar-resize','调整左侧导航宽度','sidebar'),dockGrip=separator('dock-resize','调整右侧工作区宽度','explorer-panel');sidebar.after(sideGrip);row.append(dockGrip);dockGrip.hidden=true;
function limits(kind){return kind==='side'?[180,Math.min(360,Math.max(180,app.clientWidth-380))]:[320,Math.max(320,row.clientWidth-366)];}
function render(){
 const overlay=app.clientWidth<900;app.classList.toggle('sidebar-overlay',overlay);app.classList.toggle('sidebar-hidden',prefs.hidden&&!overlay);
 sidebar.style.width=clamp(prefs.side,...limits('side'))+'px';sideGrip.hidden=overlay||prefs.hidden;
 const compact=row.clientWidth<720;row.dataset.mode=!opened?'chat':full||compact?'focus':'split';
 if(panel){panel.hidden=!opened;panel.style.width=clamp(prefs.dock,...limits('dock'))+'px';}
 $('chat-panel').hidden=opened&&(full||compact);dockGrip.hidden=!opened||full||compact;
 for(const [kind,grip] of [['side',sideGrip],['dock',dockGrip]]){const [min,max]=limits(kind);grip.setAttribute('aria-valuemin',min);grip.setAttribute('aria-valuemax',max);grip.setAttribute('aria-valuenow',Math.round(clamp(prefs[kind],min,max)));grip.setAttribute('aria-valuetext',Math.round(clamp(prefs[kind],min,max))+' 像素');}
 const expanded=overlay?app.classList.contains('sidebar-open'):!prefs.hidden;$('sidebar-toggle').setAttribute('aria-expanded',String(expanded));$('sidebar-toggle').setAttribute('aria-label',expanded?'收起左侧导航':'展开左侧导航');
 $('open-explorer').setAttribute('aria-expanded',String(opened));$('open-explorer').setAttribute('aria-pressed',String(opened));
 const focus=$('explorer-focus');if(focus){focus.textContent=full?'恢复并排':'放大';focus.hidden=compact;focus.disabled=compact;focus.setAttribute('aria-pressed',String(full));focus.title=compact?'窗口较窄，已使用完整工作区':'切换并排 / 专注文件';}
}
function bind(grip,kind,direction){let drag=null;
 grip.addEventListener('pointerdown',e=>{if(e.button!==0)return;e.preventDefault();grip.focus();drag={id:e.pointerId,x:e.clientX,width:kind==='side'?sidebar.getBoundingClientRect().width:panel.getBoundingClientRect().width};grip.setPointerCapture(e.pointerId);app.classList.add('resizing');});
 grip.addEventListener('pointermove',e=>{if(!drag||drag.id!==e.pointerId)return;prefs[kind]=clamp(drag.width+direction*(e.clientX-drag.x),...limits(kind));render();});
 const finish=()=>{if(!drag)return;drag=null;app.classList.remove('resizing');persist();};
 grip.addEventListener('pointerup',finish);grip.addEventListener('pointercancel',finish);grip.addEventListener('lostpointercapture',finish);
 grip.addEventListener('dblclick',()=>{prefs[kind]=defaults[kind];render();persist();});
 grip.addEventListener('keydown',e=>{if(!['ArrowLeft','ArrowRight','Home','End'].includes(e.key))return;e.preventDefault();const [min,max]=limits(kind),current=Number(grip.getAttribute('aria-valuenow'));prefs[kind]=e.key==='Home'?min:e.key==='End'?max:clamp(current+(e.key==='ArrowRight'?1:-1)*direction*(e.shiftKey?40:10),min,max);render();persist();});
}
bind(sideGrip,'side',1);bind(dockGrip,'dock',-1);
function toggleSidebar(){if(app.clientWidth<900)app.classList.toggle('sidebar-open');else{prefs.hidden=!prefs.hidden;persist();}render();}
function show(value){opened=Boolean(value&&panel);if(opened)window.closeSidebar?.();render();}
window.Workbench={attach(element){panel=element;row.append(element);render();},show,toggleSidebar,focus(){full=!full;render();},sessionExpired(){notice.hidden=false;},reset(){prefs={...defaults};full=false;persist();render();}};
const opener=$('open-explorer');
new ResizeObserver(render).observe(main);window.addEventListener('resize',render);
document.addEventListener('keydown',e=>{if(document.querySelector('dialog[open]'))return;if(e.altKey&&(e.ctrlKey||e.metaKey)&&e.key.toLowerCase()==='b'){e.preventDefault();toggleSidebar();}if(e.altKey&&(e.ctrlKey||e.metaKey)&&e.key.toLowerCase()==='e'){e.preventDefault();if(!opener.hidden)opener.click();}});
render();
})();
