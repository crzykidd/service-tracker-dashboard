/*
 * Toasts and banners (design 7). Loaded by base.html, so Settings and Add/Edit share it.
 *   - `.toast[data-toast]` fades out after 5 seconds; hovering or focusing it pauses the
 *     timer; its X (`[data-toast-close]`) closes it now. Reduced motion removes the fade.
 *   - `[data-flash-banner]` stays until its X (`[data-flash-dismiss]`) is pressed.
 */
(function () {
  'use strict';

  var TOAST_MS = 5000;
  var reduced = window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches;

  function dismiss(toast) {
    if (!toast.parentNode) { return; }
    if (reduced) { toast.remove(); return; }
    toast.classList.add('leaving');
    window.setTimeout(function () { toast.remove(); }, 260);
  }

  function arm(toast) {
    var timer = null;
    function start() { stop(); timer = window.setTimeout(function () { dismiss(toast); }, TOAST_MS); }
    function stop() { if (timer) { window.clearTimeout(timer); timer = null; } }
    toast.addEventListener('mouseenter', stop);
    toast.addEventListener('mouseleave', start);
    toast.addEventListener('focusin', stop);
    toast.addEventListener('focusout', start);
    start();
  }

  function init() {
    document.querySelectorAll('.toast[data-toast]').forEach(arm);
  }

  document.addEventListener('click', function (event) {
    var close = event.target.closest('[data-toast-close]');
    if (close) { dismiss(close.closest('.toast')); return; }
    var banner = event.target.closest('[data-flash-dismiss]');
    if (banner) {
      var box = banner.closest('[data-flash-banner]');
      if (box) { box.remove(); }
    }
  });

  window.STDFlash = { arm: arm, dismiss: dismiss };
  if (document.readyState === 'loading') { document.addEventListener('DOMContentLoaded', init); }
  else { init(); }
})();
