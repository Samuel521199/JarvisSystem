/* Optional DOM regression runner. Pass a development-only LinkeDOM module path.
 * This does not render a browser, inspect the desktop or launch Explorer. */
const assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
const path=require('node:path');
const root=path.resolve(__dirname,'..');
const {parseHTML}=require(process.argv[2]||'linkedom');
const {window,document}=parseHTML(fs.readFileSync(path.join(root,'apps/web/index.html'),'utf8'));
const p={id:'a'.repeat(32),name:'示例项目',path:'H:\\Example',available:true},q={id:'b'.repeat(32),name:'另一个项目',path:'H:\\Other',available:true};
let store={profiles:{},archived_chats:[]},notices=[],posts=[],clipboard='',docs=new Map();
for(const [id,project_id,title] of [['1'.repeat(32),p.id,'已有会话'],['2'.repeat(32),p.id,'第二会话'],['3'.repeat(32),q.id,'其他项目聊天']])docs.set(id,{project_id,title,context_note:'',messages:[]});
const tick=async()=>{for(let i=0;i<12;i++)await new Promise(resolve=>setImmediate(resolve));};
for(const el of document.querySelectorAll('dialog')){el.showModal=function(){this.open=true;};el.close=function(){this.open=false;};}
let focused=document.body;Object.defineProperty(document,'activeElement',{get:()=>focused});window.HTMLElement.prototype.focus=function(){focused=this;};window.HTMLElement.prototype.getBoundingClientRect=function(){return {top:160,bottom:190,left:20,right:230,width:210,height:30};};
window.HTMLElement.prototype.showModal=function(){this.open=true;};window.HTMLElement.prototype.close=function(){this.open=false;};
const localStorage={getItem:()=>null,setItem:()=>{}},location={hash:'#project='+p.id,pathname:'/'};
window.history={replaceState(_a,_b,path){location.hash=path.startsWith('#')?path:'';}};
const Conversations={async list(){return [...docs].map(([id,r])=>({id,project_id:r.project_id,title:r.title}));},async load(id){return docs.get(id);},capture(){return [];},async flush(){},async save(){},async remove(id){docs.delete(id);}};
const context={window,document,localStorage,location,console,crypto:require('node:crypto').webcrypto,AbortSignal,AbortController,setTimeout,clearTimeout,innerWidth:1280,innerHeight:800,NONCE:'test',busy:false,history:[],Conversations,Attachments:{hasDraft:()=>false,snapshot:()=>[],restore:()=>{}},setControls(){},notify(s){notices.push(s);},resetConversation(){context.history=[];document.getElementById('messages').replaceChildren();document.getElementById('message').value='';document.getElementById('session-title').textContent='当前对话';},providerHint(){},trimHistory(){},navigator:{clipboard:{async writeText(text){clipboard=text;}}},confirm:()=>true};

