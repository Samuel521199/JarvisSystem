(() => {
  'use strict';
  const open = document.getElementById('shared-reference-open');
  if (!open) return;
  const dialog = document.createElement('dialog');
  dialog.className = 'shared-reference-dialog';
  dialog.setAttribute('aria-labelledby', 'shared-reference-title');
  dialog.innerHTML = `<div class="shared-reference-heading"><h2 id="shared-reference-title">引用共享资料副本</h2><button type="button" data-close aria-label="关闭共享资料选择" title="关闭">×</button></div>
    <p>只选择本次要使用的资料。副本会作为附件发给当前选定模型，回答可保存到本会话；不会自动写入个人记忆。副本不随原卡的修改或撤销更新。</p>
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
        for (const card of space.cards.filter(c => !c.deleted && !c.conflict)) {
          ++count;
          const section = document.createElement('section'), title = document.createElement('h3'),
            preview = document.createElement('p'), button = document.createElement('button');
          title.textContent = space.label + ' · ' + card.versions[0].title;
          preview.textContent = card.versions[0].text.slice(0, 240);
          button.type = 'button'; button.textContent = '加入当前对话附件';
          button.onclick = async () => {
            if (window.Workspace?.isBusy?.()) {status.textContent = '请等待当前发送结束。'; return;}
            button.disabled = true;
            try {
              const value = await request({action: 'reference', space: space.id, item: card.id, expected: card.expected});
              if (ticket !== serial || conversation !== scope() || !dialog.open || window.Workspace?.isBusy?.()) return;
              window.Attachments.addText(value.attachment);
              status.textContent = '已添加资料副本；可在发送前移除，点击发送时才会交给模型。';
              button.textContent = '已加入附件';
            } catch (error) {
              if (ticket === serial) {status.textContent = error.message; button.disabled = false;}
            }
          };
          section.append(title, preview, button); list.append(section);
        }
      }
      status.textContent = count ? '选择一张或多张资料卡；附件沿用本轮容量限制。' : '没有可引用的资料卡。已删除、未配对、已撤销或存在冲突的卡不在此列出。';
    } catch (error) { if (ticket === serial) status.textContent = error.message; }
  };
})();
