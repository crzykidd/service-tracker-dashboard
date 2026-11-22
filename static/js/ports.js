// Ports page: remember the whole page state (view, sort, kind, host, search, conflicts only)
// in this browser, and apply the filters as soon as a dropdown or the checkbox changes.
// The page still works without JS (the Apply button is only hidden when this script runs).
(function () {
  const STATE_KEY = 'ports:state';

  function read() {
    try { return localStorage.getItem(STATE_KEY); } catch (e) { return null; }
  }
  function write(value) {
    try {
      if (value) localStorage.setItem(STATE_KEY, value); else localStorage.removeItem(STATE_KEY);
    } catch (e) { /* storage blocked: nothing to remember */ }
  }

  // Runs before the tables render (the script is not deferred). A bare `/ports` (the nav
  // tab) opens the remembered state; a URL with parameters is the new state to remember.
  const search = window.location.search.replace(/^\?/, '');
  if (!search) {
    const saved = read();
    if (saved) {
      window.location.replace(window.location.pathname + '?' + saved);
      return;
    }
  } else {
    write(search);
  }

  document.addEventListener('DOMContentLoaded', function () {
    const form = document.getElementById('ports-filters');
    if (!form) return;
    const apply = form.querySelector('button[type="submit"]');
    if (apply) apply.classList.add('hidden');

    form.querySelectorAll('select, input[type="checkbox"]').forEach(function (el) {
      el.addEventListener('change', function () { form.submit(); });
    });
    // The search box submits on Enter (native form behavior) and when it loses focus
    // after an edit.
    const q = form.querySelector('input[name="q"]');
    if (q) q.addEventListener('change', function () { form.submit(); });

    // Reset forgets the remembered state, then loads the defaults.
    const reset = document.getElementById('ports-reset');
    if (reset) reset.addEventListener('click', function () { write(null); });
  });
})();
