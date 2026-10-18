// Anatomy drawing API, MIT; fixed teaching geometry, not manufacturing data.
const M=LESSON.model,P={scale:2.65,origin:[310,260]},distance=12+12*M.ratio,cx1=-distance/2,cx2=distance/2;
const sheet=document.createElement('style');
sheet.textContent=ISO_CSS+PAGE_CSS.replace('__WIDTH__','720')+'.lesson-intro{margin:0 0 20px}.lesson-intro h1{font-size:22px;margin:0 0 6px;color:var(--anatomy-strong)}.lesson-intro p{margin:4px 0}.lesson-controls{display:flex;gap:14px;flex-wrap:wrap;padding:14px;font:14px system-ui}.lesson-controls button{font:inherit;padding:7px 12px;cursor:pointer}.lesson-controls label{display:flex;gap:7px;align-items:center}.lesson-controls input{max-width:140px}@media(max-width:500px){.lesson-controls{gap:8px}}';
document.head.append(sheet);document.body.className='iso';document.body.dataset.theme=LESSON.parameters.theme;
const gear=(cx,cy,radius,teeth,angle,z)=>{
 const points=Array.from({length:teeth*4},(_,i)=>{const a=angle+i*Math.PI*2/(teeth*4),r=radius+([1,2].includes(i%4)?1.8:-1.3);return[cx+Math.cos(a)*r,cy+Math.sin(a)*r];});
 return solidSvg(extrude(points,z,5,P),{tone:'hi'})+solidSvg(cylinder(cx,cy,4,z+5,3,P),{tone:'mid'})+lineSvg(segment([cx,cy,z+8],[cx+Math.cos(angle)*(radius-4),cy+Math.sin(angle)*(radius-4),z+8],P),{tone:'hi',free:true});
};
const base=solidSvg(slabOf({x:-75,y:-40,w:150,d:80,r:4},0,6,P,8,1),{tone:'lo'});
const stand=cx=>solidSvg(cylinder(cx,0,8,6,7,P),{tone:'mid'})+solidSvg(cylinder(cx,0,2.5,13,16,P),{tone:'mid'});
const svg=figureSvg({width:620,height:390,label:'齿轮传动原理与拆解',body:base+stand(cx1)+stand(cx2)+'<g id="gears"></g>'});
const controls='<div class="lesson-controls"><button id="pause" type="button">暂停</button><button id="explode" type="button">拆解</button><label>转速 <input id="speed" aria-label="输入转速" type="range" min="0" max="4" step="0.25" value="1"></label><label>角度 <input id="angle" aria-label="输入轴角度" type="range" min="0" max="360" value="0"></label></div>';
document.getElementById('lesson').innerHTML=plateHtml({fig:'Jarvis · Anatomy',title:LESSON.parameters.title,hint:'调节角度与转速 · 拆解 / 组装',readout:'',caption:'外啮合齿轮：输出方向相反，角速度与齿数成反比。齿形为教学简化，不能用于加工。',body:svg+controls});
const intro=document.createElement('header');intro.className='lesson-intro';
const title=document.createElement('h1');title.textContent='齿轮为什么能减速？';
const explanation=document.createElement('p');explanation.textContent='小齿轮为输入（12 齿），大齿轮为输出（'+M.driven_teeth+' 齿）。输入转一圈，输出反向转 '+(1/M.ratio).toFixed(2)+' 圈。';
const formula=document.createElement('p');formula.textContent='输出角度 = −输入角度 × 12 / '+M.driven_teeth+'。拖动角度观察比例；点击拆解查看齿轮、轴与底座。';
intro.append(title,explanation,formula);document.getElementById('lesson').prepend(intro);
const $=id=>document.getElementById(id),G=$('gears'),still=matchMedia('(prefers-reduced-motion: reduce)');
let angle=0,speed=1,paused=still.matches,apart=false,frame=0,last=0;
function draw(){const driven=-angle*M.driver_teeth/M.driven_teeth;G.innerHTML=gear(cx1,0,12,12,angle*Math.PI/180,apart?70:20)+gear(cx2,0,12*M.ratio,M.driven_teeth,driven*Math.PI/180+Math.PI/M.driven_teeth,apart?55:20);document.querySelector('[data-readout]').textContent='输入 '+angle.toFixed(1)+'° · 输出 '+driven.toFixed(1)+'° · 传动比 '+M.ratio+':1';$('pause').textContent=paused?'播放':'暂停';$('explode').textContent=apart?'组装':'拆解';$('angle').value=String(angle);window.__jarvisLesson={model:M,angle,driven,apart,paused};}
function tick(now){frame=0;if(!paused&&!document.hidden){if(last)angle=(angle+Math.min(now-last,50)*speed*.025)%360;last=now;draw();frame=requestAnimationFrame(tick);}else last=0;}
function run(){if(!frame&&!paused&&!document.hidden)frame=requestAnimationFrame(tick);}
$('pause').onclick=()=>{paused=!paused;last=0;draw();run();};$('explode').onclick=()=>{apart=!apart;draw();};
$('speed').oninput=e=>{speed=Number(e.target.value);};$('angle').oninput=e=>{paused=true;angle=Number(e.target.value);draw();};
document.addEventListener('visibilitychange',()=>{last=0;run();});still.addEventListener('change',e=>{if(e.matches){paused=true;draw();}});draw();run();
