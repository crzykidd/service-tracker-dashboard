// Ports page: remember the view (grouped/flat and the flat sort) in this browser, and apply
// the filters as soon as a dropdown or the checkbox changes. The page still works without
// JS (the Apply button is only hidden when this script runs).
(function () {
  const VIEW_KEY = 'ports:view';
  const SORT_KEY = 'ports:sort';

  function read(key) {
    try { return localStorage.getItem(key); } catch (e) { return null; }
  }
  function write(key, value) {
    try { localStorage.setItem(key, value); } catch (e) { /* storage blocked: nothing to remember */ }
  }

  // Runs before the tables render (the script is not deferred): a URL with no `view`
  // (the nav tab, Reset) gets the remembered view instead of the default.
  const params = new URLSearchParams(window.location.search);
  if (!params.has('view')) {
    const savedView = read(VIEW_KEY);
    if (savedView === 'flat') {
      params.set('view', 'flat');
      const savedSort = read(SORT_KEY);
      if (savedSort && !params.has('sort')) params.set('sort', savedSort);
      window.location.replace(window.location.pathname + '?' + params.toString());
      return;
    }
  } else {
    write(VIEW_KEY, params.get('view') === 'flat' ? 'flat' : 'grouped');
    if (params.get('view') === 'flat' && params.get('sort')) write(SORT_KEY, params.get('sort'));
  }

  document.addEventListener('DOMContentLoaded', function () {
    const form = document.getElementById('ports-filters');
    if (!form) return;
    const apply = form.querySelector('button[type="submit"]');
    if (apply) apply.classList.add('hidden');

    form.querySelectorAll('select, input[type="checkbox"]').forEach(function (el) {
      el.addEventListener('change', function () {
        if (el.name === 'view') write(VIEW_KEY, el.value);
        if (el.name === 'sort') write(SORT_KEY, el.value);
        form.submit();
      });
    });
    // The search box submits on Enter (native form behavior) and when it loses focus
    // after an edit.
    const search = form.querySelector('input[name="q"]');
    if (search) search.addEventListener('change', function () { form.submit(); });
  });
})();
