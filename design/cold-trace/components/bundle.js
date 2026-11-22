/* Cold Trace runtime 0.1. No dependencies. Load once per page from a deferred script tag.
   It gives every .ct-btn the one-touch throw, flips [data-ct-switch] switches,
   draws [data-ct-curtain] aurora curtains and manages the colour mode.
   Exposes window.ColdTrace = { throwKey, setTheme, getTheme, curtain, init }. */
(function (global) {
  'use strict';

  var THROW_MS = 400;
  var THEME_KEY = 'ct-theme';

  /* Throw: one light touch plays the whole press, however short the touch. */
  function throwKey(btn) {
    if (!btn || btn.disabled || btn.getAttribute('aria-disabled') === 'true') return;
    if (btn.classList.contains('is-thrown')) return;
    btn.classList.add('is-thrown');
    setTimeout(function () { btn.classList.remove('is-thrown'); }, THROW_MS + 20);
  }

  function closest(target, selector) {
    return target && target.closest ? target.closest(selector) : null;
  }

  function onPointerDown(e) {
    throwKey(closest(e.target, '.ct-btn'));
  }

  function onKeyDown(e) {
    if (e.repeat || (e.key !== 'Enter' && e.key !== ' ')) return;
    throwKey(closest(e.target, '.ct-btn'));
  }

  /* Switches: buttons with role="switch" and data-ct-switch flip aria-checked on click
     and fire a "ct-switch" event with detail { checked }. Framework components that
     manage aria-checked themselves should leave data-ct-switch off. */
  function onClick(e) {
    var sw = closest(e.target, '[data-ct-switch]');
    if (!sw || sw.disabled) return;
    var next = sw.getAttribute('aria-checked') !== 'true';
    sw.setAttribute('aria-checked', String(next));
    sw.dispatchEvent(new CustomEvent('ct-switch', { bubbles: true, detail: { checked: next } }));
  }

  /* Colour mode: 'dark', 'light' or 'system'. Stored per viewer when storage allows. */
  function systemMode() {
    return global.matchMedia && global.matchMedia('(prefers-color-scheme: light)').matches ? 'light' : 'dark';
  }

  function getTheme() {
    var saved = null;
    try { saved = global.localStorage.getItem(THEME_KEY); } catch (err) { saved = null; }
    return saved || 'dark';
  }

  function setTheme(mode, root) {
    root = root || document.documentElement;
    try { global.localStorage.setItem(THEME_KEY, mode); } catch (err) { /* storage blocked: still apply */ }
    root.setAttribute('data-theme', mode === 'system' ? systemMode() : mode);
    document.dispatchEvent(new CustomEvent('ct-theme', { detail: { mode: mode } }));
  }

  /* Curtain: fills an element with aurora hairlines. reflect: true draws the
     compressed reflection below a waterline instead. */
  function curtain(el, opts) {
    opts = opts || {};
    var n = opts.count || 72;
    var seed = opts.seed || 0;
    var water = 75.8;
    var frag = document.createDocumentFragment();
    for (var k = 0; k < n; k++) {
      var t = k / (n - 1);
      var env = Math.pow(Math.sin(Math.PI * t), 0.7);
      var top = 4 + 7 * (0.5 + 0.5 * Math.sin(t * 8.2 + 0.6)) + 4 * (0.5 + 0.5 * Math.sin(t * 19.5 + seed)) + (1 - env) * 16;
      var len = 24 + 14 * (0.5 + 0.5 * Math.sin(t * 5.6 + 1.2)) + 10 * env;
      var bottom = Math.min(top + len, 68);
      var o = (0.16 + 0.78 * Math.pow(0.5 + 0.5 * Math.sin(t * 13.8 + 0.3 + seed), 2)) * env;
      var line = document.createElement('i');
      line.className = 'ct-curtain__l';
      line.style.left = (14 + 72 * t).toFixed(2) + '%';
      if (opts.reflect) {
        line.style.top = (0.42 * (water - bottom) / (100 - water) * 100).toFixed(2) + '%';
        line.style.height = (0.42 * (bottom - top) / (100 - water) * 100).toFixed(2) + '%';
        line.style.opacity = (o * 0.4).toFixed(3);
        line.style.transformOrigin = '50% 0';
        line.style.background = 'linear-gradient(to top, transparent, var(--ct-arc) 18%, var(--ct-signal) 52%, var(--ct-live) 84%, transparent)';
      } else {
        line.style.top = top.toFixed(2) + '%';
        line.style.height = (bottom - top).toFixed(2) + '%';
        line.style.opacity = o.toFixed(3);
      }
      line.style.animationDelay = (-((k * 0.37) % 3.2)).toFixed(2) + 's';
      frag.appendChild(line);
    }
    el.appendChild(frag);
  }

  var started = false;
  function init() {
    if (started) return;
    started = true;
    document.addEventListener('pointerdown', onPointerDown);
    document.addEventListener('keydown', onKeyDown);
    document.addEventListener('click', onClick);
    var curtains = document.querySelectorAll('[data-ct-curtain]');
    for (var i = 0; i < curtains.length; i++) {
      var el = curtains[i];
      if (el.childElementCount) continue;
      curtain(el, {
        count: Number(el.getAttribute('data-ct-curtain')) || undefined,
        reflect: el.hasAttribute('data-ct-reflect'),
        seed: Number(el.getAttribute('data-ct-seed')) || 0
      });
    }
  }

  global.ColdTrace = { throwKey: throwKey, setTheme: setTheme, getTheme: getTheme, curtain: curtain, init: init, version: '0.1.0' };

  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', init);
  else init();
})(window);
