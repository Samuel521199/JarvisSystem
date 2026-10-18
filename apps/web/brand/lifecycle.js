/* Full-viewport visual lifecycle. Never stops the assistant or discards a conversation. */
(() => {
  'use strict';
  const base = new URL('.', document.currentScript.src);
  const motion = matchMedia('(prefers-reduced-motion: reduce)');
  let active = null, seenInstance = '';
  function play(kind, {leave = false, gesture = false, entry = false} = {}) {
    if (!['boot', 'exit'].includes(kind) || active || document.hidden) return false;
    const reduced = motion.matches || document.documentElement.hasAttribute('data-brand-paused');
    const previous = document.activeElement;
    const dialog = document.createElement('dialog');
    dialog.className = 'jarvis-cinema'; dialog.dataset.sequence = kind;
    if (reduced) dialog.dataset.reduced = '';
    dialog.setAttribute('aria-labelledby', 'cinema-title');
    dialog.innerHTML = `<div class="cinema-grid" aria-hidden="true"></div>
      <header class="cinema-header"><span>JARVIS <small>PERSONAL INTELLIGENCE</small></span><span class="cinema-edition">${kind === 'boot' ? '01 / ASSEMBLY' : '02 / DISASSEMBLY'}</span></header>
      <div class="cinema-center"><div class="cinema-coordinate" aria-hidden="true">J / CORE</div>
        <div class="cinema-stage" aria-hidden="true"><div class="cinema-ghost"></div><div class="cinema-parts"></div><div class="cinema-flare"></div></div>
        <div class="cinema-copy"><p class="cinema-kicker">${kind === 'boot' ? 'ASSEMBLY SEQUENCE' : 'UNTIL NEXT TIME'}</p>
        <h2 id="cinema-title">${kind === 'boot' ? '我在，准备开始。' : '暂别，仍与你同在。'}</h2>
        <p class="cinema-description">${leave ? '正在离开工作台 · 后台助手继续运行' : entry ? '进入你的智能工作台。' : '视觉演示 · 不改变助手运行状态'}</p></div>
        <div class="cinema-progress" aria-hidden="true"><span></span></div>
        <button type="button" class="cinema-return" hidden>返回工作台</button></div>
      <footer class="cinema-controls"><button type="button" data-brand-sound>音效：关</button><span>机械音效可选 · Esc 跳过</span><button type="button" data-cinema-skip>跳过动画</button></footer>`;
    const imageURL = new URL('core.png', base).href;
    dialog.style.setProperty('--cinema-art', `url("${imageURL}")`);
    const parts = dialog.querySelector('.cinema-parts');
    for (let i = 0; i < 9; i++) {
      const part = document.createElement('span'); part.className = 'cinema-part cinema-part-' + i;
      const image = new Image(512, 512); image.src = imageURL; image.alt = ''; image.draggable = false;
      part.append(image); parts.append(part);
    }
    const record = {dialog, timer: 0, previous, leave, ended: false}; active = record;
    function close() {
      clearTimeout(record.timer); window.JarvisSound?.stop();
      if (dialog.open) dialog.close(); dialog.remove();
      if (active === record) active = null;
      document.documentElement.removeAttribute('data-brand-cinema');
      if (previous?.isConnected) previous.focus({preventScroll: true});
    }
    function finish() {
      clearTimeout(record.timer); window.JarvisSound?.stop();
      if (!leave) { close(); return; }
      record.ended = true; dialog.dataset.ended = '';
      dialog.querySelector('#cinema-title').textContent = '工作台已离开';
      dialog.querySelector('.cinema-description').textContent = '后台助手继续运行；对话保留在当前标签页。';
      dialog.querySelector('[data-cinema-skip]').hidden = true;
      dialog.querySelector('.cinema-controls > span').textContent = '返回可继续当前会话';
      const back = dialog.querySelector('.cinema-return'); back.hidden = false; back.focus();
    }
    record.finish = finish; record.close = close;
    dialog.querySelector('[data-cinema-skip]').addEventListener('click', finish);
    dialog.querySelector('.cinema-return').addEventListener('click', () => { close(); play('boot', {gesture: true, entry: true}); });
    dialog.addEventListener('cancel', event => { event.preventDefault(); record.ended ? close() : finish(); });
    document.body.append(dialog);
    try { dialog.showModal(); } catch { close(); return false; }
    document.documentElement.setAttribute('data-brand-cinema', '');
    for (const logo of document.querySelectorAll('jarvis-logo')) logo.resetInteraction?.();
    window.JarvisSound?.update();
    dialog.querySelector('[data-cinema-skip]').focus();
    if (!reduced) window.JarvisSound?.play(kind, gesture);
    record.timer = setTimeout(finish, reduced ? 250 : kind === 'boot' ? 3900 : 3300);
    return true;
  }
  function enter(instance) {
    if (!instance || active || document.hidden || seenInstance === instance) return;
    try { if (sessionStorage.getItem('jarvis.brand.intro') === instance) { seenInstance = instance; return; } } catch {}
    if (!play('boot', {entry: true})) return;
    seenInstance = instance;
    try { sessionStorage.setItem('jarvis.brand.intro', instance); } catch {}
  }
  document.addEventListener('click', event => {
    const preview = event.target.closest('[data-brand-sequence]');
    if (preview) play(preview.dataset.brandSequence, {gesture: true});
    if (event.target.closest('[data-jarvis-leave]')) play('exit', {leave: true, gesture: true});
  });
  document.addEventListener('visibilitychange', () => { if (document.hidden && active && !active.ended) active.finish(); });
  motion.addEventListener('change', () => { if (motion.matches && active && !active.ended) active.finish(); });
  window.addEventListener('pagehide', () => active?.close());
  window.JarvisCinema = Object.freeze({play, enter});
})();
