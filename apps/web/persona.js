"use strict";
(() => {
  const el=id=>document.getElementById(id),panel=el('persona-panel');
  let revision=null,working=false,pending=null;
  const status=(text,error=false)=>{el('persona-status').textContent=text;el('persona-status').dataset.error=String(error);};
  const temporary=()=>Boolean(window.Workspace?.memoryContext?.().temporary);
  function controls(){for(const input of panel.querySelectorAll('input,select,button'))input.disabled=working||temporary()||(revision===null&&input.id!=='persona-reload');}
  async function api(payload){
    const control=new AbortController(),timer=setTimeout(()=>control.abort(),10000);
    try{
      const response=await fetch('/api/persona',{method:payload?'POST':'GET',credentials:'omit',cache:'no-store',signal:control.signal,
        headers:{'X-Jarvis-Nonce':NONCE,...(payload?{'Content-Type':'application/json'}:{})},body:payload?JSON.stringify(payload):undefined});
      const data=await response.json();if(!response.ok)throw new Error(data.user_message||'交流设置操作未确认。');
      if(data.schema_version!==2)throw new Error('宿主尚未支持这版交流配置，请重启后刷新。');return data;
    }catch(error){if(error.name==='AbortError')throw new Error('结果尚未确认，输入已保留。原样重试会复用请求标识。');throw error;}
    finally{clearTimeout(timer);}
  }
  async function load(preserve=false){
    const data=await api();revision=data.revision;
    if(!preserve){el('persona-name').value=data.preferred_name;el('persona-style').value=data.style;el('persona-relationship').value=data.relationship;pending=null;}
    el('persona-version').textContent='当前修订 '+revision;controls();
  }
  async function change(action){
    if(working||temporary()||revision===null)return;
    const profile=action==='profile'?{preferred_name:el('persona-name').value.trim(),style:el('persona-style').value,relationship:el('persona-relationship').value}:null;
    const encoded=JSON.stringify({action,revision,profile});
    if(!pending||pending.encoded!==encoded)pending={encoded,payload:{action,revision,profile,request_id:crypto.randomUUID().replaceAll('-','')}};
    working=true;controls();status('正在保存…');
    try{await api(pending.payload);pending=null;await load();status('已保存。从下一轮普通对话开始使用，事实与任务保持不变。');}
    catch(error){status(error.message,true);}finally{working=false;controls();}
  }
  el('persona-form').addEventListener('submit',event=>{event.preventDefault();change('profile');});
  el('persona-undo').addEventListener('click',()=>change('undo'));
  el('persona-reset').addEventListener('click',()=>change('reset'));
  el('persona-reload').addEventListener('click',async()=>{
    if(working)return;working=true;controls();
    try{await load(true);status('已核对当前修订，编辑区保留；请确认后再保存。');}
    catch(error){status(error.message,true);}finally{working=false;controls();}
  });
  window.PersonaPanel={controls,open:async()=>{
    if(working)return;
    if(temporary()){controls();status('临时会话不读取或修改交流设置。');return;}
    working=true;controls();status('正在读取交流设置…');
    try{await load();status('称呼和表达用于普通对话，包括所选云端模型；不改变身份、事实或权限。');}
    catch(error){status(error.message,true);}finally{working=false;controls();}
  }};
})();
