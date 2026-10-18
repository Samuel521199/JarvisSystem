/* Visible settings overview only. No background polling when the page is hidden. */
(() => {
  'use strict';
  const host = document.getElementById('resource-usage');
  if (!host) return;
  const nonce = document.querySelector('meta[name="jarvis-nonce"]')?.content || '';
  let timer, request, epoch = 0;
  const active = () => !document.hidden && (!document.getElementById('home-view').hidden || !document.getElementById('modules-view').hidden);
  const finite = value => typeof value === 'number' && Number.isFinite(value);
  const pct = value => finite(value) ? `${Math.round(value)}%` : '—';
  const gib = value => finite(value) ? (value / 1073741824).toFixed(1) : '—';
  const seconds = value => finite(value) ? (value/1000).toFixed(2)+'s' : '—';
  const panels=[];
  for(const parent of [document.getElementById('home-view'),document.getElementById('modules-view')]){
    const panel=document.createElement('section');panel.className='panel runtime-panel';panel.setAttribute('aria-label','并行运行与延迟');
    panel.innerHTML='<div class="panel-heading"><div><h2>并行运行与延迟</h2><p data-runtime="stamp">正在读取…</p></div></div><div class="runtime-grid">'+
      '<article><h3>聊天</h3><strong data-runtime="chat-active">—</strong><p data-runtime="chat-latency">等待样本</p><small data-runtime="chat-outcomes"></small></article>'+
      '<article><h3>后台任务</h3><strong data-runtime="task-active">—</strong><p data-runtime="task-latency">等待样本</p><small data-runtime="queue"></small></article>'+
      '<article><h3>Jarvis 宿主</h3><strong data-runtime="host">—</strong><p data-runtime="host-detail">正在采样</p></article>'+
      '<article><h3>本地模型</h3><strong data-runtime="local_model">—</strong><p data-runtime="local_model-detail">未由本实例启动</p></article>'+
      '<article><h3>对话模型进程</h3><strong data-runtime="dialogue-process">—</strong><p data-runtime="dialogue-process-detail">按需启动 · 空闲不常驻</p></article>'+
      '<article><h3>后台模型进程</h3><strong data-runtime="background-process">—</strong><p data-runtime="background-process-detail">与聊天分开使用</p></article></div>'+
      '<p class="footnote" data-runtime="dialogue"></p><p class="footnote" data-runtime="events"></p><p class="footnote">耗时为宿主准入到返回，不含首字延迟；后台排队年龄包括人工暂停和停机时间。统计取本次启动最近 200 个已结束请求，重启清零。进程 CPU 按整机逻辑核归一，内存只含宿主和本实例管理的模型；工作集可能共享，不相加为总占用。</p>';
    if(parent.id==='modules-view')parent.prepend(panel);else parent.append(panel);panels.push(panel);
  }
  function runtime(data){
    const r=data.runtime;
    for(const panel of panels){
      const put=(key,text)=>panel.querySelector('[data-runtime="'+key+'"]').textContent=text;
      if(!r){for(const value of panel.querySelectorAll('[data-runtime]'))value.textContent='暂不可用';continue;}
      put('stamp','本次启动 '+new Date(r.started_at).toLocaleTimeString('zh-CN',{hour12:false})+' · 聊天与任务交叠 '+r.overlap_seconds.toFixed(2)+'s');
      for(const lane of ['chat','task']){
        const value=r.lanes[lane],d=value.duration;
        put(lane+'-active',value.active+' / '+(lane==='chat'?r.limits.chat_slots:r.limits.task_slots)+' 进行中');
        put(lane+'-latency',(d.samples?'P50 '+seconds(d.p50_ms)+' · P95 '+seconds(d.p95_ms)+' · '+d.samples+' 个样本':'尚无已结束样本')+(value.active?' · 当前最久 '+seconds(value.oldest_active_ms):''));
      }
      const outcomes=r.lanes.chat.outcomes;
      put('chat-outcomes','完成 '+(outcomes.SUCCEEDED||0)+' · 失败 '+(outcomes.FAILED||0)+' · 停止 '+(outcomes.CANCELLED||0)+' · 待核对 '+(outcomes.UNKNOWN||0));
      const turns=r.dialogue;put('dialogue',turns?'回复回执：'+turns.active+' 个处理中 · 缓存 '+turns.retained_results+' 条 · 预留 '+(turns.reserved_bytes/1048576).toFixed(1)+' / '+(turns.capacity_bytes/1048576).toFixed(0)+' MiB · 编号 '+turns.issued_ids+' / '+turns.capacity_ids+' · 内存统计仅本次启动 · 持久恢复'+({enabled:'已开启',unavailable:'不可用',disabled:'未启用'}[turns.recovery]||'未启用'):'回复回执统计暂不可用');
      const exits={succeeded:'完成',failed:'失败',unknown:'待核对',cancelled:'已取消',host_closed:'宿主关闭',timeout:'超时回收',context_timeout:'上下文准备超时',crashed:'异常退出',invalid_output:'输出异常',invalid_or_stopped:'协议异常或核心停止',unavailable:'启动不可用',start_failed:'启动失败',cancelled_before_input:'发送前取消'};
      for(const [key,dp] of [['dialogue-process',r.dialogue_processes],['background-process',r.background_processes]]){
        put(key,dp?.enabled?dp.active+' / '+dp.capacity+' 运行中':'未启用');
        put(key+'-detail',dp?.enabled?(dp.processes||[]).map(p=>'PID '+p.pid+' · '+({context:'准备上下文',model:'等待模型',starting:'启动中',waiting:'等待结果'}[p.phase]||'处理中')+' · '+(finite(p.working_set_bytes)?(p.working_set_bytes/1048576).toFixed(1)+' MiB':'内存暂不可用')+' · '+p.seconds+'s').join('；')+(dp.active?'；':'按需启动 · 空闲不常驻；')+'单进程提交上限 '+Math.round(dp.memory_limit_bytes/1048576)+' MiB'+(dp.last?'；最近：'+(exits[dp.last.reason]||'已退出')+' '+dp.last.seconds+'s':''):'当前实例未接入独立模型进程');
      }
      const q=r.queue,reasons={memory_pressure:'等待内存',resource_recovering:'等待内存稳定',resource_unavailable:'内存读数不可用'};
      put('queue',!q||q.unavailable?'队列暂不可用':(q.owned?'':'其他实例接管 · ')+(q.paused?'已暂停':'可派发')+' · 等待 '+q.waiting+' / '+q.capacity+' · '+(reasons[q.resources?.reason]||'资源准入按派发检查')+(q.unreviewed_unknown?' · 有结果待核对':'')+' · 排队 P95 '+seconds(r.lanes.task.queue_wait.p95_ms));
      const c=r.counters;put('events','本地计算 '+(c.calculation_completed||0)+' 次 · 请求槽满 '+(c.chat_busy||0)+' 次 · 页面等待超时 '+(c.http_wait_timeout||0)+' 次（后台可能仍在完成） · 后台完成 '+((r.lanes.task.outcomes.CONFIRMED||0)+(r.lanes.task.outcomes.SUCCEEDED||0))+' 次');
      for(const key of ['host','local_model']){
        const p=!data.stale&&data.sampled_at?(data.processes||[]).find(p=>p.name===key):null;
        put(key,p?.status==='available'?(p.working_set_bytes/1048576).toFixed(1)+' MiB':'—');
        put(key+'-detail',p?.status==='available'?'工作集 · 私有提交 '+(p.private_bytes/1048576).toFixed(1)+' MiB · CPU '+pct(p.cpu_percent):key==='host'?'暂不可用':'未采到本实例模型读数');
      }
    }
  }
  function metric(id, value, detail, progress) {
    const card = document.getElementById(`resource-${id}`);
    card.querySelector('strong').textContent = value;
    card.querySelector('small').textContent = detail;
    const bar = card.querySelector('progress');
    bar.hidden = !finite(progress);
    if (finite(progress)) bar.value = Math.max(0, Math.min(100, progress));
  }
  function render(data) {
    runtime(data);
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
