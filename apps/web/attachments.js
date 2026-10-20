"use strict";
(() => {
  const el=id=>document.getElementById(id),bytes=s=>new TextEncoder().encode(s).length;
  const MiB=1024*1024,MAX_FILES=8,MAX_TOTAL=8*MiB;
  const textExtensions=new Set('txt md markdown csv tsv json jsonl yaml yml toml xml html htm css scss js jsx mjs cjs ts tsx py pyi java c h cpp hpp cs go rs sh ps1 bat cmd sql log ini cfg conf svg srt vtt tex r rb php swift kt vue svelte gitignore env'.split(' '));
  let draft=[],previewURLs=[],dragDepth=0;
  const sizes=n=>n>=MiB?(n/MiB).toFixed(1)+' MiB':n>=1024?(n/1024).toFixed(1)+' KiB':n+' B';
  const wire=()=>draft.filter(x=>x.status==='ready').map(x=>x.attachment);
  const allImages=items=>items.flatMap(m=>m.attachments||[]).filter(a=>a.kind==='image');
  const imageBytes=a=>a.data.length/4*3-(a.data.endsWith('==')?2:a.data.endsWith('=')?1:0);
  function messageText(m){let text=m.content;for(const a of m.attachments||[])text+=a.kind==='text'?'\n\n[附件资料：'+a.name+']\n'+a.text+'\n[附件结束]':'\n[图片附件：'+a.name+']';return text;}
  function fits(items,maxText=32768,maxImages=8,maxBytes=MAX_TOTAL){const images=allImages(items);return items.reduce((s,m)=>s+bytes(messageText(m)),0)<=maxText&&images.length<=maxImages&&images.reduce((s,a)=>s+imageBytes(a),0)<=maxBytes;}
  function context(items,current){const images=allImages([current]);const recent=items.slice(-20);while(recent.length&&!fits(recent,Math.min(32768,65536-bytes(messageText(current))),8-images.length,MAX_TOTAL-images.reduce((s,a)=>s+imageBytes(a),0)))recent.shift();while(recent[0]?.role==='assistant')recent.shift();return recent;}
  function issue(){
    if(draft.some(x=>x.status==='reading'))return '正在读取附件，请稍候。';
    if(draft.some(x=>x.status==='error'))return '部分附件未就绪，请重试或移除后发送。';
    const current={content:el('message').value.trim(),attachments:wire()};
    if(!fits([current],65000))return '正文与文本附件合计最多约 64 KiB，图片最多 8 张、合计 8 MiB。请减少内容。';
    const item=chosenModel();
    if(item&&!item.image_input&&(allImages([current]).length||allImages(context(history,current)).length))return '本轮或历史含图片，请选择支持图片的模型（如 Gemini、GPT 或 Claude），或新建纯文本会话。';
    if(!item&&allImages([current]).length&&modelCatalog.length&&!modelCatalog.some(m=>m.image_input&&m.is_provider_default))return '当前自动路由没有已接通图片输入的默认模型，请改选支持图片的模型。';
    return '';
  }
  function update(){
    const error=issue(),count=draft.length,note=el('attachment-status');
    const dropped=history.length-context(history,{content:el('message').value.trim(),attachments:wire()}).length;
    note.hidden=!count&&!error&&!dropped;note.dataset.error=String(Boolean(error));
    note.textContent=error||(count+' 个附件 · 仅在本页保留，发送时交给所选模型。')+(dropped?' 本轮将省略 '+dropped+' 条最早的历史（含其附件）。':'');
  }
  function blobURL(a){const raw=Uint8Array.from(atob(a.data),c=>c.charCodeAt(0));return URL.createObjectURL(new Blob([raw],{type:a.media_type}));}
  function card(item,removable){
    const a=item.attachment,row=document.createElement('div');row.className='attachment-card';row.dataset.state=item.status;
    if(a?.kind==='image'){const img=document.createElement('img'),url=blobURL(a);img.src=url;img.alt=item.name;row.append(img);if(removable)previewURLs.push(url);else{img.addEventListener('load',()=>URL.revokeObjectURL(url),{once:true});img.addEventListener('error',()=>URL.revokeObjectURL(url),{once:true});}}
    else{const icon=document.createElement('span');icon.className='attachment-file-icon';icon.textContent=item.name.split('.').pop().slice(0,5).toUpperCase();icon.setAttribute('aria-hidden','true');row.append(icon);}
    const copy=document.createElement('span'),title=document.createElement('strong'),detail=document.createElement('small');copy.className='attachment-copy';title.textContent=item.name;title.title=item.name;
    detail.textContent=item.status==='error'?item.error:item.status==='reading'?'正在读取…':sizes(item.size)+' · '+(a?.kind==='image'?'图片已就绪':'正文已读取');copy.append(title,detail);row.append(copy);
    if(removable){if(item.status==='error'){const retry=document.createElement('button');retry.type='button';retry.className='attachment-retry';retry.textContent='重新读取';retry.addEventListener('click',()=>read(item));copy.append(retry);}const remove=document.createElement('button');remove.type='button';remove.className='attachment-remove';remove.textContent='×';remove.setAttribute('aria-label','移除附件 '+item.name);remove.addEventListener('click',()=>{draft=draft.filter(x=>x!==item);render();el('message').focus();});row.append(remove);}
    return row;
  }
  function render(){for(const url of previewURLs)URL.revokeObjectURL(url);previewURLs=[];el('attachment-list').replaceChildren(...draft.map(x=>card(x,true)));el('attachment-list').hidden=!draft.length;update();}
  async function read(item){
    item.status='reading';item.error='';item.attachment=null;render();
    try{
      const file=item.file,name=item.name,ext=name.includes('.')?name.split('.').pop().toLowerCase():'';
      if(!file.size)throw new Error('文件为空或是文件夹；文件夹请使用“打开项目”。');
      if(file.size>4*MiB)throw new Error('单张图片最多 4 MiB；文本文件最多 48 KiB。');
      const raw=new Uint8Array(await file.arrayBuffer());let mime='';
      if(raw[0]===137&&raw[1]===80&&raw[2]===78&&raw[3]===71)mime='image/png';
      else if(raw[0]===255&&raw[1]===216&&raw[2]===255)mime='image/jpeg';
      else if(String.fromCharCode(...raw.slice(0,4))==='RIFF'&&String.fromCharCode(...raw.slice(8,12))==='WEBP')mime='image/webp';
      if(mime){
        const url=URL.createObjectURL(new Blob([raw],{type:mime}));
        try{await new Promise((resolve,reject)=>{const img=new Image();img.onload=()=>img.naturalWidth>8000||img.naturalHeight>8000||img.naturalWidth*img.naturalHeight>20000000?reject(new Error('图片尺寸过大，请缩小至 8000 像素边长、2000 万像素以内。')):resolve();img.onerror=()=>reject(new Error('图片无法读取，请重新导出 PNG、JPEG 或 WebP。'));img.src=url;});}finally{URL.revokeObjectURL(url);}
        let binary='';for(let n=0;n<raw.length;n+=16384)binary+=String.fromCharCode(...raw.subarray(n,n+16384));
        item.attachment={kind:'image',name,media_type:mime,data:btoa(binary)};
      }else{
        if(!textExtensions.has(ext)&&!file.type.startsWith('text/')&&!/^(readme|license|dockerfile|makefile)$/i.test(name))throw new Error('暂不解析此格式。请转换为 TXT/Markdown，或将需要的页面截图后添加。');
        if(file.size>48*1024)throw new Error('文本文件最多 48 KiB，请拆分后添加。');
        const encoding=raw[0]===255&&raw[1]===254?'utf-16le':raw[0]===254&&raw[1]===255?'utf-16be':'utf-8';
        let text;try{text=new TextDecoder(encoding,{fatal:true}).decode(raw);}catch{throw new Error('文本编码无法读取，请另存为 UTF-8 后添加。');}
        if(bytes(text)>48*1024||/[\x00-\x08\x0b\x0c\x0e-\x1f]/.test(text))throw new Error('不是可读文本，或解码后超过 48 KiB。');
        item.attachment={kind:'text',name,text};
      }
      item.status='ready';
    }catch(error){item.status='error';item.error=error.message||'读取失败，请重新选择文件。';}
    render();
  }
  function add(files){
    for(const file of Array.from(files)){
      if(draft.length>=MAX_FILES){notify('每条消息最多添加 8 个附件，剩余文件未添加。');break;}
      const name=(file.name||'粘贴图片.png').replace(/[\x00-\x1f\x7f/\\]/g,'_').slice(0,180);
      if(draft.some(x=>x.name===name&&x.size===file.size&&x.file.lastModified===file.lastModified)){notify('已跳过重复附件：'+name);continue;}
      if(file.size+draft.reduce((s,x)=>s+x.size,0)>MAX_TOTAL+MAX_FILES*48*1024){notify('附件总大小超过 8 MiB，请先移除一些附件。');continue;}
      const item={id:crypto.randomUUID(),name,size:file.size,file,status:'reading'};draft.push(item);read(item);
    }
    el('message').focus();
  }
  function insert(text){if(!text)return;if(bytes(el('message').value)+bytes(text)>65000){notify('拖入的文字过长，请缩短后添加。');return;}const input=el('message');input.setRangeText(text,input.selectionStart,input.selectionEnd,'end');input.focus();update();}
  const files=transfer=>Array.from(transfer?.files||[]);
  const hasFiles=event=>Array.from(event.dataTransfer?.types||[]).includes('Files');
  document.addEventListener('dragenter',event=>{if(hasFiles(event)){event.preventDefault();dragDepth++;if(!el('chat-panel').hidden)el('composer').classList.add('drag-over');}});
  document.addEventListener('dragover',event=>{if(hasFiles(event)){event.preventDefault();event.dataTransfer.dropEffect='copy';}});
  document.addEventListener('dragleave',event=>{if(hasFiles(event)&&--dragDepth<=0){dragDepth=0;el('composer').classList.remove('drag-over');}});
  document.addEventListener('drop',event=>{
    dragDepth=0;el('composer').classList.remove('drag-over');if(!hasFiles(event))return;event.preventDefault();
    if(el('chat-panel').hidden){notify('请先切回当前对话，再添加附件。');return;}
    const items=Array.from(event.dataTransfer.items||[]);if(items.some(x=>x.webkitGetAsEntry?.()?.isDirectory))notify('文件夹请使用“打开项目文件夹”；此处只添加文件。');
    add(files(event.dataTransfer));
  });
  el('composer').addEventListener('dragover',event=>{if(!hasFiles(event)&&Array.from(event.dataTransfer?.types||[]).some(x=>['text/plain','text/uri-list','text/html'].includes(x)))event.preventDefault();});
  el('composer').addEventListener('drop',event=>{if(hasFiles(event))return;event.preventDefault();let text=event.dataTransfer.getData('text/plain')||event.dataTransfer.getData('text/uri-list').split('\n').filter(x=>!x.startsWith('#')).join('\n');if(!text){notify('请拖入可复制的文字、链接，或先把图片保存为文件。');return;}insert(text);});
  el('composer').addEventListener('paste',event=>{const incoming=files(event.clipboardData);if(incoming.length){event.preventDefault();add(incoming);}});
  el('attach-button').addEventListener('click',()=>el('attachment-input').click());
  el('attachment-input').addEventListener('change',event=>{add(event.target.files);event.target.value='';});
  el('message').addEventListener('input',update);
  function addText(attachment){
    if(!attachment||attachment.kind!=='text'||typeof attachment.name!=='string'||typeof attachment.text!=='string'||bytes(attachment.text)>49152||!attachment.text.trim())throw new Error('文字附件格式无效。');
    if(draft.length>=8)throw new Error('每条消息最多添加 8 个附件。');
    if(!fits([{content:el('message').value,attachments:[...wire(),attachment]}],65536))throw new Error('消息与附件超出本轮容量，请先缩短内容。');
    const item={id:crypto.randomUUID(),name:attachment.name,size:bytes(attachment.text),status:'ready',attachment};draft.push(item);render();return item.id;
  }
  window.Attachments={addText,
    snapshot:()=>draft.slice(),restore:items=>{draft=(items||[]).slice();render();},hasDraft:()=>draft.length>0,
    clear:()=>{draft=[];render();},update,wire,issue,messageText,fits,context,
    consume:items=>{const ids=new Set(items.map(x=>x.id));draft=draft.filter(x=>!ids.has(x.id));render();},
    retry:items=>{if(!draft.length){draft=items.slice();render();return true;}return false;},
    show:(article,items)=>{if(!items.length)return;const list=document.createElement('div');list.className='message-attachments';list.setAttribute('aria-label','本条消息的附件');for(const item of items)list.append(card(item,false));article.append(list);},
    offerRetry:(article,items,message)=>{if(!items.length)return;const button=document.createElement('button');button.type='button';button.className='attachment-retry';button.textContent='恢复本次附件与问题';button.addEventListener('click',()=>{if(draft.length||el('message').value.trim()){notify('请先发送或清空当前草稿，再恢复本次附件。');return;}draft=items.slice();el('message').value=message;render();el('message').focus();});article.append(button);}
  };
  render();
})();
