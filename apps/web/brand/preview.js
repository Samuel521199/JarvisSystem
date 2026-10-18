(() => {
  const captions = {idle:'能量稳定，等你开口。',thinking:'扫描推进 · 分区响应 · 思路汇聚。',sleep:'暂时休息，等你唤醒。'};
  const labels = {idle:'待命 / STANDBY',thinking:'思考 / PROCESSING',sleep:'休眠 / SLEEP'};
  for (const button of document.querySelectorAll('[data-preview-state]')) {
    button.addEventListener('click', () => {
      const state = button.dataset.previewState;
      window.JarvisBrand.setState(state);
      document.getElementById('preview-status').textContent = captions[state];
      document.getElementById('preview-readout').textContent = labels[state];
      for (const item of document.querySelectorAll('[data-preview-state]')) item.setAttribute('aria-pressed',String(item === button));
    });
  }
})();
