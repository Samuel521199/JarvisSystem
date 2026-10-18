/* Small, local Web Audio cues. No downloads, microphone, music loops or model calls. */
(() => {
  'use strict';
  let enabled = false, context = null, master = null;
  const voices = new Set();
  let generation = 0;
  try { enabled = localStorage.getItem('jarvis.brand.sound') === 'on'; } catch {}
  function ready() { return context?.state === 'running'; }
  function update() {
    for (const button of document.querySelectorAll('[data-brand-sound]')) {
      const label = enabled ? ready() ? '音效：开 · 点击关闭' : '音效：点击解锁' : '音效：关 · 点击开启';
      if (button.hasAttribute('data-sound-icon')) {
        button.querySelector('.topbar-tooltip').textContent = label;
        button.setAttribute('aria-label', label);
        button.dataset.soundState = enabled ? ready() ? 'on' : 'locked' : 'off';
      } else button.textContent = enabled ? ready() ? '音效：开' : '音效：点此解锁' : '音效：关';
      button.setAttribute('aria-pressed', String(enabled && ready()));
      if (!button.hasAttribute('data-sound-icon')) button.title = '短促机械合成音；不启用麦克风';
    }
  }
  async function unlock() {
    const Audio = window.AudioContext || window.webkitAudioContext;
    if (!Audio) return false;
    try {
    if (!context || context.state === 'closed') {
      context = new Audio();
      master = context.createGain(); master.gain.value = .16;
      const limiter = context.createDynamicsCompressor();
      limiter.threshold.value = -12; limiter.ratio.value = 8;
      limiter.attack.value = .003; limiter.release.value = .1;
      master.connect(limiter); limiter.connect(context.destination);
      context.addEventListener('statechange', update);
    }
    await context.resume();
    } catch { return false; }
    update(); return ready();
  }
  function stop() {
    generation++;
    for (const source of [...voices]) {
      try { source.stop(); } catch {}
      source.onended?.();
    }
    voices.clear();
  }
  function voice(source, start, duration, level, filter = null) {
    const gain = context.createGain(), at = context.currentTime + start;
    gain.gain.setValueAtTime(0, at);
    gain.gain.linearRampToValueAtTime(level, at + Math.min(.018, duration / 4));
    gain.gain.exponentialRampToValueAtTime(.0001, at + duration);
    if (filter) { source.connect(filter); filter.connect(gain); } else source.connect(gain);
    gain.connect(master); voices.add(source);
    source.onended = () => { source.disconnect(); filter?.disconnect(); gain.disconnect(); voices.delete(source); };
    source.start(at); source.stop(at + duration + .02);
  }
  function tone(start, duration, from, to, level = .22, type = 'sine') {
    const oscillator = context.createOscillator(); oscillator.type = type;
    oscillator.frequency.setValueAtTime(from, context.currentTime + start);
    oscillator.frequency.exponentialRampToValueAtTime(to, context.currentTime + start + duration);
    voice(oscillator, start, duration, level);
  }
  function air(start, duration, frequency = 1100) {
    const buffer = context.createBuffer(1, Math.ceil(context.sampleRate * duration), context.sampleRate);
    const channel = buffer.getChannelData(0);
    for (let i = 0; i < channel.length; i++) channel[i] = Math.random() * 2 - 1;
    const source = context.createBufferSource(); source.buffer = buffer;
    const filter = context.createBiquadFilter(); filter.type = 'bandpass'; filter.Q.value = 1.8;
    filter.frequency.setValueAtTime(frequency, context.currentTime + start);
    filter.frequency.exponentialRampToValueAtTime(280, context.currentTime + start + duration);
    voice(source, start, duration, .3, filter);
  }
  async function play(kind, gesture = false) {
    if (!enabled) return false;
    stop(); const ticket = generation;
    // An automatic intro never tries to circumvent browser autoplay restrictions.
    if (!ready() && (!gesture || !await unlock())) { update(); return false; }
    if (ticket !== generation || !enabled || document.hidden) return false;
    if (kind === 'boot') {
      air(0, .75, 1700); tone(0, 1.25, 70, 180, .24);
      [.18, .31, .48, .66, .84, 1.02, 1.20, 1.38, 1.55].forEach((at, i) => {
        tone(at, .09, 480 + i * 65, 115, .21, 'triangle');
      });
      air(1.65, .38, 2600); tone(1.68, .4, 100, 52, .34);
      tone(1.88, .65, 660, 880, .12); tone(2.08, .8, 990, 1320, .08);
    } else {
      tone(0, .8, 520, 150, .18); air(.22, .65, 1900);
      [.32, .49, .66, .83, 1.0, 1.17, 1.34, 1.51, 1.68].forEach((at, i) => {
        tone(at, .11, 780 - i * 55, 100, .16, 'triangle');
      });
      air(1.5, .8, 1300); tone(1.72, .95, 150, 38, .26);
    }
    return true;
  }
  document.addEventListener('click', async event => {
    const button = event.target.closest('[data-brand-sound]');
    if (!button) return;
    if (enabled && ready()) { enabled = false; stop(); }
    else {
      enabled = await unlock();
      if (enabled && !document.hidden) tone(0, .16, 660, 880, .08);
      if (document.hidden) { stop(); context?.suspend().catch(() => {}); }
    }
    try { localStorage.setItem('jarvis.brand.sound', enabled ? 'on' : 'off'); } catch {}
    update();
  });
  document.addEventListener('visibilitychange', () => { if (document.hidden) { stop(); context?.suspend().catch(() => {}); } });
  window.addEventListener('pagehide', () => { stop(); context?.close().catch(() => {}); });
  window.JarvisSound = Object.freeze({play, stop, update}); update();
})();
