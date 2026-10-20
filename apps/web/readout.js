/* Explicit local reply readout; two bounded WAV buffers, no microphone or cloud. */
(()=>{'use strict';
const root=document.getElementById('chat-readout'),messages=document.getElementById('messages');if(!root||!messages)return;
const $=id=>document.getElementById('readout-'+id);
let active=null,serial=0,optionsLoaded=false,lastArticle=null,lastButton=null;
const wait=ms=>new Promise(resolve=>setTimeout(resolve,ms));
async function api(path,payload,keepalive=false){const c=new AbortController(),timer=setTimeout(()=>c.abort(),8000);
 try{const r=await fetch(path,{method:payload?'POST':'GET',credentials:'omit',cache:'no-store',keepalive,headers:{'X-Jarvis-Nonce':NONCE,...(payload?{'Content-Type':'application/json'}:{})},body:payload?JSON.stringify(payload):undefined,signal:c.signal});if(!r.ok){const e=await r.json();throw new Error(e.user_message||'本地朗读暂不可用。');}return r;}finally{clearTimeout(timer);}}
async function operation(payload,keepalive=false){return (await api('/api/speech/readout',payload,keepalive)).json();}
function status(text){$('status').textContent=text;}
function dispose(s){if(s.audio){s.audio.pause();s.audio.onended=null;s.audio.onerror=null;s.audio.removeAttribute('src');s.audio.load();}for(const value of s.buffers.values())URL.revokeObjectURL(value.url);s.buffers.clear();s.button?.setAttribute('aria-pressed','false');}
async function stop(message='朗读已停止。',keepalive=false){serial++;const s=active;if(!s)return;active=null;s.cancelled=true;dispose(s);$('pause').disabled=true;$('stop').disabled=true;status(message);try{await operation({action:'stop',id:s.id},keepalive);}catch{if(!keepalive)$('error').textContent='停止请求未确认；本页播放已停止，没有重试。可在语音设置中核对。';}}
async function options(){if(optionsLoaded)return;const v=await (await api('/api/speech/primary')).json();for(const [field,key] of [['voice','voices'],['emotion','emotions'],['language','languages']]){const value=$(field).value;$(field).replaceChildren(...Object.entries(v.capabilities[key]).map(([id,label])=>new Option(label,id)));$(field).value=value;}optionsLoaded=true;}
function controls(s){$('pause').disabled=!s;$('stop').disabled=!s;$('pause').title=s?.paused?'继续朗读':'暂停朗读';$('pause').setAttribute('aria-label',$('pause').title);$('pause').textContent=s?.paused?'▶':'Ⅱ';}
async function play(s){if(active!==s||s.cancelled||s.paused||s.audio||!s.buffers.has(s.playIndex))return;
 const value=s.buffers.get(s.playIndex),audio=new Audio(value.url);s.audio=audio;s.current=value;
 audio.onended=()=>{if(active!==s)return;URL.revokeObjectURL(value.url);s.buffers.delete(s.playIndex);s.playIndex++;s.audio=null;s.current=null;play(s);};
 audio.onerror=()=>{if(active===s){$('error').textContent='音频无法播放，请重新朗读。';stop('播放已停止。');}};
 try{await audio.play();if(active===s)status(`正在朗读第 ${s.playIndex+1} / ${s.total} 段 · ${value.result.expression||'自然表达'}`);}
 catch{if(active===s){s.paused=true;controls(s);status('语音已准备，请点击播放继续。');}}
}
async function start(article,button){const pending=stop(),ticket=serial;await pending;if(ticket!==serial||!article.isConnected)return;lastArticle=article;lastButton=button;root.hidden=false;$('error').textContent='';
 const s={id:crypto.randomUUID().replaceAll('-',''),article,button,cancelled:false,paused:false,buffers:new Map(),audio:null,playIndex:0,generateIndex:0,total:0};active=s;button?.setAttribute('aria-pressed','true');controls(s);status('正在准备本地语音；首次加载可能需要数秒…');
 try{await options();if(active!==s)return;
  let view;try{view=await operation({action:'start',id:s.id,text:$('text').value,voice:$('voice').value,emotion:$('emotion').value,language:$('language').value,direction:$('direction').value});}
  catch(error){view=await (await api('/api/speech/readout/'+s.id)).json();if(!view.active)throw error;}
  if(active!==s){await operation({action:'stop',id:s.id});return;}
  s.total=view.total;$('preparation').textContent=(view.notices||[]).join('；')||'本地合成，按短句连续播放；暂停保留位置，停止会取消本次合成。';
  while(active===s&&!s.cancelled){
   if(!s.article.isConnected){await stop('已切换会话，旧回复朗读已停止。');break;}
   if(s.playIndex>=s.total){await operation({action:'finish',id:s.id});if(active===s){active=null;dispose(s);controls(null);status('朗读完成。');}break;}
   const canGenerate=s.generateIndex<s.total&&s.generateIndex<=s.playIndex+1;
   if(canGenerate){
    try{view=await operation({action:'next',id:s.id,index:s.generateIndex});}
    catch(error){view=await (await api('/api/speech/readout/'+s.id)).json();if(!view.active||!view.items?.[s.generateIndex])throw error;}
   }else view=await (await api('/api/speech/readout/'+s.id)).json();
   if(active!==s)break;if(!view.active)throw new Error(view.message||'朗读已失效。');
   const item=view.items[s.generateIndex];
   if(item?.status==='SUCCEEDED'&&!s.buffers.has(s.generateIndex)){
    const response=await api(item.result.audio_url),blob=await response.blob();if(active!==s)break;
    s.buffers.set(s.generateIndex,{url:URL.createObjectURL(blob),result:item.result});s.generateIndex++;
   }else if(item&&['FAILED','CANCELLED'].includes(item.status))throw new Error(item.message||'本次语音合成未完成。');
   if(!s.audio&&!s.paused&&s.buffers.has(s.playIndex))await play(s);
   if(!s.paused&&!s.audio&&!s.buffers.has(s.playIndex))status(`正在生成第 ${Math.min(s.generateIndex+1,s.total)} / ${s.total} 段，文字聊天可继续…`);
   await wait(canGenerate?250:1500);
  }
 }catch(error){if(active===s){$('error').textContent=error.message;$('options').open=true;await stop('朗读未完成，文字回复仍可使用。');}}
}
function attach(article){if(!article.matches?.('.message.assistant')||article.querySelector('.readout-message-action'))return;const actions=document.createElement('div');actions.className='readout-message-action';const button=document.createElement('button');button.type='button';button.className='readout-button';button.title='朗读这条回复';button.setAttribute('aria-label',button.title);button.setAttribute('aria-pressed','false');button.innerHTML='<svg class="icon" viewBox="0 0 24 24" aria-hidden="true"><path d="M11 5 6 9H3v6h3l5 4V5Zm4 3a6 6 0 0 1 0 8m3-11a10 10 0 0 1 0 14"/></svg>';
 button.addEventListener('click',()=>{if(active?.article===article){$('pause').click();return;}$('text').value=article.querySelector('.bubble')?.textContent||'';start(article,button);});actions.append(button);article.append(actions);}
for(const article of messages.children)attach(article);
new MutationObserver(records=>{for(const record of records)for(const node of record.addedNodes)attach(node);if(active&&!active.article.isConnected)stop('已切换会话，旧回复朗读已停止。');if(lastArticle&&!lastArticle.isConnected){root.hidden=true;$('text').value='';lastArticle=lastButton=null;}}).observe(messages,{childList:true});
$('pause').addEventListener('click',async()=>{const s=active;if(!s)return;s.paused=!s.paused;controls(s);if(s.paused){s.audio?.pause();status('朗读已暂停。');}else if(s.audio){try{await s.audio.play();status(`正在朗读第 ${s.playIndex+1} / ${s.total} 段`);}catch{s.paused=true;controls(s);status('请再次点击播放。');}}else play(s);});
$('stop').addEventListener('click',()=>stop());$('restart').addEventListener('click',()=>{if(lastArticle?.isConnected)start(lastArticle,lastButton);});
$('close-options').addEventListener('click',()=>{$('options').open=false;$('options').querySelector('summary').focus();});
document.addEventListener('click',event=>{if($('options').open&&!event.target.closest('#readout-options'))$('options').open=false;});
document.addEventListener('keydown',event=>{if(event.key==='Escape'&&$('options').open){$('options').open=false;$('options').querySelector('summary').focus();}});
$('options').addEventListener('toggle',()=>{if($('options').open)options().catch(e=>{$('error').textContent=e.message;});});
window.JarvisReadout={stop,speak(article){if(!article?.isConnected)return;attach(article);$('text').value=article.querySelector('.bubble')?.textContent||'';return start(article,article.querySelector('.readout-button'));}};
window.addEventListener('pagehide',()=>{stop('页面已关闭，朗读已停止。',true);});
})();
