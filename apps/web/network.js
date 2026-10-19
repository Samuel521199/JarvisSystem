(() => {
  'use strict';
  const $ = id => document.getElementById(id);
  const nonce = document.querySelector('meta[name="jarvis-nonce"]').content;
  let state = null, busy = false, serial = 0;
  async function request(body) {
    const response = await fetch('/api/network', {method: body ? 'POST' : 'GET', credentials: 'omit', cache: 'no-store',
      headers: {'X-Jarvis-Nonce': nonce, ...(body ? {'Content-Type': 'application/json'} : {})},
      body: body ? JSON.stringify(body) : undefined, signal: AbortSignal.timeout(6000)});
    const value = await response.json();
    if (!response.ok) throw new Error(value.user_message || value.message || '网络设置未确认，请刷新核对。');
    return value;
  }
  function render() {
    const toggle = $('network-offline');
    toggle.checked = !!state?.offline;
    toggle.disabled = busy || !state?.valid;
    $('network-refresh').disabled = busy;
    $('network-state').textContent = !state ? '正在读取' : !state.valid ? '配置异常 · 禁止外联' : state.offline ? '仅此软件离线' : '允许联网';
    $('network-detail').textContent = state?.offline ? '本地模型、记忆和文件仍可使用。云模型、远程 MCP、余额查询与受控浏览器已暂停。' : 'Jarvis 可按已配置的路由和权限联网；其他软件始终保持原有网络状态。';
    $('network-revision').textContent = state?.valid ? `修订 ${state.revision} · 重启后保留` : '网络配置暂不可读';
  }
  async function refresh() {
    if (busy) return;
    const id = ++serial;
    try { const value = await request(); if (id === serial) {state = value; render(); $('network-message').textContent = '';} }
    catch (error) { if (id === serial) {$('network-message').textContent = error.message; $('network-offline').disabled = true;} }
  }
  $('network-offline').addEventListener('change', async () => {
    if (busy || !state) return;
    const desired = $('network-offline').checked, revision = state.revision;
    ++serial; busy = true; render(); $('network-message').textContent = '正在保存网络限制…';
    try {state = await request({offline: desired, revision}); $('network-message').textContent = desired ? '已启用。自动路由使用本地模型；不会自动下载或启动模型。' : '已恢复联网；中断或失败的工作不会自动重发。';}
    catch (error) { $('network-message').textContent = error.message; try {state = await request();} catch {state = null;} }
    finally {busy = false; render();}
  });
  $('network-refresh').addEventListener('click', refresh);
  document.addEventListener('jarvis:settings-view', event => {if (event.detail === 'network') refresh();});
  if (location.hash === '#network') refresh();
  render();
})();
