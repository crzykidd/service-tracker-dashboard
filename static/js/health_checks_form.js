// Add/Edit page: repeatable service-check rows (clone a <template>) and
// per-type field visibility (HTTP-only, DNS-only). Removed rows simply leave the form; the server
// deletes saved checks that are missing from the submission.
(function () {
  // "Min cert days" only applies to an https:// target: the entry's URL input
  // for a URL check, the row's own target for an HTTP service check.
  function syncCert(scope) {
    scope.querySelectorAll('[data-cert-field]').forEach(function (field) {
      var source = document.getElementById(field.getAttribute('data-cert-source'));
      var row = field.closest('[data-check-row]');
      var select = row && row.querySelector('[data-check-type]');
      var isHttp = !select || select.value === 'http';
      var https = !!source && /^https:\/\//i.test(source.value.trim());
      field.classList.toggle('hidden', !(isHttp && https));
    });
  }

  function syncRow(row) {
    var select = row.querySelector('[data-check-type]');
    var isHttp = !select || select.value === 'http';
    var isDns = !!select && select.value === 'dns';
    row.querySelectorAll('[data-http-only]').forEach(function (el) {
      el.classList.toggle('hidden', !isHttp);
    });
    row.querySelectorAll('[data-dns-only]').forEach(function (el) {
      el.classList.toggle('hidden', !isDns);
    });
    row.querySelectorAll('[data-not-dns]').forEach(function (el) {
      el.classList.toggle('hidden', isDns);
    });
    var label = row.querySelector('[data-target-label]');
    if (label) label.textContent = isDns ? 'DNS server' : 'Target';
    var target = row.querySelector('[data-target-placeholder]');
    if (target) {
      target.placeholder = isDns ? target.getAttribute('data-dns-placeholder')
                                 : target.getAttribute('data-target-placeholder');
    }
    syncCert(row);
  }

  function syncEmpty(list) {
    var empty = document.getElementById('service-checks-empty');
    if (empty) empty.classList.toggle('hidden', list.querySelector('[data-check-row]') !== null);
  }

  document.addEventListener('DOMContentLoaded', function () {
    syncCert(document);
    document.addEventListener('input', function (ev) {
      if (ev.target.matches('input[type="text"], input[type="url"]')) syncCert(document);
    });
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
