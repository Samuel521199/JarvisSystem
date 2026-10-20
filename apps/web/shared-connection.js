(() => {
  'use strict';
  const root = document.getElementById('shared-connection-root');
  if (!root) return;
  root.innerHTML = `<div class="panel-head"><h2>连接诊断与恢复</h2><button data-check>检查原设备连接</button></div>
    <p data-current class="shared-wrap"></p><p data-status role="status" aria-live="polite"></p>
    <details data-recovery><summary>另一台设备更换了地址</summary>
      <p>在对端重新打开共享监听，再填写它显示的新地址。先核验原设备证书和空间；检查不会同步资料，也不会信任新的身份。</p>
      <label>对端新的共享地址<input data-endpoint placeholder="https://192.168.1.20:18182" spellcheck="false" autocomplete="off"></label>
      <button data-preview>核验新地址</button><div data-plan hidden><p data-proof class="shared-wrap"></p>
      <p>确认只保存连接地址，资料及模型用途保持原样。随后可点击“立即双向同步”。预览两分钟内有效。</p>
      <button data-apply class="primary">确认更新连接地址</button></div>
    </details>`;
  const q = selector => root.querySelector(selector);
  const nonce = document.querySelector('meta[name="jarvis-nonce"]').content;
  let current = null, key = '', busy = false, dirty = false, plan = null, confirmation = null, epoch = 0;
  const status = message => q('[data-status]').textContent = message;
  function controls() {
    const locked = busy || document.getElementById('federation-root').dataset.operationBusy === 'true';
    root.querySelectorAll('button,input').forEach(e => e.disabled = locked);
    q('[data-apply]').disabled = locked || !plan;
  }
  function show(space) {
    const next = space ? space.id+':'+space.state+':'+space.endpoint : '';
    if (key !== next) {
      ++epoch; key = next; current = space; plan = null; dirty = false;
      root.hidden = !space || space.role !== 'client' || space.state !== 'active';
      q('[data-current]').textContent = space ? '当前记录地址：'+space.endpoint : '';
      q('[data-endpoint]').value = ''; q('[data-plan]').hidden = true;
      status(confirmation?.space === space?.id && confirmation?.endpoint === space?.endpoint
        ? confirmation.message : '按需检查，不在后台轮询；若对端休眠或关闭监听，本机资料仍可使用。');
    }
    controls();
  }
  async function request(body) {
    const response = await fetch('/api/federation', {method:'POST', cache:'no-store', credentials:'omit',
      headers:{'X-Jarvis-Nonce':nonce,'Content-Type':'application/json'},body:JSON.stringify(body),
      signal:AbortSignal.timeout(25000)});
    const value = await response.json();
    if (!response.ok) throw new Error(value.user_message || value.message || '操作结果未确认，请刷新检查当前地址。');
    return value;
  }
  async function run(action) {
    if (busy || !current || current.state !== 'active') return;
    const id = ++epoch, sid = current.id;
    const payload = {action,space:sid};
    if (action === 'connection_preview') {
      payload.endpoint = q('[data-endpoint]').value.trim();
      plan = null; q('[data-plan]').hidden = true;
    }
    if (action === 'connection_apply') { if (!plan) return; payload.token = plan.token; }
    busy = true; confirmation = null; controls(); status('正在核验原配对设备…');
    try {
      const value = await request(payload);
      if (id !== epoch || sid !== current?.id) return;
      if (action === 'connection_preview') {
        plan = value; dirty = false;
        q('[data-proof]').textContent = `原设备身份已核验 · ${value.latency_ms} ms。地址：${value.old_endpoint} → ${value.endpoint}。指纹：${value.fingerprint}`;
        q('[data-plan]').hidden = false; status('检查完成，地址尚未修改。');
      } else if (action === 'connection_apply') {
        plan = null; dirty = false; q('[data-plan]').hidden = true;
        confirmation = value;
        status(value.message); document.getElementById('shared-refresh').click();
      } else {
        status(value.message+(value.reachable ? ` 往返 ${value.latency_ms} ms。` : ''));
      }
    } catch (error) {
      if (id === epoch) {plan=null;q('[data-plan]').hidden=true;status(error.message);}
    } finally {busy=false;controls();}
  }
  q('[data-endpoint]').oninput = () => {dirty=true;plan=null;q('[data-plan]').hidden=true;controls();};
  q('[data-check]').onclick = () => run('connection_check');
  q('[data-preview]').onclick = () => run('connection_preview');
  q('[data-apply]').onclick = () => run('connection_apply');
  window.SharedConnection = {canSwitch:()=> {
    if (busy) return false;
    if ((dirty || plan) && !confirm('连接地址尚未确认保存，是否放弃本次输入并切换？')) return false;
    dirty=false;plan=null;q('[data-plan]').hidden=true;return true;
  }};
  window.addEventListener('jarvis:shared-space', event => show(event.detail));
  window.addEventListener('beforeunload', event => {if(dirty||plan){event.preventDefault();event.returnValue='';}});
  root.hidden = true;
})();
