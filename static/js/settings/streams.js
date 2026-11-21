/*
 * Settings -> Streams (design 9.8): the Edit stream dialog opener, the shared
 * Disable… / Delete… dialog (one per stream, the mode picks route, wording and the
 * "clear blocks" box) and Purge MQTT/HA. Everything is delegated from the document.
 * No Jinja here: URLs and names come from data-* attributes on the buttons / dialogs.
 */
(function () {
  'use strict';

  var ui = (window.STDSettings || {}).ui || {};
  var csrf = function () { return (document.querySelector('meta[name="csrf-token"]') || {}).content || ''; };

  /* ------------------------------------------------------------ Edit stream */

  document.addEventListener('click', function (event) {
    var btn = event.target.closest('[data-stream-edit]');
    if (!btn) { return; }
    var dlg = document.getElementById(btn.getAttribute('data-stream-edit'));
    if (dlg && ui.openModal) { ui.openModal(dlg, btn); }
  });

  // Discarding a dirty Edit dialog puts every block back to what the server rendered.
  document.addEventListener('std:modal-discard', function (event) {
    var dlg = event.target;
    if (!dlg || !dlg.id || dlg.id.indexOf('stream-edit-') !== 0) { return; }
    dlg.querySelectorAll('form').forEach(function (f) { f.reset(); });
  });

  /* ------------------------------------------------------ Disable… / Delete… */

  function sync(dlg) {
    var purge = dlg.querySelector('input[name=cleanup][value=purge]').checked;
    dlg.querySelector('.stream-clear-blocks').classList.toggle('hidden', !(dlg.dataset.mode === 'disable' && purge));
  }

  document.addEventListener('click', function (event) {
    var btn = event.target.closest('.stream-dialog-open');
    if (!btn) { return; }
    var dlg = document.getElementById(btn.dataset.dialog);
    if (!dlg) { return; }
    var disable = btn.dataset.mode === 'disable';
    dlg.dataset.mode = btn.dataset.mode;
    dlg.querySelector('form').action = disable ? dlg.dataset.disableAction : dlg.dataset.deleteAction;
    dlg.querySelector('.stream-dialog-title').textContent = disable ? 'Disable' : 'Delete';
    dlg.querySelector('.stream-dialog-submit').textContent = disable ? 'Disable stream' : 'Delete stream';
    dlg.querySelector('.stream-keep-delete').classList.toggle('hidden', disable);
    dlg.querySelector('.stream-keep-disable').classList.toggle('hidden', !disable);
    dlg.querySelector('.stream-delete-note').classList.toggle('hidden', disable);
    dlg.querySelector('.stream-disable-note').classList.toggle('hidden', !disable);
    sync(dlg);
    if (ui.openModal) { ui.openModal(dlg, btn); } else { dlg.showModal(); }
  });

  document.addEventListener('change', function (event) {
    if (!event.target.matches || !event.target.matches('.stream-dialog input[name=cleanup]')) { return; }
    sync(event.target.closest('.stream-dialog'));
  });

  /* --------------------------------------------------------- Purge MQTT/HA */

  // Per stream (PRD 17.5): one publisher job for every entry of the stream.
  document.addEventListener('click', async function (event) {
    var btn = event.target.closest('.stream-notify-purge');
    if (!btn) { return; }
    var ok = await ui.confirm({
      title: 'Purge MQTT/HA',
      body: 'Purge the MQTT topics and Home Assistant devices of every entry of "' + btn.dataset.name +
            '" and publish what is still eligible? Home Assistant will recreate their devices.',
      confirmLabel: 'Purge',
      danger: true
    });
    if (!ok) { return; }
    var row = btn.closest('[data-stream-row]');
    var out = row && row.querySelector('.stream-notify-result');
    if (!out) { return; }
    btn.disabled = true;
    out.textContent = 'Purging... (up to 15 seconds)';
    try {
      var resp = await fetch(btn.dataset.url, {
        method: 'POST', credentials: 'same-origin', headers: { 'X-CSRFToken': csrf() }
      });
      var data = await resp.json();
      out.textContent = data.ok
        ? 'Cleared ' + data.topics_cleared + ' topics for ' + data.entries + ' entr' + (data.entries === 1 ? 'y' : 'ies') +
          ' on ' + data.channels.length + ' channel(s); republished what is still eligible.'
        : 'Purge failed: ' + data.message;
    } catch (err) {
      out.textContent = 'Purge failed: could not reach STD (' + err + ').';
    } finally {
      btn.disabled = false;
    }
  });
})();
