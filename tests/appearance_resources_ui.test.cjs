/* Browser-independent lifecycle branches; visible layout is checked in browser. */
const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');
const source = file => fs.readFileSync(path.join(__dirname,'../apps/web',file),'utf8');

function appearance(saved='dark', blocked=false) {
  const documentEvents={}, windowEvents={}, mediaEvents={}, choices=[];
  const select={addEventListener:(name,fn)=>select[name]=fn}, notice={}, announcement={};
  const host={querySelector:()=>select};
  const previews={set innerHTML(html) {
    for (const [,value] of html.matchAll(/data-theme-choice="([^"]+)"/g)) choices.push({dataset:{themeChoice:value},
      setAttribute(name,value){this[name]=value;},addEventListener(name,fn){this[name]=fn;}});
  },querySelectorAll:()=>choices};
  const root={dataset:{}};
  const media={matches:true,addEventListener:(name,fn)=>mediaEvents[name]=fn};
  vm.runInNewContext(source('theme.js'), {
    document:{documentElement:root,readyState:'loading',addEventListener:(n,f)=>documentEvents[n]=f,
      querySelectorAll:selector=>({'[data-appearance-control]':[host],'[data-appearance-previews]':[previews],
        '[data-theme-choice]':choices,'.appearance-picker':[select],'.appearance-storage-note':[notice],'.appearance-announcement':[announcement]})[selector]||[]},
    window:{matchMedia:()=>media,addEventListener:(n,f)=>windowEvents[n]=f},
    localStorage:{getItem(){if(blocked)throw Error();return saved;},setItem(k,v){if(blocked)throw Error();saved=v;}},
  });
  documentEvents.DOMContentLoaded();
  return {root,choices,select,notice,announcement,media,mediaEvents,windowEvents,saved:()=>saved};
}

test('preview click applies, saves and selects exactly one palette',()=>{
  const ui=appearance();
  assert.equal(ui.choices.length,6);
  for(const choice of ui.choices){
    choice.click();
    assert.equal(ui.root.dataset.theme,choice.dataset.themeChoice);
    assert.equal(ui.saved(),choice.dataset.themeChoice);
    assert.equal(ui.select.value,choice.dataset.themeChoice);
    assert.equal(ui.choices.filter(c=>c['aria-pressed']==='true').length,1);
  }
});
test('system follows OS, explicit palettes win and invalid stored values fall back',()=>{
  const ui=appearance('invalid');
  assert.equal(ui.select.value,'system');
  assert.equal(ui.root.dataset.theme,'dark');
  ui.media.matches=false;ui.mediaEvents.change();
  assert.equal(ui.root.dataset.theme,'light');
  ui.choices.find(c=>c.dataset.themeChoice==='forest').click();
  ui.media.matches=true;ui.mediaEvents.change();
  assert.equal(ui.root.dataset.theme,'forest');
});
test('cross-tab storage updates selection; blocked storage still allows switching',()=>{
  const ui=appearance();
  ui.windowEvents.storage({key:'jarvis.appearance.v1',newValue:'mist'});
  assert.equal(ui.root.dataset.theme,'mist');
  assert.equal(ui.choices.find(c=>c.dataset.themeChoice==='mist')['aria-pressed'],'true');
  const blocked=appearance('dark',true);
  blocked.choices.find(c=>c.dataset.themeChoice==='midnight').click();
  assert.equal(blocked.root.dataset.theme,'midnight');
  assert.equal(blocked.notice.hidden,false);
  assert.match(blocked.announcement.textContent,/仅本页/);
});

function resources() {
  const events={},windowEvents={},timers=new Map(),calls=[],home={hidden:true},doc={hidden:false};
  const ids={'home-view':home,'resource-usage':{},'resource-updated':{}};
  for(const name of ['cpu','gpu','memory','vram']) {
    const children={strong:{},small:{},progress:{}};
    ids[`resource-${name}`]={children,querySelector:s=>children[s]};
  }
  let id=0;
  vm.runInNewContext(source('resources.js'),{
    document:Object.assign(doc,{getElementById:n=>ids[n],querySelector:()=>({content:'test-nonce'}),addEventListener:(n,f)=>events[n]=f}),
    window:{addEventListener:(n,f)=>windowEvents[n]=f},AbortController,Date,
    setTimeout:(f,ms)=>{timers.set(++id,{f,ms});return id;},clearTimeout:i=>timers.delete(i),
    fetch:(url,options)=>new Promise((resolve,reject)=>calls.push({url,options,resolve,reject})),
  });
  const flush=()=>new Promise(resolve=>setImmediate(resolve));
  const finish=async(data,index=calls.length-1)=>{calls[index].resolve({ok:true,json:async()=>data});await flush();};
  return {home,doc,ids,events,windowEvents,timers,calls,finish,flush};
}
const snapshot={sampled_at:'2026-10-16T12:00:00Z',stale:false,cpu_percent:0,gpu_percent:null,
  memory:{percent:25,used_bytes:1073741824,total_bytes:4294967296},adapters:[]};
test('resource polling starts only on home and stops when hidden or navigating away',async()=>{
  const ui=resources();ui.windowEvents.pageshow();assert.equal(ui.calls.length,0);
  ui.home.hidden=false;ui.events['jarvis:settings-view']();assert.equal(ui.calls.length,1);
  await ui.finish(snapshot);
  assert.equal(ui.ids['resource-cpu'].children.strong.textContent,'0%');
  assert.equal(ui.ids['resource-gpu'].children.strong.textContent,'—');
  assert.equal(ui.ids['resource-gpu'].children.progress.hidden,true);
  assert.equal(ui.timers.size,1);
  ui.doc.hidden=true;ui.events.visibilitychange();assert.equal(ui.timers.size,0);
  ui.doc.hidden=false;ui.events.visibilitychange();assert.equal(ui.calls.length,2);
  ui.home.hidden=true;ui.events['jarvis:settings-view']();
  assert.equal(ui.calls[1].options.signal.aborted,true);
  await ui.finish(snapshot);
  assert.equal(ui.timers.size,0);
});
test('late responses cannot replace a newer sample; stale values are cleared',async()=>{
  const ui=resources();ui.home.hidden=false;ui.windowEvents.pageshow();
  ui.doc.hidden=true;ui.events.visibilitychange();ui.doc.hidden=false;ui.events.visibilitychange();
  await ui.finish({...snapshot,cpu_percent:12},1);
  await ui.finish({...snapshot,cpu_percent:90},0);
  assert.equal(ui.ids['resource-cpu'].children.strong.textContent,'12%');
  ui.events['jarvis:settings-view']();await ui.finish({...snapshot,stale:true});
  assert.equal(ui.ids['resource-cpu'].children.strong.textContent,'—');
  assert.equal(ui.ids['resource-cpu'].children.progress.hidden,true);
});
