/* Visible settings overview only. No background polling when the page is hidden. */
(() => {
  'use strict';
  const host = document.getElementById('resource-usage');
  if (!host) return;
  const nonce = document.querySelector('meta[name="jarvis-nonce"]')?.content || '';
  let timer, request, epoch = 0;
  const active = () => !document.hidden && !document.getElementById('home-view').hidden;
  const finite = value => typeof value === 'number' && Number.isFinite(value);
  const pct = value => finite(value) ? `${Math.round(value)}%` : '—';
  const gib = value => finite(value) ? (value / 1073741824).toFixed(1) : '—';
  function metric(id, value, detail, progress) {
    const card = document.getElementById(`resource-${id}`);
    card.querySelector('strong').textContent = value;
    card.querySelector('small').textContent = detail;
    const bar = card.querySelector('progress');
    bar.hidden = !finite(progress);
    if (finite(progress)) bar.value = Math.max(0, Math.min(100, progress));
  }
  function render(data) {
    const stale = data.stale || !data.sampled_at;
    const missing = stale ? (data.refreshing ? '正在采样' : '暂不可用') : '暂不可用';
    const cpu = stale ? null : data.cpu_percent, gpu = stale ? null : data.gpu_percent;
    metric('cpu', pct(cpu), finite(cpu) ? '全部逻辑处理器' : missing, cpu);
    const memory = stale ? null : data.memory;
    metric('memory', pct(memory?.percent), memory ? `${gib(memory.used_bytes)} / ${gib(memory.total_bytes)} GiB` : missing, memory?.percent);
    const adapters = stale ? [] : (data.adapters || []);
    const names = adapters.map(a => a.name).join(' · ');
    metric('gpu', pct(gpu), finite(gpu) ? (names || '最忙引擎') : missing, gpu);
    document.getElementById('resource-gpu').title = `${names || 'GPU'} · 全部 GPU 中最忙引擎的占用`;
    const sum = key => adapters.length && adapters.every(a => finite(a[key])) ? adapters.reduce((n,a) => n + a[key], 0) : null;
    const used = sum('dedicated_used_bytes'), total = sum('dedicated_total_bytes');
    const shared = sum('shared_used_bytes'), sharedTotal = sum('shared_total_bytes');
    const ratio = finite(used) && total > 0 ? used / total * 100 : null;
    metric('vram', finite(used) ? `${gib(used)} / ${gib(total)}` : '—', finite(used) ? `GiB 专用 · 共享 ${gib(shared)} GiB` : missing, ratio);
    document.getElementById('resource-vram').title = `专用显存 ${gib(used)} / ${gib(total)} GiB；共享内存 ${gib(shared)} GiB，驱动报告上限 ${gib(sharedTotal)} GiB。共享内存来自系统内存，请勿与内存占用相加。`;
    const stamp = document.getElementById('resource-updated');
    stamp.textContent = stale ? (data.refreshing ? '采样中…' : '暂未获取') : `更新于 ${new Date(data.sampled_at).toLocaleTimeString('zh-CN', {hour12:false})}`;
  }
  async function load() {
    if (!active() || request) return;
    const current = new AbortController(), generation = epoch;
    request = current;
    const timeout = setTimeout(() => current.abort(), 4000);
    let delay = 3000;
    try {
      const response = await fetch('/api/resources', {headers:{'X-Jarvis-Nonce':nonce},signal:current.signal,cache:'no-store'});
      if (!response.ok) throw new Error('Resource snapshot unavailable');
      const data = await response.json();
      if (generation !== epoch || !active()) return;
      render(data);
      if (data.refreshing) delay = 750;
    } catch {
      if (generation === epoch && active()) {
        render({stale:true});
        document.getElementById('resource-updated').textContent = '暂不可用 · 将自动重试';
      }
    } finally {
      clearTimeout(timeout);
      if (request === current) request = null;
      if (generation === epoch && active()) timer = setTimeout(load, delay);
    }
  }
  function resume() {
    epoch++;
    clearTimeout(timer);
    request?.abort();
    request = null;
    if (active()) load();
  }
  document.addEventListener('jarvis:settings-view', resume);
  document.addEventListener('visibilitychange', resume);
  window.addEventListener('pagehide', () => { epoch++; clearTimeout(timer); request?.abort(); });
  window.addEventListener('pageshow', resume);
})();
