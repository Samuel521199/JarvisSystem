/* Design prototype only. No network requests, persistent storage or runtime actions. */
(() => {
  'use strict';
  const $ = (selector, root = document) => root.querySelector(selector);
  const $$ = (selector, root = document) => [...root.querySelectorAll(selector)];
  const visibilityObserver = 'IntersectionObserver' in window ? new IntersectionObserver(entries => {
    entries.forEach(entry => entry.target.toggleAttribute('data-offscreen', !entry.isIntersecting));
  }) : null;
  const copy = value => JSON.parse(JSON.stringify(value));
  const icon = name => `<svg aria-hidden="true"><use href="#i-${name}"/></svg>`;
  const modes = ['inspect', 'heal', 'evolve'];
  const names = {inspect:'自检', heal:'自愈', evolve:'进化'};
  // Deliberately illustrative. The deployed UI must read the verified model catalog.
  const models = [
    {id:'gemini-pro', name:'Gemini 3.1 Pro · Vertex', levels:['low','medium','high'], native:'thinkingLevel', supports:modes},
    {id:'gpt-sol', name:'GPT-6.1 Sol · OpenAI', levels:['low','medium','high','xhigh','max'], native:'reasoning.effort', supports:modes},
    {id:'qwen-flash', name:'Qwen3.8 Flash · 百炼', levels:['off','on'], native:'enable_thinking', supports:modes},
    {id:'local-diagnostic', name:'本地诊断模型 · 待验收', levels:['fixed'], native:'固定模式 / 待验收', supports:['inspect']}
  ];
  const levelNames = {low:'低',medium:'中',high:'高',xhigh:'极高',max:'最高',off:'关闭思考',on:'开启思考',fixed:'固定模式'};
  const profiles = {
    inspect:{trigger:'rules',interval:'30',primary:{model:'qwen-flash',level:'on'},backups:[{model:'gemini-pro',level:'low'}],budgetMode:'notify',budget:'2'},
    heal:{trigger:'recipes',interval:'30',primary:{model:'gemini-pro',level:'medium'},backups:[{model:'gpt-sol',level:'high'}],budgetMode:'notify',budget:'10'},
    evolve:{trigger:'goals',interval:'30',primary:{model:'gemini-pro',level:'high'},backups:[{model:'gpt-sol',level:'high'},{model:'qwen-flash',level:'on'}],budgetMode:'notify',budget:'20'}
  };
  const drafts = copy(profiles);
  const data = {
    inspect:{english:'SYSTEM AWARENESS', status:'待命 · 正常检查不调用模型', title:'先理解状态，再采取行动。', description:'从运行证据、包完整性与结果中发现变化。检查只产生报告，修复与升级各有自己的入口。', meta:[['检查方式','事件优先'],['兜底策略','30 分钟 · 可设置'],['模型消耗','规则检查 0 token']], action:'演示一次自检', icon:'scan', hint:'只演示四个阶段，不运行真实探针', cards:[
      ['01 / RUNTIME','确定性检查','运行与包完整性','读取登记对象的状态、版本与摘要。只检查受影响的范围。','不扫描整台电脑'],
      ['02 / EVIDENCE','结果检查','能力是否仍然可靠','重放有界样例，对比冻结的预期结果。未覆盖的能力单独列出。','缓存复用需显示检查时间'],
      ['03 / INSIGHT','按需诊断','遇到异常，再借助模型','规则无法解释时，按专属模型策略分析最小必要证据。','AI 诊断需单独启用']
    ], steps:[['收集证据','范围与时间'],['校验变化','摘要与契约'],['运行样例','隔离结果检查'],['形成报告','不触发修复']], messages:['正在整理登记对象的检查证据。','正在对比包、契约与环境版本。','正在演示独立结果检查。','演示完成：生成检查报告；没有启动自愈或进化。']},
    heal:{english:'RESTORE RELIABILITY',status:'待命 · 围绕已知故障',title:'修复裂隙，让能力重新可靠。',description:'先恢复原本承诺的能力，再核验故障是否消失。确定性配方优先，需要代码修改时才进入隔离研发。',meta:[['处理对象','故障事件'],['恢复顺序','已验证配方优先'],['完成依据','原故障复测']],action:'演示一次自愈',icon:'heal',hint:'样例：清单工具输出退化，恢复既有契约',cards:[
      ['01 / INCIDENT','示例事件','CSV 输出发生退化','同一个故障合并处理。先区分代码缺陷、资源不足和模型不可用。','对象：文件清单工具 · 样例'],
      ['02 / RECOVERY','恢复路径','恢复已验证的版本','保留恢复材料；若需要修复代码，建立独立候选并验证旧能力。','不夹带新功能'],
      ['03 / CONFIRM','关闭条件','复测后，才算修好','恢复动作、复测与观察分开记录。再次复发时重开故障事件。','失败保留证据，不无限尝试']
    ],steps:[['确认故障','固定影响范围'],['恢复能力','配方或候选修复'],['独立复测','重现原故障'],['观察恢复','保留回退路径']],messages:['已识别一个演示故障，绑定当前契约。','正在演示恢复上一可用版本。','正在演示原故障复测；没有增加功能。','演示完成：恢复原能力并进入观察。未执行实际修复。']},
    evolve:{english:'BECOME MORE CAPABLE',status:'等待目标 · 不为升级而升级',title:'你的下一个目标，是成长的方向。',description:'把真实需要变成可验证的能力。保存当前基线，在独立候选中实验，证明有用以后，再融入 Jarvis。',meta:[['驱动力','主人目标与证据'],['对比方式','保留旧能力'],['研发时间','空闲与预算允许时']],action:'演示一次进化',icon:'grow',hint:'样例：在 CSV / Markdown 基础上增加 TSV',cards:[
      ['01 / INTENT','目标样例','让清单工具支持 TSV','v1 正常工作，新格式是能力目标，不应被误报为系统故障。','来源：主人明确需求'],
      ['02 / EXPERIMENT','独立候选','先实验，再比较','固定验收，生成新代码与技能包；兼容性、质量和成本一起比较。','候选失败不覆盖当前能力'],
      ['03 / CONTINUITY','发布条件','留下有用的进步','通过独立验收后发布并观察。记录收益，按保留规则退役旧材料。','不靠代码数量证明成长']
    ],steps:[['明确目标','固定基线与验收'],['候选研发','代码与技能包'],['验证收益','兼容与实际效果'],['发布观察','记录成长证据']],messages:['演示目标已固定：保留旧格式，增加 TSV。','正在演示候选研发；原有版本保持可用。','正在演示兼容性检查与新旧对比。','演示完成：展示候选采用与观察流程。未生成或发布真实代码。']}
  };
  const states = Object.fromEntries(modes.map(mode => [mode,{step:-1,running:false,message:'选择上方按钮，体验这个能力的工作过程。',timer:null}]));
  let current = 'inspect';
  let toastTimer;
  function art(){return `<div class="art" aria-hidden="true"><div class="core-glow"></div><svg class="framework" viewBox="0 0 240 190"><path class="frame-main" d="m120 12 76 41v82l-76 43-76-43V53Z"/><path d="M17 70h27m152 50h27M120 12V0m0 178v12M15 135h29m152-82h28"/><path class="fractures" d="m87 50 33-17 33 17m-66 90 33 18 33-18M64 76v39m112-39v39"/><g class="new-branches"><path d="M76 66 28 39V14M163 66l48-27V14M77 127l-49 28v23m135-51 49 28v23"/><path d="M24 9h8v8h-8zM207 9h8v8h-8zM24 174h8v8h-8zM208 174h8v8h-8z"/></g></svg><div class="core-art"><img src="../../../apps/web/brand/core.png" alt="" width="132" height="132"></div><div class="scan-line"></div><span class="art-label">J / CONTINUITY</span></div>`;}
  function renderPanel(mode){
    const oldArt = $('.art', $('#panel-'+mode));
    if(oldArt) visibilityObserver?.unobserve(oldArt);
    const d=data[mode], p=profiles[mode];
    const model=models.find(m=>m.id===p.primary.model);
    const meta=d.meta.map(([label,value],i)=>{
      if(mode==='inspect'&&i===0)value=p.trigger==='manual'?'仅手动':p.trigger==='anomaly'?'事件 + 按需诊断':'事件优先';
      if(mode==='inspect'&&i===1)value=p.trigger==='manual'?'不自动巡检':p.interval==='0'?'周期已关闭':p.interval+' 分钟 · 可设置';
      return `<span>${label} <strong>${value}</strong></span>`;
    }).join('');
    $('#panel-'+mode).innerHTML=`<div class="hero" data-kind="${mode}"><div class="hero-copy"><div class="state-line"><i></i><span>${d.status}</span></div><h2>${d.title}</h2><p>${d.description}</p><div class="hero-meta">${meta}</div></div>${art()}</div><div class="run-control"><button class="primary-button demo-start">${icon(d.icon)}${d.action}</button><button class="subtle-button demo-stop" hidden>停止演示</button><button class="subtle-button panel-policy">${names[mode]}策略</button><span class="run-hint">${d.hint}</span></div><div class="section-caption"><h3>${mode==='inspect'?'了解检查范围':mode==='heal'?'让恢复有迹可循':'从一个具体目标开始'}</h3><span>EXAMPLE / ${d.english}</span></div><div class="cards">${d.cards.map(c=>`<article class="card"><div class="card-top"><span class="card-number">${c[0]}</span><span class="card-status">${c[1]}</span></div><h4>${c[2]}</h4><p>${c[3]}</p><div class="card-detail">${c[4]}</div></article>`).join('')}</div><div class="policy-strip"><div class="policy-icon">${icon('tune')}</div><div><strong>${mode==='inspect'?'规则先行，模型按需':'这项能力有自己的模型策略'}</strong><span class="model-chip">${model.name} · ${levelNames[p.primary.level]}　→　${p.backups.length} 个备选</span><p>${mode==='inspect'&&p.trigger==='rules'?'当前演示策略：AI 诊断关闭，所选模型暂不派发。':'示例配置；每个备选使用自己的档位，共享任务预算。'}</p></div><button class="subtle-button panel-policy">调整策略 ${icon('arrow')}</button></div><div class="timeline" aria-label="${names[mode]}演示阶段">${d.steps.map(s=>`<div class="timeline-item">${s[0]}<small>${s[1]}</small></div>`).join('')}</div><div class="demo-message" aria-live="polite"></div>`;
    const panel=$('#panel-'+mode);
    visibilityObserver?.observe($('.art',panel));
    $('.demo-start',panel).addEventListener('click',()=>startDemo(mode));
    $('.demo-stop',panel).addEventListener('click',()=>stopDemo(mode));
    $$('.panel-policy',panel).forEach(b=>b.addEventListener('click',openDrawer));
    updateStage(mode);
  }
  function updateStage(mode){
    const panel=$('#panel-'+mode),s=states[mode];
    panel.classList.toggle('is-running',s.running); panel.dataset.kind=mode;
    $('.demo-start',panel).disabled=s.running;
    $('.demo-stop',panel).hidden=!s.running;
    $('.state-line span',panel).textContent=s.running?`演示中 · ${data[mode].steps[s.step][0]}`:data[mode].status;
    $$('.timeline-item',panel).forEach((node,i)=>{node.classList.toggle('active',i===s.step&&s.running);node.classList.toggle('done',i<s.step||i===s.step&&!s.running);});
    $('.demo-message',panel).textContent=s.message;
  }
  function startDemo(mode){
    const s=states[mode]; clearTimeout(s.timer); s.running=true;s.step=0;s.message=data[mode].messages[0];updateStage(mode);
    const next=()=>{if(document.hidden){s.timer=setTimeout(next,1200);return;}s.step++;if(s.step>=3){s.step=3;s.running=false;}s.message=data[mode].messages[s.step];updateStage(mode);if(s.running)s.timer=setTimeout(next,1900);};
    s.timer=setTimeout(next,1900);
  }
  function stopDemo(mode){const s=states[mode];clearTimeout(s.timer);s.running=false;s.message='演示已停止。没有实际任务、模型调用或发布需要撤销。';updateStage(mode);}
  function dirty(mode=current){return JSON.stringify(drafts[mode])!==JSON.stringify(profiles[mode]);}
  function switchMode(mode,focus=false){
    current=mode;document.body.dataset.mode=mode;
    modes.forEach(m=>{const selected=m===mode;$('#tab-'+m).setAttribute('aria-selected',String(selected));$('#tab-'+m).tabIndex=selected?0:-1;$('#panel-'+m).hidden=!selected;});
    if(!$('#policy-drawer').hidden)renderDrawer();
    if(focus)$('#tab-'+mode).focus();
  }
  $$('.tabs [role=tab]').forEach(tab=>{
    tab.addEventListener('click',()=>switchMode(tab.dataset.tab));
    tab.addEventListener('keydown',event=>{let index=modes.indexOf(current);if(event.key==='ArrowRight')index=(index+1)%3;else if(event.key==='ArrowLeft')index=(index+2)%3;else if(event.key==='Home')index=0;else if(event.key==='End')index=2;else return;event.preventDefault();switchMode(modes[index],true);});
  });
  function notify(message){clearTimeout(toastTimer);$('#toast').textContent=message;$('#toast').hidden=false;toastTimer=setTimeout(()=>$('#toast').hidden=true,3500);}
  function openDrawer(){ $('#policy-drawer').hidden=false;$('#open-policy').setAttribute('aria-expanded','true');renderDrawer();$('#close-policy').focus(); }
  function closeDrawer(){ $('#policy-drawer').hidden=true;$('#open-policy').setAttribute('aria-expanded','false');$('#open-policy').focus();if(dirty())notify('未保存草稿已暂留在本标签。刷新页面会还原。'); }
  $('#open-policy').addEventListener('click',()=>$('#policy-drawer').hidden?openDrawer():closeDrawer());
  $('#close-policy').addEventListener('click',closeDrawer);
  document.addEventListener('keydown',event=>{if(event.key==='Escape'&&!$('#policy-drawer').hidden)closeDrawer();});
  const triggers={inspect:[['rules','规则自检 · AI 诊断关闭'],['anomaly','事件自检 + 异常时 AI 诊断'],['manual','仅手动检查']],heal:[['recipes','仅自动执行已验证配方'],['bounded','配方 + 已授权范围内代码修复'],['manual','仅手动处理故障']],evolve:[['goals','仅主人明确目标进入研发'],['propose','自动提出机会，等待选择'],['bounded','已设范围内空闲时自主研发']]};
  const triggerNotes={inspect:'正常规则检查始终为 0 token。诊断开关只决定何时调用下方模型。',heal:'自愈恢复已有契约；确定性恢复不依赖模型。未授权范围保留为待处理。',evolve:'进化围绕目标，不由计时器无目的启动。示例不会执行真实研发。'};
  function changed(){ $('#dirty-status').textContent=dirty()?'当前标签有未保存更改':'无未保存更改';$('#save-policy').disabled=!dirty();$('#revert-policy').disabled=!dirty(); }
  function renderDrawer(){
    const p=drafts[current];$('#policy-title').textContent=names[current]+'策略';$('#profile-status').textContent='独立档案 / '+names[current]+' · 只影响此用途的下一次任务';
    $('#trigger-select').replaceChildren(...triggers[current].map(([value,label])=>new Option(label,value)));$('#trigger-select').value=p.trigger;
    $('#interval-field').hidden=current!=='inspect';$('#interval-select').value=p.interval;$('#trigger-note').textContent=triggerNotes[current];
    $('#primary-heading').textContent=current==='inspect'?'AI 辅助诊断 · 首选模型':'首选模型';
    $('#budget-mode').value=p.budgetMode;$('#budget-value').value=p.budget;
    renderRoutes();changed();$('#route-result').textContent='配置模拟不发出任何模型请求；请选择一种故障情形。';
  }
  function nativeValue(model,level){return model.id==='qwen-flash'?`${model.native} = ${level==='on'}`:model.id==='gemini-pro'?`${model.native} = ${level.toUpperCase()}`:`${model.native}${level==='fixed'?'':' = '+level}`;}
  function makeRoute(route,index){
    const primary=index<0,model=models.find(m=>m.id===route.model),box=document.createElement('div');box.className='route-box';
    const label=primary?'首选':'备选 '+(index+1);
    box.innerHTML=`<div class="route-label"><span>${label}</span>${primary?'':`<div class="route-buttons"><button type="button" data-direction="up" aria-label="上移${label}" title="上移">↑</button><button type="button" data-direction="down" aria-label="下移${label}" title="下移">↓</button><button type="button" data-direction="remove" aria-label="移除${label}" title="移除">×</button></div>`}</div><div class="route-grid"><label class="field">模型<select aria-label="${label}模型"></select></label><label class="field">推理档位<select aria-label="${label}推理档位"></select></label></div><div class="native-setting"></div>`;
    const [select,effort]=$$('select',box);
    select.replaceChildren(...models.filter(m=>m.supports.includes(current)).map(m=>new Option(m.name,m.id)));select.value=route.model;
    effort.replaceChildren(...model.levels.map(l=>new Option(levelNames[l],l)));effort.value=route.level;effort.disabled=model.levels.length===1;
    $('.native-setting',box).textContent=nativeValue(model,route.level);
    select.addEventListener('change',()=>{route.model=select.value;const selected=models.find(m=>m.id===route.model);route.level=selected.levels.includes('medium')?'medium':selected.levels.at(-1);renderRoutes();changed();});
    effort.addEventListener('change',()=>{route.level=effort.value;$('.native-setting',box).textContent=nativeValue(models.find(m=>m.id===route.model),route.level);changed();});
    if(!primary){
      const list=drafts[current].backups; $('[data-direction=up]',box).disabled=index===0;$('[data-direction=down]',box).disabled=index===list.length-1;
      $$('.route-buttons button',box).forEach(b=>b.addEventListener('click',()=>{const direction=b.dataset.direction;if(direction==='remove')list.splice(index,1);else{const target=index+(direction==='up'?-1:1);[list[index],list[target]]=[list[target],list[index]];}renderRoutes();changed();}));
    }
    return box;
  }
  function renderRoutes(){ const p=drafts[current];$('#primary-route').replaceChildren(makeRoute(p.primary,-1));$('#backup-routes').replaceChildren(...p.backups.map(makeRoute));$('#backup-count').textContent=`${p.backups.length} / 3`;$('#add-backup').disabled=p.backups.length>=3; }
  $('#add-backup').addEventListener('click',()=>{const p=drafts[current],used=new Set([p.primary.model,...p.backups.map(r=>r.model)]);const model=models.find(m=>m.supports.includes(current)&&!used.has(m.id));if(!model){notify('示例目录中没有未使用的合格模型；不添加重复线路。');return;}p.backups.push({model:model.id,level:model.levels.includes('medium')?'medium':model.levels.at(-1)});renderRoutes();changed();});
  $('#trigger-select').addEventListener('change',event=>{drafts[current].trigger=event.target.value;changed();});
  $('#interval-select').addEventListener('change',event=>{drafts[current].interval=event.target.value;changed();});
  $('#budget-mode').addEventListener('change',event=>{drafts[current].budgetMode=event.target.value;changed();});
  $('#budget-value').addEventListener('input',event=>{drafts[current].budget=event.target.value;changed();});
  $('#save-policy').addEventListener('click',()=>{
    const p=drafts[current];
    if(!$('#budget-value').reportValidity()||!Number.isFinite(Number(p.budget))||Number(p.budget)<=0){notify('请填写有效的预算提醒值。');return;}
    const routes=[p.primary,...p.backups];if(new Set(routes.map(r=>r.model)).size!==routes.length){notify('首选和备选不能重复；请选择不同线路。');return;}
    profiles[current]=copy(p);renderPanel(current);changed();notify(names[current]+'设置已保存在本次预览内存中。实际 Jarvis 配置未改变。');
  });
  $('#revert-policy').addEventListener('click',()=>{drafts[current]=copy(profiles[current]);renderDrawer();});
  $('#simulate-route').addEventListener('click',()=>{
    const p=drafts[current],failure=$('#failure-select').value;
    if(failure==='unknown'){$('#route-result').textContent='首选请求已发出，结果待核对。\n保留 UNKNOWN，不自动重发、不自动切到备选。原请求仍可能计费。\n这只是演示，没有真实请求。';return;}
    if(failure==='all'){$('#route-result').textContent='所有合格线路暂不可用。\n保留旧能力与检查点，等待连接恢复。确定性自检仍可工作。\n这只是演示，没有真实请求。';return;}
    const next=p.backups.find(r=>r.model!==p.primary.model&&r.model!=='local-diagnostic');
    if(!next){$('#route-result').textContent='首选明确不可用；没有不重复且已合格的示例备选。\n等待可用线路，不假装本地待验收模型已能完成任务。';return;}
    const first=models.find(m=>m.id===p.primary.model),fallback=models.find(m=>m.id===next.model);
    $('#route-result').textContent=`${first.name} → ${fallback.name}\n原因：模拟明确额度耗尽。\n备选档位：${levelNames[next.level]}（${nativeValue(fallback,next.level)}）\n只演示切换路径，实际调用 0 次；不改变 AI 诊断开关。`;
  });
  $('#motion-toggle').addEventListener('click',()=>{const paused=!document.body.hasAttribute('data-paused');document.body.toggleAttribute('data-paused',paused);const text=paused?'恢复装饰动画':'暂停装饰动画';$('#motion-toggle').setAttribute('aria-pressed',String(paused));$('#motion-toggle').setAttribute('aria-label',text);$('#motion-toggle').title=text;$('.tooltip',$('#motion-toggle')).textContent=text;});
  document.addEventListener('visibilitychange',()=>document.body.toggleAttribute('data-hidden',document.hidden));
  if(new URL(location.href).searchParams.has('embedded')) $('#open-device').hidden=true;
  $('#open-device').addEventListener('click',()=>{$('#device-frame').src='index.html?embedded=1';$('#device-dialog').showModal();});
  $('#close-device').addEventListener('click',()=>$('#device-dialog').close());
  $('#device-dialog').addEventListener('close',()=>{$('#device-frame').src='about:blank';$('#open-device').focus();});
  const handle=$('.resize-handle');let resizing=false;
  function resize(value){const max=Math.min(520,innerWidth-204-420),width=Math.max(320,Math.min(Math.max(320,max),value));document.documentElement.style.setProperty('--drawer',width+'px');handle.setAttribute('aria-valuenow',String(Math.round(width)));}
  handle.addEventListener('pointerdown',event=>{resizing=true;handle.setPointerCapture(event.pointerId);event.preventDefault();});
  handle.addEventListener('pointermove',event=>{if(resizing)resize(innerWidth-event.clientX);});
  handle.addEventListener('pointerup',()=>resizing=false);handle.addEventListener('pointercancel',()=>resizing=false);
  handle.addEventListener('keydown',event=>{if(!['ArrowLeft','ArrowRight'].includes(event.key))return;event.preventDefault();resize(Number(handle.getAttribute('aria-valuenow'))+(event.key==='ArrowLeft'?20:-20));});
  window.addEventListener('pagehide',()=>{modes.forEach(mode=>clearTimeout(states[mode].timer));clearTimeout(toastTimer);visibilityObserver?.disconnect();});
  modes.forEach(renderPanel);switchMode('inspect');
})();
