/* Per-session user requirements. Page memory only; no storage or model calls. */
(() => {
  "use strict";
  const panel=document.createElement("details");panel.id="session-context";panel.className="session-context";
  const summary=document.createElement("summary"),title=document.createElement("span"),badge=document.createElement("span");
  title.textContent="本会话要求";badge.id="context-badge";summary.append(title,badge);
  const body=document.createElement("div");body.className="context-body";
  const label=document.createElement("label");label.htmlFor="context-note";label.textContent="每次发送都保留的目标、限制或回答偏好";
  const note=document.createElement("textarea");note.id="context-note";note.rows=3;note.maxLength=8192;
  note.placeholder="例如：使用中文；代码适配 Windows；优先复用现有模块。";note.setAttribute("aria-describedby","context-help context-count");
  const help=document.createElement("p");help.id="context-help";help.textContent="随当前会话发送给所选供应商。各会话独立，随已发送的聊天文字归档；临时会话仅在本页。修改后下次发送生效。";
  const footer=document.createElement("div");footer.className="context-footer";
  const count=document.createElement("span");count.id="context-count";
  const clear=document.createElement("button");clear.id="context-clear";clear.type="button";clear.textContent="清空要求";
  footer.append(count,clear);
  const report=document.createElement("p");report.id="context-report";report.setAttribute("role","status");report.hidden=true;
  body.append(label,note,help,footer,report);panel.append(summary,body);
  document.getElementById("composer").before(panel);
  const size=()=>new TextEncoder().encode(note.value).length;
  const wire=()=>note.value.trim();
  function update(){
    const bytes=size();count.textContent=bytes.toLocaleString()+" / 8,192 字节";
    count.classList.toggle("context-invalid",bytes>8192);note.setAttribute("aria-invalid",String(bytes>8192));
    badge.textContent=bytes>8192?"超过上限":wire()?"已固定":"未设置";
    if(bytes<=8192&&document.getElementById("toast").textContent==="会话要求超过 8 KiB，请缩短后发送。")notify("");
    controls();
  }
  function controls(){const locked=busy||Boolean(window.Workspace?.isBusy());note.disabled=locked;clear.disabled=locked||!note.value;}
  function restore(saved){note.value=saved?.note||"";panel.open=Boolean(saved?.open);report.textContent=saved?.report||"";report.hidden=!report.textContent;update();}
  note.addEventListener("input",()=>{report.textContent="要求已修改，下次发送使用此版本。";report.hidden=false;update();});
  clear.addEventListener("click",()=>{note.value="";report.textContent="下次不再附带固定要求；历史中已引用的内容仍保留。";report.hidden=false;update();note.focus();});
  window.SessionContext={wire,controls,
    issue:()=>size()>8192?"会话要求超过 8 KiB，请缩短后发送。":null,
    snapshot:()=>({note:note.value,open:panel.open,report:report.textContent}),restore,
    clear:()=>restore(null),
    report(info,clientDropped=0){
      if(info?.calculation){report.textContent='本次由本地计算器完成，未调用模型；只使用当前完整算式。';report.hidden=false;return;}
      if(!info?.context){report.textContent="本次未取得上下文装配报告。";report.hidden=false;return;}
      report.textContent="本次模型收到 "+info.kept_messages+" / "+info.input_messages+" 条随请求提交的历史；"+
        (info.context.note_applied?"固定要求已携带。":"未附带固定要求。")+
        (info.truncated?"较早历史已按完整轮次省略，未生成摘要。":"")+
        (clientDropped>0?"发送前页面另省略了 "+clientDropped+" 条历史。":"")+
        (info.memory_view?"知识视图："+info.memory_view.knowledge_project_ids.length+" 个项目，"+(info.memory?.references.length||0)+" 条记忆引用、"+(info.knowledge?.citations.length||0)+" 段资料；"+info.memory_view.bytes+" 字节。"+ (info.memory_view.coverage.some(p=>p.status!=='matched')?"部分项目无匹配摘录或存在读取缺口。":""):"");
      report.hidden=false;
    }
  };
  update();
})();
