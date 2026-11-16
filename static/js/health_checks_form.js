// Add/Edit page: repeatable service-check rows (clone a <template>) and
// HTTP-only field visibility. Removed rows simply leave the form; the server
// deletes saved checks that are missing from the submission.
(function () {
  function syncRow(row) {
    var select = row.querySelector('[data-check-type]');
    var isHttp = !select || select.value === 'http';
    row.querySelectorAll('[data-http-only]').forEach(function (el) {
      el.classList.toggle('hidden', !isHttp);
    });
  }

  function syncEmpty(list) {
    var empty = document.getElementById('service-checks-empty');
    if (empty) empty.classList.toggle('hidden', list.querySelector('[data-check-row]') !== null);
  }

  document.addEventListener('DOMContentLoaded', function () {
    var list = document.getElementById('service-checks');
    var tpl = document.getElementById('service-check-template');
    var addBtn = document.getElementById('add-service-check');
    if (!list || !tpl || !addBtn) return;

    var counter = 0;
    list.querySelectorAll('input[name="svc_row"]').forEach(function (el) {
      var m = /^n(\d+)$/.exec(el.value);
      if (m) counter = Math.max(counter, parseInt(m[1], 10));
    });
    list.querySelectorAll('[data-check-row]').forEach(syncRow);

    addBtn.addEventListener('click', function () {
      counter += 1;
      var html = tpl.innerHTML.split('__KEY__').join('n' + counter);
      var holder = document.createElement('div');
      holder.innerHTML = html.trim();
      var row = holder.firstElementChild;
      list.appendChild(row);
      syncRow(row);
      syncEmpty(list);
      var first = row.querySelector('input[type="text"]');
      if (first) first.focus();
    });

    list.addEventListener('click', function (ev) {
      var btn = ev.target.closest('[data-remove-check]');
      if (!btn) return;
      var row = btn.closest('[data-check-row]');
      if (row) row.remove();
      syncEmpty(list);
    });

    list.addEventListener('change', function (ev) {
      if (ev.target.matches('[data-check-type]')) syncRow(ev.target.closest('[data-check-row]'));
    });
  });
})();