for(const key of ['ProjectMenu','Workspace'])Object.defineProperty(context,key,{get:()=>window[key]});
context.fetch=async(path,options={})=>{const body=options.body?JSON.parse(options.body):null;let result;if(body)posts.push({path,body});
 if(path==='/api/workspace/projects')result={projects:[p,q]};
 else if(path==='/api/workspace/organization')result=structuredClone(store);
 else if(path.endsWith('/edit')){const id=path.split('/').at(-2);store.profiles[id]={...body.document,revision:body.revision+1};result=store.profiles[id];}
 else if(path.endsWith('/archive')){const id=path.split('/').at(-2);if(body.archived)store.archived_chats.push(...body.chat_ids.map(id2=>({id:id2,project_id:id})));else store.archived_chats=store.archived_chats.filter(r=>!body.chat_ids.includes(r.id));result={};}
 else if(path.endsWith('/reveal'))result={status:'opened'};
 else throw new Error('Unexpected fetch '+path);
 return {ok:true,async json(){return result;}};
};
vm.createContext(context);
for(const name of ['project_menu.js','workspace.js'])vm.runInContext(fs.readFileSync(path.join(root,'apps/web',name),'utf8'),context,{filename:name});
(async()=>{
 await tick();assert.equal(document.querySelectorAll('.project-more').length,2);
 const more=()=>document.querySelector('.project-more[data-project-id="'+p.id+'"]');
 const item=text=>{const b=[...document.querySelectorAll('#project-menu button')].find(b=>b.textContent===text);assert.ok(b,'Menu missing '+text);return b;};
 const stylesheet=fs.readFileSync(path.join(root,'apps/web/project_menu.css'),'utf8');assert.match(stylesheet,/^\.project-more\{[^}]*opacity:1/);assert.doesNotMatch(stylesheet,/\.project-more\{[^}]*opacity:0/);
 assert.equal(more().hidden,false);more().click();assert.equal(document.getElementById('project-menu').hidden,false);
 for(const label of ['编辑项目…','置顶项目','分区 ›','在资源管理器中打开','复制项目路径','归档聊天','已归档聊天','移除项目…'])assert.equal(item(label).disabled,false,label);
 document.dispatchEvent(new window.Event('keydown'));more().closest('.project-heading').dispatchEvent(new window.Event('contextmenu',{bubbles:true,cancelable:true}));assert.equal(document.getElementById('project-menu').hidden,false);
 item('编辑项目…').click();
 document.getElementById('project-edit-name').value='自定义名字';document.getElementById('project-edit-description').value='项目说明';document.getElementById('project-edit-section').value='研发';document.getElementById('project-edit-form').dispatchEvent(new window.Event('submit',{cancelable:true}));await tick();
 assert.equal(window.Workspace.currentProject().name,'自定义名字');assert.match(document.getElementById('project-list').textContent,/研发/);assert.equal(document.getElementById('project-edit-dialog').open,false);
 more().click();item('置顶项目').click();await tick();assert.ok(store.profiles[p.id].pinned);assert.match(document.getElementById('project-list').textContent,/置顶/);
 more().click();item('取消置顶').click();await tick();assert.equal(store.profiles[p.id].pinned,false);
 more().click();item('分区 ›').click();item('未分区').click();await tick();assert.equal(store.profiles[p.id].section,'');
 document.getElementById('message').value='保留聊天草稿';more().click();item('归档聊天').click();await tick();assert.equal(store.archived_chats.length,2);assert.equal(document.querySelector('[data-session-id="'+ '1'.repeat(32)+'"]'),null);assert.ok(document.querySelector('[data-session-id="'+ '3'.repeat(32)+'"]'));assert.ok(document.getElementById('current-chat'));
 more().click();item('已归档聊天 · 2').click();await tick();document.querySelector('#project-archives-list button').click();await tick();assert.equal(store.archived_chats.length,1);assert.ok(document.querySelector('[data-session-id="'+ '1'.repeat(32)+'"]'));document.getElementById('project-archives-close').click();
 more().click();item('复制项目路径').click();await tick();assert.equal(clipboard,p.path);
 more().click();item('在资源管理器中打开').click();await tick();assert.ok(posts.some(r=>r.path.endsWith('/reveal')&&Object.keys(r.body).length===0));
 more().click();item('移除项目…').click();await tick();assert.equal(window.Workspace.currentProject(),null);assert.equal(more(),null);assert.ok(document.getElementById('current-chat'));assert.equal(docs.size,3);
 document.querySelector('.project-recovery-entry').click();document.querySelector('#project-removed-list button').click();await tick();assert.ok(more());assert.equal(store.profiles[p.id].removed,false);
 window.Workspace.newSession(window.Workspace.allProjects().find(row=>row.id===p.id));document.getElementById('message').value='最新草稿';
 Conversations.capture=()=>[{role:'user',content:'未确认保存的消息'}];Conversations.save=async()=>{throw new Error('simulated save failure');};window.Workspace.remember();await tick();
 const previousArchivePosts=posts.filter(r=>r.path.endsWith('/archive')).length;
 more().click();item('归档聊天').click();await tick();assert.equal(posts.filter(r=>r.path.endsWith('/archive')).length,previousArchivePosts);assert.ok(notices.some(s=>s.includes('当前聊天尚未保存成功')));assert.equal(document.getElementById('message').value,'最新草稿');
 console.log(JSON.stringify({status:'passed',checks:['always-visible more button CSS and all eight menu entries enabled','project row context menu','menu/details','edit/alias/description','pin and unpin','section menu and move to ungrouped','archive by project','restore archived chat','copy and reveal root','remove active project and recover without lost active control','stored chat bodies preserved','previous autosave failure prevents archive and retains newest draft'],notice_count:notices.length,method:'LinkeDOM and API doubles; no browser rendering or physical interaction'}));
})().catch(e=>{console.error(e);process.exitCode=1;});
