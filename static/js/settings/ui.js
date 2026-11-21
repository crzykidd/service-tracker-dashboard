/*
 * Shared Settings UI behaviour (design 6.5 to 6.9), attached to window.STDSettings.ui:
 *   - modals: opener memory + focus return, guarded Esc / X / Cancel, backdrop rule
 *   - the "..." menu (WAI-ARIA menu button, full keyboard support)
 *   - the shared confirm dialog and `data-confirm` forms
 *   - collapsible groups with a tri-state checkbox (first used in phase 2)
 *   - the reset bridge for the sticky save bar's Discard
 * Everything is delegated from the document, so markup rendered later needs no wiring.
 */
(function () {
  'use strict';

  var S = window.STDSettings = window.STDSettings || {};
  var ui = S.ui = {};

  /* ---------------------------------------------------------------- modals */

  // Every showModal() remembers what had focus, so closing returns it there.
  if (window.HTMLDialogElement) {
    var nativeShow = HTMLDialogElement.prototype.showModal;
    HTMLDialogElement.prototype.showModal = function () {
      this._stdOpener = document.activeElement;
      return nativeShow.apply(this, arguments);
    };
  }

  // The dialog's guarded form: the first dirty one when it holds several (Edit stream
  // has one per block), else the first.
  function guardedForm(dialog) {
    var first = null;
    var forms = dialog.querySelectorAll('form[data-unsaved-guard]');
    for (var i = 0; i < forms.length; i++) {
      if (!forms[i]._unsavedGuard) { continue; }
      if (!first) { first = forms[i]; }
      if (forms[i]._unsavedGuard.isDirty()) { return forms[i]; }
    }
    return first;
  }

  function openModal(dialog, opener) {
    if (!dialog || dialog.open) { return; }
    dialog.showModal();
    if (opener) { dialog._stdOpener = opener; }
    var target = dialog.querySelector('[autofocus]') ||
      dialog.querySelector('.std-modal-body input:not([type=hidden]):not([disabled]), .std-modal-body select, .std-modal-body textarea');
    if (target && target.focus) { target.focus(); }
  }

  // Close, asking first when the dialog holds a dirty guarded form.
  function requestClose(dialog) {
    var form = guardedForm(dialog);
    if (form && form._unsavedGuard.isDirty()) {
      ui.confirm({
        title: 'Discard unsaved changes?',
        body: 'What you typed in this dialog will be lost.',
        confirmLabel: 'Discard',
        danger: true
      }).then(function (ok) {
        if (!ok) { return; }
        dialog.dispatchEvent(new CustomEvent('std:modal-discard', { bubbles: true }));
        form._unsavedGuard.reset();
        dialog.close();
      });
      return;
    }
    dialog.close();
  }

  ui.openModal = openModal;
  ui.closeModal = requestClose;

  document.addEventListener('cancel', function (event) {
    var dialog = event.target;
    if (!(dialog instanceof HTMLDialogElement) || dialog.id === 'confirm-modal') { return; }
    var form = guardedForm(dialog);
    if (form && form._unsavedGuard.isDirty()) {
      event.preventDefault();
      requestClose(dialog);
    }
  }, true);

  document.addEventListener('close', function (event) {
    var dialog = event.target;
    if (!(dialog instanceof HTMLDialogElement)) { return; }
    var opener = dialog._stdOpener;
    dialog._stdOpener = null;
    if (opener && opener.isConnected && opener.focus && !opener.closest('[hidden]')) { opener.focus(); }
  }, true);

  document.addEventListener('click', function (event) {
    var closer = event.target.closest('[data-modal-close]');
    if (closer) {
      var dlg = closer.closest('dialog');
      if (dlg) { requestClose(dlg); }
      return;
    }
    // Backdrop: the click lands on the dialog element itself. Guarded dialogs ignore it.
    var t = event.target;
    if (t instanceof HTMLDialogElement && t.open && t.classList.contains('std-modal') && !guardedForm(t)) {
      var r = t.getBoundingClientRect();
      var inside = event.clientX >= r.left && event.clientX <= r.right &&
                   event.clientY >= r.top && event.clientY <= r.bottom;
      if (!inside) { t.close(); }
    }
  });

  /* ----------------------------------------------------------- confirm dialog */

  var pending = null;

  function confirmDialog() { return document.getElementById('confirm-modal'); }

  // ui.confirm({title, body, confirmLabel, danger}) -> Promise<boolean>
  ui.confirm = function (opts) {
    opts = opts || {};
    var dlg = confirmDialog();
    if (!dlg) { return Promise.resolve(window.confirm(opts.body || opts.title || 'Are you sure?')); }
    if (pending) { pending(false); }
    document.getElementById('confirm-title').textContent = opts.title || 'Are you sure?';
    document.getElementById('confirm-body').textContent = opts.body || '';
    var ok = document.getElementById('confirm-ok');
    ok.textContent = opts.confirmLabel || 'OK';
    ok.classList.toggle('btn-danger', !!opts.danger);
    ok.classList.toggle('btn-primary', !opts.danger);
    return new Promise(function (resolve) {
      pending = resolve;
      dlg.showModal();
      ok.focus();
    });
  };

  function settle(value) {
    if (!pending) { return; }
    var resolve = pending;
    pending = null;
    resolve(value);
  }

  (function wireConfirm() {
    document.addEventListener('click', function (event) {
      if (event.target.closest('#confirm-ok')) { settle(true); confirmDialog().close(); return; }
      if (event.target.closest('[data-confirm-cancel]')) { confirmDialog().close(); }
    });
    document.addEventListener('close', function (event) {
      if (event.target && event.target.id === 'confirm-modal') { settle(false); }
    }, true);
  })();

  // Forms with data-confirm="text" ask first and submit only on OK.
  document.addEventListener('submit', function (event) {
    var form = event.target;
    if (!(form instanceof HTMLFormElement) || !form.hasAttribute('data-confirm')) { return; }
    if (form._stdConfirmed) { form._stdConfirmed = false; return; }
    event.preventDefault();
    event.stopImmediatePropagation();
    var submitter = event.submitter || null;
    var label = form.getAttribute('data-confirm-label') ||
      (submitter && submitter.textContent.trim()) || 'OK';
    var danger = form.hasAttribute('data-confirm-danger') ||
      !!(submitter && (submitter.classList.contains('btn-danger') || submitter.classList.contains('kebab-item--danger')));
    ui.confirm({
      title: form.getAttribute('data-confirm-title') || 'Please confirm',
      body: form.getAttribute('data-confirm'),
      confirmLabel: label,
      danger: danger
    }).then(function (ok) {
      if (!ok) { return; }
      form._stdConfirmed = true;
      try { form.requestSubmit(submitter && submitter.form === form ? submitter : undefined); }
      catch (e) { form.requestSubmit(); }
    });
  }, true);

  /* ------------------------------------------------------------------- menus */

  function menuOf(trigger) { return document.getElementById(trigger.getAttribute('aria-controls')); }
  function itemsOf(menu) { return Array.prototype.slice.call(menu.querySelectorAll('[role=menuitem]:not([disabled])')); }

  function closeMenu(trigger, returnFocus) {
    var menu = menuOf(trigger);
    if (!menu) { return; }
    menu.hidden = true;
    menu.classList.remove('kebab-menu--up');
    menu.style.right = '';
    trigger.setAttribute('aria-expanded', 'false');
    if (returnFocus) { trigger.focus(); }
  }

  function closeAllMenus(except) {
    document.querySelectorAll('.kebab[aria-expanded="true"]').forEach(function (t) {
      if (t !== except) { closeMenu(t, false); }
    });
  }

  function place(menu) {
    var r = menu.getBoundingClientRect();
    if (r.bottom > window.innerHeight && r.height < menu.parentNode.getBoundingClientRect().top) {
      menu.classList.add('kebab-menu--up');
    }
    r = menu.getBoundingClientRect();
    if (r.left < 8) { menu.style.right = (r.left - 8) + 'px'; }
  }

  function openMenu(trigger, focus) {
    closeAllMenus(trigger);
    var menu = menuOf(trigger);
    if (!menu) { return; }
    menu.hidden = false;
    trigger.setAttribute('aria-expanded', 'true');
    place(menu);
    var items = itemsOf(menu);
    if (focus === 'first' && items.length) { items[0].focus(); }
    if (focus === 'last' && items.length) { items[items.length - 1].focus(); }
  }

  ui.menus = { open: openMenu, close: closeMenu };

  document.addEventListener('click', function (event) {
    var trigger = event.target.closest('.kebab');
    if (trigger) {
      if (trigger.getAttribute('aria-expanded') === 'true') { closeMenu(trigger, false); }
      else { openMenu(trigger, event.detail === 0 ? 'first' : null); }
      return;
    }
    if (!event.target.closest('.kebab-menu')) { closeAllMenus(null); }
  });

  // Capture: choosing an item closes the menu (focus back on the trigger) before the
  // item's own handler runs, so a dialog it opens returns focus to a visible button.
  document.addEventListener('click', function (event) {
    var item = event.target.closest('.kebab-menu [role=menuitem]');
    if (!item) { return; }
    var menu = item.closest('.kebab-menu');
    var trigger = document.querySelector('.kebab[aria-controls="' + menu.id + '"]');
    if (trigger) { closeMenu(trigger, true); }
  }, true);

  document.addEventListener('keydown', function (event) {
    var trigger = event.target.closest && event.target.closest('.kebab');
    if (trigger) {
      if (event.key === 'ArrowDown') { event.preventDefault(); openMenu(trigger, 'first'); }
      else if (event.key === 'ArrowUp') { event.preventDefault(); openMenu(trigger, 'last'); }
      return;
    }
    var menu = event.target.closest && event.target.closest('.kebab-menu');
    if (!menu) { return; }
    var tr = document.querySelector('.kebab[aria-controls="' + menu.id + '"]');
    var items = itemsOf(menu);
    var i = items.indexOf(document.activeElement);
    if (event.key === 'ArrowDown') { event.preventDefault(); items[(i + 1) % items.length].focus(); }
    else if (event.key === 'ArrowUp') { event.preventDefault(); items[(i - 1 + items.length) % items.length].focus(); }
    else if (event.key === 'Home') { event.preventDefault(); items[0].focus(); }
    else if (event.key === 'End') { event.preventDefault(); items[items.length - 1].focus(); }
    else if (event.key === 'Escape') { event.preventDefault(); event.stopPropagation(); if (tr) { closeMenu(tr, true); } }
    else if (event.key === 'Tab') { if (tr) { closeMenu(tr, false); } }
  });

  /* ------------------------------------------------------- clipboard, toast */

  // ui.copyText(text) -> Promise<boolean>. Falls back to a temporary textarea when the
  // async clipboard API is missing (plain http).
  ui.copyText = function (text) {
    if (navigator.clipboard && navigator.clipboard.writeText) {
      return navigator.clipboard.writeText(text).then(function () { return true; }, function () { return legacyCopy(text); });
    }
    return Promise.resolve(legacyCopy(text));
  };

  function legacyCopy(text) {
    var ta = document.createElement('textarea');
    ta.value = text;
    ta.setAttribute('readonly', '');
    ta.style.position = 'fixed';
    ta.style.opacity = '0';
    document.body.appendChild(ta);
    ta.select();
    var ok = false;
    try { ok = document.execCommand('copy'); } catch (e) { ok = false; }
    ta.remove();
    return ok;
  }

  // ui.toast(message): the same markup as a server-rendered success toast.
  ui.toast = function (message) {
    var region = document.getElementById('toast-region');
    if (!region) { return; }
    var t = document.createElement('div');
    t.className = 'toast toast--success';
    t.setAttribute('role', 'status');
    t.setAttribute('data-toast', '');
    var icon = document.createElement('span');
    icon.className = 'toast-icon';
    icon.setAttribute('aria-hidden', 'true');
    icon.textContent = '\u2713';
    var text = document.createElement('span');
    text.className = 'toast-text';
    text.textContent = message;
    var close = document.createElement('button');
    close.type = 'button';
    close.className = 'toast-close';
    close.setAttribute('aria-label', 'Dismiss');
    close.setAttribute('data-toast-close', '');
    close.innerHTML = '&times;';
    t.appendChild(icon); t.appendChild(text); t.appendChild(close);
    region.appendChild(t);
    if (window.STDFlash) { window.STDFlash.arm(t); }
  };

  // [data-copy-text="..."] (any button, usually a menu item) copies that text and toasts.
  document.addEventListener('click', function (event) {
    var btn = event.target.closest('[data-copy-text]');
    if (!btn) { return; }
    var label = btn.getAttribute('data-copy-label') || 'Copied';
    Promise.resolve(ui.copyText(btn.getAttribute('data-copy-text'))).then(function (ok) {
      ui.toast(ok ? label : 'Could not copy; select the text and copy it by hand.');
    });
  });

  /* --------------------------------------------- collapsible groups, tri-state */

  var groups = S.groups = S.groups || {};

  function groupParts(group) {
    var body = group.querySelector('.settings-group-body');
    var check = group.querySelector('.settings-group-check');
    // A group whose rows mark their box with data-group-row (the import page, where a row also
    // holds per-field boxes) counts only those; otherwise every checkbox in the body is a row.
    var boxes = [];
    if (body) {
      boxes = Array.prototype.slice.call(body.querySelectorAll('input[type=checkbox][data-group-row]'));
      if (!boxes.length) { boxes = Array.prototype.slice.call(body.querySelectorAll('input[type=checkbox]')); }
    }
    return { body: body, check: check, boxes: boxes };
  }

  // A row is filtered out (by a search) when it or an ancestor below the body is [hidden].
  function isFiltered(box, body) {
    for (var el = box; el && el !== body; el = el.parentElement) {
      if (el.hidden) { return true; }
    }
    return false;
  }

  function refreshGroup(group) {
    var p = groupParts(group);
    if (!p.check) { return; }
    var affected = p.boxes.filter(function (b) { return !isFiltered(b, p.body); });
    var on = affected.filter(function (b) { return b.checked; }).length;
    p.check.checked = affected.length > 0 && on === affected.length;
    p.check.indeterminate = on > 0 && on < affected.length;
    var count = group.querySelector('.settings-group-count');
    if (count) {
      count.textContent = p.boxes.filter(function (b) { return b.checked; }).length + ' of ' + p.boxes.length;
    }
  }

  function setCollapsed(group, collapsed) {
    var p = groupParts(group);
    var toggle = group.querySelector('.settings-group-toggle');
    if (p.body) { p.body.hidden = collapsed; }
    if (toggle) { toggle.setAttribute('aria-expanded', collapsed ? 'false' : 'true'); }
    group.setAttribute('data-collapsed', collapsed ? 'true' : 'false');
  }

  groups.refresh = refreshGroup;
  groups.refreshAll = function (root) {
    (root || document).querySelectorAll('.settings-group').forEach(refreshGroup);
  };
  groups.setCollapsed = setCollapsed;

  document.addEventListener('click', function (event) {
    var toggle = event.target.closest('.settings-group-toggle');
    if (!toggle) { return; }
    var group = toggle.closest('.settings-group');
    setCollapsed(group, toggle.getAttribute('aria-expanded') === 'true');
  });

  document.addEventListener('change', function (event) {
    var group = event.target.closest && event.target.closest('.settings-group');
    if (!group) { return; }
    if (event.target.classList.contains('settings-group-check')) {
      // A click on a partial or empty group ticks every affected row; on a full group it clears them.
      var p = groupParts(group);
      var want = event.target.checked;
      p.boxes.forEach(function (b) {
        if (isFiltered(b, p.body) || b.checked === want) { return; }
        b.checked = want;
        b.dispatchEvent(new Event('change', { bubbles: true }));
      });
    }
    refreshGroup(group);
  });

  /* ---------------------------------------------------------- reset bridge */

  // A form's Discard is <button type="reset">. After the browser restores the values,
  // tell the unsaved guard (and the groups) to look again.
  document.addEventListener('reset', function (event) {
    var form = event.target;
    window.setTimeout(function () {
      form.dispatchEvent(new Event('change', { bubbles: true }));
      form.querySelectorAll('.settings-group').forEach(refreshGroup);
    }, 0);
  });

  function init() { groups.refreshAll(document); }
  if (document.readyState === 'loading') { document.addEventListener('DOMContentLoaded', init); }
  else { init(); }
})();
