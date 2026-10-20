/* One provenance journal; execution stays in the existing K4/K5 lanes. */
(() => {
  'use strict';
  const parent=document.getElementById('evolution-pane-evolve');if(!parent)return;
  const root=document.createElement('details');root.id='learning-loop-panel';
  root.innerHTML=`<summary>需求驱动的学习与改造</summary>
    <p>从具体问题出发，保留资料来源，审阅后交给现有工具成长或自身模块改造。浏览本页不调用模型，不启动定时学习。</p>
    <p data-message role="status" aria-live="polite"></p>
    <div data-opportunities></div>
    <label>关联会话<select data-conversation></select></label><label>实际问题或重复劳动<textarea data-goal rows="2" maxlength="1200"></textarea></label>
    <button type="button" data-create>记录学习需求</button><button type="button" data-refresh>刷新原回执</button>
    <label>学习需求<select data-demand></select></label>
    <div data-work hidden>
    <h3>1 · 查资料与保存证据</h3><label>技术库名称或 Context7 库 ID<input data-library placeholder="例如 Python"></label>
    <button type="button" data-research>通过现有 MCP 查询文档</button>
    <div data-libraries></div><button type="button" data-collect>将已完成的文档结果纳入候选</button>
    <p>需要先启用对应 MCP。查询进入原任务队列，结果可在原会话查看；同一需求重试查询不会产生新请求编号。</p>
    <label>资料来源<input data-source maxlength="500" placeholder="URL、资料标题或文档任务编号"></label>
    <label>理解、适用条件与疑点<textarea data-notes rows="4" maxlength="4000"></textarea></label>
    <label>已确认的文档任务 ID（可选）<input data-task placeholder="task_…"></label><button type="button" data-evidence>保存候选知识</button>
    <h3>2 · 审阅与交接</h3><label>审阅依据<textarea data-review rows="2" maxlength="1000"></textarea></label><button type="button" data-approve>确认当前来源适用于此需求</button>
    <label>改进目标<select data-target><option value="ranking">自身模块 · 检索排序</option><option value="tool">项目工具 · 按既有成长策略</option></select></label>
    <label>编码模型<select data-model></select></label><label>工具契约<select data-domain><option value="clean-lines">清理重复清单</option><option value="group-counts">分类数量汇总</option><option value="byte-total">文件大小汇总</option></select></label>
    <input data-policy type="hidden" value="0"><button type="button" data-load-policy>读取此会话的项目成长策略</button><p data-policy-status>项目工具需已有有效成长策略；检索排序不需要项目。</p>
    <button type="button" data-start>交给生成与独立评估</button>
    <p>工具沿用项目预授权、灰度和收益观察。检索候选在下方“自身模块改造”中审阅试用，实际观察后保留或回退；研究笔记不能改变验收标准。</p>
    <h3>3 · 真实效果与撤回</h3><label>使用反馈<textarea data-feedback rows="2"></textarea></label>
    <button type="button" data-useful>对我有用</button><button type="button" data-unhelpful>没有改善</button><button type="button" data-withdraw>撤回来源并停止相关改造</button>
    <p data-progress role="status"></p><details><summary>查看来源、交接与收益回执</summary><pre data-receipt tabindex="0"></pre></details></div>`;
  parent.append(root);
  const q=s=>root.querySelector(s),nonce=document.querySelector('meta[name="jarvis-nonce"]').content;
  let rows=[],busy=false,id='',requestId=null,dirty=false;
  function headers(){return {'X-Jarvis-Nonce':nonce,'Content-Type':'application/json'};}
  async function get(path){const r=await fetch(path,{headers:headers(),cache:'no-store',credentials:'omit'});const v=await r.json();if(!r.ok)throw new Error(v.user_message||v.message||'资料暂不可用');return v;}
  function options(select,items,value){select.replaceChildren(...items.map(([key,label])=>{const o=document.createElement('option');o.value=key;o.textContent=label;return o;}));if(items.some(x=>x[0]===value))select.value=value;}
  function render(){
    options(q('[data-demand]'),rows.map(r=>[r.id,r.goal]),id);id=q('[data-demand]').value;
    const row=rows.find(r=>r.id===id);q('[data-work]').hidden=!row;
    q('[data-libraries]').replaceChildren();
    for(const library of row?.research_candidates||[]){
      const b=document.createElement('button');b.type='button';b.textContent='查询 '+library;
      b.onclick=()=>act('research',{library});q('[data-libraries]').append(b);
    }
    q('[data-receipt]').textContent=row?JSON.stringify(row,null,2):'';
    const labels={DRAFT:'等待资料',EVIDENCE_READY:'来源已保存，等待审阅',REVIEWED:'当前来源已审阅',HANDOFF:'已交给改造流程',WITHDRAWN:'来源已撤回'};
    q('[data-progress]').textContent=row?(labels[row.state]||row.state)+(row.outcome?' · 原执行器：'+row.outcome.status:''):'';
    root.querySelectorAll('input,textarea,button,select').forEach(e=>e.disabled=busy);
    q('[data-start]').disabled=busy||!row||!['REVIEWED','HANDOFF'].includes(row.state);
  }
  async function reload(){
    const data=await get('/api/evolution/learning');rows=data.demands;
    q('[data-opportunities]').replaceChildren();
    for(const item of data.opportunities||[]){
      const p=document.createElement('p'),b=document.createElement('button');b.type='button';
      p.textContent=item.reason+'：'+item.goal;b.textContent='纳入学习';
      b.onclick=()=>act('capture',{id:crypto.randomUUID().replaceAll('-',''),task_id:item.task_id});
      p.append(b);q('[data-opportunities]').append(p);
    }
    render();
  }
  async function act(action,extra={}){
    if(busy)return;busy=true;render();
    try{
      const r=await fetch('/api/evolution/learning',{method:'POST',headers:headers(),credentials:'omit',
        body:JSON.stringify({action,id,...extra})});const v=await r.json();
      if(!r.ok)throw new Error(v.user_message||v.message||'学习交接未完成；请核对原回执');
      id=v.id;if(action==='create')requestId=null;
      if(action==='collect'){
        q('[data-source]').value=v.evidence.source;q('[data-notes]').value=v.evidence.notes;
        q('[data-task]').value=v.evidence.artifact?.task_id||'';
      }
      dirty=false;
      await reload();q('[data-message]').textContent='已保存。生成、试用和收益以原执行器回执为准。';
    }catch(e){q('[data-message]').textContent=e.message;}finally{busy=false;render();}
  }
  q('[data-create]').onclick=()=>{requestId ||= crypto.randomUUID().replaceAll('-','');act('create',{id:requestId,goal:q('[data-goal]').value,conversation_id:q('[data-conversation]').value});};
  q('[data-goal]').oninput=()=>{requestId=null;};q('[data-conversation]').onchange=()=>{requestId=null;};
  q('[data-demand]').onchange=()=>{
    if(dirty&&!confirm('研究笔记或审阅尚未保存，放弃并切换？')){q('[data-demand]').value=id;return;}
    id=q('[data-demand]').value;dirty=false;
    const row=rows.find(r=>r.id===id);
    q('[data-source]').value=row?.evidence?.source||'';q('[data-notes]').value=row?.evidence?.notes||'';
    q('[data-task]').value=row?.evidence?.artifact?.task_id||'';q('[data-review]').value=row?.review?.note||'';
    q('[data-feedback]').value=row?.feedback?.note||'';render();
  };
  q('[data-refresh]').onclick=()=>reload().catch(e=>q('[data-message]').textContent=e.message);
  q('[data-research]').onclick=()=>act('research',{library:q('[data-library]').value});
  q('[data-collect]').onclick=()=>act('collect');
  q('[data-evidence]').onclick=()=>act('evidence',{source:q('[data-source]').value,notes:q('[data-notes]').value,task_id:q('[data-task]').value||null});
  q('[data-approve]').onclick=()=>act('review',{note:q('[data-review]').value});
  q('[data-start]').onclick=()=>act('start',{target:q('[data-target]').value,model:q('[data-model]').value,domain:q('[data-domain]').value,policy_revision:Number(q('[data-policy]').value)});
  for(const [selector,useful] of [['[data-useful]',true],['[data-unhelpful]',false]])
    q(selector).onclick=()=>act('feedback',{useful,note:q('[data-feedback]').value});
  q('[data-withdraw]').onclick=()=>act('withdraw');
  q('[data-load-policy]').onclick=async()=>{
    const row=rows.find(r=>r.id===id);if(!row)return;
    try{const info=await get('/api/project-tools/'+row.conversation_id+'/growth');
      q('[data-policy]').value=info.policy.revision;
      q('[data-policy-status]').textContent=info.policy.enabled?'已读取授权策略；开始时会再次核对有效期与任务域。':'此项目尚未授权成长；请先在项目工具库设置可持续成长策略。';
    }catch(e){q('[data-policy-status]').textContent=e.message;}
  };
  for(const field of ['source','notes','task','review','feedback'])q('[data-'+field+']').addEventListener('input',()=>{dirty=true;});
  window.addEventListener('beforeunload',e=>{if(dirty){e.preventDefault();e.returnValue='';}});
  root.addEventListener('toggle',async()=>{
    if(!root.open||busy)return;
    try{
      await reload();
      const chats=await get('/api/conversations');
      options(q('[data-conversation]'),(chats.conversations||chats.chats||[]).map(c=>[c.id,c.title||c.id]),q('[data-conversation]').value);
      const catalog=await get('/api/models');
      const model=document.getElementById('ranking-model');
      options(q('[data-model]'),(catalog.models||[]).map(m=>[m.provider+'::'+m.model,(m.label||m.model)+' · '+m.provider]),model?.value||'');
    }catch(e){q('[data-message]').textContent=e.message;}
  });
})();
