"use strict";
(() => {
  const dialog=document.createElement('dialog');dialog.id='personal-candidates';dialog.className='candidate-dialog';
  const heading=document.createElement('div');heading.className='candidate-heading';
  const title=document.createElement('h2');title.id='candidate-heading';title.textContent='整理为记忆与未结事项';dialog.setAttribute('aria-labelledby',title.id);
  const close=document.createElement('button');close.type='button';close.textContent='关闭';heading.append(title,close);
  const hint=document.createElement('p');hint.textContent='先用本机规则整理，不消耗模型用量。也可按需让模型提取事实候选；核对原句、主体和用途后再保存。未结事项仍由本机规则整理，不会启动任务或提醒。';
  const source=document.createElement('blockquote'),status=document.createElement('p'),list=document.createElement('div');status.setAttribute('role','status');list.id='candidate-list';
  const toolbar=document.createElement('details');toolbar.className='candidate-model-tools';toolbar.id='candidate-model-tools';toolbar.open=true;
  const modelSummary=document.createElement('summary');modelSummary.textContent='选择语义整理模型';toolbar.append(modelSummary);
  const modelLabel=document.createElement('label'),model=document.createElement('select');model.id='candidate-model';modelLabel.textContent='语义整理模型';modelLabel.append(model);
  const levelLabel=document.createElement('label'),level=document.createElement('select');level.id='candidate-reasoning';levelLabel.textContent='推理档位';levelLabel.append(level);
  const disclosure=document.createElement('p');disclosure.id='candidate-disclosure';
  const generate=document.createElement('button'),stop=document.createElement('button');generate.type=stop.type='button';generate.id='candidate-generate';stop.id='candidate-stop';generate.textContent='用此模型重新整理事实';stop.textContent='停止整理';stop.hidden=true;
  toolbar.append(modelLabel,levelLabel,disclosure);
  const modelActions=document.createElement('div');modelActions.className='candidate-actions';modelActions.append(generate,stop);
  dialog.append(heading,hint,source,toolbar,modelActions,status,list);document.body.append(dialog);
  let working=false,context=null,run=null,query=null;
  const labels={personal_fact:'主人事实',preference:'个人偏好',episode:'个人经历',shared_experience:'共同经历',project_fact:'项目事实',work_result:'工作结果',third_party:'他人信息',fiction:'虚构角色'};
  const subjects={personal_fact:'owner',preference:'owner',episode:'owner',shared_experience:'owner',project_fact:'project',work_result:'project',third_party:'other',fiction:'character'};
  function controls(){
    for(const e of dialog.querySelectorAll('button,input,textarea,select'))e.disabled=working||e.dataset.saved==='true'||e.dataset.previewStale==='true';
    generate.disabled=working||!context||!model.value;stop.disabled=!run;stop.hidden=!run;close.disabled=working&&!run;
  }
  async function api(action,payload,signal){
    const response=await fetch('/api/personal-candidates/'+action,{method:'POST',credentials:'omit',cache:'no-store',headers:{'X-Jarvis-Nonce':NONCE,'Content-Type':'application/json'},body:JSON.stringify(payload),signal:signal||AbortSignal.timeout(12000)});
    const value=await response.json();if(!response.ok){const error=new Error(value.user_message||'操作未确认，请在记忆面板核对。');error.code=value.error_category;throw error;}return value;
  }
  function field(card,label,value,max,multiline=false){const l=document.createElement('label'),input=document.createElement(multiline?'textarea':'input');l.textContent=label;input.value=value;input.maxLength=max;if(multiline)input.rows=3;l.append(input);card.append(l);return input;}
  function choice(card,text,checked){const label=document.createElement('label'),input=document.createElement('input');label.className='candidate-check';input.type='checkbox';input.checked=checked;label.append(input,document.createTextNode(text));card.append(label);return input;}
  function configureLevels(){
    const item=modelCatalog.find(x=>modelKey(x)===model.value),levels=item?.reasoning_levels||[];
    level.replaceChildren();for(const v of levels.length?levels:[''])level.add(new Option(levelNames[v]||'固定模式',v));
    if(levels.length)level.value=item.reasoning_default;
    modelSummary.textContent=item?'语义整理模型：'+(item.label||item.model):'选择语义整理模型';
    disclosure.textContent=item?'点击后会把上方整条原文发送到 '+(names[item.provider]||item.provider)+' / '+item.model+'；不附带历史、其他记忆、项目文件或技能，不自动切换供应商。保存后仍默认仅本地使用。':'请等待模型目录加载。';
    controls();
  }
  function selectModels(){
    model.replaceChildren();for(const item of modelCatalog)model.add(new Option((names[item.provider]||item.provider)+' · '+(item.label||item.model),modelKey(item)));
    const selected=chosenModel();if(selected)model.value=modelKey(selected);
    configureLevels();
  }
  function sameConversation(){return Workspace.currentConversation().id===query?.source.conversation_id&&!Workspace.currentConversation().temporary&&window.MemoryPanel?.context()?.enabled;}
  function render(data,semantic=false){
    list.replaceChildren();
    for(const item of data.candidates){
      const card=document.createElement('article');card.className='candidate-card';
      const type=document.createElement('strong');type.textContent=semantic?'模型提出的事实候选':item.kind==='fact'?'规则提出的事实候选':'候选未结事项';card.append(type);
      if(semantic){const quote=document.createElement('blockquote');quote.textContent='原句：'+item.quote;card.append(quote);}
      const name=field(card,'名称',item.title,60),content=field(card,item.kind==='continuity'?'当前记录':'记忆内容',item.content,1024,true);
      const next=item.kind==='continuity'?field(card,'下一步（不会自动执行）',item.next_step,512,true):null;
      const scope=document.createElement('select'),scopeLabel=document.createElement('label');scopeLabel.textContent='使用范围';scope.setAttribute('aria-label','使用范围');
      scope.add(new Option(data.project_id?'当前项目':'普通个人会话','current'));
      if((semantic||item.kind==='fact')&&data.project_id)scope.add(new Option('通用个人记忆','global'));scopeLabel.append(scope);card.append(scopeLabel);
      let category,subject,daily,work;
      if(semantic){
        const label=document.createElement('label');label.textContent='类型 / 主体';category=document.createElement('select');category.setAttribute('aria-label','类型 / 主体');
        for(const [k,v] of Object.entries(labels))if(data.project_id||subjects[k]!=='project')category.add(new Option(v,k));
        category.value=item.classification.kind;label.append(category);card.append(label);
        subject=field(card,'他人或角色名称',item.classification.subject_label,80);
        daily=choice(card,'用于我的日常聊天',item.classification.uses.includes('personal_chat'));work=choice(card,'用于协助我的工作',item.classification.uses.includes('work_assist'));
        const note=document.createElement('p');note.textContent='两项都不选则仅保存。虚构角色只保存；“工作结果”只是你确认的记录，不证明任务已执行。';card.append(note);
        function update(reset){
          const k=category.value,other=['other','character'].includes(subjects[k]);subject.parentElement.hidden=!other;if(!other)subject.value='';
          if(reset){daily.checked=subjects[k]==='owner';work.checked=subjects[k]==='project';}
          if(k==='fiction'){daily.checked=work.checked=false;}
          daily.disabled=work.disabled=k==='fiction';
          if(subjects[k]==='project')scope.value='current';
          scope.disabled=subjects[k]==='project';
        }
        category.onchange=()=>update(true);update(false);
        card._policyControls=()=>update(false);
      }
      const actions=document.createElement('div'),save=document.createElement('button'),ignore=document.createElement('button'),receipt=document.createElement('p');actions.className='candidate-actions';save.type=ignore.type='button';save.textContent='确认并保存';ignore.textContent='忽略';actions.append(save,ignore);card.append(actions,receipt);list.append(card);
      save.dataset.candidateSave='true';
      ignore.onclick=()=>card.remove();
      const reviewPanel=document.createElement('section');reviewPanel.className='candidate-review';reviewPanel.hidden=true;card.insertBefore(reviewPanel,actions);
      let checked=null,pending=null;
      function payload(){return semantic?{preview_token:data.preview_token,candidate_id:item.candidate_id,title:name.value,content:content.value,scope:scope.value,
        classification:{kind:category.value,subject:subjects[category.value],subject_label:subject.value,uses:category.value==='fiction'?[]:[...(daily.checked?['personal_chat']:[]),...(work.checked?['work_assist']:[])],expires_at:null}}
        :{source:data.source,project_id:data.project_id,source_digest:data.source_digest,scope:scope.value,candidate:{kind:item.kind,title:name.value,content:content.value,next_step:next?.value||'',candidate_id:item.candidate_id}};}
      function completed(result){
        receipt.textContent=result.text;actions.remove();reviewPanel.remove();pending=null;
        for(const el of card.querySelectorAll('input,textarea,select'))el.dataset.saved='true';
      }
      async function resolve(decision,target=null){
        pending={review_token:checked.review_token,decision,target_id:target};
        completed(await api('semantic-resolve',pending));
      }
      async function perform(task){
        if(working)return;if(!sameConversation()){status.textContent='会话或记忆开关已变化，请重新整理。';return;}
        working=true;controls();receipt.textContent='正在本机核对…';
        try{await task();}
        catch(e){
          if(e.code)pending=null;
          if(e.code==='candidate_review_changed'){
            for(const button of list.querySelectorAll('[data-candidate-save]'))button.dataset.previewStale='true';
            receipt.textContent=e.message;
            status.textContent='记忆已经变化，本批旧预览停止保存，编辑内容仍保留。请核对后点击“用此模型重新整理事实”；不会自动调用模型。';
          }else receipt.textContent=e.message+' 重试相同内容使用同一回执；如结果不确定，请在记忆面板核对。';
          if(pending)save.textContent='重试同一次保存';
        }
        finally{working=false;controls();policyControls();}
      }
      function showReview(result){
        checked=result;reviewPanel.replaceChildren();reviewPanel.hidden=false;
        const heading=document.createElement('strong');heading.textContent=result.matches.length?'已有记忆 · 请决定如何处理':'未发现相近记录';reviewPanel.append(heading);
        const hint=document.createElement('p');hint.textContent='本机词项核对，不调用模型。提示不代表已经判断出矛盾；不会自动合并。';reviewPanel.append(hint);
        const proposed=document.createElement('blockquote');proposed.className='candidate-proposed';proposed.textContent='本次候选：'+content.value;reviewPanel.append(proposed);
        const relationNames={duplicate:'重复表达',unclassified:'相同内容 · 旧记录未分类',possible_change:'可能发生变化',possible_addition:'可能补充',related:'相关内容 · 待核对'};
        for(const match of result.matches){
          const old=document.createElement('article');old.className='candidate-existing';
          const label=document.createElement('strong');label.textContent=relationNames[match.relation];
          const title=document.createElement('p');title.textContent=match.document.title+' · 修订 '+match.revision;
          const body=document.createElement('blockquote');body.textContent=match.document.content;
          const reason=document.createElement('p');reason.textContent=match.reason;
          const origin=document.createElement('details'),summary=document.createElement('summary'),quote=document.createElement('p');summary.textContent='查看已有记忆的来源与权限';
          const policy=match.document.classification;
          quote.textContent=(match.provenance?.excerpt?'来源原文：'+match.provenance.excerpt:'来源：独立保存或主人已纠正。')+'\n保留类型：'+(labels[policy?.kind]||'未分类')+'；用途：'+(policy?.uses?.map(x=>({personal_chat:'日常聊天',work_assist:'工作协助'}[x]||x)).join('、')||(policy?'仅保存':'沿用旧记录'))+'；接入方：'+(match.document.providers.map(x=>names[x]||x).join('、')||'仅本地')+'；有效期：'+(policy?.expires_at||'未设到期时间')+'。';origin.append(summary,quote);
          const action=document.createElement('button');action.type='button';action.dataset.candidateSave='true';
          const keep=['duplicate','unclassified'].includes(match.relation);action.textContent=keep?'沿用已有记忆':'用上方内容更新这条';
          action.onclick=()=>perform(()=>resolve(keep?'keep':'replace',match.id));
          old.append(label,title,body,reason,origin,action);reviewPanel.append(old);
        }
        if(result.truncated||result.source_unusable){const note=document.createElement('p');note.textContent=(result.truncated?'共找到 '+result.total_matches+' 条，先显示 5 条。':'')+(result.source_unusable?'另有 '+result.source_unusable+' 条来源失效或未完成核查的记录未参与比较。':'')+'可在记忆面板继续核对。';reviewPanel.append(note);}
        if(!result.matches.some(x=>x.relation==='duplicate')){
          const fresh=document.createElement('button');fresh.type='button';fresh.textContent=result.matches.length?'另存一条新记忆':'保存为新记忆';fresh.dataset.candidateSave='true';fresh.onclick=()=>perform(()=>resolve('new'));reviewPanel.append(fresh);
        }
        receipt.textContent='核对完成，尚未保存。更新仅替换旧记忆内容与来源，沿用其名称、分类、用途、有效期和权限。上方用途设置用于另存新记忆；另存时请使用不同名称。';
      }
      if(semantic){
        const check=document.createElement('button');check.type='button';check.textContent='核对已有记忆';check.dataset.candidateSave='true';actions.prepend(check);
        check.onclick=()=>perform(async()=>showReview(await api('semantic-review',payload())));
        card.addEventListener('input',e=>{if(!e.target.matches('input,textarea,select'))return;checked=pending=null;reviewPanel.hidden=true;reviewPanel.replaceChildren();save.textContent='确认并保存';receipt.textContent='内容已编辑，保存前会重新在本机核对。';});
      }
      save.onclick=()=>perform(async()=>{
        if(!semantic){completed(await api('confirm',payload()));return;}
        if(pending){completed(await api('semantic-resolve',pending));return;}
        const result=await api('semantic-review',payload());showReview(result);
        if(!result.matches.length)await resolve('new');
      });
    }
    policyControls();
  }
  function policyControls(){if(!working)for(const card of list.children)if(!card.querySelector('[data-saved]'))card._policyControls?.();}
  async function open(node){
    if(busy||working||Workspace.isBusy())return;
    const current=Workspace.currentConversation();
    if(current.temporary){notify('临时会话不整理持久候选。');return;}
    if(!window.MemoryPanel?.context()?.enabled){notify('请先在记忆面板启用普通会话记忆。');return;}
    working=true;context=null;toolbar.open=true;list.replaceChildren();source.textContent='';status.textContent='正在读取已保存的来源消息…';dialog.showModal();controls();
    try{
      await Workspace.flushConversation();
      const index=Array.from(document.querySelectorAll('#messages > .message')).indexOf(node);
      query={source:{conversation_id:current.id,message_index:index},project_id:Workspace.memoryContext().project_id};
      context=await api('suggest',query);source.textContent=context.source_text;selectModels();
      status.textContent=context.candidates.length?'本机规则候选尚未保存。':'未匹配本机规则。可按需使用模型整理，或输入“记住：名称=内容”。';
      render(context);
    }catch(e){status.textContent=e.message;}finally{working=false;controls();policyControls();}
  }
  generate.onclick=async()=>{
    if(working||!sameConversation())return;const item=modelCatalog.find(x=>modelKey(x)===model.value);if(!item)return;
    const active={id:crypto.randomUUID().replaceAll('-',''),controller:new AbortController()};run=active;working=true;list.replaceChildren();controls();
    status.textContent='正在提取候选…还没有保存任何记忆。';
    try{
      const data=await api('semantic',{...query,provider:item.provider,model:item.model,reasoning:level.value||null,request_id:active.id},
        AbortSignal.any([active.controller.signal,AbortSignal.timeout(125000)]));
      if(run!==active)return;
      const usage=data.model_used===false?' 本次未调用模型。':data.result.usage?' 本次用量：'+JSON.stringify(data.result.usage):' 供应商未返回本次用量。';
      if(data.result.status!=='SUCCEEDED'){status.textContent=(data.result.user_message||'本次整理未完成，没有保存。')+usage;return;}
      context=data;source.textContent=data.source_text;toolbar.open=false;render(data,true);
      status.textContent=(data.notice||(data.candidates.length?'请逐条核对原句、主体和用途，20 分钟内确认；预览过期或服务重启后需重新整理。':'没有值得保留的候选，没有保存。'))+
        usage;
    }catch(e){if(run===active){status.textContent=(e.name==='TimeoutError'?'等待超时，已请求停止。':e.message)+' 未保存、未自动重试；远端可能已有用量。';await cancelRequest(active.id);}}
    finally{if(run===active){run=null;working=false;controls();policyControls();}}
  };
  async function cancelRequest(id){try{await fetch('/api/chat/cancel',{method:'POST',credentials:'omit',headers:{'X-Jarvis-Nonce':NONCE,'Content-Type':'application/json'},body:JSON.stringify({request_id:id}),signal:AbortSignal.timeout(5000)});}catch{}}
  function stopRun(){
    if(!run)return;const active=run;run=null;active.controller.abort();working=false;controls();policyControls();
    status.textContent='已停止接收候选，并请求后台取消。没有保存；远端已接收的请求可能仍有用量。';cancelRequest(active.id);
  }
  model.onchange=configureLevels;stop.onclick=stopRun;
  close.onclick=()=>{if(run)stopRun();if(!working)dialog.close();};
  dialog.addEventListener('cancel',e=>{if(run)stopRun();else if(working)e.preventDefault();});
  function attach(){
    for(const node of document.querySelectorAll('#messages > .message.user')){
      if(node.querySelector('.candidate-entry')||node.dataset.personalControl==='true'||node.dataset.taskControl==='true'||node.dataset.attachmentsOmitted==='true'||node.querySelector('.message-attachments'))continue;
      const button=document.createElement('button');button.type='button';button.className='candidate-entry';button.textContent='整理为记忆…';button.onclick=()=>open(node);node.append(button);
    }
  }
  new MutationObserver(attach).observe($('messages'),{childList:true});attach();
})();

