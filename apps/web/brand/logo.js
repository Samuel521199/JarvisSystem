/* Reusable <jarvis-logo>: artwork + optional local pointer response; no service calls. */
(() => {
  'use strict';
  const base = new URL('.', document.currentScript.src);
  const states = new Set(['idle', 'thinking', 'offline', 'sleep']);
  let currentState = document.querySelector('jarvis-logo')?.dataset.state || 'idle';
  const motion = matchMedia('(prefers-reduced-motion: reduce)');
  const mouse = matchMedia('(hover: hover) and (pointer: fine)');
  const observer = 'IntersectionObserver' in window ? new IntersectionObserver(entries => {
    for (const entry of entries) {
      entry.target.dataset.inView = String(entry.isIntersecting);
      if (!entry.isIntersecting) entry.target.resetInteraction();
    }
  }) : null;
  class JarvisLogo extends HTMLElement {
    connectedCallback() {
      this.listeners?.abort();
      this.listeners = new AbortController();
      this.frame = 0;
      this.style.setProperty('--jarvis-art', `url("${new URL('core.png', base).href}")`);
      if (!this.querySelector('.jarvis-surface')) {
        const layer = (name, artwork = true) => {
          const span = document.createElement('span'); span.className = 'jarvis-' + name;
          if (artwork) {
            const img = new Image(512, 512);
            img.alt = ''; img.decoding = 'async'; img.draggable = false;
            img.src = new URL('core.png', base).href; span.append(img);
          }
          return span;
        };
        const floating = layer('float', false), surface = layer('surface', false);
        const segments = layer('segments', false);
        for (let i = 0; i < 4; i++) { const part = layer('segment'); part.style.setProperty('--segment', i); segments.append(part); }
        surface.append(layer('idle-halo'), layer('edge'), layer('echo'), layer('core'), segments, layer('scan', false), layer('star'), layer('glint'), layer('sheen', false));
        const meter = layer('meter', false); meter.setAttribute('aria-hidden', 'true');
        for (let i = 0; i < 5; i++) { const bar = document.createElement('i'); bar.style.setProperty('--bar', i); meter.append(bar); }
        floating.append(surface); this.replaceChildren(floating, meter);
      }
      this.dataset.state = currentState;
      this.resetInteraction();
      if (this.hasAttribute('interactive')) {
        // Linked marks keep one keyboard stop on their existing navigation link.
        const target = this.closest('a, button') || this;
        if (target === this) this.tabIndex = 0;
        else this.removeAttribute('tabindex');
        const options = {signal: this.listeners.signal, passive: true};
        target.addEventListener('pointerenter', event => this.point(event), options);
        target.addEventListener('pointermove', event => this.point(event), options);
        target.addEventListener('pointerleave', () => this.resetInteraction(), options);
        target.addEventListener('pointercancel', () => this.resetInteraction(), options);
        target.addEventListener('pointerdown', event => {
          if (event.pointerType === 'touch' && this.canReact()) this.engage(-3, 3);
        }, options);
        target.addEventListener('pointerup', event => {
          if (event.pointerType === 'touch') this.resetInteraction();
        }, options);
        target.addEventListener('focus', () => {
          if (target.matches(':focus-visible') && this.canReact()) this.engage(-3, 3);
        }, options);
        target.addEventListener('blur', () => this.resetInteraction(), options);
      }
      observer?.observe(this);
      queueMicrotask(() => { updateMotionControls(); window.JarvisSound?.update(); });
    }
    canReact() {
      return this.isConnected && this.hasAttribute('interactive') &&
        !motion.matches && !document.hidden && !document.documentElement.hasAttribute('data-brand-cinema') && this.dataset.inView !== 'false' &&
        !document.documentElement.hasAttribute('data-brand-paused') &&
        (this.dataset.state === 'idle' || this.dataset.state === 'thinking');
    }
    point(event) {
      if (event.pointerType !== 'mouse' || !mouse.matches || !this.canReact()) return;
      // Coalesce only incoming pointer events; there is no continuously running JS loop.
      this.pointX = event.clientX; this.pointY = event.clientY;
      if (this.frame) return;
      this.frame = requestAnimationFrame(() => {
        this.frame = 0;
        if (!this.canReact()) return;
        const bounds = this.getBoundingClientRect();
        if (!bounds.width || !bounds.height) return;
        const clamp = value => Math.max(-1, Math.min(1, value));
        const x = clamp((this.pointX - bounds.left) / bounds.width * 2 - 1);
        const y = clamp((this.pointY - bounds.top) / bounds.height * 2 - 1);
        this.engage(-y * 8, x * 9);
      });
    }
    engage(rx, ry) {
      this.style.setProperty('--tilt-x', rx.toFixed(2) + 'deg');
      this.style.setProperty('--tilt-y', ry.toFixed(2) + 'deg');
      this.dataset.engaged = 'true';
    }
    resetInteraction() {
      if (this.frame) cancelAnimationFrame(this.frame);
      this.frame = 0;
      delete this.dataset.engaged;
      this.style.setProperty('--tilt-x', '0deg');
      this.style.setProperty('--tilt-y', '0deg');
    }
    disconnectedCallback() {
      this.resetInteraction(); this.listeners?.abort(); observer?.unobserve(this);
    }
  }
  if (!customElements.get('jarvis-logo')) customElements.define('jarvis-logo', JarvisLogo);
  function updateMotionControls() {
    const paused = document.documentElement.hasAttribute('data-brand-paused');
    for (const logo of document.querySelectorAll('jarvis-logo')) {
      if (!logo.canReact()) logo.resetInteraction();
    }
    for (const button of document.querySelectorAll('[data-brand-motion]')) {
      button.setAttribute('aria-pressed', String(paused || motion.matches));
      button.textContent = motion.matches ? '已遵循系统减弱动效' : paused ? '播放动效' : '暂停动效';
      button.disabled = motion.matches;
    }
  }
  document.addEventListener('click', event => {
    const button = event.target.closest('[data-brand-motion]');
    if (!button || motion.matches) return;
    document.documentElement.toggleAttribute('data-brand-paused'); updateMotionControls();
  });
  function visibility() {
    document.documentElement.toggleAttribute('data-brand-hidden', document.hidden);
    updateMotionControls();
  }
  document.addEventListener('visibilitychange', visibility);
  motion.addEventListener('change', updateMotionControls);
  mouse.addEventListener('change', () => {
    for (const logo of document.querySelectorAll('jarvis-logo')) logo.resetInteraction();
  });
  window.JarvisBrand = Object.freeze({
    setState(state) {
      if (!states.has(state)) return;
      currentState = state;
      for (const logo of document.querySelectorAll('jarvis-logo')) logo.dataset.state = state;
      updateMotionControls();
    }
  });
  visibility(); updateMotionControls();
})();
