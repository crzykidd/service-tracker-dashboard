/* ============================================================
   Service Tracker Dashboard — shared JavaScript
   Covers: auto-refresh, group-collapse, view-controls,
   filter-input, tiled tile-click, tile drawers, tools popover,
   dashboard group-toggle, clipboard copy.
   ============================================================ */

(function () {
  'use strict';

  /* ── Auto-refresh ─────────────────────────────────────── */
  let secondsSinceRefresh = 0;
  let refreshInterval = 60;

  function initRefresh() {
    const refreshLabel    = document.getElementById('refreshTimer');
    const refreshDropdown = document.getElementById('refreshInterval');
    const saved = localStorage.getItem('refreshInterval');
    if (saved !== null) {
      refreshInterval = parseInt(saved, 10);
      if (refreshDropdown) refreshDropdown.value = saved;
    }
    if (refreshDropdown) {
      refreshDropdown.addEventListener('change', function () {
        refreshInterval = parseInt(this.value, 10);
        localStorage.setItem('refreshInterval', this.value);
      });
    }
    setInterval(() => {
      secondsSinceRefresh++;
      if (refreshLabel) {
        const m = Math.floor(secondsSinceRefresh / 60);
        const s = secondsSinceRefresh % 60;
        refreshLabel.textContent = `Refreshed ${m > 0 ? m + 'm ' : ''}${s}s ago`;
      }
      if (refreshInterval > 0 && secondsSinceRefresh >= refreshInterval) {
        window.location.reload();
      }
    }, 1000);
  }

  /* ── View-control submit-on-change ───────────────────── */
  function initViewControls() {
    document.querySelectorAll('.view-control').forEach(function (el) {
      el.addEventListener('change', function () {
        const params = new URLSearchParams(window.location.search);
        const key = this.dataset.param;
        const value = (this.type === 'checkbox') ? (this.checked ? 'true' : 'false') : this.value;
        params.set(key, value);
        window.location.search = params.toString();
      });
    });
  }

  /* ── Tiled: group-collapse persistence ───────────────── */
  function initTiledGroupCollapse() {
    document.querySelectorAll('.group-header').forEach(header => {
      const groupName  = header.dataset.group;
      const container  = document.querySelector(`[data-group-container="${groupName}"]`);
      const icon       = header.querySelector('.toggle-icon');
      if (!container) return;
      const isCollapsed = localStorage.getItem(`groupCollapse:${groupName}`) === 'true';
      if (isCollapsed) {
        container.style.display = 'none';
        if (icon) icon.textContent = '▸';
      }
      header.addEventListener('click', () => {
        const collapsed = container.style.display === 'none';
        container.style.display = collapsed ? '' : 'none';
        if (icon) icon.textContent = collapsed ? '▾' : '▸';
        localStorage.setItem(`groupCollapse:${groupName}`, (!collapsed).toString());
      });
    });
  }

  /* ── Dashboard: group-collapse persistence ───────────── */
  function initDashboardGroupCollapse() {
    document.querySelectorAll('[id^="toggle-icon-"]').forEach(iconEl => {
      const groupId = iconEl.id.replace('toggle-icon-', '');
      const isCollapsed = localStorage.getItem(`group-collapsed-${groupId}`) === 'true';
      const entries = document.querySelectorAll(`tr.group-entry[data-group-id='${groupId}']`);
      entries.forEach(row => row.style.display = isCollapsed ? 'none' : '');
      iconEl.textContent = isCollapsed ? '▶' : '▼';
    });
  }

  /* ── Filter input (unified, view-detected) ───────────── */
  function initFilter() {
    const filterInput = document.getElementById('filterInput');
    if (!filterInput) return;

    const view = document.body.dataset.view;

    filterInput.addEventListener('input', function () {
      const filter = this.value.toLowerCase();

      if (view === 'dashboard') {
        document.querySelectorAll('table tbody tr[data-entry]').forEach(row => {
          const group  = (row.dataset.group  || '').toLowerCase();
          const name   = (row.dataset.container || '').toLowerCase();
          const stack  = (row.dataset.stack  || '').toLowerCase();
          row.style.display =
            (group.includes(filter) || name.includes(filter) || stack.includes(filter)) ? '' : 'none';
        });

      } else if (view === 'compact') {
        document.querySelectorAll('.compact-tile:not(.group-header)').forEach(tile => {
          const name   = (tile.querySelector('.container-name')?.textContent || '').toLowerCase();
          const host   = (tile.querySelector('.host-name')?.textContent      || '').toLowerCase();
          const prev   = tile.previousElementSibling;
          const grpTxt = (prev && prev.classList.contains('group-header'))
                         ? prev.textContent.toLowerCase() : '';
          tile.style.display = (name.includes(filter) || host.includes(filter) || grpTxt.includes(filter)) ? '' : 'none';
        });

      } else {
        // tiled (default)
        document.querySelectorAll('.tile-wrapper').forEach(wrapper => {
          const name   = (wrapper.querySelector('.container-name')?.textContent || '').toLowerCase();
          const grpCon = wrapper.closest('[data-group-container]');
          const grpTxt = grpCon?.previousElementSibling?.textContent?.toLowerCase() || '';
          wrapper.style.display = (name.includes(filter) || grpTxt.includes(filter)) ? '' : 'none';
        });
      }
    });
  }

  /* ── Tiled: tile-body click → open URL ───────────────── */
  function initTileClick() {
    document.querySelectorAll('.tile').forEach(tile => {
      const internalUrl = tile.dataset.internalurl;
      const externalUrl = tile.dataset.externalurl;
      if (!internalUrl && !externalUrl) return;
      tile.style.cursor = 'pointer';
      tile.addEventListener('click', function (event) {
        // Don't fire if clicking an interactive child
        if (event.target.closest('a, button')) return;
        window.open(internalUrl || externalUrl, '_blank');
      });
    });
  }

  /* ── Tiled: expand drawer ────────────────────────────── */
  let currentOpenDrawer = null;
  let currentOpenTile   = null;

  function closeCurrentDrawer() {
    if (currentOpenDrawer) {
      currentOpenDrawer.classList.remove('drawer-open');
      currentOpenTile.classList.remove('tile-open');
      const chevron = currentOpenTile.querySelector('.tile-chevron');
      if (chevron) {
        chevron.querySelector('i').className = 'ti ti-chevron-down';
        chevron.setAttribute('aria-expanded', 'false');
      }
      currentOpenDrawer = null;
      currentOpenTile   = null;
    }
  }

  function initDrawers() {
    document.querySelectorAll('.tile-chevron').forEach(btn => {
      btn.addEventListener('click', function (e) {
        e.stopPropagation();
        const wrapper = this.closest('.tile-wrapper');
        const tile    = wrapper.querySelector('.tile');
        const drawerId = this.dataset.drawer;
        const drawer  = document.getElementById(drawerId);
        if (!drawer) return;

        if (currentOpenDrawer === drawer) {
          closeCurrentDrawer();
          return;
        }
        closeCurrentDrawer();

        drawer.classList.add('drawer-open');
        tile.classList.add('tile-open');
        this.querySelector('i').className = 'ti ti-chevron-up';
        this.setAttribute('aria-expanded', 'true');
        currentOpenDrawer = drawer;
        currentOpenTile   = tile;
      });
    });

    // Close on outside click
    document.addEventListener('click', function (e) {
      if (!currentOpenDrawer) return;
      if (!e.target.closest('.tile-wrapper')) closeCurrentDrawer();
    });
  }

  /* ── Tiled drawer: tools popover ────────────────────── */
  function initToolsPopovers() {
    document.querySelectorAll('.drawer-btn-tools').forEach(btn => {
      btn.addEventListener('click', function (e) {
        e.stopPropagation();
        const wrap    = this.closest('.drawer-tools-wrap');
        const dropdown = wrap.querySelector('.tools-dropdown');
        if (!dropdown) return;
        const isOpen  = dropdown.classList.contains('dropdown-open');
        // Close all other open dropdowns
        document.querySelectorAll('.tools-dropdown.dropdown-open').forEach(d => d.classList.remove('dropdown-open'));
        if (!isOpen) dropdown.classList.add('dropdown-open');
      });
    });

    document.addEventListener('click', function (e) {
      if (!e.target.closest('.drawer-tools-wrap')) {
        document.querySelectorAll('.tools-dropdown.dropdown-open').forEach(d => d.classList.remove('dropdown-open'));
      }
    });
  }

  /* ── Tiled drawer: delete action ────────────────────── */
  function initDrawerDelete() {
    document.querySelectorAll('.drawer-btn-delete').forEach(btn => {
      btn.addEventListener('click', function (e) {
        e.stopPropagation();
        const entryId       = this.dataset.entryId;
        const containerName = this.dataset.containerName;
        const isStatic      = this.dataset.isStatic === 'true';

        let confirmed = false;
        if (isStatic) {
          const typed = prompt(
            `STATIC ENTRY: Type the container name to confirm deletion.\n\n` +
            `Container: "${containerName}"\n\nThis cannot be undone.`
          );
          confirmed = (typed === containerName);
        } else {
          confirmed = confirm(`Delete "${containerName}"? This cannot be undone.`);
        }

        if (!confirmed) return;

        const form = document.createElement('form');
        form.method = 'POST';
        form.action = `/edit/${entryId}`;

        const addField = (name, value) => {
          const input = document.createElement('input');
          input.type  = 'hidden';
          input.name  = name;
          input.value = value;
          form.appendChild(input);
        };
        addField('delete', '1');
        addField('delete_confirmation', containerName);

        document.body.appendChild(form);
        form.submit();
      });
    });
  }

  /* ── Dashboard: toggleGroup ──────────────────────────── */
  window.toggleGroup = function (groupId) {
    const entries = document.querySelectorAll(`tr.group-entry[data-group-id='${groupId}']`);
    const icon    = document.getElementById(`toggle-icon-${groupId}`);
    const isCollapsed = localStorage.getItem(`group-collapsed-${groupId}`) === 'true';
    const newState = !isCollapsed;
    entries.forEach(row => row.style.display = newState ? 'none' : '');
    if (icon) icon.textContent = newState ? '▶' : '▼';
    localStorage.setItem(`group-collapsed-${groupId}`, newState);
  };

  /* ── Dashboard: clipboard copy ───────────────────────── */
  window.copyToClipboard = function (text, el) {
    navigator.clipboard.writeText(text).then(() => {
      const original = el.innerHTML;
      el.innerHTML = '<em>Copied!</em>';
      setTimeout(() => { el.innerHTML = original; }, 1000);
    });
  };

  /* ── Bootstrap ───────────────────────────────────────── */
  document.addEventListener('DOMContentLoaded', function () {
    initRefresh();
    initViewControls();
    initFilter();

    const view = document.body.dataset.view;
    if (view === 'tiled') {
      initTiledGroupCollapse();
      initTileClick();
      initDrawers();
      initToolsPopovers();
      initDrawerDelete();
    } else if (view === 'dashboard') {
      initDashboardGroupCollapse();
    }
    // compact has no extra init beyond refresh/filter/view-controls
  });

})();
