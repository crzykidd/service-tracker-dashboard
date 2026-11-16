/* ============================================================
   Health detail panel (PRD 13.7): per-check state, uptime, recent
   failures and a Gatus-style 24h / 7d bar strip. Markup shell is
   partials/health_detail.html; data comes from
   GET /service/<id>/health?range=24h|7d. Plain DOM, no libraries.
   ============================================================ */
(function () {
  'use strict';

  const TYPE_LABELS = { http: 'HTTP', tcp: 'TCP', ping: 'Ping' };
  const STATE_LABELS = { up: 'Up', down: 'Down', unknown: 'Not run yet' };
  const CHECK_NOW_DELAY_MS = 7000; // scheduler tick (5 s) + probe time

  function el(tag, cls, text) {
    const n = document.createElement(tag);
    if (cls) n.className = cls;
    if (text !== undefined && text !== null) n.textContent = text;
    return n;
  }

  function fmtTime(iso) {
    if (!iso) return 'never';
    return new Date(iso).toLocaleString([], {
      month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit'
    });
  }

  function fmtClock(iso) {
    return new Date(iso).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
  }

  function ago(iso) {
    if (!iso) return 'never';
    const s = Math.max(0, Math.round((Date.now() - new Date(iso).getTime()) / 1000));
    if (s < 60) return s + 's ago';
    if (s < 3600) return Math.round(s / 60) + 'm ago';
    if (s < 86400) return Math.round(s / 3600) + 'h ago';
    return Math.round(s / 86400) + 'd ago';
  }

  function fmtUptime(v) {
    return v === null || v === undefined ? 'n/a' : v.toFixed(v === 100 ? 0 : 1) + '%';
  }

  /* ── Tooltip (shared; hover on desktop, tap on touch) ──── */
  let tip = null;
  let tipBar = null;

  function ensureTip() {
    if (!tip) {
      tip = el('div', 'health-tooltip');
      tip.setAttribute('role', 'tooltip');
      tip.hidden = true;
      document.body.appendChild(tip);
    }
    return tip;
  }

  function hideTip() {
    if (tip) tip.hidden = true;
    tipBar = null;
  }

  function showTip(bar) {
    const t = ensureTip();
    const d = bar._bucket;
    t.textContent = '';
    const day = new Date(d.start).toLocaleDateString([], { month: 'short', day: 'numeric' });
    t.appendChild(el('div', 'health-tooltip-time', day + ' ' + fmtClock(d.start) + ' – ' + fmtClock(d.end)));
    if (!d.ok && !d.fail) {
      t.appendChild(el('div', 'health-tooltip-line', 'No samples'));
    } else {
      t.appendChild(el('div', 'health-tooltip-line',
        d.ok + ' ok' + (d.fail ? ', ' + d.fail + ' failed' : '')));
    }
    d.messages.forEach(function (m) { t.appendChild(el('div', 'health-tooltip-msg', m)); });
    t.hidden = false;
    const r = bar.getBoundingClientRect();
    const tw = t.offsetWidth;
    const left = Math.min(Math.max(8, r.left + r.width / 2 - tw / 2 + window.scrollX),
                          window.scrollX + document.documentElement.clientWidth - tw - 8);
    t.style.left = left + 'px';
    t.style.top = (r.top + window.scrollY - t.offsetHeight - 8) + 'px';
    tipBar = bar;
  }

  document.addEventListener('mouseover', function (e) {
    const bar = e.target.closest && e.target.closest('.hbar');
    if (bar && bar._bucket) showTip(bar); else if (tipBar) hideTip();
  });
  document.addEventListener('click', function (e) {
    const bar = e.target.closest && e.target.closest('.hbar');
    if (bar && bar._bucket) { showTip(bar); } else if (tipBar) { hideTip(); }
  });
  document.addEventListener('scroll', hideTip, true);

  /* ── Rendering ─────────────────────────────────────────── */
  function renderCheck(c, range) {
    const box = el('div', 'health-check');
    box.dataset.state = c.state;

    const head = el('div', 'health-check-head');
    head.appendChild(el('span', 'health-dotmark health-' + c.state));
    head.appendChild(el('span', 'health-check-name', c.name));
    head.appendChild(el('span', 'health-check-type', TYPE_LABELS[c.check_type] || c.check_type));
    head.appendChild(el('span', 'health-check-state health-text-' + c.state, STATE_LABELS[c.state] || c.state));
    box.appendChild(head);

    if (c.target) box.appendChild(el('div', 'health-check-target', c.target));

    const meta = el('div', 'health-check-meta');
    const bits = ['Checked ' + ago(c.last_checked_at)];
    if (c.latency_ms !== null && c.latency_ms !== undefined) bits.push(c.latency_ms + ' ms');
    if (c.status_code) bits.push('status ' + c.status_code);
    bits.push('Uptime 24h ' + fmtUptime(c.uptime_24h) + ' · 7d ' + fmtUptime(c.uptime_7d));
    meta.textContent = bits.join(' · ');
    box.appendChild(meta);
    if (c.state === 'down' && c.message) box.appendChild(el('div', 'health-check-msg', c.message));

    const strip = el('div', 'health-bars health-bars-' + range);
    c.bars.forEach(function (b) {
      const state = b.fail ? 'fail' : (b.ok ? 'ok' : 'none');
      const bar = el('div', 'hbar hbar-' + state);
      bar._bucket = b;
      bar.setAttribute('aria-label',
        fmtTime(b.start) + ': ' + (b.ok || b.fail ? b.ok + ' ok, ' + b.fail + ' failed' : 'no samples'));
      strip.appendChild(bar);
    });
    box.appendChild(strip);
    const axis = el('div', 'health-axis');
    axis.appendChild(el('span', null, range === '7d' ? '7 days ago' : '24 hours ago'));
    axis.appendChild(el('span', null, 'now'));
    box.appendChild(axis);

    if (c.failures.length) {
      const det = el('details', 'health-failures');
      det.appendChild(el('summary', null, 'Recent failures (' + c.failures.length + ')'));
      const ul = el('ul');
      c.failures.forEach(function (f) {
        const li = el('li');
        li.appendChild(el('span', 'health-fail-time', fmtTime(f.ts)));
        li.appendChild(document.createTextNode(' ' + (f.message || (f.status_code ? 'status ' + f.status_code : 'failed'))));
        ul.appendChild(li);
      });
      det.appendChild(ul);
      box.appendChild(det);
    }
    return box;
  }

  function render(root, data) {
    const body = root.querySelector('[data-health-body]');
    body.textContent = '';
    if (!data.checks.length) {
      body.appendChild(el('div', 'health-detail-note', 'No health checks are enabled for this service.'));
      return;
    }
    data.checks.forEach(function (c) { body.appendChild(renderCheck(c, data.range)); });
  }

  function load(root) {
    const range = root.dataset.range || '24h';
    root.dataset.loaded = '1';
    return fetch(root.dataset.url + '?range=' + encodeURIComponent(range), {
      headers: { 'Accept': 'application/json' }, credentials: 'same-origin'
    }).then(function (r) {
      if (!r.ok) throw new Error('HTTP ' + r.status);
      return r.json();
    }).then(function (data) {
      render(root, data);
    }).catch(function (err) {
      root.dataset.loaded = '';
      const body = root.querySelector('[data-health-body]');
      body.textContent = '';
      body.appendChild(el('div', 'health-detail-note health-detail-error',
        'Could not load health history (' + err.message + ').'));
    });
  }

  function ensureLoaded(root) {
    if (!root.dataset.loaded) load(root);
  }

  /* ── Controls ──────────────────────────────────────────── */
  document.addEventListener('click', function (e) {
    const rangeBtn = e.target.closest && e.target.closest('.health-range-btn');
    if (rangeBtn) {
      const root = rangeBtn.closest('[data-health-detail]');
      root.dataset.range = rangeBtn.dataset.range;
      root.querySelectorAll('.health-range-btn').forEach(function (b) {
        b.classList.toggle('active', b === rangeBtn);
      });
      load(root);
      return;
    }
    const now = e.target.closest && e.target.closest('[data-check-now]');
    if (now) {
      const root = now.closest('[data-health-detail]');
      now.disabled = true;
      const label = now.innerHTML;
      now.textContent = 'Queued…';
      window.stdPost(root.dataset.checkUrl).then(function (r) {
        if (!r.ok) throw new Error('HTTP ' + r.status);
        return r.json();
      }).then(function (res) {
        now.textContent = res.queued ? 'Checking…' : 'Nothing to check';
        setTimeout(function () {
          load(root).then(function () { now.disabled = false; now.innerHTML = label; });
        }, res.queued ? CHECK_NOW_DELAY_MS : 0);
      }).catch(function () {
        now.textContent = 'Failed';
        setTimeout(function () { now.disabled = false; now.innerHTML = label; }, 2000);
      });
      return;
    }
    const exp = e.target.closest && e.target.closest('[data-health-expand]');
    if (exp) {
      const row = document.getElementById('health-row-' + exp.dataset.healthExpand);
      if (!row) return;
      const open = row.hasAttribute('hidden');
      row.toggleAttribute('hidden', !open);
      exp.setAttribute('aria-expanded', open ? 'true' : 'false');
      exp.classList.toggle('open', open);
      if (open) row.querySelectorAll('[data-health-detail]').forEach(ensureLoaded);
    }
  });

  window.stdHealthDetail = {
    open: function (container) {
      container.querySelectorAll('[data-health-detail]').forEach(ensureLoaded);
    }
  };

  document.addEventListener('DOMContentLoaded', function () {
    document.querySelectorAll('[data-health-detail][data-autoload]').forEach(ensureLoaded);
  });
})();
