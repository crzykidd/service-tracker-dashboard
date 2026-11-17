/*
 * Unsaved-changes guard. No dependencies.
 *
 * Mark a form with `data-unsaved-guard`. The guard snapshots the form's values
 * on load and treats the form as dirty while its current values differ from
 * that snapshot (so typing a value and reverting it is clean again). While
 * dirty:
 *   - a `beforeunload` handler asks the browser to confirm leaving;
 *   - elements inside the form with `data-unsaved-save` get a highlight ring and
 *     elements with `data-unsaved-hint` are shown.
 * Submitting the form, or clicking an element with `data-unsaved-discard`,
 * disarms the guard so the navigation it causes is not prompted.
 *
 * `data-unsaved-start-dirty` starts the form dirty regardless of the snapshot
 * (a page re-rendered after a failed save already holds unsaved input).
 * Scripts that change a value programmatically should dispatch a bubbling
 * `change` event on the form so the guard re-checks.
 */
(function () {
  'use strict';

  var HIGHLIGHT = ['ring-2', 'ring-yellow-400'];

  function serialize(form) {
    var pairs = [];
    new FormData(form).forEach(function (value, key) {
      if (key === 'csrf_token') { return; }
      pairs.push(key + '=' + (typeof value === 'string' ? value : value.name));
    });
    // Order-independent: re-sorting a table must not look like an edit.
    return pairs.sort().join('\n');
  }

  function init(form) {
    if (form._unsavedGuard) { return form._unsavedGuard; }
    var baseline = serialize(form);
    var startDirty = form.hasAttribute('data-unsaved-start-dirty');
    var armed = true;
    var dirty = false;

    function isDirty() {
      return armed && (startDirty || serialize(form) !== baseline);
    }

    function refresh() {
      dirty = isDirty();
      form.setAttribute('data-unsaved-dirty', dirty ? 'true' : 'false');
      form.querySelectorAll('[data-unsaved-save]').forEach(function (el) {
        HIGHLIGHT.forEach(function (c) { el.classList.toggle(c, dirty); });
      });
      form.querySelectorAll('[data-unsaved-hint]').forEach(function (el) {
        el.classList.toggle('hidden', !dirty);
      });
    }

    function onBeforeUnload(event) {
      if (!isDirty()) { return undefined; }
      event.preventDefault();
      event.returnValue = '';  // browsers show their own generic text
      return '';
    }

    function disarm() {
      armed = false;
      refresh();
    }

    form.addEventListener('input', refresh);
    form.addEventListener('change', refresh);
    form.addEventListener('submit', disarm);
    form.querySelectorAll('[data-unsaved-discard]').forEach(function (el) {
      el.addEventListener('click', disarm);
    });
    window.addEventListener('beforeunload', onBeforeUnload);
    // Back/forward cache restores the page with the guard disarmed otherwise.
    window.addEventListener('pageshow', function (event) {
      if (event.persisted) { armed = true; refresh(); }
    });

    refresh();
    form._unsavedGuard = { isDirty: isDirty, disarm: disarm, refresh: refresh };
    return form._unsavedGuard;
  }

  function initAll() {
    document.querySelectorAll('form[data-unsaved-guard]').forEach(init);
  }

  window.UnsavedGuard = { init: init, initAll: initAll };
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', initAll);
  } else {
    initAll();
  }
})();
