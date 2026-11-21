/* Settings -> Groups: column sorting and the delete toggle (the delete happens on Save). */
(function () {
  'use strict';
  var S = window.STDSettings = window.STDSettings || {};

  function sortTable(columnIndex) {
    var table = document.getElementById('group-table');
    if (!table) { return; }
    var tbody = table.querySelector('tbody');
    var rows = Array.from(tbody.querySelectorAll('tr:not([data-no-sort])'));
    var ascending = table.getAttribute('data-sort-dir') !== 'asc';
    table.setAttribute('data-sort-dir', ascending ? 'asc' : 'desc');

    rows.sort(function (a, b) {
      var aCell = a.children[columnIndex];
      var bCell = b.children[columnIndex];
      var aInput = aCell.querySelector('input[type=text], input[type=number]');
      var bInput = bCell.querySelector('input[type=text], input[type=number]');
      var aValue = aInput ? aInput.value : aCell.innerText.trim();
      var bValue = bInput ? bInput.value : bCell.innerText.trim();
      var isNumeric = !isNaN(aValue) && aValue.trim() !== '' && !isNaN(bValue);
      if (isNumeric) {
        aValue = parseFloat(aValue);
        bValue = parseFloat(bValue);
      }
      return (aValue < bValue ? -1 : aValue > bValue ? 1 : 0) * (ascending ? 1 : -1);
    });

    var newRow = tbody.querySelector('tr[data-no-sort]');
    rows.forEach(function (row) { tbody.insertBefore(row, newRow); });
  }

  document.addEventListener('click', function (event) {
    var btn = event.target.closest('[data-group-delete-toggle]');
    if (!btn) { return; }
    var row = btn.closest('tr');
    var flag = row.querySelector('input[type=hidden][name$="-delete"]');
    var marked = flag.value !== '1';
    flag.value = marked ? '1' : '0';
    row.classList.toggle('opacity-50', marked);
    row.classList.toggle('line-through', marked);
    btn.textContent = marked ? 'Undo' : 'Delete';
    flag.form.dispatchEvent(new Event('change', { bubbles: true }));
  });

  S.groups = Object.assign(S.groups || {}, { sortTable: sortTable });
  window.sortTable = sortTable;
})();
