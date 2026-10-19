/* Reviewed lifecycle controls inside the existing resizable tool pane. */
(()=>{'use strict';
const labels={LEGACY:'既有工具 · 未做本轮灰度',CANARY:'灰度观察',PAUSED:'灰度已暂停',ACTIVE:'已正式启用',REJECTED:'候选被拒绝',RETIRED:'能力已退役',ABANDONED:'本轮候选已放弃',DISABLED:'稳定工具已停用',ROLLED_BACK:'稳定选择已恢复旧版'};
const operations=new Set(['publish','trial','promote','pause','resume','discard','retire','restore','retire-version','archive-version','load-version']);
function el(tag,text){const e=document.createElement(tag);if(text!==undefined)e.textContent=text;return e;}
function check(parent,text,value=false){const l=el('label',text),n=el('input');n.type='checkbox';n.checked=value;n.style.cssText='width:auto;display:inline-block;margin-right:8px';l.prepend(n);parent.append(l);return n;}
function field(parent,title,value,large=false){const l=el('label',title),n=el(large?'textarea':'input');n.value=value;l.append(n);parent.append(l);return n;}
function button(parent,text,fn,disabled=false){const b=el('button',text);b.type='button';b.disabled=disabled;b.onclick=fn;parent.append(b);return b;}
function admission(parent,notify){
 const approved=check(parent,'我已核对用途、独立验收和本次灰度范围'),note=field(parent,'准入审阅依据','',true);
 const minimum=field(parent,'至少核验的新输入数',2),maximum=field(parent,'本轮最多试用次数',10),seconds=field(parent,'单次候选运行延迟上限（秒）',15);
 for(const [n,min,max] of [[minimum,2,10],[maximum,2,30],[seconds,1,30]]){n.type='number';n.min=min;n.max=max;n.step=1;}
 parent.append(el('p','进入灰度不会替换稳定版本。试用需要独立预期和用途反馈，达标后仍须明确正式启用。'));
 return ()=>{if(!approved.checked||note.value.trim().length<5){notify('请勾选核对并填写准入审阅依据。');return null;}return {reviewed:true,review_note:note.value,minimum_verified:Number(minimum.value),maximum_trials:Number(maximum.value),maximum_seconds:Number(seconds.value)};};
}
function render(item,parent,{send,input,expected,verify,getDraft,setDraft,notify}){
 const life=item.lifecycle||{revision:0,phase:'LEGACY'},a=item.assessment||{},box=el('section');box.className='tool-lifecycle';box.dataset.phase=life.phase;
 box.append(el('h4',labels[life.phase]||life.phase),el('p','本轮独立新输入 '+(a.verified_novel_inputs||0)+' / '+(a.limits?.minimum_verified||2)+' · 有用途反馈 '+(a.useful_inputs||0)+' · 试用 '+(a.trials||0)+' / '+(a.limits?.maximum_trials||10)));
 if(life.reason)box.append(el('p','状态依据：'+life.reason));
 if(life.contract_quality){const q=life.contract_quality,review=el('details');review.className='tool-contract-quality';review.append(el('summary','契约体检 · 结构'+(q.structurally_consistent?'一致':'待修正')+'，业务正确性仍需审阅'),el('p','公开 '+q.public_cases+' / 独立留出 '+q.heldout_cases+' / 不同输入 '+q.distinct_inputs));for(const s of [...q.blockers,...q.review_questions])review.append(el('p',s));review.append(el('pre',JSON.stringify(q,null,2)));box.append(review);}
 box.append(el('small',a.benefit_basis||'尚无本轮实际收益证据。'));
 const details=el('details');details.append(el('summary','查看实际观察与准入依据'),el('pre',JSON.stringify({assessment:a,review:life.review,versions:item.versions},null,2)));box.append(details);
 const d=getDraft()||{},useful=check(box,'本次结果有实际用途（明确反馈，不由模型打分）',d.useful??false),benefit=field(box,'本次用途与独立预期依据',d.benefit||'',true),note=field(box,'本次启用/暂停/退役审阅依据',d.reviewNote||'',true),reviewed=check(box,'我已核对本次生命周期操作',d.reviewed??false);
 useful.onchange=()=>setDraft({useful:useful.checked});benefit.oninput=()=>setDraft({benefit:benefit.value});note.oninput=()=>setDraft({reviewNote:note.value});reviewed.onchange=()=>setDraft({reviewed:reviewed.checked});
 const base={tool_id:item.tool_id,generation:item.generation,lifecycle_revision:life.revision};
 function transition(operation,extra={}){if(!reviewed.checked||note.value.trim().length<5){notify('请核对并填写本次操作依据。');return;}send({...base,operation,reviewed:true,review_note:note.value,...extra});}
 button(box,'灰度试用候选',()=>{try{if(!verify.checked)throw Error('请勾选核对本次独立预期；保留案例与重复输入不会增加准入计数。');if(benefit.value.trim().length<5)throw Error('请说明本次用途与预期依据。');send({...base,operation:'trial',input:JSON.parse(input.value),expected:expected.value,useful:useful.checked,benefit_note:benefit.value});}catch(e){notify(e instanceof SyntaxError?'请提供有效 JSON 输入。':e.message);}},life.phase!=='CANARY'||a.trials>=a.limits?.maximum_trials);
 button(box,'核对后正式启用',()=>transition('promote'),!a.eligible_to_promote);
 button(box,'暂停灰度',()=>transition('pause'),life.phase!=='CANARY');
 button(box,'审阅后继续灰度',()=>transition('resume'),life.phase!=='PAUSED');
 button(box,'放弃本轮灰度',()=>transition('discard'),!['CANARY','PAUSED','REJECTED'].includes(life.phase));
 button(box,'退役此能力',()=>transition('retire'),life.phase==='RETIRED');
 button(box,'重新准入退役能力',()=>transition('restore'),life.phase!=='RETIRED'||!life.retired_version);
 const old=(item.versions||[]).filter(v=>v.state==='VERIFIED'&&![item.active,item.previous,life.candidate,life.retired_version,life.retired_candidate].includes(v.id));
 if(old.length){const select=el('select');select.setAttribute('aria-label','可退役的旧版本');for(const v of old){const o=el('option',v.id.slice(0,16));o.value=v.id;select.append(o);}box.append(select);button(box,'退役所选旧版本',()=>transition('retire-version',{version:select.value}));}
 const storage=el('details');storage.className='tool-version-storage';storage.append(el('summary','旧版本归档与在线容量'));
 for(const [state,label,operation,caption] of [['RETIRED','可归档的退役版本','archive-version','核对并归档版本'],['ARCHIVED','可载回的归档版本','load-version','载回为退役版本']]){const rows=(item.versions||[]).filter(v=>v.state===state);if(!rows.length)continue;const select=el('select');select.setAttribute('aria-label',label);for(const v of rows){const o=el('option',v.id.slice(0,16));o.value=v.id;select.append(o);}storage.append(select);button(storage,caption,()=>transition(operation,{version:select.value}));}
 storage.append(el('p','只整理无稳定/灰度/恢复引用的退役版本。归档保留完整材料并释放在线包名额；载回仍退役，不直接启用。不删除文件或历史回执，也不等于释放磁盘空间。'));box.append(storage);
 box.append(el('small','退役只阻止使用，保留代码、回执和用户文件；恢复会重新经过灰度。'));
 parent.append(box);
}
window.ToolLifecycleUI={operations,admission,render};
})();
