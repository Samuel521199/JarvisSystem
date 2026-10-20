// Offline event tests for the real attachment module; no browser, network or API keys.
const assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
const {randomUUID}=require('node:crypto');
class Element{
  constructor(){this.children=[];this.handlers={};this.value='';this.hidden=false;this.dataset={};this.selectionStart=0;this.selectionEnd=0;this.classList={add(){},remove(){}};}
  addEventListener(name,fn){(this.handlers[name]??=[]).push(fn);}
  emit(name,event={}){for(const fn of this.handlers[name]||[])fn(event);}
  append(...items){this.children.push(...items);}
  replaceChildren(...items){this.children=items;}
  setAttribute(){} focus(){} click(){this.emit('click');}
  setRangeText(text,start,end){this.value=this.value.slice(0,start)+text+this.value.slice(end);}
}
const elements=new Map(),document=new Element();document.getElementById=id=>{if(!elements.has(id))elements.set(id,new Element());return elements.get(id);};document.createElement=()=>new Element();
const notifications=[],state={document,window:{},chosenModel:()=>null,history:[],modelCatalog:[],notify:text=>notifications.push(text),TextEncoder,TextDecoder,Uint8Array,Blob,URL,atob,btoa,crypto:{randomUUID},Image:class{set src(_){this.naturalWidth=this.naturalHeight=160;queueMicrotask(()=>this.onload());}}};
vm.createContext(state);vm.runInContext(fs.readFileSync('apps/web/attachments.js','utf8'),state);
const ui=state.window.Attachments,el=document.getElementById,tick=()=>new Promise(resolve=>setImmediate(resolve));
const file=(name,text,type='text/plain')=>({name,type,size:Buffer.byteLength(text),lastModified:1,arrayBuffer:async()=>Uint8Array.from(Buffer.from(text)).buffer});
const drop=(files,extra={})=>{let prevented=false;document.emit('drop',{preventDefault(){prevented=true;},dataTransfer:{types:['Files'],files,items:[],...extra}});return prevented;};
(async()=>{
  assert.equal(drop([file('notes.txt','真实拖拽正文')]),true);await tick();assert.equal(ui.wire()[0].text,'真实拖拽正文');
  const old=ui.snapshot();ui.clear();assert.equal(ui.hasDraft(),false);ui.restore(old);assert.equal(ui.wire()[0].name,'notes.txt');
  let complete;const delayed={...file('slow.txt','later'),arrayBuffer:()=>new Promise(resolve=>complete=resolve)};drop([delayed]);
  const pending=ui.snapshot().at(-1);assert.match(ui.issue(),/读取/);ui.consume([pending]);complete(Uint8Array.from(Buffer.from('later')).buffer);await tick();assert.equal(ui.wire().length,1);
  ui.clear();const clipboard=file('clipboard.png','not image','image/png');el('composer').emit('paste',{clipboardData:{files:[clipboard]},preventDefault(){}});await tick();assert.equal(ui.snapshot()[0].status,'error');assert.match(ui.issue(),/未就绪/);
  ui.clear();drop([file('bad.pdf','%PDF-1.4','application/pdf')]);await tick();assert.equal(ui.snapshot()[0].status,'error');
  ui.clear();el('message').value='';el('composer').emit('drop',{preventDefault(){},dataTransfer:{types:['text/plain'],getData:type=>type==='text/plain'?'拖入的文字':''}});assert.equal(el('message').value,'拖入的文字');
  ui.clear();drop(Array.from({length:10},(_,i)=>file('n'+i+'.txt','x')));await tick();assert.equal(ui.snapshot().length,8);assert.ok(notifications.some(n=>n.includes('最多添加 8')));
  const submitted=ui.snapshot();ui.consume(submitted);drop([file('new.txt','新草稿')]);await tick();assert.equal(ui.retry(submitted),false);assert.equal(ui.wire()[0].name,'new.txt');
  ui.clear();drop([file('folder','')],{items:[{webkitGetAsEntry:()=>({isDirectory:true})}]});await tick();assert.ok(notifications.some(n=>n.includes('文件夹请使用')));
  ui.clear();el('message').value='';
  ui.addText({kind:'text',name:'共享资料.txt',text:'明确选择的资料'});
  assert.equal(ui.wire()[0].text,'明确选择的资料');
  for(const bad of [{kind:'text',name:'x',text:' '},{kind:'text',name:'x',text:'中'.repeat(16385)},{kind:'image',name:'x',text:'x'}])assert.throws(()=>ui.addText(bad));
  assert.equal(ui.wire().length,1);
  for(let i=1;i<8;i++)ui.addText({kind:'text',name:'x',text:'x'});
  assert.throws(()=>ui.addText({kind:'text',name:'ninth',text:'x'}),/8/);
  ui.clear();el('message').value='x'.repeat(65530);
  assert.throws(()=>ui.addText({kind:'text',name:'x',text:'x'.repeat(100)}),/容量/);
  assert.equal(ui.wire().length,0);
  console.log('PASS: drag, paste, text insertion, read errors, removal races, session drafts, count limits and new-draft preservation');
})().catch(error=>{console.error(error);process.exitCode=1;});
