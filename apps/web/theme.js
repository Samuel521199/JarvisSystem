/* Apply before first paint; preferences stay in this browser, never in model requests. */
(() => {
  'use strict';
  const key = 'jarvis.appearance.v1';
  const modes = {system:'跟随系统',light:'浅色',dark:'深色',warm:'暖纸'};
  const media = window.matchMedia('(prefers-color-scheme: dark)');
  let mode = 'system', canSave = true;
  const valid = value => Object.hasOwn(modes, value) ? value : 'system';
  try { mode = valid(localStorage.getItem(key)); } catch { canSave = false; }

  function apply(announce = false) {
    const actual = mode === 'system' ? (media.matches ? 'dark' : 'light') : mode;
    document.documentElement.dataset.theme = actual;
    document.querySelectorAll('.appearance-picker').forEach(select => { select.value = mode; });
    document.querySelectorAll('.appearance-storage-note').forEach(note => { note.hidden = canSave; });
    if (announce) document.querySelectorAll('.appearance-announcement').forEach(note => {
      note.textContent = `已切换为${modes[mode]}配色${canSave ? '，已保存。' : '，仅本页生效。'}`;
    });
  }
  apply();
  media.addEventListener('change', () => { if (mode === 'system') apply(); });
  window.addEventListener('storage', event => {
    if (event.key === key || event.key === null) {
      mode = valid(event.newValue);
      apply();
    }
  });
  function mount() {
    document.querySelectorAll('[data-appearance-control]').forEach(host => {
      host.innerHTML = `<label class="appearance-control"><span class="appearance-swatch" aria-hidden="true"></span><span class="appearance-caption">外观</span><select class="appearance-picker" aria-label="页面配色" title="切换配色，自动保存到本机浏览器">${Object.entries(modes).map(([value,label]) => `<option value="${value}">${label}</option>`).join('')}</select></label><span class="appearance-storage-note" hidden title="浏览器未允许保存偏好；本次切换仍可使用。">本次有效</span><span class="appearance-announcement" role="status" aria-live="polite"></span>`;
      host.querySelector('select').addEventListener('change', event => {
        mode = valid(event.target.value);
        try { localStorage.setItem(key, mode); canSave = true; } catch { canSave = false; }
        apply(true);
      });
    });
    apply();
  }
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', mount, {once:true});
  else mount();
})();
