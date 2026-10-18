"use strict";
(() => {
  const queues=new Map(),versions=new Map();
  async function api(path,payload){
    const control=new AbortController(),timer=setTimeout(()=>control.abort(),8000);
    try{
      const response=await fetch('/api/conversations'+path,{method:payload===undefined?'GET':'POST',credentials:'omit',cache:'no-store',headers:{'X-Jarvis-Nonce':NONCE,...(payload===undefined?{}:{'Content-Type':'application/json'})},body:payload===undefined?undefined:JSON.stringify(payload),signal:control.signal});
      const data=await response.json();if(!response.ok)throw new Error(data.user_message||'会话归档暂不可用。');return data;
    }catch(error){if(error.name==='AbortError')throw new Error('本机会话保存未确认，请重试；当前内容仍保留在页面。');throw error;}
    finally{clearTimeout(timer);}
  }
  function serial(id,work){const next=(queues.get(id)||Promise.resolve()).catch(()=>{}).then(work);queues.set(id,next);next.finally(()=>{if(queues.get(id)===next)queues.delete(id);}).catch(()=>{});return next;}
  function capture(){return Array.from(document.querySelectorAll('#messages > .message')).map(node=>({role:['user','assistant','error','stopped'].find(role=>node.classList.contains(role))||'error',content:node.querySelector('.bubble')?.textContent||'',meta:node.querySelector('.message-meta p')?.textContent||'',short_meta:node.querySelector('.message-meta summary')?.textContent||'',attachments_omitted:node.dataset.attachmentsOmitted==='true'||Boolean(node.querySelector('.message-attachments')),incomplete:node.classList.contains('incomplete'),...(node.dataset.replyRef?{reply_ref:node.dataset.replyRef}:{}),...(node.dataset.growthRef?{growth_ref:node.dataset.growthRef}:{}),...(node.dataset.growthRequestId?{growth_request_id:node.dataset.growthRequestId}:{}),...(node.dataset.personalControl==='true'?{personal_control:true}:{}),...(node.dataset.taskControl==='true'?{task_control:true}:{}),...(node.dataset.taskRef?{task_ref:node.dataset.taskRef}:{}),...(node.dataset.taskRequestId?{task_request_id:node.dataset.taskRequestId}:{}),...(node.dataset.knowledgeRefs?{knowledge_refs:JSON.parse(node.dataset.knowledgeRefs)}:{}),...(node.dataset.knowledgeCitations?{knowledge_citations:JSON.parse(node.dataset.knowledgeCitations)}:{}),...(node.dataset.continuityRefs?{continuity_refs:JSON.parse(node.dataset.continuityRefs)}:{}),...(node.dataset.memoryRefs?{memory_refs:JSON.parse(node.dataset.memoryRefs)}:{})}));}
  window.Conversations={capture,async flush(){await Promise.all([...queues.values()]);},
    async list(){const data=await api('');for(const row of data.conversations)versions.set(row.id,row.revision);return data.conversations;},
    async load(id){const data=await api('/'+id);versions.set(id,data.revision);return data.document;},
    save(id,document){return serial(id,async()=>{const data=await api('/'+id,{revision:versions.get(id)||0,document});versions.set(id,data.revision);return data;});},
    remove(id){return serial(id,async()=>{const data=await api('/'+id+'/delete',{revision:versions.get(id)||0});versions.delete(id);return data;});}
  };
})();
