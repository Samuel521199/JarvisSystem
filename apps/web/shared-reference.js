(() => {
  'use strict';
  const open = document.getElementById('shared-reference-open');
  if (!open) return;
  const dialog = document.createElement('dialog');
  dialog.className = 'shared-reference-dialog';
  dialog.setAttribute('aria-labelledby', 'shared-reference-title');
  dialog.innerHTML = `<div class="shared-reference-heading"><h2 id="shared-reference-title">引用共享资料</h2><button type="button" data-close aria-label="关闭共享资料选择" title="关闭">×</button></div>
    <p>只引用本次会话获准的资料。发送及切换备选模型前会核对用途、接入方和版本；变化后停止使用原引用及相关历史。已经外发的内容无法撤回，回答仍可留在本地会话中。</p>
    <p data-status role="status" aria-live="polite"></p><div data-list></div>
    <a href="/settings#federation">管理设备与共享</a>`;
  document.body.append(dialog);
  const status = dialog.querySelector('[data-status]'), list = dialog.querySelector('[data-list]');
  const nonce = document.querySelector('meta[name="jarvis-page-session"]').content;
  let serial = 0;
  const scope = () => window.Workspace?.currentConversation?.()?.id || '';
  async function request(body) {
    const response = await fetch('/api/federation', {method: body ? 'POST' : 'GET', credentials: 'omit',
      cache: 'no-store', headers: {'X-Jarvis-Nonce': nonce, ...(body ? {'Content-Type': 'application/json'} : {})},
      body: body ? JSON.stringify(body) : undefined, signal: AbortSignal.timeout(8000)});
    const value = await response.json();
    if (!response.ok) throw new Error(value.user_message || value.message || '共享资料暂不可用。');
    return value;
  }
  function close() { ++serial; dialog.close(); list.replaceChildren(); }
  dialog.querySelector('[data-close]').onclick = close;
  dialog.addEventListener('cancel', () => { ++serial; });
  window.addEventListener('jarvis:conversation-context', close);
  window.addEventListener('jarvis:message-start', close);
  open.onclick = async () => {
    const ticket = ++serial, conversation = scope();
    list.replaceChildren(); status.textContent = '正在读取本机共享资料…'; dialog.showModal();
    try {
      const state = await request();
      if (ticket !== serial || conversation !== scope()) return;
      if (state.recovery_required) throw new Error('共享资料需要恢复，请到设置中检查。');
      let count = 0;
      for (const space of state.spaces.filter(s => s.state === 'active')) {
        const project=window.Workspace?.memoryContext?.()?.project_id||null;
        for (const card of [...space.cards,...(space.received_cards||[]).filter(c=>c.project_id===project)].filter(c => !c.deleted && !c.conflict)) {
          ++count;
          const section = document.createElement('section'), title = document.createElement('h3'),
            preview = document.createElement('p'), button = document.createElement('button');
          title.textContent = space.label + ' · ' + card.versions[0].title;
          preview.textContent = card.versions[0].text.slice(0, 240);
          button.type = 'button'; button.textContent = '加入当前对话引用';
          button.onclick = async () => {
            if (window.Workspace?.isBusy?.()) {status.textContent = '请等待当前发送结束。'; return;}
            button.disabled = true;
            try {
              const value = await request({action: 'reference_issue', space: space.id, item: card.id, expected: card.expected, scope: {conversation_id:conversation,project_id:window.Workspace?.memoryContext?.()?.project_id || null}});
              if (ticket !== serial || conversation !== scope() || !dialog.open || window.Workspace?.isBusy?.()) return;
              window.Attachments.addShared(value);
              status.textContent = '已加入受控引用；可移除。发送时重新检查，不提前复制正文。';
              button.textContent = '已加入引用';
            } catch (error) {
              if (ticket === serial) {status.textContent = error.message; button.disabled = false;}
            }
          };
          section.append(title, preview, button); list.append(section);
        }
      }
      status.textContent = count ? '选择已授权的资料卡；每轮附件与引用合计最多 8 项。' : '没有可引用的资料卡。已删除、未配对、已撤销或存在冲突的卡不在此列出。';
    } catch (error) { if (ticket === serial) status.textContent = error.message; }
  };
})();
