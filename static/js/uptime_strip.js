/* ============================================================
   "Show uptime" toggle + inline 24h strips (PRD 13.7). The checkbox is
   remembered in the std_show_uptime cookie ('1' / '0'); the server renders
   it checked and puts `show-uptime` on <body> from that cookie. Strip
   containers (.uptime-strip[data-uptime-id]) are always in the markup and
   only filled, in ONE request, while the toggle is on. Auto-refresh reloads
   the page, so a reload re-fetches only while it is on. Bars reuse the
   detail panel's .hbar markup and tooltip (health_detail.js).
   ============================================================ */
(function () {
  'use strict';

  const COOKIE = 'std_show_uptime';
  const CHUNK = 500; // server cap on ids per request

  function setCookie(on) {
    document.cookie = COOKIE + '=' + (on ? '1' : '0') +
      '; Path=/; SameSite=Lax; Max-Age=' + 31536000;
  }

  function el(tag, cls, text) {
    const n = document.createElement(tag);
    if (cls) n.className = cls;
    if (text !== undefined && text !== null) n.textContent = text;
    return n;
  }

  function fmtUptime(v) {
    return v === null || v === undefined ? 'n/a' : v.toFixed(v === 100 ? 0 : 1) + '%';
  }

  function fmtTime(iso) {
    return new Date(iso).toLocaleString([], {
      month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit'
    });
  }

  function render(box, data) {
    box.textContent = '';
    const compact = box.classList.contains('uptime-strip-compact');
    if (!data || !data.bars.length) {
      if (!compact) box.appendChild(el('span', 'uptime-pct uptime-pct-none', '—'));
      return;
    }
    const strip = el('div', 'health-bars health-bars-24h');
    data.bars.forEach(function (b) {
      const bar = el('div', 'hbar hbar-' + (b.fail ? 'fail' : (b.ok ? 'ok' : 'none')));
      bar._bucket = b;
      bar.setAttribute('aria-label',
        fmtTime(b.start) + ': ' + (b.ok || b.fail ? b.ok + ' ok, ' + b.fail + ' failed' : 'no samples'));
      strip.appendChild(bar);
    });
    box.appendChild(strip);
    if (!compact) {
      const pct = el('span', 'uptime-pct' + (data.uptime === null ? ' uptime-pct-none' : ''),
        fmtUptime(data.uptime));
      pct.title = 'Uptime over the last 24 hours';
      box.appendChild(pct);
    }
  }

  function fetchStrips() {
    const boxes = Array.prototype.slice.call(document.querySelectorAll('.uptime-strip[data-uptime-id]'));
    const byId = {};
    boxes.forEach(function (b) { (byId[b.dataset.uptimeId] = byId[b.dataset.uptimeId] || []).push(b); });
    const ids = Object.keys(byId);
    for (let i = 0; i < ids.length; i += CHUNK) {
      const part = ids.slice(i, i + CHUNK);
      fetch('/health/strips?ids=' + part.join(','), {
        headers: { 'Accept': 'application/json' }, credentials: 'same-origin'
      }).then(function (r) {
        if (!r.ok) throw new Error('HTTP ' + r.status);
        return r.json();
      }).then(function (data) {
        part.forEach(function (id) {
          byId[id].forEach(function (box) { render(box, data[id]); });
        });
      }).catch(function () { /* strips are optional; leave them empty */ });
    }
  }

  document.addEventListener('DOMContentLoaded', function () {
    const toggle = document.getElementById('showUptimeToggle');
    if (document.body.classList.contains('show-uptime')) fetchStrips();
    if (!toggle) return;
    toggle.addEventListener('change', function () {
      setCookie(toggle.checked);
      document.body.classList.toggle('show-uptime', toggle.checked);
      if (toggle.checked) fetchStrips();
    });
  });
})();
