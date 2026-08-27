/* The Settings destination: XML path configuration and reindex actions.
 *
 * Inventory §2.8's Settings window changes the Rekordbox XML path by merging
 * it into settings.json without checking that the chosen file exists. This
 * destination preserves those semantics. A browser file input cannot reveal
 * a native absolute path, so the web surface uses an explicit path field; the
 * divergence is recorded in §6.3 rather than hidden behind a fake picker.
 *
 * The reindex UI (the second half of this destination) follows Export's
 * patterns for progress, polling, reattachment and cancellation, with one
 * critical difference: Export's cancellation KEEPS partial results; reindex's
 * cancellation DISCARDS everything. That difference must be legible in the UI
 * before the button is pressed and after it completes.
 */

import { api, ApiError } from '../api.js';
import { POLL_INTERVAL_MS, POLL_RETRY_MS } from './export.js';
import {
  progressPercent,
  formatDuration,
  remainingSeconds,
} from './export.js';
import { askyesno, showerror, showinfo, showwarning } from './message-box.js';

export function mountSettings({
  pollIntervalMs = POLL_INTERVAL_MS,
  retryIntervalMs = POLL_RETRY_MS,
  now = () => Date.now(),
} = {}) {
  const form = document.getElementById('settings-form');
  const input = document.getElementById('settings-xml-path');
  const submit = document.getElementById('settings-submit');
  const status = document.getElementById('settings-status');

  // -- Reindex UI elements --
  const reindexRoot = document.getElementById('settings-reindex');
  const actionsDiv = document.getElementById('reindex-actions');
  const incrementalBtn = document.getElementById('reindex-incremental');
  const fullBtn = document.getElementById('reindex-full');
  const progressDiv = document.getElementById('reindex-progress');
  const progressLabel = document.getElementById('reindex-progress-label');
  const progressTrack = document.getElementById('reindex-progress-track');
  const progressFill = document.getElementById('reindex-progress-fill');
  const progressStatus = document.getElementById('reindex-progress-status');
  const progressTiming = document.getElementById('reindex-progress-timing');
  const stopBtn = document.getElementById('reindex-stop');
  const stopNote = document.getElementById('reindex-stop-note');
  const outcomeDiv = document.getElementById('reindex-outcome');

  /* The latest reindex job document, and whether we are still asking about it. */
  let job = null;
  let watching = null;
  let timer = null;
  let connectionLost = false;
  /* Job ids whose terminal dialog has already been shown, so a re-render or a
   * late poll cannot raise it twice - and so a job that finished before this
   * page existed never raises one at all. */
  const announced = new Set();

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
      report("Changes are saved to this library's settings.json.");
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

  // -- Reindex logic --

  function running() {
    return Boolean(job && job.state === 'running');
  }

  function renderControls() {
    const busy = running();
    incrementalBtn.disabled = busy;
    fullBtn.disabled = busy;
  }

  function renderProgress() {
    if (!running()) {
      progressDiv.hidden = true;
      return;
    }
    progressDiv.hidden = false;

    const { current, total, message } = job.progress;
    const percent = progressPercent(current, total);

    progressLabel.textContent =
      current > 0
        ? `Indexing... (${current}/${total})`
        : 'Indexing...';

    progressFill.style.setProperty('--progress', `${percent.toFixed(1)}%`);
    progressTrack.setAttribute('aria-valuenow', String(Math.round(percent)));
    progressTrack.setAttribute('aria-valuetext', `${progressLabel.textContent} — ${Math.round(percent)}%`);

    progressStatus.textContent = current > 0 ? message : '';

    const elapsed = job.started_at ? now() / 1000 - job.started_at : 0;
    const left = remainingSeconds(current, total, elapsed);
    progressTiming.textContent =
      left === null
        ? `${formatDuration(elapsed)} elapsed`
        : `${formatDuration(elapsed)} elapsed · about ${formatDuration(left)} remaining`;

    stopBtn.disabled = Boolean(job.cancel_requested);
    stopBtn.textContent = job.cancel_requested ? 'Stopping…' : 'Stop Reindex';
    stopNote.textContent = job.cancel_requested
      ? 'Stopping at the next checkpoint. All embeddings computed so far will be discarded.'
      : 'Stopping discards all embeddings computed so far — nothing is committed.';
  }

  function renderOutcome() {
    if (!job || job.state === 'running') {
      if (!connectionLost) {
        outcomeDiv.hidden = true;
        return;
      }
    }

    const lines = [];
    let title = '';

    if (job && job.state === 'succeeded') {
      title = job.cancel_requested
        ? 'Reindex complete — the stop arrived too late to take effect'
        : 'Reindex complete';
      lines.push(completionMessage(job.result));
    } else if (job && job.state === 'cancelled') {
      title = 'Reindex stopped';
      lines.push(cancelledMessage());
    } else if (job && job.state === 'failed') {
      title = 'Reindex failed';
      lines.push(errorMessage(job.error));
    }

    if (connectionLost) {
      title = title || 'Reindex running';
      lines.push('Lost contact with the local server. Still trying — the reindex keeps going without this page.');
    }

    outcomeDiv.hidden = false;
    outcomeDiv.innerHTML = '';
    const eyebrow = document.createElement('p');
    eyebrow.className = 'eyebrow';
    eyebrow.textContent = title;
    const body = document.createElement('p');
    body.className = 'settings__outcome-body';
    body.textContent = lines.join('\n\n');
    outcomeDiv.append(eyebrow, body);
  }

  function render() {
    renderControls();
    renderProgress();
    renderOutcome();
  }

  function completionMessage(result) {
    const mode = result.requested_mode;
    const isIncremental = mode === 'incremental';

    let msg = '✓ Index Updated!\n\n';
    msg += `Mode: ${isIncremental ? 'Incremental' : 'Full rebuild'}\n`;
    msg += `Tracks indexed: ${result.total_tracks_indexed}\n`;
    msg += `New tracks added: ${result.new_tracks_added}\n`;
    if (result.failed > 0) {
      msg += `Failed: ${result.failed}\n`;
    }
    msg += `\nStatus: ${result.status}`;
    if (result.up_to_date) {
      msg += '\nThe index was already up to date.';
    }
    // PR #30 refreshed the server's session; the browser's copy may still be stale.
    msg += '\n\nNote: Other destinations (Library, Explore) may need a page reload to see updated counts.';
    return msg;
  }

  function cancelledMessage() {
    return (
      '⚠ Reindex Stopped\n\n' +
      'All embeddings computed during this run were discarded. The index remains ' +
      'unchanged from before this reindex started.\n\n' +
      'To update the index, run a new reindex operation.'
    );
  }

  function errorMessage(error) {
    return error || 'An unknown error occurred.';
  }

  async function incrementalClicked() {
    try {
      const body = await api.startReindex({ forceFull: false });
      attach(body.job, { announce: true });
    } catch (error) {
      if (error instanceof ApiError && error.code === 'no_xml_path') {
        await showwarning(
          'No Collection Configured',
          'Set a Rekordbox XML path above before running a reindex.',
        );
        return;
      }
      if (error instanceof ApiError && error.code === 'job_in_progress') {
        await showwarning('Job Already Running', error.message);
        reattach();
        return;
      }
      await showerror('Reindex Error', errorMessage(error.message));
    }
  }

  async function fullClicked() {
    const confirmed = await askyesno(
      'Confirm Full Rebuild',
      'A full rebuild re-embeds every track in your collection, even ones that ' +
        'already have embeddings.\n\n' +
        'On the real 1,532-track library, a full rebuild takes approximately ' +
        '75 minutes at ~3 seconds per track.\n\n' +
        'An incremental update (the other button) processes only new tracks and ' +
        'completes in seconds.\n\n' +
        'Are you sure you want to rebuild the entire index?',
    );
    if (!confirmed) {
      return;
    }

    try {
      const body = await api.startReindex({ forceFull: true });
      attach(body.job, { announce: true });
    } catch (error) {
      if (error instanceof ApiError && error.code === 'no_xml_path') {
        await showwarning(
          'No Collection Configured',
          'Set a Rekordbox XML path above before running a reindex.',
        );
        return;
      }
      if (error instanceof ApiError && error.code === 'job_in_progress') {
        await showwarning('Job Already Running', error.message);
        reattach();
        return;
      }
      await showerror('Reindex Error', errorMessage(error.message));
    }
  }

  async function stopClicked() {
    if (!watching) {
      return;
    }
    stopBtn.disabled = true;
    try {
      const body = await api.cancelJob(watching);
      observe(body.job);
    } catch (error) {
      stopBtn.disabled = false;
      await showerror('Reindex Error', errorMessage(error.message));
    }
  }

  function attach(document_, { announce }) {
    job = document_;
    watching = document_.state === 'running' ? document_.id : null;
    if (!announce) {
      announced.add(document_.id);
    }
    render();
    if (watching) {
      schedule(pollIntervalMs);
    } else {
      finished();
    }
  }

  function schedule(delay) {
    window.clearTimeout(timer);
    timer = window.setTimeout(poll, delay);
  }

  async function poll() {
    if (!watching) {
      return;
    }
    const mine = watching;
    try {
      const body = await api.job(mine);
      if (watching !== mine) {
        return;
      }
      connectionLost = false;
      observe(body.job);
    } catch (error) {
      if (watching !== mine) {
        return;
      }
      connectionLost = true;
      render();
      schedule(retryIntervalMs);
    }
  }

  function observe(document_) {
    job = document_;
    if (document_.state === 'running') {
      watching = document_.id;
      render();
      schedule(pollIntervalMs);
      return;
    }
    watching = null;
    window.clearTimeout(timer);
    render();
    finished();
  }

  function finished() {
    if (!job || job.state === 'running' || announced.has(job.id)) {
      return;
    }
    announced.add(job.id);

    if (job.state === 'succeeded') {
      const body = completionMessage(job.result);
      showinfo(
        'Reindex Complete',
        job.cancel_requested
          ? `${body}\n\nYour stop arrived after the last checkpoint, so the reindex finished in full.`
          : body,
      );
      return;
    }
    if (job.state === 'cancelled') {
      showinfo('Reindex Stopped', cancelledMessage());
      return;
    }
    showerror('Reindex Error', errorMessage(job.error));
  }

  /**
   * Find a job this page did not start. Called at mount.
   *
   * THIS IS WHAT MAKES A RELOAD SURVIVABLE. `JobRegistry` outlives the request
   * that created it, so a reindex started 75 minutes ago is still running
   * after ⌘R - but the page has lost the id it was given, which is exactly why
   * `GET /api/jobs` exists. A terminal job found this way is shown in the
   * outcome panel and NOT announced: its dialog belongs to the page that was
   * watching when it ended.
   */
  async function reattach() {
    let body;
    try {
      body = await api.jobs();
    } catch (error) {
      return;
    }
    const reindexJobs = (body.jobs || []).filter((each) => each.kind === 'reindex');
    if (!reindexJobs.length) {
      return;
    }
    // Newest first (`JobRegistry.all`), so the first is the one to show.
    const latest = reindexJobs[0];
    attach(latest, { announce: latest.state === 'running' });
  }

  incrementalBtn.addEventListener('click', incrementalClicked);
  fullBtn.addEventListener('click', fullClicked);
  stopBtn.addEventListener('click', stopClicked);

  load();
  reattach();
}
