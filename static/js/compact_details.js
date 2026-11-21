/* ============================================================
   Compact view details dialog (PRD 13.7). The expand button on a
   tile fetches GET /service/<id>/details (an HTML fragment rendered
   by our own escaped template) into one shared <dialog>, then starts
   the health detail through health_detail.js. Delete reuses the
   shared delete popover; the dialog closes first because the popover
   would otherwise sit under the dialog's top layer.
   ============================================================ */
(function () {
  'use strict';

  let dlg = null;
  let content = null;
  let trigger = null;
  let seq = 0;

  function note(text) {
    const d = document.createElement('div');
    d.className = 'p-4 text-gray-400';
    d.textContent = text;
    return d;
  }

  function open(btn) {
    trigger = btn;
    const id = btn.dataset.compactExpand;
    const mine = ++seq;
    content.replaceChildren(note('Loading…'));
    if (!dlg.open) dlg.showModal();
    fetch('/service/' + encodeURIComponent(id) + '/details', { credentials: 'same-origin' })
      .then(function (r) {
        if (!r.ok) throw new Error(String(r.status));
        return r.text();
      })
      .then(function (html) {
        if (mine !== seq || !dlg.open) return;
        content.innerHTML = html;           // our own server-rendered, escaped fragment
        const edit = content.querySelector('[data-compact-edit]');
        if (edit) {
          const u = new URL(edit.getAttribute('href'), window.location.origin);
          u.searchParams.set('ref', window.location.pathname + window.location.search);
          edit.setAttribute('href', u.pathname + u.search);
        }
        if (window.stdHealthDetail) window.stdHealthDetail.open(content);
      })
      .catch(function () {
        if (mine !== seq) return;
        const err = note('Could not load the details. It may have been deleted.');
        const close = document.createElement('button');
        close.type = 'button';
        close.className = 'drawer-btn mt-2';
        close.textContent = 'Close';
        close.setAttribute('data-modal-close', '');
        err.appendChild(document.createElement('br'));
        err.appendChild(close);
        content.replaceChildren(err);
      });
  }

  function onDelete(btn) {
    const deleteUrl = btn.dataset.deleteUrl;
    const name = btn.dataset.containerName;
    const stream = btn.dataset.stream === '1';
    const anchor = trigger;
    dlg.close();
    if (!anchor || !window.showDeletePopover) return;
    window.showDeletePopover(anchor, name, function (block) {
      const opts = block ? {
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ block: true })
      } : {};
      window.stdPost(deleteUrl, opts)
        .then(function (r) {
          if (!r.ok) throw new Error();
          const tile = anchor.closest('.compact-tile');
          if (tile) tile.remove();
        })
        .catch(function () { alert('Delete failed. Please try again.'); });
    }, { stream: stream });
  }

  document.addEventListener('DOMContentLoaded', function () {
    dlg = document.getElementById('compact-details');
    if (!dlg) return;
    content = document.getElementById('compact-details-content');

    document.addEventListener('click', function (e) {
      const t = e.target;
      if (!t.closest) return;
      const exp = t.closest('[data-compact-expand]');
      if (exp) { e.stopPropagation(); open(exp); return; }
      if (!dlg.contains(t) && t !== dlg) return;
      if (t.closest('[data-modal-close]')) { dlg.close(); return; }
      const del = t.closest('[data-compact-delete]');
      if (del) { onDelete(del); return; }
      if (t === dlg) dlg.close();            // backdrop click
    });

    dlg.addEventListener('close', function () {
      seq++;
      content.replaceChildren();
      if (trigger && document.contains(trigger)) trigger.focus();
    });
  });
})();
