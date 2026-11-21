/* Settings -> Backup & restore: restore source toggle and the chosen file name. */
(function () {
  'use strict';
  var S = window.STDSettings = window.STDSettings || {};

  function toggleRestoreSource(value) {
    var serverSection = document.getElementById('server-file-selector-section');
    var uploadSection = document.getElementById('file-upload-section');
    if (!serverSection || !uploadSection) { return; }
    if (value === 'upload') {
      serverSection.classList.add('hidden');
      uploadSection.classList.remove('hidden');
    } else {
      uploadSection.classList.add('hidden');
      serverSection.classList.remove('hidden');
    }
  }

  document.addEventListener('change', function (event) {
    var radio = event.target.closest('[data-restore-source]');
    if (radio) { toggleRestoreSource(radio.value); }
  });

  var fileInput = document.getElementById('restore_file_input');
  var fileDisplay = document.getElementById('file-name-display');
  if (fileInput && fileDisplay) {
    fileInput.addEventListener('change', function () {
      fileDisplay.textContent = this.files.length > 0 ? this.files[0].name : 'YAML up to 10MB';
    });
  }

  S.backup = { toggleRestoreSource: toggleRestoreSource };
  window.toggleRestoreSource = toggleRestoreSource;
})();
