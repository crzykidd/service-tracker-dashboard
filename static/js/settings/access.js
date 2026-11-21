/*
 * Settings -> About / Users / API keys: the default-credentials warning, the Users dialogs
 * and the API key dialogs (design 9.1, 9.9, 9.10). Everything is delegated from the document.
 */
(function () {
  'use strict';

  var ui = (window.STDSettings || {}).ui || {};

  // The default-credentials warning shows unless it was dismissed this browser session.
  var box = document.getElementById('credential-warning');
  if (box) {
    var key = 'std-credential-warning-dismissed';
    var dismissed = false;
    try { dismissed = sessionStorage.getItem(key) === '1'; } catch (e) { /* storage blocked */ }
    if (!dismissed) { box.style.display = 'flex'; }
    var btn = document.getElementById('credential-warning-dismiss');
    if (btn) {
      btn.addEventListener('click', function () {
        box.style.display = 'none';
        try { sessionStorage.setItem(key, '1'); } catch (e) { /* storage blocked */ }
      });
    }
  }

  function open(dialogId, opener) {
    var dlg = document.getElementById(dialogId);
    if (dlg && ui.openModal) { ui.openModal(dlg, opener); }
    return dlg;
  }

  // form.reset() would restore values a validation re-render put in the markup, so clear by hand.
  function blank(form) {
    form.querySelectorAll('input:not([type=hidden]), select').forEach(function (el) {
      if (el.type === 'checkbox') { el.checked = false; }
      else if (el.tagName === 'SELECT') { el.selectedIndex = 0; }
      else { el.value = ''; }
    });
  }

  function clearErrors(dlg) {
    dlg.querySelectorAll('[data-flash-slot]').forEach(function (el) { el.remove(); });
    dlg.querySelectorAll('[aria-invalid]').forEach(function (el) { el.removeAttribute('aria-invalid'); });
  }

  document.addEventListener('click', function (event) {
    // Users: Add user, Set password (one dialog; the button carries the user and the route).
    if (event.target.closest('[data-user-add]')) {
      var add = document.getElementById('user-modal');
      if (add) {
        blank(add.querySelector('form'));
        clearErrors(add);
        open('user-modal', event.target.closest('[data-user-add]'));
      }
      return;
    }
    var pw = event.target.closest('[data-user-password]');
    if (pw) {
      var dlg = document.getElementById('password-modal');
      if (!dlg) { return; }
      var form = dlg.querySelector('form');
      var pwUrl = pw.getAttribute('data-password-url') || '';
      // Only a same-site path (from url_for); never a scheme or protocol-relative URL.
      if (pwUrl.charAt(0) !== '/' || pwUrl.charAt(1) === '/') { return; }
      form.action = pwUrl;
      blank(form);
      clearErrors(dlg);
      document.getElementById('password-modal-title').textContent = 'Set password for ' + pw.getAttribute('data-user-name');
      open('password-modal', pw);
      return;
    }

    // API keys: Create key opens an empty dialog.
    var create = event.target.closest('[data-api-key-add]');
    if (create) {
      var kd = document.getElementById('api-key-modal');
      if (kd) {
        blank(kd.querySelector('form'));
        clearErrors(kd);
        syncScope();
        open('api-key-modal', create);
      }
      return;
    }

    // The show-once dialog: Copy puts the key on the clipboard.
    var copy = event.target.closest('#copy-api-key');
    if (copy) {
      var input = document.getElementById('new-api-key');
      input.select();
      Promise.resolve(ui.copyText ? ui.copyText(input.value) : false).then(function (ok) {
        copy.textContent = ok ? 'Copied' : 'Press Ctrl+C';
      });
    }
  });

  // One help line per scope; no script means all three stay visible.
  function syncScope() {
    var sel = document.getElementById('new-key-scope');
    if (!sel) { return; }
    document.querySelectorAll('[data-scope-help]').forEach(function (el) {
      el.hidden = el.getAttribute('data-scope-help') !== sel.value;
    });
  }
  document.addEventListener('change', function (event) {
    if (event.target && event.target.id === 'new-key-scope') { syncScope(); }
  });

  // The show-once key is selected on open so a manual Ctrl+C works at once.
  var secret = document.getElementById('new-api-key');
  if (secret) {
    var cp = document.getElementById('copy-api-key');
    window.setTimeout(function () { if (cp) { cp.focus(); } }, 0);
  }
})();
