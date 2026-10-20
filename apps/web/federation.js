(() => {
  'use strict';
  const root = document.getElementById('federation-root');
  if (!root) return;
  root.innerHTML = `
    <div class="shared-intro"><span class="shared-orbit" aria-hidden="true">◇</span><div><h2>两台设备，一份共同资料</h2><p>离线也能编辑。连接后对账；意见不同的版本，由你合并。</p></div></div>
    <p id="shared-message" role="status" aria-live="polite"></p>
    <div id="shared-recovery" class="panel" hidden><h2>共享资料需要检查</h2><p>可读且签名有效的资料可以恢复为只读；先保留原数据库和版本标记，全部旧连接保持撤销。旧备份中缺失的新内容无法凭空找回。</p><div class="shared-row"><button id="shared-recovery-close">关闭共享监听</button><button id="shared-recovery-preview">检查恢复范围</button></div><p id="shared-recovery-detail"></p><button id="shared-recover" hidden>保留原件并恢复只读资料</button></div>
    <div class="panel"><div class="panel-head"><h2>本机身份</h2><button id="shared-refresh" class="quiet">刷新</button></div>
    <p id="shared-device"></p><p id="shared-fingerprint" class="muted shared-wrap"></p>
    <button id="shared-initialize" class="primary">启用设备身份</button>
    <div id="shared-controls" hidden>
    <details><summary>接收另一台设备的连接</summary><p>在其中一台设备启动即可。填写本机的局域网 IPv4 地址；127.0.0.1 仅用于同机测试。重启后监听保持关闭。</p>
    <div class="shared-row"><label>本机地址<input id="shared-address" value="127.0.0.1" spellcheck="false"></label><label>端口<input id="shared-port" type="number" min="1" max="65535" value="18182"></label><button id="shared-listen">启动共享监听</button><button id="shared-close">关闭监听</button></div>
    <p id="shared-endpoint"></p><div class="shared-row"><label>空间名称<input id="shared-label" maxlength="60" placeholder="例如：两台电脑上的共同计划"></label><button id="shared-invite">创建配对码</button></div>
    <label id="shared-code-label" hidden>配对码 · 10 分钟内有效，只交给你要连接的设备<textarea id="shared-code" readonly rows="3"></textarea></label>
    </details>
    <details><summary>加入另一台设备的共享空间</summary><p>配对码固定连接地址和设备证书。只共享这个空间中新写入的资料卡。</p>
    <label>粘贴配对码<textarea id="shared-join-code" rows="3" spellcheck="false" autocomplete="off"></textarea></label><button id="shared-join">配对并加入</button></details>
    </div></div>
    <div class="panel"><div class="panel-head"><h2>共享空间</h2><select id="shared-spaces" aria-label="选择共享空间"></select></div>
    <p id="shared-space-info"></p><div class="shared-row"><button id="shared-sync" class="primary">立即双向同步</button><button id="shared-retry">重试原配对</button><button id="shared-revoke">撤销此空间的连接</button></div>
    <div class="shared-row"><button id="shared-export">导出资料副本</button><button id="shared-archive-preview">预览空间归档</button></div><p id="shared-archive-detail"></p><button id="shared-archive" hidden>归档并撤销连接</button>
    <div id="shared-notebook" hidden><div class="shared-row"><select id="shared-cards" aria-label="选择资料卡"></select><button id="shared-new">新建资料卡</button></div>
    <p id="shared-card-state"></p><div id="shared-versions"></div>
    <label>标题<input id="shared-title" maxlength="100"></label><label>正文<textarea id="shared-text" rows="7" placeholder="仅填写你明确要共享的内容；最多 4000 UTF-8 字节"></textarea></label>
    <div class="shared-row"><button id="shared-save" class="primary">保存到本机</button><button id="shared-delete">删除此卡</button></div></div></div>
    <div class="panel" id="shared-connection-root" hidden></div>
    <div class="panel" id="shared-scopes-root" hidden></div>
    <div class="panel" id="shared-access-root"></div>
    <div class="panel"><h2>已归档空间</h2><p>归档释放在线名额并保留来源、冲突和删除记录；恢复后仅可阅读，不重新连接。</p><div id="shared-archives"></div></div>
    <p class="muted">聊天、个人记忆、项目文件和任务各自留在本机。共享卡需另行设置本机模型用途后，在聊天输入区引用；不自动写入记忆。撤销连接不能擦除已发送的副本。每空间最多 32 张卡（含删除记录），8 个在线空间，32 个归档；导出文件为明文资料，需自行妥善保存。</p>`;
  const $ = id => document.getElementById('shared-' + id);
  const nonce = document.querySelector('meta[name="jarvis-nonce"]').content;
  const EMPTY = '4f53cda18c2baa0c0354bb5f9a3ecbe5ed12ab4d8e11ba873c2f11161202b945';
  let state = null, busy = false, dirty = false, selected = '', item = '', expected = EMPTY, archivePlan = null, recoveryPlan = null;
  function space() { return state?.spaces.find(s => s.id === selected); }
  function message(value) { $('message').textContent = value; }
  async function request(body) {
    const response = await fetch('/api/federation', {method: body ? 'POST' : 'GET', credentials: 'omit',
      cache: 'no-store', headers: {'X-Jarvis-Nonce': nonce, ...(body ? {'Content-Type': 'application/json'} : {})},
      body: body ? JSON.stringify(body) : undefined, signal: AbortSignal.timeout(25000)});
    const value = await response.json();
    if (!response.ok) throw new Error(value.user_message || value.message || '设备共享暂不可用，请刷新核对。');
    return value;
  }
  function options(element, rows, value) {
    element.replaceChildren(...rows.map(([id, label]) => { const o = document.createElement('option'); o.value = id; o.textContent = label; return o; }));
    element.value = value;
  }
  function editor(force = false) {
    const s = space(), card = s?.cards.find(c => c.id === item);
    for (const id of ['title', 'text']) { $(id).disabled = busy || !s; $(id).readOnly = s?.state !== 'active' || !!card?.deleted; }
    $('save').disabled = busy || s?.state !== 'active' || !!card?.deleted;
    $('delete').disabled = busy || !card || card.deleted || s?.state !== 'active';
    if (dirty && !force) return;
    expected = card?.expected || EMPTY;
    $('title').value = card?.versions[0]?.title || '';
    $('text').value = card?.versions[0]?.text || '';
    $('versions').replaceChildren();
    if (card?.conflict) for (const v of card.versions) {
      const panel = document.createElement('details'), title = document.createElement('summary'), body = document.createElement('pre');
      title.textContent = `设备 ${v.author.slice(0, 8)} · ${v.title}`;
      body.textContent = v.text; panel.append(title, body); $('versions').append(panel);
    }
    $('card-state').textContent = card?.deleted ? '此卡已删除；原编号不会恢复。' : card?.conflict ? '存在两份并发版本。请阅读各版本，在下方编辑合并内容后保存。' : s?.state === 'revoked' ? '本机只读资料，可查看和复制；连接仍已撤销。' : item ? '本地保存后，在加入端点击同步，另一台设备才会收到。' : '新卡尚未保存。';
  }
  function render() {
    root.dataset.operationBusy = String(busy);
    root.querySelectorAll('button, input, textarea, select').forEach(e => { e.disabled = busy; });
    $('device').textContent = state?.node ? `设备 ${state.node.slice(0, 12)} · ${state.offline ? '软件离线' : '允许连接'}` : state?.recovery_required ? '共享状态异常，原资料保留' : '尚未读取设备状态';
    $('fingerprint').textContent = state?.fingerprint ? `证书指纹 ${state.fingerprint}` : '尚未启用；不启动监听，不创建共享数据。';
    $('initialize').hidden = !!state?.initialized || !!state?.recovery_required;
    $('recovery').hidden = !state?.recovery_required;
    $('recover').hidden = !recoveryPlan || !state?.recovery_required;
    $('controls').hidden = !state?.initialized;
    $('endpoint').textContent = state?.endpoint ? `正在监听 ${state.endpoint}` : '共享监听已关闭';
    $('listen').disabled = busy || !state?.initialized || !!state?.endpoint || state?.offline;
    $('close').disabled = busy || !state?.endpoint;
    $('invite').disabled = busy || !state?.endpoint || state?.offline;
    $('join').disabled = busy || !state?.initialized || state?.offline;
    if (!state?.spaces.some(s => s.id === selected)) selected = state?.spaces[0]?.id || '';
    options($('spaces'), (state?.spaces || []).map(s => [s.id, s.label]), selected);
    const s = space();
    const names = {active: '已配对', inviting: '等待另一设备加入', pending: '配对结果待确认', revoked: '连接已撤销'};
    $('space-info').textContent = s ? `${names[s.state]} · ${s.role === 'archive' ? '本机只读资料' : s.role === 'host' ? '共享端：由加入端发起双向同步' : '加入端：点击同步收发两端变更'} · ${s.cards.length}/32 张卡${s.last_sync ? ' · 最近同步 ' + new Date(s.last_sync * 1000).toLocaleString() : ''}` : '先创建或加入一个共享空间。';
    $('sync').disabled = busy || s?.state !== 'active' || s?.role !== 'client' || state?.offline || s?.scoped_enabled;
    $('retry').hidden = s?.state !== 'pending'; $('retry').disabled = busy || state?.offline;
    $('revoke').disabled = busy || !s || s.state === 'revoked';
    $('export').disabled = busy || !s;
    $('archive-preview').disabled = busy || !s || dirty;
    $('archive').hidden = !archivePlan || archivePlan.space !== selected;
    $('archive').disabled = busy || dirty;
    $('archives').replaceChildren();
    for (const row of state?.archives || []) {
      const section = document.createElement('div'), label = document.createElement('span'),
        downloadButton = document.createElement('button'), restore = document.createElement('button');
      section.className = 'shared-row'; label.textContent = `${row.label} · ${row.cards} 张卡 · ${(row.bytes/1024).toFixed(1)} KiB`;
      downloadButton.textContent = '导出'; downloadButton.disabled = busy;
      downloadButton.onclick = () => run({action:'export',space:row.id,archived:true}, '已准备明文资料下载。', download);
      restore.textContent = row.restored ? '已恢复只读' : '恢复为只读'; restore.disabled = busy || row.restored;
      restore.onclick = () => {if(discard())run({action:'restore_archive',space:row.id}, '已恢复只读资料，连接仍已撤销。', value => {selected=row.id;item=value.spaces.find(s=>s.id===row.id)?.cards[0]?.id || '';});};
      section.append(label, downloadButton, restore); $('archives').append(section);
    }
    $('notebook').hidden = !s || !['active', 'revoked'].includes(s.state);
    options($('cards'), [['', s?.state === 'revoked' ? '选择资料卡' : '新建资料卡'], ...(s?.cards || []).map(c => [c.id, c.deleted ? '已删除 · ' + c.id.slice(0, 8) : (c.conflict ? '待合并 · ' : '') + c.versions[0].title])], item);
    $('new').disabled = busy || s?.state !== 'active';
    editor();
    window.dispatchEvent(new CustomEvent('jarvis:shared-space',{detail:s||null}));
  }
  async function run(body, success, onResult) {
    if (body && ['invite','join','archive','restore_archive','recover','revoke'].includes(body.action) &&
        window.SharedScopes && !SharedScopes.canSwitch()) return;
    if (body && ['invite','join','archive','restore_archive','recover','revoke'].includes(body.action) &&
        window.SharedConnection && !SharedConnection.canSwitch()) return;
    if (body && ['invite','join','archive','restore_archive','recover','revoke'].includes(body.action) &&
        window.SharedAccess && !SharedAccess.canSwitch()) return;
    if (busy) return;
    busy = true; render(); message(body ? '正在处理…' : '正在读取…');
    try {
      const value = await request(body);
      if (onResult) onResult(value);
      state = Array.isArray(value.spaces) ? value : await request();
      message(success || '');
    } catch (error) {
      message(error.name === 'TimeoutError' ? '结果未确认，请刷新；配对重试使用原编号，草稿仍保留。' : error.message);
      try { state = await request(); } catch {}
    } finally { busy = false; render(); }
  }
  function discard() { if (dirty && !confirm('草稿尚未保存，是否放弃草稿并切换？')) return false; dirty = false; return true; }
  function download(value) {
    const url = URL.createObjectURL(new Blob([value.content], {type:'application/json;charset=utf-8'}));
    const link = document.createElement('a'); link.href=url;link.download=value.filename;
    document.body.append(link);link.click();link.remove();setTimeout(()=>URL.revokeObjectURL(url),2000);
  }
  $('refresh').onclick = () => run();
  $('initialize').onclick = () => run({action: 'initialize'}, '设备身份已启用；监听仍然关闭。');
  $('listen').onclick = () => run({action: 'listen', address: $('address').value.trim(), port: Number($('port').value)}, '共享监听已启动。');
  $('close').onclick = () => run({action: 'close'}, '共享监听已关闭；本地编辑继续可用。');
  $('invite').onclick = () => run({action: 'invite', label: $('label').value.trim()}, '配对码只显示在此页面，请交给目标设备。', value => {
    $('code-label').hidden = false; $('code').value = value.invitation; selected = value.space;
  });
  $('join').onclick = () => run({action: 'join', invitation: $('join-code').value.trim()}, '已配对。请新建资料卡或点击同步。', () => { $('join-code').value = ''; selected = ''; });
  $('retry').onclick = () => run({action: 'retry', space: selected}, '原配对已确认。');
  $('sync').onclick = () => run({action: 'sync', space: selected}, '两端资料已对账。若有冲突，请查看并合并；未保存草稿仍保留。');
  $('revoke').onclick = () => { if (confirm('撤销此空间连接？本机资料保留，另一设备已有的副本不会被远程擦除。')) run({action: 'revoke', space: selected}, '此空间已拒绝后续同步。'); };
  $('export').onclick = () => run({action:'export',space:selected,archived:false}, '已准备明文资料下载；文件不含设备私钥或连接权限。', download);
  $('archive-preview').onclick = () => run({action:'archive_preview',space:selected}, '已生成归档预览，尚未改变空间。', value => {archivePlan=value;$('archive-detail').textContent=`${value.label} · ${value.cards} 张卡 · ${(value.bytes/1024).toFixed(1)} KiB。${value.effect}`;});
  $('archive').onclick = () => {if(!archivePlan)return;run({action:'archive',space:archivePlan.space,expected:archivePlan.expected}, '空间已归档，连接已撤销，在线名额已释放。',()=>{archivePlan=null;$('archive-detail').textContent='';selected='';item='';dirty=false;});};
  $('recovery-close').onclick = () => run({action:'close'}, '共享监听已关闭。');
  $('recovery-preview').onclick = () => run({action:'recovery_preview'}, '检查完成；尚未改变原件。', value => {recoveryPlan=value;$('recovery-detail').textContent=`${value.spaces} 个空间、${value.cards} 张卡、${value.archives} 个归档。${value.effect}`;});
  $('recover').onclick = () => {if(!recoveryPlan||!discard())return;run({action:'recover',expected:recoveryPlan.expected}, '已保留原件并恢复只读资料；需要使用新空间重新配对。',()=>{recoveryPlan=null;item='';});};
  $('spaces').onchange = () => { if (window.SharedScopes && !SharedScopes.canSwitch()) { $('spaces').value = selected; return; } if (window.SharedConnection && !SharedConnection.canSwitch()) { $('spaces').value = selected; return; } if (window.SharedAccess && !SharedAccess.canSwitch()) { $('spaces').value = selected; return; } if (!discard()) { $('spaces').value = selected; return; } selected = $('spaces').value; item = ''; render(); };
  $('cards').onchange = () => { if (!discard()) { $('cards').value = item; return; } item = $('cards').value; render(); };
  $('new').onclick = () => { if (discard()) {item = ''; render(); $('title').focus();} };
  for (const id of ['title', 'text']) $(id).oninput = () => { dirty = true; };
  function save(deleted) {
    if (deleted && !confirm('删除此卡并在下次同步时传播删除记录？旧编号无法恢复。')) return;
    const chosen = item || crypto.randomUUID().replaceAll('-', '');
    run({action: 'edit', space: selected, item: chosen, expected, title: $('title').value, text: $('text').value, deleted},
      deleted ? '已在本机删除；下一次同步会发送删除记录。' : '已保存到本机。', () => { dirty = false; item = chosen; });
  }
  $('save').onclick = () => save(false); $('delete').onclick = () => save(true);
  document.addEventListener('jarvis:settings-view', e => { if (e.detail === 'federation') run(); });
  window.addEventListener('beforeunload', e => { if (dirty) {e.preventDefault(); e.returnValue = '';} });
  render();
  if (location.hash === '#federation') run();
})();
