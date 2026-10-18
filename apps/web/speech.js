/* Independent local TTS panels. Observation never loads weights. */
(()=>{'use strict';
const nonce=document.querySelector('meta[name="jarvis-nonce"]').content;
function mount(prefix,endpoint,fast){
 const $=id=>document.getElementById(`${prefix}-${id}`);if(!$('panel'))return;
 const primary=prefix==='primary-speech';let choicesLoaded=false,previewEpoch=0;
 let timer=null,busy=false,loading=false,data=null,audioId=null,audioUrl=null,request=null;
 const visible=()=>location.hash==='#modules'&&!document.hidden;
 const names={stopped:'未加载',loading:'正在校验和加载',ready:'就绪',busy:'正在合成',failed:'语音组件失败'};
 function error(message){$('error').textContent=message;$('error').hidden=!message;}
 async function api(path,payload,signal){const r=await fetch(path,{method:payload?'POST':'GET',headers:{'X-Jarvis-Nonce':nonce,...(payload?{'Content-Type':'application/json'}:{})},body:payload?JSON.stringify(payload):undefined,signal});if(!r.ok){const e=await r.json();throw new Error(e.user_message||e.error?.message||'语音操作失败');}return r;}
 function render(value){data=value;const m=value.memory,job=value.job;
  const gib=n=>typeof n==='number'?`${(n/1024**3).toFixed(2)} GiB`:'暂不可读';
  $('status').textContent=`${value.installed?'已安装':'尚未安装完整'} · ${names[value.state]||value.state} · ${value.device} / CPU ${value.threads} 线程`+(m?` · 推理进程 RAM ${gib(m.working_set_bytes)} · RAM 峰值 ${gib(m.peak_working_set_bytes)}`:'')+(primary&&value.gpu_memory?` · GPU 专用 ${gib(value.gpu_memory.dedicated_bytes)} · GPU 共享 ${gib(value.gpu_memory.shared_bytes)}`:'')+(job?.status==='RUNNING'?' · 此操作在后台进行，聊天可继续':'');
  if(primary&&!choicesLoaded&&value.capabilities){for(const [field,key] of [['voice','voices'],['emotion','emotions'],['language','languages']]){const selected=$(field).value;$(field).replaceChildren(...Object.entries(value.capabilities[key]).map(([id,name])=>new Option(name,id)));$(field).value=selected;}choicesLoaded=true;}
  $('start').disabled=busy||!value.installed||value.owned||value.busy;
  $('stop').disabled=busy||!(value.owned||value.busy);
  $('generate').disabled=busy||value.state!=='ready'||value.busy||value.readout_active;
  if(value.readout_active){$('status').textContent+=' · 聊天朗读正在使用语音组件';$('generate').title='请先停止聊天朗读，或停止语音模型。';}else $('generate').title='';
  if(job?.status==='FAILED')error(job.message||'合成失败，可重新加载语音组件。');
  if(job?.status==='SUCCEEDED'&&job.result?.audio_url&&audioId!==job.id)showAudio(job).catch(e=>error(e.message));
 }
 async function showAudio(job){audioId=job.id;const response=await api(job.result.audio_url);const blob=await response.blob();
  if(audioUrl)URL.revokeObjectURL(audioUrl);audioUrl=URL.createObjectURL(blob);$('audio').src=audioUrl;$('download').href=audioUrl;
  const r=job.result;$('result-info').textContent=`已生成 ${r.audio_seconds.toFixed(2)} 秒语音 · 合成耗时 ${r.elapsed_seconds.toFixed(2)} 秒 · ${r.sample_rate_hz} Hz`+(primary?` · 应用表达：${r.expression||data?.capabilities?.emotions?.[r.emotion]||r.emotion}`:'');$('result').hidden=false;
  if(primary&&r.segments)renderPlan({segments:r.segments,speech_segments:r.speech_segments,pause_ms:r.pause_ms,warnings:r.warnings,direction:r.direction},true);
 }
 async function load(){if(!visible()||loading)return;loading=true;request=new AbortController();const timeout=setTimeout(()=>request.abort(),5000);
  try{render(await (await api(endpoint,undefined,request.signal)).json());}catch(e){if(visible())error(e.name==='AbortError'?'语音状态读取超时。':e.message);}finally{clearTimeout(timeout);loading=false;request=null;schedule();}}
 function schedule(){clearTimeout(timer);if(visible())timer=setTimeout(load,data?.busy?((fast||primary)?150:2000):primary&&data?.owned?2000:8000);}
 async function action(payload){busy=true;error('');if(data)render(data);try{render(await (await api(endpoint,payload)).json());}catch(e){error(e.message);}finally{busy=false;if(data)render(data);schedule();}}
 function bytes64(buffer){const bytes=new Uint8Array(buffer);let text='';for(let i=0;i<bytes.length;i+=16384)text+=String.fromCharCode(...bytes.subarray(i,i+16384));return btoa(text);}
 $('start').addEventListener('click',()=>action({action:'start'}));
 $('stop').addEventListener('click',()=>action({action:'stop'}));
 function speechPayload(actionName){return {action:actionName,text:$('text').value,voice:$('voice').value,emotion:$('emotion').value,language:$('language').value,direction:$('direction').value};}
 function renderPlan(plan,completed=false){
  $('preview-summary').textContent=`${completed?'已生成':'预览'} ${plan.speech_segments} 段表达 · 显式停顿 ${plan.pause_ms}ms`+(plan.direction?' · 使用表达提示':'')+(plan.warnings?.length?` · ${plan.warnings.join(' ')}`:'')+(!completed?' · 预览不加载模型，不生成音频。':'');
  $('preview-list').replaceChildren(...plan.segments.map(row=>{const li=document.createElement('li');const time=completed?`${row.start_seconds.toFixed(2)}–${row.end_seconds.toFixed(2)}s · `:'';li.textContent=time+(row.type==='pause'?`停顿 ${row.milliseconds}ms`:`${row.expression}：${row.text}`);return li;}));$('preview-result').hidden=false;
 }
 if(primary){
  $('preview').addEventListener('click',async()=>{const epoch=++previewEpoch;error('');$('preview').disabled=true;try{const value=await (await api(endpoint,speechPayload('preview'))).json();if(epoch===previewEpoch)renderPlan(value.preview);}catch(e){if(epoch===previewEpoch){$('preview-result').hidden=true;error(e.message);}}finally{$('preview').disabled=false;}});
  for(const field of ['text','voice','emotion','language','direction'])$(field).addEventListener('input',()=>{previewEpoch++;$('preview-result').hidden=true;});
 }
 if(!fast&&!primary)$('mode').addEventListener('change',()=>{const disabled=$('mode').value!=='instruct';$('emotion').disabled=disabled;if(disabled)$('emotion').value='neutral';});
 $('form').addEventListener('submit',async e=>{e.preventDefault();if(busy)return;
  try{if(primary){previewEpoch++;$('preview-result').hidden=true;await action(speechPayload('synthesize'));return;}
   const file=$('reference').files[0];if(file&&file.size>3000000)throw new Error('参考音频最大 3 MB。');
   const payload={action:'synthesize',text:$('text').value,mode:fast?'clone':$('mode').value,emotion:fast?'neutral':$('emotion').value,reference_text:$('transcript').value};
   if(file)payload.reference_audio=bytes64(await file.arrayBuffer());await action(payload);
  }catch(exc){error(exc.message);}});
 function sync(){clearTimeout(timer);if(visible())load();else request?.abort();}
 window.addEventListener('hashchange',sync);document.addEventListener('visibilitychange',sync);
 window.addEventListener('pagehide',()=>{clearTimeout(timer);request?.abort();if(audioUrl)URL.revokeObjectURL(audioUrl);});sync();
}
mount('primary-speech','/api/speech/primary',false);mount('fast-speech','/api/speech/fast',true);mount('speech','/api/speech',false);
})();
