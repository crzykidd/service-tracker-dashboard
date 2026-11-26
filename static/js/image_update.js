/*
 * Image update "Check now" (PRD 24). Any `[data-image-check][data-url]` link or button POSTs to its
 * URL (CSRF token from the page's meta tag) and shows the answer as a toast. The check itself runs
 * later in the background job; the page never waits for the registry. Delegated, so it also works in
 * the Compact details dialog, which is fetched when it opens.
 */
(function () {
  'use strict';

  function region() {
    var box = document.getElementById('toast-region');
    if (!box) {
      box = document.createElement('div');
      box.id = 'toast-region';
      box.className = 'toast-region';
      box.setAttribute('role', 'status');
      box.setAttribute('aria-live', 'polite');
      document.body.appendChild(box);
    }
    return box;
  }

  function toast(kind, text) {
    var el = document.createElement('div');
    el.className = 'toast toast--' + kind;
    el.setAttribute('role', 'status');
    el.setAttribute('data-toast', '');
    var msg = document.createElement('span');
    msg.className = 'toast-text';
    msg.textContent = text;
    var close = document.createElement('button');
    close.type = 'button';
    close.className = 'toast-close';
    close.setAttribute('aria-label', 'Dismiss');
    close.setAttribute('data-toast-close', '');
    close.innerHTML = '&times;';
    el.appendChild(msg);
    el.appendChild(close);
    region().appendChild(el);
    if (window.STDFlash) { window.STDFlash.arm(el); }
  }

  function ask(message) {
    var ui = window.STDSettings && window.STDSettings.ui;
    if (ui && typeof ui.confirm === 'function') {
      return ui.confirm({ title: 'Check again?', body: message, confirmLabel: 'Check again' });
    }
    return Promise.resolve(window.confirm(message));
  }

  function post(url, force) {
    var meta = document.querySelector('meta[name="csrf-token"]');
    return fetch(url + (force ? (url.indexOf('?') < 0 ? '?' : '&') + 'force=1' : ''), {
      method: 'POST',
      headers: { 'X-CSRFToken': meta ? meta.content : '', 'Accept': 'application/json' },
      credentials: 'same-origin'
    }).then(function (resp) {
      return resp.json().catch(function () { return {}; }).then(function (body) {
        return { resp: resp, body: body };
      });
    });
  }

  function show(answer) {
    var body = answer.body, ok = answer.resp.ok;
    toast(ok ? 'success' : 'info', body.message || (ok ? 'Check requested.' : 'Could not start the check.'));
  }

  // Docker Hub "Test login": posts the typed values (a blank field means the stored value) to the
  // test route, which asks auth.docker.io only. The answer is a fixed message.
  function testLogin(button) {
    var form = document.getElementById('dockerhub-form');
    var meta = document.querySelector('meta[name="csrf-token"]');
    var body = new URLSearchParams();
    body.set('dockerhub_username', (form.elements.dockerhub_username.value || ''));
    body.set('dockerhub_token', (form.elements.dockerhub_token.value || ''));
    button.setAttribute('aria-disabled', 'true');
    fetch(button.getAttribute('data-url'), {
      method: 'POST',
      headers: { 'X-CSRFToken': meta ? meta.content : '', 'Accept': 'application/json',
                 'Content-Type': 'application/x-www-form-urlencoded' },
      body: body.toString(),
      credentials: 'same-origin'
    }).then(function (resp) {
      return resp.json().catch(function () { return {}; });
    }).then(function (answer) {
      toast(answer.ok ? 'success' : 'info', answer.message || 'Could not test the login.');
    }).catch(function () {
      toast('info', 'Could not test the login.');
    }).then(function () {
      button.removeAttribute('aria-disabled');
    });
  }

  document.addEventListener('click', function (event) {
    var test = event.target.closest('[data-dockerhub-test]');
    if (test) {
      event.preventDefault();
      if (test.getAttribute('aria-disabled') !== 'true') { testLogin(test); }
      return;
    }
    var trigger = event.target.closest('[data-image-check]');
    if (!trigger) { return; }
    event.preventDefault();
    if (trigger.getAttribute('aria-disabled') === 'true') { return; }
    trigger.setAttribute('aria-disabled', 'true');
    var url = trigger.getAttribute('data-url');
    post(url, false).then(function (answer) {
      if (answer.resp.status === 409 && answer.body.confirm_required) {
        return ask(answer.body.message).then(function (yes) {
          if (!yes) { return; }
          return post(url, true).then(show);
        });
      }
      show(answer);
    }).catch(function () {
      toast('info', 'Could not reach STD; try again.');
    }).then(function () {
      trigger.removeAttribute('aria-disabled');
    });
  });
})();
