/* Settings -> Import preview (backup phase 4): row disclosure, the mode switch, live counts in the
   apply bar, status-chip filtering and search. Groups, the tri-state and the confirm dialog are
   ui.js's. Without this file the form still posts the ticked boxes. */
(function () {
  'use strict';
  var S = window.STDSettings = window.STDSettings || {};
  var form = document.querySelector('[data-imp-form]');
  if (!form) { return; }
  var root = document.getElementById('settings-root');

  function $all(sel, ctx) { return Array.prototype.slice.call((ctx || form).querySelectorAll(sel)); }
  function rowOf(el) { return el.closest('[data-imp-row]'); }
  function rowBox(row) { return row.querySelector('[data-group-row]'); }
  function mode() {
    var checked = form.querySelector('input[name=mode]:checked');
    return checked ? checked.value : 'fill';
  }

  /* ---------------------------------------------------------------- counts */

  function overwriteCount() {
    return $all('[data-imp-field][data-kind=differs]').filter(function (f) {
      var box = rowBox(rowOf(f));
      return f.checked && !f.disabled && box && box.checked;
    }).length;
  }

  function updateCounts() {
    var records = 0, fields = 0, fresh = 0;
    $all('[data-imp-row]').forEach(function (row) {
      var box = rowBox(row);
      if (!box || !box.checked) { return; }
      records += 1;
      if (box.hasAttribute('data-imp-new')) { fresh += 1; }
      $all('[data-imp-field]', row).forEach(function (f) { if (f.checked && !f.disabled) { fields += 1; } });
    });
    var set = { records: records, fields: fields, 'new': fresh };
    Object.keys(set).forEach(function (k) {
      var el = form.querySelector('[data-imp-count=' + k + ']');
      if (el) { el.textContent = set[k]; }
    });
    var n = overwriteCount();
    if (mode() === 'overwrite' && n > 0) {
      form.setAttribute('data-confirm', 'Overwrite ' + n + ' value' + (n === 1 ? '' : 's') + ' that differ' + (n === 1 ? 's' : '') + '?');
      form.setAttribute('data-confirm-label', 'Overwrite');
      form.setAttribute('data-confirm-title', 'Apply import');
      form.setAttribute('data-confirm-danger', '');
    } else {
      form.removeAttribute('data-confirm');
      form.removeAttribute('data-confirm-danger');
    }
  }

  /* ------------------------------------------------------------ mode switch */

  function applyMode() {
    var m = mode();
    if (root) { root.setAttribute('data-imp-mode', m); }
    $all('.imp-segmented label').forEach(function (l) {
      var input = l.querySelector('input');
      l.classList.toggle('is-on', !!(input && input.checked));
    });
    $all('[data-imp-field][data-kind=differs][data-applicable=true]').forEach(function (f) {
      f.disabled = m !== 'overwrite';
      if (m !== 'overwrite') { f.checked = false; }
    });
    var label = form.querySelector('[data-imp-mode-label]');
    if (label) { label.textContent = m === 'fill' ? 'fill missing only' : 'overwrite differences'; }
    var note = form.querySelector('[data-imp-mode-note]');
    if (note) {
      note.textContent = m === 'fill' ? 'Differing values are shown greyed out. Switch to overwrite to apply them.'
                                      : 'Tick a differing field to overwrite it.';
    }
    updateCounts();
  }

  /* ---------------------------------------------------- filter, search, bulk */

  var activeChips = {};

  function applyFilter() {
    var q = (form.querySelector('[data-imp-search]') || { value: '' }).value.trim().toLowerCase();
    var anyChip = Object.keys(activeChips).length > 0;
    $all('[data-imp-row]').forEach(function (row) {
      var show = true;
      if (anyChip && !activeChips[row.getAttribute('data-status')]) { show = false; }
      if (show && q && (row.getAttribute('data-search') || '').indexOf(q) === -1) { show = false; }
      row.hidden = !show;
    });
    if (S.groups) { S.groups.refreshAll(form); }
  }

  form.addEventListener('click', function (event) {
    var disclose = event.target.closest('[data-imp-disclose]');
    if (disclose) {
      var detail = rowOf(disclose).querySelector('.imp-detail');
      var open = disclose.getAttribute('aria-expanded') === 'true';
      if (detail) { detail.hidden = open; }
      disclose.setAttribute('aria-expanded', open ? 'false' : 'true');
      return;
    }
    var chip = event.target.closest('[data-imp-chip]');
    if (chip) {
      var key = chip.getAttribute('data-imp-chip');
      var on = chip.getAttribute('aria-pressed') !== 'true';
      chip.setAttribute('aria-pressed', on ? 'true' : 'false');
      if (on) { activeChips[key] = true; } else { delete activeChips[key]; }
      applyFilter();
      return;
    }
    var bulk = event.target.closest('[data-imp-select]');
    if (bulk) {
      var want = bulk.getAttribute('data-imp-select') === 'all';
      $all('[data-imp-row]').forEach(function (row) {
        var box = rowBox(row);
        if (row.hidden || !box || box.disabled || box.checked === want) { return; }
        box.checked = want;
        box.dispatchEvent(new Event('change', { bubbles: true }));
      });
    }
  });

  form.addEventListener('input', function (event) {
    if (event.target.matches('[data-imp-search]')) { applyFilter(); }
  });

  form.addEventListener('change', function (event) {
    var t = event.target;
    if (t.name === 'mode') { applyMode(); return; }
    if (t.matches('[data-imp-field]') && t.checked) {
      // Ticking a field means the operator wants the row.
      var box = rowBox(rowOf(t));
      if (box && !box.checked) { box.checked = true; if (S.groups) { S.groups.refreshAll(form); } }
    }
    if (t.matches('[data-imp-target]') && t.value) {
      var rb = rowBox(rowOf(t));
      if (rb && !rb.checked) { rb.checked = true; if (S.groups) { S.groups.refreshAll(form); } }
    }
    updateCounts();
  });

  // A changed stream mapping rebuilds the plan: submit it at once.
  document.addEventListener('change', function (event) {
    var sel = event.target.closest && event.target.closest('[data-imp-map]');
    if (sel && sel.form) { sel.form.requestSubmit(); }
  });

  applyMode();
  if (S.groups) { S.groups.refreshAll(form); }
})();
