/*
 * Settings navigation: which section is showing (design 5.3).
 *
 * The server renders every section but hides all except the one it knows about, and
 * puts `data-initial-section` / `data-open-modal` on #settings-root. This script then:
 *   1. picks the section (data-initial-section > URL hash, aliases resolved > default),
 *      shows it and syncs the sidebar (aria-current) and the mobile select;
 *   2. canonicalises the URL with replaceState to <settings path>?<query minus section>#slug
 *      (so a reload after a failed save or a created key is a plain GET, and a legacy
 *      ?section=info link becomes #about);
 *   3. opens the dialog named by data-open-modal;
 *   4. follows `hashchange` and the select's `change`.
 * Sections never have an id equal to a bare slug (they are `section-<slug>`), so a hash
 * never scrolls the page.
 */
(function () {
  'use strict';

  var root = document.getElementById('settings-root');
  if (!root) { return; }

  var S = window.STDSettings = window.STDSettings || {};

  var aliases = {};
  try { aliases = JSON.parse(root.getAttribute('data-section-aliases') || '{}'); } catch (e) { aliases = {}; }
  var fallback = root.getAttribute('data-default-section') || 'about';
  var settingsUrl = root.getAttribute('data-settings-url') || '/settings';

  var sections = Array.prototype.slice.call(root.querySelectorAll('.settings-section'));
  var slugs = sections.map(function (el) { return el.id.replace(/^section-/, ''); });
  var links = Array.prototype.slice.call(root.querySelectorAll('.settings-nav-link[data-section]'));
  var select = document.getElementById('settings-nav-select');

  function resolve(raw) {
    if (!raw) { return null; }
    var value = String(raw).replace(/^#/, '').trim().toLowerCase();
    if (slugs.indexOf(value) !== -1) { return value; }
    if (Object.prototype.hasOwnProperty.call(aliases, value)) { return aliases[value]; }
    return null;
  }

  function show(slug) {
    sections.forEach(function (el) {
      el.classList.toggle('hidden', el.id !== 'section-' + slug);
    });
    links.forEach(function (a) {
      if (a.getAttribute('data-section') === slug) { a.setAttribute('aria-current', 'page'); }
      else { a.removeAttribute('aria-current'); }
    });
    if (select && select.value !== slug) { select.value = slug; }
    S.currentSection = slug;
  }

  function canonicalUrl(slug) {
    var path = new URL(settingsUrl, window.location.href).pathname;
    var query = '';
    if (window.location.pathname === path) {
      var params = new URLSearchParams(window.location.search);
      params.delete('section');
      query = params.toString();
    }
    return path + (query ? '?' + query : '') + '#' + slug;
  }

  function init() {
    var slug = resolve(root.getAttribute('data-initial-section')) || resolve(window.location.hash) || fallback;
    show(slug);
    try { window.history.replaceState(window.history.state, '', canonicalUrl(slug)); } catch (e) { /* ignore */ }

    var modalId = root.getAttribute('data-open-modal');
    if (modalId) {
      var dlg = document.getElementById(modalId);
      if (dlg && S.ui && S.ui.openModal) { S.ui.openModal(dlg); }
    }
  }

  // Closing the stream Preview dialog drops ?preview= so a reload shows plain Settings.
  document.addEventListener('close', function (event) {
    if (!event.target || event.target.id !== 'stream-preview-modal') { return; }
    try {
      var params = new URLSearchParams(window.location.search);
      if (!params.has('preview')) { return; }
      params.delete('preview');
      var query = params.toString();
      window.history.replaceState(window.history.state, '',
        window.location.pathname + (query ? '?' + query : '') + window.location.hash);
    } catch (e) { /* ignore */ }
  }, true);

  window.addEventListener('hashchange', function () {
    var slug = resolve(window.location.hash);
    if (slug) { show(slug); }
  });
  if (select) {
    select.addEventListener('change', function () { window.location.hash = select.value; });
  }

  // Old callers: showSection('notifications').
  S.showSection = function (raw) {
    var slug = resolve(raw);
    if (!slug) { return; }
    show(slug);
    try { window.history.replaceState(window.history.state, '', canonicalUrl(slug)); } catch (e) { /* ignore */ }
  };
  window.showSection = S.showSection;
  S.nav = { resolve: resolve, show: show };

  init();
})();
