/*
 * Settings -> Notifications (design 9.6): the card list, the Add/Edit channel dialog,
 * Send test, the remove / purge / orphan dialogs and the 5 s status poll.
 * Data: <script type="application/json" id="notification-channels-data"> (the secret is
 * never in it, only `secret_set`); URLs: data-* on #section-notifications.
 */
(function () {
  'use strict';

  var section = document.getElementById('section-notifications');
  var form = document.getElementById('notification-form');
  if (!section || !form) { return; }

  var channels = [];
  try { channels = JSON.parse(document.getElementById('notification-channels-data').textContent || '[]'); }
  catch (e) { channels = []; }

  var ui = (window.STDSettings || {}).ui || {};
  var modal = document.getElementById('channel-modal');
  var $ = function (id) { return document.getElementById(id); };
  var csrf = function () { return (document.querySelector('meta[name="csrf-token"]') || {}).content || ''; };
  var byId = function (id) { return channels.find(function (c) { return String(c.id) === String(id); }); };
  var DOT = { connected: 'ok', connecting: 'warn', error: 'bad' };

  /* ------------------------------------------------------------ channel dialog */

  function clearInvalid() {
    form.querySelectorAll('[aria-invalid]').forEach(function (el) { el.removeAttribute('aria-invalid'); });
    modal.querySelectorAll('[data-flash-slot]').forEach(function (el) { el.remove(); });
  }

  function syncHaFields() {
    $('nf-ha-fields').classList.toggle('is-dimmed', !$('nf-ha-discovery').checked);
  }

  function passwordHint(ch) {
    var set = !!(ch && ch.secret_set);
    $('nf-password-state').textContent = set ? '(set; leave blank to keep)' : '';
    $('nf-clear-row').hidden = !set;
  }

  function fill(ch) {
    var c = ch ? ch.config : {};
    clearInvalid();
    $('nf-channel-id').value = ch ? ch.id : '';
    $('channel-modal-title').textContent = ch ? 'Edit MQTT channel' : 'Add MQTT channel';
    $('nf-name').value = ch ? ch.name : '';
    $('nf-enabled').checked = ch ? ch.enabled : false;
    $('nf-host').value = c.host || '';
    $('nf-port').value = c.port || '';
    $('nf-tls').checked = !!c.tls;
    $('nf-tls-insecure').checked = !!c.tls_insecure;
    $('nf-username').value = c.username || '';
    $('nf-password').value = '';
    $('nf-clear-password').checked = false;
    $('nf-client-id').value = c.client_id || '';
    $('nf-base-topic').value = c.base_topic || 'std';
    $('nf-qos').value = String(c.qos === undefined ? 1 : c.qos);
    $('nf-keepalive').value = c.keepalive || 60;
    $('nf-ha-discovery').checked = !!c.ha_discovery;
    $('nf-ha-prefix').value = c.ha_prefix || 'homeassistant';
    $('nf-ha-device-prefix').value = c.ha_device_prefix || 'STD';
    passwordHint(ch);
    $('nf-test-result').textContent = '';
    $('nf-cleanup-old-base').checked = true;
    modal.querySelector('details.std-modal-advanced').open = false;
    syncHaFields();
    updateCleanupRow();
    // A freshly filled dialog is clean: take a new baseline (and drop start-dirty).
    if (form._unsavedGuard) { form._unsavedGuard.reset(); }
  }

  // "Remove the old topics from the broker" (PRD 17.5): shown while editing a saved
  // channel whose base topic (or, with discovery on, discovery / device prefix) differs
  // from what is stored; checked by default.
  function updateCleanupRow() {
    var row = $('nf-cleanup-row');
    var ch = byId($('nf-channel-id').value);
    if (!ch) { row.hidden = true; return; }
    var c = ch.config;
    var baseChanged = $('nf-base-topic').value.trim().replace(/\/+$/, '') !== c.base_topic;
    var haChanged = !!c.ha_discovery && (
      ($('nf-ha-prefix').value.trim() || 'homeassistant') !== c.ha_prefix ||
      ($('nf-ha-device-prefix').value.trim() || 'STD') !== c.ha_device_prefix);
    row.hidden = !(baseChanged || haChanged);
    $('nf-cleanup-note').textContent = baseChanged
      ? "Clears every retained topic under '" + c.base_topic + "/' (including its status) and this install's " +
        'discovery configs from the broker, then switches. The old base is remembered for the orphan scan.'
      : "Clears this install's Home Assistant discovery configs under '" + c.ha_prefix +
        "/' so Home Assistant drops the old devices; the new ones are published after the save.";
  }
  form.addEventListener('input', updateCleanupRow);
  form.addEventListener('change', function () { updateCleanupRow(); syncHaFields(); });

  function openChannelDialog(ch, opener) {
    fill(ch);
    if (ui.openModal) { ui.openModal(modal, opener); } else { modal.showModal(); }
  }

  document.addEventListener('click', function (event) {
    var edit = event.target.closest('[data-notification-edit]');
    if (edit) {
      var ch = byId(edit.dataset.notificationEdit);
      if (ch) { openChannelDialog(ch, edit); }
      return;
    }
    var add = event.target.closest('[data-notification-add]');
    if (add) { openChannelDialog(null, add); }
  });

  // After a failed save the server re-rendered the dialog with what was typed:
  // keep it (start-dirty), just show the password hint.
  if ($('nf-channel-id').value) { passwordHint(byId($('nf-channel-id').value)); }
  syncHaFields();
  updateCleanupRow();

  /* --------------------------------------------------------------- Send test */

  function showResult(out, ok, text) {
    out.classList.remove('text-green-400', 'text-red-400', 'text-gray-300');
    out.classList.add(ok === null ? 'text-gray-300' : (ok ? 'text-green-400' : 'text-red-400'));
    out.textContent = text;
  }

  $('nf-test').addEventListener('click', async function () {
    var out = $('nf-test-result');
    var btn = $('nf-test');
    showResult(out, null, 'Sending...');
    btn.disabled = true;
    try {
      var resp = await fetch(section.dataset.testUrl, {
        method: 'POST', headers: { 'X-CSRFToken': csrf() }, body: new FormData(form),
      });
      var data = await resp.json();
      showResult(out, !!data.ok, (data.ok ? 'Success: ' : 'Failed: ') + data.message);
    } catch (err) {
      showResult(out, false, 'Failed: could not reach STD (' + err + ').');
    } finally {
      btn.disabled = false;
    }
  });

  // Card "Send test": the saved config with a blank password (the route then uses the stored one).
  document.addEventListener('click', async function (event) {
    var item = event.target.closest('[data-notification-test]');
    if (!item) { return; }
    var ch = byId(item.dataset.notificationTest);
    var card = item.closest('[data-channel-id]');
    if (!ch || !card) { return; }
    var out = card.querySelector('.notification-purge-result');
    var c = ch.config;
    var body = new FormData();
    body.append('channel_id', ch.id);
    body.append('password', '');
    ['host', 'port', 'username', 'client_id', 'base_topic', 'qos', 'keepalive', 'ha_prefix', 'ha_device_prefix']
      .forEach(function (k) { if (c[k] !== null && c[k] !== undefined) { body.append(k, c[k]); } });
    ['tls', 'tls_insecure', 'ha_discovery'].forEach(function (k) { if (c[k]) { body.append(k, '1'); } });
    out.textContent = 'Sending test message...';
    try {
      var resp = await fetch(section.dataset.testUrl, {
        method: 'POST', headers: { 'X-CSRFToken': csrf() }, body: body, credentials: 'same-origin',
      });
      var data = await resp.json();
      out.textContent = (data.ok ? 'Test succeeded: ' : 'Test failed: ') + data.message;
    } catch (err) {
      out.textContent = 'Test failed: could not reach STD (' + err + ').';
    }
  });

  // Enabling a disabled channel: the switch submits its toggle form.
  document.addEventListener('change', function (event) {
    var sw = event.target.closest && event.target.closest('[data-switch-submit]');
    if (sw && sw.form) { sw.form.requestSubmit(); }
  });

  /* ---------------------------------------------------------- purge (PRD 17.5) */

  var purgeDialog = $('purge-dialog');
  var purgeBtn = null;
  document.addEventListener('click', function (event) {
    var btn = event.target.closest('[data-notification-purge]');
    if (!btn) { return; }
    purgeBtn = btn;
    $('purge-name').textContent = btn.dataset.channelName;
    $('purge-republish').checked = true;
    purgeDialog.showModal();
  });
  $('purge-cancel').addEventListener('click', function () { purgeDialog.close(); });
  $('purge-confirm').addEventListener('click', async function () {
    var btn = purgeBtn;
    var republish = $('purge-republish').checked;
    purgeDialog.close();
    if (!btn) { return; }
    var out = btn.closest('[data-channel-id]').querySelector('.notification-purge-result');
    btn.disabled = true;
    out.textContent = 'Purging... (up to 15 seconds)';
    try {
      var body = new FormData();
      body.append('republish', republish ? '1' : '0');
      var resp = await fetch(btn.dataset.purgeUrl, {
        method: 'POST', headers: { 'X-CSRFToken': csrf() }, body: body, credentials: 'same-origin',
      });
      var data = await resp.json();
      out.textContent = data.ok
        ? 'Cleared ' + data.topics_cleared + ' topics (' + data.state_topics + ' state, ' +
          data.discovery_topics + ' discovery); ' + (data.republished ? 'republished.' : 'not republished.')
        : 'Purge failed: ' + data.message;
    } catch (err) {
      out.textContent = 'Purge failed: could not reach STD (' + err + ').';
    } finally {
      btn.disabled = false;
    }
  });

  /* --------------------------------------------------- delete / disable dialog */

  // "Remove this channel's data from the broker first" (checked for delete, unchecked for
  // disable). A broker that can't be reached is reported and the operator can go ahead
  // without the cleanup. Cancelling flips the Enabled switch back.
  var rmDialog = $('channel-remove-dialog');
  var rmBtn = null, rmFailed = false, rmDone = false;
  function rmLabel() {
    var del = rmBtn.dataset.channelRemove === 'delete';
    var on = $('remove-cleanup').checked;
    $('remove-confirm').textContent = rmFailed ? (del ? 'Delete anyway' : 'Disable anyway')
      : (del ? (on ? 'Delete and clean the broker' : 'Delete') : (on ? 'Disable and clean the broker' : 'Disable'));
  }
  document.addEventListener('click', function (event) {
    var btn = event.target.closest('[data-channel-remove]');
    if (!btn) { return; }
    rmBtn = btn; rmFailed = false; rmDone = false;
    var del = btn.dataset.channelRemove === 'delete';
    var connected = btn.dataset.channelConnected === '1';
    $('remove-title').textContent = del ? 'Delete notification channel' : 'Disable notification channel';
    $('remove-name').textContent = btn.dataset.channelName;
    $('remove-intro').textContent = del
      ? 'The channel is removed. STD stops publishing to this broker.'
      : 'STD stops publishing to this broker until you enable the channel again.';
    $('remove-cleanup-label').textContent = "Remove this channel's data from the broker first";
    $('remove-cleanup').checked = del && connected;
    $('remove-cleanup-note').textContent = connected
      ? 'Clears the retained STD topics and Home Assistant devices' + (del ? ', including the status topic.' : '; the status topic reads offline.')
      : 'This channel is not connected, so its broker cannot be cleaned. Enable it and wait for connected first.';
    $('remove-error').hidden = true;
    rmLabel();
    rmDialog.showModal();
  });
  rmDialog.addEventListener('close', function () {
    if (rmBtn && !rmDone && rmBtn.type === 'checkbox') { rmBtn.checked = true; }
  });
  $('remove-cleanup').addEventListener('change', rmLabel);
  $('remove-cancel').addEventListener('click', function () { rmDialog.close(); });
  $('remove-confirm').addEventListener('click', async function () {
    var btn = rmBtn;
    var confirmBtn = $('remove-confirm');
    confirmBtn.disabled = true;
    $('remove-error').hidden = true;
    try {
      var body = new FormData();
      body.append('cleanup', $('remove-cleanup').checked ? '1' : '0');
      var resp = await fetch(btn.dataset.actionUrl, {
        method: 'POST', body: body, credentials: 'same-origin',
        headers: { 'X-CSRFToken': csrf(), 'Accept': 'application/json' },
      });
      var data = await resp.json();
      if (data.ok) {
        rmDone = true;
        window.location.href = section.dataset.settingsUrl;
        return;
      }
      rmFailed = true;
      $('remove-cleanup').checked = false;
      $('remove-error').textContent = data.message + ' Nothing was changed.';
      $('remove-error').hidden = false;
      rmLabel();
    } catch (err) {
      $('remove-error').textContent = 'Could not reach STD (' + err + ').';
      $('remove-error').hidden = false;
    } finally {
      confirmBtn.disabled = false;
    }
  });

  /* ------------------------------------------------------------ orphan scan */

  var orphanDialog = $('orphan-dialog');
  var orphanBtn = null, orphanTopics = [];
  document.addEventListener('click', function (event) {
    var btn = event.target.closest('[data-notification-orphans]');
    if (!btn) { return; }
    orphanBtn = btn; orphanTopics = [];
    $('orphan-name').textContent = btn.dataset.channelName;
    $('orphan-status').textContent = '';
    $('orphan-list').hidden = true;
    $('orphan-clear').hidden = true;
    orphanDialog.showModal();
  });
  $('orphan-close').addEventListener('click', function () { orphanDialog.close(); });
  $('orphan-scan').addEventListener('click', async function () {
    var scanBtn = $('orphan-scan');
    scanBtn.disabled = true;
    $('orphan-clear').hidden = true;
    $('orphan-list').hidden = true;
    $('orphan-status').textContent = 'Scanning... (up to 15 seconds)';
    try {
      var body = new FormData();
      body.append('extra_base', $('orphan-extra').value);
      var resp = await fetch(orphanBtn.dataset.scanUrl, {
        method: 'POST', headers: { 'X-CSRFToken': csrf() }, body: body, credentials: 'same-origin',
      });
      var data = await resp.json();
      if (!data.ok) { $('orphan-status').textContent = 'Scan failed: ' + data.message; return; }
      orphanTopics = data.orphans.map(function (o) { return o.topic; });
      var list = $('orphan-list');
      list.textContent = '';
      data.orphans.forEach(function (o) {
        var li = document.createElement('li');
        li.textContent = o.topic + '  (' + o.kind + ')';
        list.appendChild(li);
      });
      list.hidden = !data.orphans.length;
      $('orphan-status').textContent = data.count
        ? 'Found ' + data.count + ' orphaned topic' + (data.count === 1 ? '' : 's') + '.'
        : 'No orphans found.';
      var clearBtn = $('orphan-clear');
      clearBtn.textContent = 'Clear ' + data.count + ' orphan' + (data.count === 1 ? '' : 's');
      clearBtn.hidden = !data.count;
    } catch (err) {
      $('orphan-status').textContent = 'Scan failed: could not reach STD (' + err + ').';
    } finally {
      scanBtn.disabled = false;
    }
  });
  $('orphan-clear').addEventListener('click', async function () {
    var clearBtn = $('orphan-clear');
    clearBtn.disabled = true;
    $('orphan-status').textContent = 'Clearing...';
    try {
      var body = new FormData();
      orphanTopics.forEach(function (t) { body.append('topic', t); });
      body.append('extra_base', $('orphan-extra').value);
      var resp = await fetch(orphanBtn.dataset.clearUrl, {
        method: 'POST', headers: { 'X-CSRFToken': csrf() }, body: body, credentials: 'same-origin',
      });
      var data = await resp.json();
      if (!data.ok) { $('orphan-status').textContent = 'Clear failed: ' + data.message; return; }
      $('orphan-status').textContent = 'Cleared ' + data.topics_cleared + ' topic' +
        (data.topics_cleared === 1 ? '' : 's') + (data.skipped.length ? ' (' + data.skipped.length + ' skipped).' : '.');
      $('orphan-list').hidden = true;
      clearBtn.hidden = true;
      orphanTopics = [];
    } catch (err) {
      $('orphan-status').textContent = 'Clear failed: could not reach STD (' + err + ').';
    } finally {
      clearBtn.disabled = false;
    }
  });

  /* ------------------------------------------------------------ live status */

  async function pollStatus() {
    if (section.classList.contains('hidden') || document.hidden) { return; }
    try {
      var resp = await fetch(section.dataset.statusUrl, { credentials: 'same-origin' });
      if (!resp.ok) { return; }
      var data = await resp.json();
      document.querySelectorAll('#notification-list [data-channel-id]').forEach(function (row) {
        var st = data[row.dataset.channelId];
        if (!st) { return; }
        var word = row.querySelector('.notification-state');
        word.textContent = st.state;
        word.dataset.state = st.state;
        var dot = row.querySelector('.status-dot');
        if (dot) { dot.className = 'status-dot status-dot--' + (DOT[st.state] || 'off'); }
        var err = row.querySelector('.notification-error');
        err.textContent = st.last_error || '';
        err.hidden = st.state !== 'error';
      });
    } catch (err) { /* transient; the next tick retries */ }
  }
  setInterval(pollStatus, 5000);
})();
