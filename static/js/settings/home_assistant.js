/*
 * Settings -> Home Assistant (design 9.7): search across the grouped entries, Select all /
 * none on the visible rows, and the "changed" marker. Group collapse, the tri-state
 * checkbox and the live count come from ui.js (STDSettings.groups); the Save bar and
 * Discard come from the unsaved guard.
 */
(function () {
  'use strict';

  var form = document.getElementById('ha-entries-form');
  var filter = document.getElementById('ha-filter');
  if (!form || !filter) { return; }

  var groups = (window.STDSettings || {}).groups || {};
  var groupEls = Array.prototype.slice.call(form.querySelectorAll('.settings-group'));
  var rows = Array.prototype.slice.call(form.querySelectorAll('[data-ha-row]'));
  var noMatch = document.getElementById('ha-no-match');
  var before = null;  // collapse state to restore when the search is cleared

  function boxOf(row) { return row.querySelector('input[type=checkbox]'); }

  function setChecked(box, on) {
    if (box.checked === on) { return; }
    box.checked = on;
    box.dispatchEvent(new Event('change', { bubbles: true }));
  }

  document.getElementById('ha-select-all').addEventListener('click', function () {
    rows.forEach(function (r) { if (!r.hidden) { setChecked(boxOf(r), true); } });
  });
  document.getElementById('ha-select-none').addEventListener('click', function () {
    rows.forEach(function (r) { if (!r.hidden) { setChecked(boxOf(r), false); } });
  });

  function applySearch() {
    var q = filter.value.trim().toLowerCase();
    if (q === '') {
      rows.forEach(function (r) { r.hidden = false; });
      groupEls.forEach(function (g, i) {
        g.hidden = false;
        if (before) { groups.setCollapsed(g, before[i]); }
      });
      before = null;
      if (noMatch) { noMatch.hidden = true; }
      groups.refreshAll(form);
      return;
    }
    if (!before) {
      before = groupEls.map(function (g) { return g.getAttribute('data-collapsed') === 'true'; });
    }
    var any = false;
    groupEls.forEach(function (g) {
      var first = g.querySelector('[data-ha-source]');
      var label = first ? first.getAttribute('data-ha-source').toLowerCase() : '';
      var labelHit = label.indexOf(q) !== -1;
      var hits = 0;
      g.querySelectorAll('[data-ha-row]').forEach(function (r) {
        var text = (r.querySelector('.name').textContent + ' ' + r.querySelector('.host').textContent + ' ' +
          r.querySelector('[data-ha-group]').textContent).toLowerCase();
        r.hidden = !(labelHit || text.indexOf(q) !== -1);
        if (!r.hidden) { hits++; }
      });
      g.hidden = hits === 0;
      if (hits) { groups.setCollapsed(g, false); any = true; }
    });
    if (noMatch) { noMatch.hidden = any; }
    groups.refreshAll(form);
  }
  filter.addEventListener('input', applySearch);

  // "• changed" on rows that differ from what is saved; also after a Discard (reset -> change).
  function markChanged() {
    rows.forEach(function (r) {
      var box = boxOf(r);
      if (box.checked !== box.defaultChecked) { r.setAttribute('data-changed', ''); }
      else { r.removeAttribute('data-changed'); }
    });
  }
  form.addEventListener('change', markChanged);
})();
