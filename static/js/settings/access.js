/* Settings -> About / Widgets / Access: the default-credentials warning and Copy buttons. */
(function () {
  'use strict';
  var S = window.STDSettings = window.STDSettings || {};

  // The default-credentials warning shows unless it was dismissed this browser session.
  var box = document.getElementById('credential-warning');
  if (box) {
    var key = 'std-credential-warning-dismissed';
    var dismissed = false;
    try { dismissed = sessionStorage.getItem(key) === '1'; } catch (e) { /* storage blocked */ }
    if (!dismissed) { box.style.display = 'flex'; }
    var btn = document.getElementById('credential-warning-dismiss');
    if (btn) {
      btn.addEventListener('click', function () {
        box.style.display = 'none';
        try { sessionStorage.setItem(key, '1'); } catch (e) { /* storage blocked */ }
      });
    }
  }

  function copyToClipboard(inputId) {
    var input = document.getElementById(inputId);
    if (!input || !navigator.clipboard) { return; }
    navigator.clipboard.writeText(input.value)
      .then(function () {
        input.classList.add('ring-2', 'ring-green-400');
        setTimeout(function () { input.classList.remove('ring-2', 'ring-green-400'); }, 1000);
      })
      .catch(function (err) { console.error('Copy failed:', err); });
  }

  S.copyToClipboard = copyToClipboard;
  window.copyToClipboard = copyToClipboard;
})();
