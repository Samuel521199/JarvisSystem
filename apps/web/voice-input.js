/* Explicit local recording, editable preview and opt-in reply readout. */
(()=>{'use strict';
const $=id=>document.getElementById(id),mic=$('voice-record');if(!mic)return;
let current=null,generation=0,replyTicket=null;
const notice=text=>{$('voice-status').textContent=text;$('voice-panel').hidden=false;};
const context=()=>{const c=window.Workspace?.currentConversation?.();return c?`${c.id}:${c.temporary}`:location.hash;};
async function api(payload,id){
 const c=new AbortController(),timer=setTimeout(()=>c.abort(),10000);
 try{const response=await fetch('/api/speech/input'+(id?'/'+id:''),{method:payload?'POST':'GET',credentials:'omit',cache:'no-store',
  headers:{'X-Jarvis-Nonce':NONCE,...(payload?{'Content-Type':'application/json'}:{})},body:payload?JSON.stringify(payload):undefined,signal:c.signal});
  const data=await response.json();if(!response.ok)throw new Error(data.user_message||'本地识别暂不可用。');return data;
 }finally{clearTimeout(timer);}
}
function controls(state){
 mic.dataset.state=state;mic.setAttribute('aria-pressed',String(state==='recording'));
 mic.title=state==='recording'?'结束录音并转写':'开始本地语音输入';mic.setAttribute('aria-label',mic.title);
 mic.disabled=['recognizing','requesting'].includes(state);
 $('voice-cancel').hidden=state==='idle';$('voice-preview-wrap').hidden=state!=='preview';
}
async function release(s){
 clearInterval(s.timer);clearTimeout(s.limit);
 s.stream?.getTracks().forEach(t=>{t.onended=null;t.stop();});
 if(s.node){s.node.port.onmessage=null;s.node.disconnect();}
 s.source?.disconnect();
 try{await s.audio?.close();}catch{}
 s.chunks=[];
}
function cancel(message='语音输入已取消。',keepalive=false){
 generation++;replyTicket=null;const s=current;current=null;controls('idle');$('voice-preview').value='';notice(message);
 if(s){release(s);fetch('/api/speech/input',{method:'POST',keepalive,credentials:'omit',headers:{'X-Jarvis-Nonce':NONCE,'Content-Type':'application/json'},
  body:JSON.stringify({action:'cancel',id:s.id})}).catch(()=>{});}
}
function encode(s){
 const length=s.chunks.reduce((n,c)=>n+c.length,0),input=new Float32Array(length);let offset=0;
 for(const chunk of s.chunks){input.set(chunk,offset);offset+=chunk.length;}
 const n=Math.min(320000,Math.floor(length*16000/s.audio.sampleRate));
 const bytes=new Uint8Array(n*2),view=new DataView(bytes.buffer),ratio=s.audio.sampleRate/16000;
 // Average each input interval, including fractional sample weights.
 for(let i=0;i<n;i++){let total=0;const lo=i*ratio,hi=(i+1)*ratio;
  for(let j=Math.floor(lo);j<Math.ceil(hi);j++)total+=(input[j]||0)*(Math.min(hi,j+1)-Math.max(lo,j));
  const value=Math.max(-1,Math.min(1,total/ratio));view.setInt16(i*2,Math.round(value*(value<0?32768:32767)),true);}
 let text='';for(let i=0;i<bytes.length;i+=16384)text+=String.fromCharCode(...bytes.subarray(i,i+16384));
 return btoa(text);
}
async function transcribe(s){
 if(current!==s||s.phase!=='recording')return;s.phase='recognizing';controls('recognizing');notice('本地识别中…录音不会发往云端。');
 const pcm=encode(s);await release(s);if(current!==s)return;
 try{
  let value;
  try{value=await api({action:'transcribe',id:s.id,pcm,language:$('voice-language').value});}
  catch(error){value=await api(null,s.id);if(value.status==='MISSING')throw error;}
  const deadline=Date.now()+55000;
  while(value.status==='RUNNING'){
   if(current!==s)return;if(Date.now()>deadline)throw new Error('识别等待超时。');
   await new Promise(r=>setTimeout(r,250));value=await api(null,s.id);
  }
  if(current!==s)return;
  if(value.status!=='SUCCEEDED')throw new Error(value.message||'此识别已取消或过期。');
  if(!value.text.trim()){cancel('没有识别到清晰语音，请重录或打字。');return;}
  s.phase='preview';$('voice-preview').value=value.text;controls('preview');
  notice(`本地转写 · ${value.audio_seconds.toFixed(1)} 秒录音 · 请检查后填入消息。尚未发送。`);
 }catch(error){if(current===s){cancel(error.message==='Failed to fetch'?'识别连接中断；没有重新识别。':error.message);}}
}
async function begin(){
 if(current?.phase==='recording'){current.node.port.postMessage('finish');return;}
 if(current)cancel();const epoch=++generation;replyTicket=null;
 const s={id:crypto.randomUUID().replaceAll('-',''),epoch,context:context(),phase:'requesting',chunks:[],count:0};
 current=s;controls('requesting');notice('正在请求麦克风；仅本机识别，最长 20 秒。');
 try{
  await window.JarvisReadout?.stop('开始录音，旧回复播报已停止。');
  if(current!==s)return;
  if(!navigator.mediaDevices?.getUserMedia||!window.AudioWorkletNode)throw new Error('此浏览器不支持本地录音，请使用现代浏览器或继续打字。');
  s.audio=new AudioContext({sampleRate:16000});await s.audio.resume();
  if(current!==s){await release(s);return;}
  // addModule is same-origin and uses the fixed capture program.
  await s.audio.audioWorklet.addModule('/voice-capture.js');
  if(current!==s){await release(s);return;}
  const stream=await navigator.mediaDevices.getUserMedia({audio:{channelCount:1,echoCancellation:true,noiseSuppression:true},video:false});
  if(current!==s){stream.getTracks().forEach(t=>t.stop());await release(s);return;}
  s.stream=stream;
  for(const track of stream.getAudioTracks())track.onended=()=>{if(current===s)cancel('麦克风已断开，录音取消；仍可打字。');};
  s.source=s.audio.createMediaStreamSource(stream);
  s.node=new AudioWorkletNode(s.audio,'jarvis-capture');
  s.node.port.onmessage=event=>{
   if(current!==s||s.phase!=='recording')return;
   if(event.data.samples){s.count+=event.data.samples.length;if(s.count>s.audio.sampleRate*20+2048){cancel('录音超过限制。');return;}s.chunks.push(event.data.samples);}
   if(event.data.finished)transcribe(s);
  };
  s.source.connect(s.node);s.node.connect(s.audio.destination);
  s.phase='recording';s.started=Date.now();controls('recording');
  const tick=()=>notice(`正在录音 ${Math.min(20,Math.floor((Date.now()-s.started)/1000))} / 20 秒 · 再点麦克风结束`);
  tick();s.timer=setInterval(tick,250);s.limit=setTimeout(()=>{if(current===s){s.node.port.postMessage('finish');setTimeout(()=>{if(current===s&&s.phase==='recording')cancel('录音设备未响应，请重试。');},1500);}},20000);
 }catch(error){if(current===s)cancel(({NotAllowedError:'麦克风权限未允许，请在浏览器设置中允许后重试。',NotFoundError:'没有找到麦克风，仍可打字。',NotReadableError:'麦克风被占用或无法读取，仍可打字。'})[error.name]||error.message);}
}
mic.addEventListener('click',begin);
$('voice-cancel').addEventListener('click',()=>cancel());
$('voice-insert').addEventListener('click',()=>{
 const s=current,text=$('voice-preview').value.trim();if(!s||s.phase!=='preview'||!text)return;
 if(context()!==s.context){cancel('已切换会话，转写未填入。');return;}
 const input=$('message'),next=input.value+(input.value?'\n':'')+text;
 if(next.length>input.maxLength){notice('输入框已满，请缩短转写或原草稿。');return;}
 input.value=next;input.dispatchEvent(new Event('input',{bubbles:true}));input.focus();
 current=null;generation++;controls('idle');$('voice-preview').value='';notice('已填入消息，可修改后发送；此后文字按当前会话模型处理。');
 api({action:'forget',id:s.id}).catch(()=>{});
});
// A microphone turn interrupts playback, never the independent background task lane.
window.addEventListener('jarvis:message-start',event=>{
 if(current)cancel('已发送文字，本轮语音输入取消。');
 window.JarvisReadout?.stop('新消息已发送，旧播报停止。');
 replyTicket={id:event.detail.id,epoch:generation,context:context(),enabled:$('voice-auto').checked};
});
window.addEventListener('jarvis:reply-ready',event=>{
 const t=replyTicket,d=event.detail;
 if(!t||t.id!==d.id||t.epoch!==generation||t.context!==context()||!t.enabled||!$('voice-auto').checked||current||document.hidden)return;
 replyTicket=null;window.JarvisReadout?.speak(d.article);
});
window.addEventListener('hashchange',()=>{if(current)cancel('切换会话，语音输入已取消。');generation++;replyTicket=null;});
window.addEventListener('jarvis:conversation-context',()=>{
 if(current&&current.context!==context())cancel('切换会话，语音输入已取消。');
 if(replyTicket&&replyTicket.context!==context()){generation++;replyTicket=null;}
});
document.addEventListener('visibilitychange',()=>{if(document.hidden&&current)cancel('页面已隐藏，语音输入已取消。');if(document.hidden){generation++;replyTicket=null;}});
window.addEventListener('pagehide',()=>cancel('页面已关闭。',true));
controls('idle');
})();
