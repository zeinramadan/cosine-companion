/* The Settings destination: one read and one instantaneous write.
 *
 * Inventory §2.8's Settings window changes the Rekordbox XML path by merging
 * it into settings.json without checking that the chosen file exists. This
 * destination preserves those semantics. A browser file input cannot reveal
 * a native absolute path, so the web surface uses an explicit path field; the
 * divergence is recorded in §6.3 rather than hidden behind a fake picker.
 *
 * Deleted-track management and both reindex actions remain out of scope for
 * this write-surface PR. They need the long-running job design in PR 3b.
 */

import { api } from '../api.js';

export function mountSettings() {
  const form = document.getElementById('settings-form');
  const input = document.getElementById('settings-xml-path');
  const submit = document.getElementById('settings-submit');
  const status = document.getElementById('settings-status');

  function report(message, state = 'idle') {
    status.textContent = message;
    status.dataset.state = state;
  }

  async function load() {
    input.disabled = true;
    submit.disabled = true;
    report('Loading settings…');

    try {
      const body = await api.settings();
      input.value = body.settings.xml_path || '';
      report('Changes are saved to this library’s settings.json.');
    } catch (error) {
      report(error.message, 'error');
    } finally {
      input.disabled = false;
      submit.disabled = false;
    }
  }

  form.addEventListener('submit', async (event) => {
    event.preventDefault();
    const xmlPath = input.value;

    if (!xmlPath.trim()) {
      report('Enter a Rekordbox XML path before saving.', 'error');
      input.focus();
      return;
    }

    input.disabled = true;
    submit.disabled = true;
    report('Saving…');

    try {
      const body = await api.updateSettings(xmlPath);
      input.value = body.settings.xml_path;
      report('Settings saved.', 'success');
    } catch (error) {
      report(error.message, 'error');
    } finally {
      input.disabled = false;
      submit.disabled = false;
    }
  });

  load();
}
