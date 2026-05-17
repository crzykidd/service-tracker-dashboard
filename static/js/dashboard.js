/* ============================================================
   Service Tracker Dashboard — shared JavaScript
   Covers: auto-refresh, group-collapse, view-controls,
   filter-input, tiled tile-click, tile drawers, tools popover,
   dashboard group-toggle, clipboard copy, delete popover,
   widget modal, refresh-pause while interacting.
   ============================================================ */

(function () {
  'use strict';

  /* ── Auto-refresh ─────────────────────────────────────── */
  let secondsSinceRefresh = 0;
  let refreshInterval = 60;

  function isInteracting() {
    if (currentOpenDrawer) return true;
    const widgetModal    = document.getElementById('widget-modal');
    const changelogModal = document.getElementById('changelog-modal');
    const deletePopover  = document.getElementById('delete-popover');
    if (widgetModal    && !widgetModal.classList.contains('hidden'))    return true;
    if (changelogModal && !changelogModal.classList.contains('hidden')) return true;
    if (deletePopover  && !deletePopover.classList.contains('hidden'))  return true;
    return false;
  }

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
      if (isInteracting()) {
        if (refreshLabel) refreshLabel.textContent = 'Refresh paused (drawer open)';
        return;
      }
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
      // Reset refresh timer so next cycle starts fresh
      secondsSinceRefresh = 0;
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

        if (window.innerWidth < 768) {
          wrapper.scrollIntoView({ behavior: 'smooth', block: 'start' });
        }
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

  /* ── Delete popover ──────────────────────────────────── */
  let _deleteOutsideHandler = null;
  let _deleteEscHandler     = null;

  function hideDeletePopover() {
    const pop = document.getElementById('delete-popover');
    if (!pop) return;
    pop.classList.add('hidden');
    if (_deleteOutsideHandler) {
      document.removeEventListener('click', _deleteOutsideHandler, true);
      _deleteOutsideHandler = null;
    }
    if (_deleteEscHandler) {
      document.removeEventListener('keydown', _deleteEscHandler);
      _deleteEscHandler = null;
    }
  }

  function showDeletePopover(triggerEl, containerName, onConfirm) {
    hideDeletePopover();

    const pop = document.getElementById('delete-popover');
    if (!pop) return;

    pop.querySelector('.delete-popover-target').textContent = containerName;
    pop.classList.remove('hidden');

    // Position: fixed, relative to viewport
    const rect = triggerEl.getBoundingClientRect();
    const popW = Math.min(280, window.innerWidth - 32);
    pop.style.maxWidth = popW + 'px';
    pop.style.width    = 'auto';

    // Default below; shift above if not enough room
    const popH = pop.offsetHeight;
    let top  = rect.bottom + 4;
    if (top + popH > window.innerHeight - 8) top = rect.top - popH - 4;
    if (top < 8) top = 8;

    // Align left edge with trigger, shift left if it clips right edge
    let left = rect.left;
    if (left + popW > window.innerWidth - 8) left = window.innerWidth - popW - 8;
    if (left < 8) left = 8;

    pop.style.top  = top  + 'px';
    pop.style.left = left + 'px';

    // Wire buttons (clone to drop any previous listeners)
    const oldConfirm = pop.querySelector('.delete-popover-confirm');
    const oldCancel  = pop.querySelector('.delete-popover-cancel');
    const newConfirm = oldConfirm.cloneNode(true);
    const newCancel  = oldCancel.cloneNode(true);
    oldConfirm.replaceWith(newConfirm);
    oldCancel.replaceWith(newCancel);

    newConfirm.addEventListener('click', () => { hideDeletePopover(); onConfirm(); });
    newCancel.addEventListener('click',  hideDeletePopover);

    // Click-outside (capture phase so it fires before other handlers)
    setTimeout(() => {
      _deleteOutsideHandler = function (e) {
        if (!pop.contains(e.target) && e.target !== triggerEl) hideDeletePopover();
      };
      document.addEventListener('click', _deleteOutsideHandler, true);
    }, 0);

    _deleteEscHandler = function (e) { if (e.key === 'Escape') hideDeletePopover(); };
    document.addEventListener('keydown', _deleteEscHandler);
  }

  /* Shared fetch-delete helper used by tile, drawer, and dashboard row. */
  function fetchDelete(entryId, onSuccess, onError) {
    fetch(`/api/v1/entries/${entryId}/delete`, { method: 'POST' })
      .then(r => r.ok ? onSuccess() : onError())
      .catch(onError);
  }

  /* ── Tiled drawer: delete action ────────────────────── */
  function initDrawerDelete() {
    document.querySelectorAll('.drawer-btn-delete').forEach(btn => {
      btn.addEventListener('click', function (e) {
        e.stopPropagation();
        const entryId       = this.dataset.entryId;
        const containerName = this.dataset.containerName;
        showDeletePopover(this, containerName, () => {
          fetchDelete(entryId, () => {
            // Remove the tile-wrapper from the DOM
            const drawer  = document.getElementById(`drawer-${entryId}`);
            const wrapper = drawer ? drawer.closest('.tile-wrapper') : null;
            if (wrapper) wrapper.remove();
            closeCurrentDrawer();
          }, () => alert('Delete failed. Please try again.'));
        });
      });
    });
  }

  /* ── Tiled: trash icon on tile ───────────────────────── */
  function initTileTrash() {
    document.querySelectorAll('.tile-trash-btn').forEach(btn => {
      btn.addEventListener('click', function (e) {
        e.stopPropagation();
        const entryId       = this.dataset.entryId;
        const containerName = this.dataset.containerName;
        showDeletePopover(this, containerName, () => {
          fetchDelete(entryId, () => {
            const wrapper = this.closest('.tile-wrapper');
            if (wrapper) wrapper.remove();
          }, () => alert('Delete failed. Please try again.'));
        });
      });
    });
  }

  /* ── Dashboard: trash icon on row ────────────────────── */
  function initDashboardTrash() {
    document.querySelectorAll('.row-trash-btn').forEach(btn => {
      btn.addEventListener('click', function (e) {
        e.stopPropagation();
        const entryId       = this.dataset.entryId;
        const containerName = this.dataset.containerName;
        showDeletePopover(this, containerName, () => {
          fetchDelete(entryId, () => {
            const row = this.closest('tr');
            if (row) row.remove();
          }, () => alert('Delete failed. Please try again.'));
        });
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

  /* ── Filter bar mobile collapse ─────────────────────── */
  function initFilterBarMobile() {
    const toggle = document.getElementById('filterBarToggle');
    const panel  = document.getElementById('filterBarPanel');
    if (!toggle || !panel) return;

    function setOpen(open) {
      toggle.setAttribute('aria-expanded', open ? 'true' : 'false');
      toggle.classList.toggle('is-open', open);
      panel.classList.toggle('fb-panel-open', open);
    }

    toggle.addEventListener('click', function (e) {
      e.stopPropagation();
      setOpen(!panel.classList.contains('fb-panel-open'));
    });

    document.addEventListener('click', function (e) {
      if (!panel.classList.contains('fb-panel-open')) return;
      if (!e.target.closest('#filterBarToggle') && !e.target.closest('#filterBarPanel')) {
        setOpen(false);
      }
    });

    document.addEventListener('keydown', function (e) {
      if (e.key === 'Escape' && panel.classList.contains('fb-panel-open')) {
        setOpen(false);
      }
    });
  }

  /* ── Widget modal ────────────────────────────────────── */
  function initWidgetModal() {
    const modal    = document.getElementById('widget-modal');
    const content  = document.getElementById('widget-modal-content');
    const titleEl  = modal ? modal.querySelector('.widget-modal-title') : null;
    const closeBtn = modal ? modal.querySelector('.widget-modal-close') : null;
    const backdrop = modal ? modal.querySelector('.widget-modal-backdrop') : null;
    if (!modal) return;

    function showWidgetModal(containerName, widgetGrid) {
      titleEl.textContent = containerName;
      content.innerHTML = '';
      if (widgetGrid && widgetGrid.children.length > 0) {
        content.appendChild(widgetGrid.cloneNode(true));
      } else {
        const msg = document.createElement('p');
        msg.className = 'widget-modal-no-data';
        msg.textContent = 'No widget data available yet.';
        content.appendChild(msg);
      }
      modal.classList.remove('hidden');
      document.addEventListener('keydown', onModalEsc);
    }

    function hideWidgetModal() {
      modal.classList.add('hidden');
      secondsSinceRefresh = 0;
      document.removeEventListener('keydown', onModalEsc);
    }

    function onModalEsc(e) { if (e.key === 'Escape') hideWidgetModal(); }

    if (closeBtn) closeBtn.addEventListener('click', hideWidgetModal);
    if (backdrop) backdrop.addEventListener('click', hideWidgetModal);

    document.querySelectorAll('.tile-widget-btn').forEach(btn => {
      btn.addEventListener('click', function (e) {
        e.stopPropagation();
        const wrapper = this.closest('.tile-wrapper');
        if (!wrapper) return;
        const containerName = (wrapper.querySelector('.container-name')?.textContent || '').trim();
        const widgetGrid = wrapper.querySelector('.drawer-widget-grid');
        showWidgetModal(containerName, widgetGrid);
      });
    });
  }

  /* ── Changelog "What's new" modal ───────────────────── */
  function initChangelogModal() {
    const modal   = document.getElementById('changelog-modal');
    if (!modal) return;

    const currentVersion = document.body.dataset.stdVersion || '';
    if (!currentVersion || currentVersion === 'unknown') return;

    const STORAGE_KEY = 'std:lastSeenVersion';
    const lastSeen    = localStorage.getItem(STORAGE_KEY);

    function showModal(sections) {
      if (!sections || sections.length === 0) return;

      const body = document.getElementById('changelog-content');
      body.innerHTML = sections.map(s => `
        <div class="changelog-version-block">
          <p class="changelog-version-header">v${s.version} — ${s.date}</p>
          ${s.html}
        </div>
      `).join('');

      modal.classList.remove('hidden');
      document.addEventListener('keydown', onEsc);
    }

    function dismiss() {
      localStorage.setItem(STORAGE_KEY, currentVersion);
      modal.classList.add('hidden');
      secondsSinceRefresh = 0;
      document.removeEventListener('keydown', onEsc);
    }

    function onEsc(e) {
      if (e.key === 'Escape') dismiss();
    }

    modal.querySelector('.changelog-modal-close').addEventListener('click', dismiss);
    modal.querySelector('.changelog-modal-dismiss').addEventListener('click', dismiss);
    modal.querySelector('.changelog-modal-backdrop').addEventListener('click', dismiss);

    if (lastSeen === null) {
      fetch('/api/v1/changelog')
        .then(r => r.json())
        .then(data => showModal(data.sections))
        .catch(() => {});
    } else if (lastSeen === currentVersion) {
      // No change — don't pop.
    } else {
      fetch(`/api/v1/changelog?since=${encodeURIComponent(lastSeen)}`)
        .then(r => r.json())
        .then(data => {
          if (!data.sections || data.sections.length === 0) {
            localStorage.setItem(STORAGE_KEY, currentVersion);
          } else {
            showModal(data.sections);
          }
        })
        .catch(() => {});
    }
  }

  /* Expose popover API for pages with inline script (e.g. edit_entry.html) */
  window.showDeletePopover = showDeletePopover;

  /* ── Bootstrap ───────────────────────────────────────── */
  document.addEventListener('DOMContentLoaded', function () {
    initRefresh();
    initViewControls();
    initFilter();
    initFilterBarMobile();
    initChangelogModal();

    const view = document.body.dataset.view;
    if (view === 'tiled') {
      initTiledGroupCollapse();
      initTileClick();
      initDrawers();
      initToolsPopovers();
      initDrawerDelete();
      initTileTrash();
      initWidgetModal();
    } else if (view === 'dashboard') {
      initDashboardGroupCollapse();
      initDashboardTrash();
    }
    // compact has no extra init beyond refresh/filter/view-controls
  });

})();
