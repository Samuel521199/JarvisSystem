/* Explicit, bounded continuous conversation. No autonomous task/file admission. */
(()=>{
'use strict';
const $=id=>document.getElementById(id),button=$('voice-session-toggle');
if(!button||!window.JarvisVoiceInput||!window.JarvisConversation)return;
const input=window.JarvisVoiceInput,readout=window.JarvisReadout,chat=window.JarvisConversation;
let current=null;
const live=s=>current===s&&s.context===input.context()&&!document.hidden;
function note(text){$('voice-panel').hidden=false;$('voice-status').textContent=text;}
function phase(s,value,text){
 if(!live(s))return;s.phase=value;button.dataset.state=value;
 $('voice-interject').hidden=value!=='speaking';
 if(text)note(text);
}
function gate(s,enabled){
 s.captureEpoch=(s.captureEpoch||0)+1;
 s.node?.port.postMessage({enabled:Boolean(enabled),epoch:s.captureEpoch});
}
function listen(s,text='正在听你说话…停顿约 1.1 秒后发送。'){
 if(!live(s))return;
 if(s.turns>=20){stop('已完成 20 轮，连续语音已退出。');return;}
 s.idle=Date.now();phase(s,'listening',text);gate(s,true);
}
function forget(id,action='forget',keepalive=false){
 if(!id)return;
 fetch('/api/speech/input',{method:'POST',keepalive,credentials:'omit',
  headers:{'X-Jarvis-Nonce':NONCE,'Content-Type':'application/json'},
  body:JSON.stringify({action,id})}).catch(()=>{});
}
function release(s){
 clearInterval(s.timer);gate(s,false);
 s.stream?.getTracks().forEach(t=>{t.onended=null;t.stop();});
 if(s.node){s.node.port.onmessage=null;s.node.disconnect();}
 s.source?.disconnect();s.audio?.close().catch(()=>{});
}
function stop(text='连续语音已退出，麦克风已释放。',keepalive=false,playback=true){
 const s=current;current=null;button.textContent='开始连续语音';button.setAttribute('aria-pressed','false');button.dataset.state='off';
 $('voice-interject').hidden=true;$('voice-duplex').disabled=false;note(text);
 if(!s)return;
 release(s);forget(s.asr,'cancel',keepalive);
 if(s.request)chat.cancelVoice(s.request);
 if(playback)readout?.stop('连续语音已退出。',keepalive);
}
function normalized(text){return text.toLowerCase().replace(/[\p{P}\p{Z}\s]/gu,'');}
function interruption(text,spoken){
 const t=normalized(text);
 if(/^(停一下|停止朗读|别说了|暂停|stop|pause)$/u.test(t))return 'stop';
 if(!t||/^(嗯|嗯嗯|哦|啊|好|好的|是的|对|ok|okay|yes|uhhuh)$/u.test(t))return 'ignore';
 if(t.length>=4&&normalized(spoken).includes(t))return 'ignore';
 return 'request';
}
async function segment(s,event){
 if(!live(s)||!['listening','speaking'].includes(s.phase))return;
 if(++s.segments>40){stop('语音片段达到本次上限，请检查环境后重新开启。');return;}
 const wasSpeaking=s.phase==='speaking',token=s.pauseToken,spoken=readout?.state()?.text||'';
 phase(s,'recognizing','正在本地判断语音并转写…');gate(s,false);
 const id=crypto.randomUUID().replaceAll('-','');s.asr=id;
 const pcm=input.encode({chunks:[event.samples],audio:s.audio});
 try{
  let result;
  try{result=await input.api({action:'transcribe',id,pcm,language:$('voice-language').value});}
  catch(error){result=await input.api(null,id);if(result.status==='MISSING')throw error;}
  const end=Date.now()+55000;
  while(result.status==='RUNNING'){
   if(!live(s))return;if(Date.now()>end)throw new Error('本地转写等待超时；没有自动重试。');
   await new Promise(r=>setTimeout(r,250));if(!live(s))return;result=await input.api(null,id);
  }
  if(!live(s))return;
  if(result.status!=='SUCCEEDED')throw new Error(result.message||'转写没有完成。');
  const text=result.text.trim();s.asr=null;s.candidate=false;forget(id);
  if(event.limited){stop('这段话达到 18 秒上限，未自动发送。转写在下方，可复制后编辑。');note('录音达到上限，未发送：'+text);return;}
  const kind=interruption(text,wasSpeaking?spoken:'');
  if(kind==='stop'){
   ++s.playEpoch;await readout?.stop('已按语音要求停止朗读。');
   if(live(s))listen(s,'朗读已停止。继续听你说话，后台任务未取消。');return;
  }
  if(!text||(wasSpeaking&&kind==='ignore')){
   if(++s.ignored>=8){stop('连续多次没有新请求，已退出。请调整环境后重试。');return;}
   if(wasSpeaking){
    await readout?.resume(token);s.pauseToken=null;
    if(live(s)){
     if(readout?.state()){phase(s,'speaking','未发现新请求，继续原位置播报。');gate(s,s.duplex);}
     else listen(s);
    }
   }else listen(s,'没有清晰语音，继续听你说话…');
   return;
  }
  s.ignored=0;++s.playEpoch;await readout?.stop('采用新的语音轮次，旧播报结束。');s.pauseToken=null;
  if(!live(s))return;
  if(!chat.ready())throw new Error('当前会话正在处理其他消息，连续语音已退出；没有排队或重发。');
  s.turns++;phase(s,'thinking',`第 ${s.turns} 轮 · ${text.slice(0,100)} · 等待回复时暂停采音分段`);
  const reply=await chat.sendVoice(text,id=>{s.request=id;});
  s.request=null;
  if(!live(s))return;
  if(!reply?.succeeded)throw new Error('这轮回复未完整完成，已退出连续语音；没有自动重发。');
  if(!readout)throw new Error('朗读组件不可用，文字回复已保留。');
  const epoch=++s.playEpoch;
  phase(s,'speaking','正在本地朗读，可点“我要插话”。');
  const playback=readout.speak(reply.article);gate(s,s.duplex);
  const completed=await playback;
  if(live(s)&&epoch===s.playEpoch&&!s.candidate&&s.phase!=='recognizing'){
   if(completed)listen(s);
   else stop('朗读未完整结束，已退出连续语音；文字回复保留。');
  }
 }catch(error){if(live(s))stop(error.message||'连续语音暂不可用，请继续打字。');}
}
async function start(){
 if(current){stop();return;}
 if(!chat.ready()){note('请先等当前回复完成，再开启连续语音。');return;}
 input.cancel('已切换到连续语音。');
 const s={context:input.context(),phase:'requesting',turns:0,segments:0,ignored:0,playEpoch:0,
  started:Date.now(),idle:Date.now(),duplex:$('voice-duplex').checked};
 current=s;$('voice-panel').querySelector('details').open=false;button.textContent='结束连续语音';button.setAttribute('aria-pressed','true');$('voice-duplex').disabled=true;
 phase(s,'requesting','正在请求麦克风…录音仅本地识别，转写文字发送当前模型。');
 s.timer=setInterval(()=>{
  if(!live(s))return;
  if(Date.now()-s.started>=600000)stop('连续语音已达到 10 分钟，已退出。');
  else if(s.phase==='listening'&&Date.now()-s.idle>=60000)stop('已安静 60 秒，连续语音已退出。');
  else if(s.phase==='speaking'&&readout?.state()?.paused&&!readout.state().ownedPause)stop('播放需要手动继续，已退出连续语音。',false,false);
 },1000);
 try{
  await readout?.stop('开始连续语音，旧播报停止。');if(!live(s))return;
  if(!navigator.mediaDevices?.getUserMedia||!window.AudioWorkletNode)throw new Error('此浏览器不支持连续语音，请继续打字。');
  s.audio=new AudioContext({sampleRate:16000});await s.audio.resume();if(!live(s)){release(s);return;}
  await s.audio.audioWorklet.addModule('/voice-session-capture.js');if(!live(s)){release(s);return;}
  const stream=await navigator.mediaDevices.getUserMedia({audio:{channelCount:1,echoCancellation:true,noiseSuppression:true},video:false});
  if(!live(s)){stream.getTracks().forEach(t=>t.stop());release(s);return;}s.stream=stream;
  for(const track of stream.getAudioTracks())track.onended=()=>{if(live(s))stop('麦克风已断开，连续语音退出。');};
  s.source=s.audio.createMediaStreamSource(stream);s.node=new AudioWorkletNode(s.audio,'jarvis-session-capture');
  s.node.port.onmessage=event=>{
   if(!live(s)||event.data.epoch!==s.captureEpoch)return;
   if(event.data.type==='speech-start'){
    if(!['listening','speaking'].includes(s.phase))return;
    s.candidate=true;s.idle=Date.now();
    if(s.phase==='speaking')s.pauseToken=readout?.pause();
    if(['listening','speaking'].includes(s.phase))note('正在听…停顿后识别。');
   }else if(event.data.type==='segment')segment(s,event.data);
  };
  s.source.connect(s.node);s.node.connect(s.audio.destination);listen(s);
 }catch(error){if(live(s))stop(error.name==='NotAllowedError'?'麦克风权限未允许，请继续打字。':error.message);}
}
$('voice-session-open').addEventListener('click',()=>{$('voice-panel').hidden=false;$('voice-panel').querySelector('details').open=true;button.focus();});
button.addEventListener('click',start);
$('voice-interject').addEventListener('click',async()=>{
 const s=current;if(!s||s.phase!=='speaking')return;
 ++s.playEpoch;gate(s,false);phase(s,'switching','正在结束旧播报…');
 await readout?.stop('开始新的语音轮次。');if(live(s))listen(s);
});
$('voice-record').addEventListener('click',()=>{if(current)stop('已切换到按键录音。');},true);
$('voice-cancel').addEventListener('click',()=>{if(current)stop();});
window.addEventListener('jarvis:message-start',event=>{if(current&&!event.detail.voice)stop('已发送文字，连续语音退出。');});
window.addEventListener('jarvis:readout-control',()=>{if(current)stop('已切换为手动控制朗读。',false,false);});
for(const name of ['hashchange','jarvis:conversation-context'])window.addEventListener(name,()=>{if(current&&current.context!==input.context())stop('会话已切换，连续语音退出。');});
document.addEventListener('visibilitychange',()=>{if(current&&document.hidden)stop('页面已隐藏，连续语音退出。');});
window.addEventListener('pagehide',()=>{if(current)stop('页面已关闭。',true);});
// Read-only state aids diagnostics; it cannot inject audio or grant authority.
window.JarvisVoiceSession={state:()=>current?{phase:current.phase,turns:current.turns,segments:current.segments}:null,stop};
})();
