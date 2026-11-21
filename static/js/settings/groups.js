/*
 * Settings -> Groups (design 9.3): the staging dialog and the delete toggle.
 *
 * Every group's values live in hidden inputs inside the one #groups-form (so Save stays
 * all-or-nothing). The Edit dialog (#group-modal, inside that form) has unnamed inputs:
 * Apply copies them into the card's hidden inputs and redraws the card, then tells the
 * unsaved guard with a `change` on the form. Nothing is sent until the save bar's Save.
 * "Add group" stages into the new-name / new-icon / new-priority inputs (one new group
 * per save, as the route allows); once staged the button reads "Edit new group".
 * A re-render after a failed save puts data-group-id on the dialog; it is filled from
 * that card (with its error text) and opened by nav.js.
 */
(function () {
  'use strict';

  var ui = (window.STDSettings || {}).ui || {};
  var dlg = document.getElementById('group-modal');
  var form = document.getElementById('groups-form');
  if (!dlg || !form) { return; }

  var nameIn = document.getElementById('group-modal-name');
  var iconIn = document.getElementById('group-modal-icon');
  var prioIn = document.getElementById('group-modal-priority');
  var errBox = document.getElementById('group-modal-errors');
  var title = document.getElementById('group-modal-title');
  var addBtn = document.querySelector('[data-group-add]');
  var current = null;   // 'new' or a group id (string) while the dialog is filled

  function rowOf(id) { return form.querySelector('[data-group-row="' + id + '"]'); }
  function hidden(row, suffix, isNew) {
    var key = isNew ? 'new-' + suffix : 'group-' + row.getAttribute('data-group-row') + '-' + suffix;
    return row.querySelector('input[type=hidden][name="' + key + '"]');
  }
  function changed() { form.dispatchEvent(new Event('change', { bubbles: true })); }

  function redraw(row, isNew) {
    var name = hidden(row, 'name', isNew).value;
    var icon = hidden(row, 'icon', isNew).value;
    var prio = hidden(row, 'priority', isNew).value;
    row.querySelector('[data-group-name-text]').textContent = name;
    row.querySelector('[data-group-icon-text]').textContent = icon;
    row.querySelector('[data-group-priority-text]').textContent = prio !== '' ? 'Priority ' + prio : 'No priority';
  }

  function refreshAdd() {
    var row = rowOf('new');
    var staged = !!(row && hidden(row, 'name', true).value);
    if (row) { row.hidden = !staged; }
    if (addBtn) { addBtn.textContent = staged ? 'Edit new group' : '+ Add group'; }
    var empty = document.getElementById('group-empty');
    if (empty) { empty.hidden = staged || form.querySelectorAll('[data-group-row]:not([data-group-row="new"])').length > 0; }
  }

  function show(errors) {
    errBox.textContent = errors.join(' ');
    errBox.hidden = errors.length === 0;
    nameIn.setAttribute('aria-invalid', errors.length ? 'true' : 'false');
  }

  function fill(id) {
    var isNew = id === 'new';
    var row = rowOf(id);
    if (!row) { return false; }
    current = id;
    nameIn.value = hidden(row, 'name', isNew).value;
    iconIn.value = hidden(row, 'icon', isNew).value;
    prioIn.value = hidden(row, 'priority', isNew).value;
    var staged = isNew && nameIn.value !== '';
    title.textContent = isNew ? (staged ? 'Edit new group' : 'Add group') : 'Edit group';
    var errors = Array.prototype.map.call(row.querySelectorAll('[data-group-error]'), function (e) { return e.textContent.trim(); });
    show(errors);
    return true;
  }

  function open(id, opener) {
    if (fill(id) && ui.openModal) { ui.openModal(dlg, opener); }
  }

  function apply() {
    var name = nameIn.value.trim();
    if (!name) { show(['A name is required.']); nameIn.focus(); return; }
    var isNew = current === 'new';
    var row = rowOf(current);
    if (!row) { return; }
    hidden(row, 'name', isNew).value = name;
    hidden(row, 'icon', isNew).value = iconIn.value.trim();
    hidden(row, 'priority', isNew).value = prioIn.value.trim();
    row.querySelectorAll('[data-group-error]').forEach(function (e) { e.remove(); });
    redraw(row, isNew);
    refreshAdd();
    changed();
    dlg.close();
  }

  document.addEventListener('click', function (event) {
    var edit = event.target.closest('[data-group-edit]');
    if (edit) { open(edit.getAttribute('data-group-edit'), edit); return; }
    var add = event.target.closest('[data-group-add]');
    if (add) { open('new', add); return; }
    if (event.target.closest('[data-group-apply]')) { apply(); return; }

    var discard = event.target.closest('[data-group-new-discard]');
    if (discard) {
      var nrow = rowOf('new');
      ['name', 'icon', 'priority'].forEach(function (s) { hidden(nrow, s, true).value = ''; });
      nrow.querySelectorAll('[data-group-error]').forEach(function (e) { e.remove(); });
      refreshAdd();
      changed();
      return;
    }

    // Delete / Undo: the delete happens on Save, so there is no confirm.
    var toggle = event.target.closest('[data-group-delete-toggle]');
    if (!toggle) { return; }
    var row = toggle.closest('[data-group-row]');
    var flag = row.querySelector('input[type=hidden][name$="-delete"]');
    var marked = flag.value !== '1';
    flag.value = marked ? '1' : '0';
    row.classList.toggle('opacity-50', marked);
    row.querySelector('[data-group-name-text]').classList.toggle('line-through', marked);
    row.querySelector('[data-group-deleted-tag]').hidden = !marked;
    row.querySelector('[data-group-undo]').hidden = !marked;
    row.querySelectorAll('[data-group-live]').forEach(function (el) { el.hidden = marked; });
    changed();
  });

  // Enter in the dialog applies it (there is no <form> to submit).
  dlg.addEventListener('keydown', function (event) {
    if (event.key === 'Enter' && event.target.tagName === 'INPUT') {
      event.preventDefault();
      apply();
    }
  });

  refreshAdd();

  // Re-render after a failed save: nav.js opens the dialog; fill it from the named row.
  var preset = dlg.getAttribute('data-group-id');
  if (preset && fill(preset)) {
    if (nameIn.focus) { nameIn.focus(); }
  }
})();
