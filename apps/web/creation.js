/* Local draft preparation: precise folder requests never go to a text model. */
(()=>{'use strict';
function classify(text){
 if(typeof text!=='string'||text.length>2000||/(不要|不用|不需要|禁止|如果|假如|例如|示例|翻译|解释|如何|怎么|能否|是否|能不能|[“”「」])/u.test(text))return null;
 const prefix='(?:请帮我|帮我|请)?\\s*';
 const drive=text.match(new RegExp('^'+prefix+'在\\s*([a-z])\\s*(?:盘|:)[\\\\/]?\\s*(?:中|上)?\\s*(?:创建|新建|建立)\\s*(?:一个|个)?\\s*([a-z0-9_\\-\\u4e00-\\u9fff]{1,64})\\s*文件夹','iu'));
 const full=text.match(new RegExp('^'+prefix+'(?:创建|新建|建立)\\s*(?:一个\\s*)?([a-z]:[\\\\/][^\\r\\n，。；;]{1,180}?)\\s*文件夹','iu'))||text.match(new RegExp('^'+prefix+'(?:创建|新建|建立)\\s*文件夹\\s*([a-z]:[\\\\/][^\\r\\n，。；;]{1,180})(?=[，。；;]|$)','iu'));
 const game=/^(?:\/游戏\s|(?:请帮我|帮我|请)?\s*(?:制作|写|创建|开发|生成|做).{0,25}(?:坦克|tank).{0,12}(?:游戏|game))/iu.test(text)||Boolean(drive&&/(?:坦克|tank).{0,12}(?:游戏|game)/iu.test(text));
 if(!drive&&!full&&!game)return null;
 return {path:drive?drive[1].toUpperCase()+':\\'+drive[2]:full?full[1].trim():null,game};
}
function prepareGame(text){
 $('composer-mode').value='skill';const select=$('skill-explicit');if(![...select.options].some(o=>o.value==='jarvis.tank-game'))select.add(new Option('坦克小游戏制作','jarvis.tank-game'));
 select.value='jarvis.tank-game';$('message').value=text;$('composer-mode').dispatchEvent(new Event('change'));SkillWorkbench.controls();
}
async function handleSubmit(){
 if($('composer-mode').value!=='chat')return false;const text=$('message').value.trim(),d=classify(text);if(!d)return false;
 if(Attachments.hasDraft()||$('file-mode').checked){notify('创建项目和游戏只使用当前文字；请先处理附件或关闭回答文件输出。');return true;}
 if(d.path||d.game&&!Workspace.currentProject()){Workspace.prepareProject(d.path,text,d.game);notify('先核对项目位置；新目录点击“创建并打开”。原需求已保留。');return true;}
 if(d.game){prepareGame(text);notify(/3D|高画质|Unity|Unreal/iu.test(text)?'已准备2D坦克原型任务。当前不能直接交付完整高画质3D；核对范围后发送可开始制作。':'已准备坦克游戏任务；核对制作范围和模型后发送开始。');return true;}
 return false;
}
window.Creation={classify,prepareGame,handleSubmit};
})();
