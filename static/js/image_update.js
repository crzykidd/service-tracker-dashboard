/*
 * Image update "Check now" (PRD 24). Any `[data-image-check][data-url]` link or button POSTs to its
 * URL (CSRF token from the page's meta tag) and shows the answer as a toast. The check itself runs
 * later in the background job; the page never waits for the registry. Delegated, so it also works in
 * the Compact details dialog, which is fetched when it opens.
 */
(function () {
  'use strict';

  function region() {
    var box = document.getElementById('toast-region');
    if (!box) {
      box = document.createElement('div');
      box.id = 'toast-region';
      box.className = 'toast-region';
      box.setAttribute('role', 'status');
      box.setAttribute('aria-live', 'polite');
      document.body.appendChild(box);
    }
    return box;
  }

  function toast(kind, text) {
    var el = document.createElement('div');
    el.className = 'toast toast--' + kind;
    el.setAttribute('role', 'status');
    el.setAttribute('data-toast', '');
    var msg = document.createElement('span');
    msg.className = 'toast-text';
    msg.textContent = text;
    var close = document.createElement('button');
    close.type = 'button';
    close.className = 'toast-close';
    close.setAttribute('aria-label', 'Dismiss');
    close.setAttribute('data-toast-close', '');
    close.innerHTML = '&times;';
    el.appendChild(msg);
    el.appendChild(close);
    region().appendChild(el);
    if (window.STDFlash) { window.STDFlash.arm(el); }
  }

  document.addEventListener('click', function (event) {
    var trigger = event.target.closest('[data-image-check]');
    if (!trigger) { return; }
    event.preventDefault();
    if (trigger.getAttribute('aria-disabled') === 'true') { return; }
    trigger.setAttribute('aria-disabled', 'true');
    var meta = document.querySelector('meta[name="csrf-token"]');
    fetch(trigger.getAttribute('data-url'), {
      method: 'POST',
      headers: { 'X-CSRFToken': meta ? meta.content : '', 'Accept': 'application/json' },
      credentials: 'same-origin'
    }).then(function (resp) {
      return resp.json().catch(function () { return {}; }).then(function (body) {
        toast(resp.ok ? 'success' : 'info', body.message || (resp.ok ? 'Check requested.' : 'Could not start the check.'));
      });
    }).catch(function () {
      toast('info', 'Could not reach STD; try again.');
    }).then(function () {
      trigger.removeAttribute('aria-disabled');
    });
  });
})();
