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
import {
  formatDuration,
  POLL_INTERVAL_MS,
  POLL_RETRY_MS,
  progressPercent,
  remainingSeconds,
} from './export.js';
import { element } from '../format.js';
import { askyesno, showerror, showinfo, showwarning } from './message-box.js';

function browserRefreshMessage(refreshState) {
  if (refreshState === 'loading') {
    return 'Refreshing the sidebar track count…';
  }
  if (refreshState === 'failed') {
    return (
      'The browser could not refresh its library summary, so the sidebar may still ' +
      'show the old count. Reload this page before relying on counts, track lists, ' +
      'or recommendations.'
    );
  }
  return (
    'The sidebar track count has been refreshed. Reload this page before relying on ' +
    'track lists or recommendations already open in Library, Explore, Set Creator, ' +
    'or Export.'
  );
}

/** A completed service result. Registry success and pipeline failure differ. */
export function completionMessage(result, { refreshState = 'ready' } = {}) {
  const mode = result.requested_mode === 'incremental' ? 'Incremental' : 'Full rebuild';
  let outcome;

  if (result.failed) {
    outcome =
      '⚠ Index not updated\n\n' +
      `No embeddings could be created for the ${result.new_tracks_found} new track(s) found.`;
  } else if (result.up_to_date) {
    outcome = '✓ Index already up to date\n\nNo new tracks needed embeddings.';
  } else {
    outcome =
      '✓ Index updated\n\n' +
      `Tracks in index: ${result.total_tracks_indexed}\n` +
      `New tracks added: ${result.new_tracks_added}`;
  }

  return `${outcome}\n\nMode: ${mode}\n\n${browserRefreshMessage(refreshState)}`;
}

/** A cancelled reindex has no result document because no work was committed. */
export function cancelledMessage() {
  return (
    'All embeddings computed during this run were discarded. The index is unchanged ' +
    'from before this reindex started.\n\nRun a new update when you are ready to try again.'
  );
}

export function errorMessage(error) {
  return error || 'An unknown error occurred.';
}

function completedTitle(document_) {
  if (document_.cancel_requested) {
    return 'Reindex complete — the stop arrived too late to take effect';
  }
  if (document_.result.failed) {
    return 'Reindex finished without new embeddings';
  }
  if (document_.result.up_to_date) {
    return 'Index already up to date';
  }
  return 'Reindex complete';
}

function completedBody(document_, refreshState) {
  const base = completionMessage(document_.result, { refreshState });
  if (!document_.cancel_requested) {
    return base;
  }
  return (
    `${base}\n\nYour stop request arrived after the final cancellation checkpoint, ` +
    'so the reindex finished and committed its complete result.'
  );
}

export function mountSettings({
  pollIntervalMs = POLL_INTERVAL_MS,
  retryIntervalMs = POLL_RETRY_MS,
  now = () => Date.now(),
  refreshLibrary = async () => true,
} = {}) {
  const form = document.getElementById('settings-form');
  const input = document.getElementById('settings-xml-path');
  const submit = document.getElementById('settings-submit');
  const status = document.getElementById('settings-status');

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
  let starting = false;
  let refreshState = 'idle';
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
    const busy = running() || starting;
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
      title = completedTitle(job);
      lines.push(completedBody(job, refreshState));
    } else if (job && job.state === 'cancelled') {
      // State alone is authoritative here because this component only renders
      // reindex jobs. web/api.py:1174-1176 hardcodes their returned WorkOutcome
      // to cancelled=False; an observed stop instead raises KeyboardInterrupt,
      // whose web/jobs.py:413-414 path publishes CANCELLED without a result.
      // Export deliberately differs: web/api.py:1112-1115 can return
      // cancelled=True with real counts, so an Export renderer could not make
      // this reindex-specific inference from state alone.
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

    if (!lines.length) {
      outcomeDiv.hidden = true;
      return;
    }

    outcomeDiv.hidden = false;
    outcomeDiv.replaceChildren(
      element('p', 'eyebrow', title),
      element('p', 'settings__outcome-body', lines.join('\n\n')),
    );
  }

  function render() {
    renderControls();
    renderProgress();
    renderOutcome();
  }

  async function startReindex(forceFull) {
    starting = true;
    renderControls();
    try {
      const body = await api.startReindex({ forceFull });
      attach(body.job, { announce: true });
    } catch (error) {
      if (error instanceof ApiError && error.code === 'no_xml_path') {
        await showwarning(
          'No Collection Configured',
          'Set and save a Rekordbox XML path above, then try the index update again.',
        );
        return;
      }
      if (error instanceof ApiError && error.code === 'job_in_progress') {
        await showwarning('Another Job Is Running', error.message);
        return;
      }
      await showerror('Reindex Error', errorMessage(error.message));
    } finally {
      starting = false;
      renderControls();
    }
  }

  async function incrementalClicked() {
    await startReindex(false);
  }

  async function fullClicked() {
    const confirmed = await askyesno(
      'Rebuild Every Embedding?',
      'A full rebuild re-embeds every track in your collection, even ones that ' +
        'already have embeddings.\n\n' +
        'On the real 1,532-track library, a full rebuild takes approximately ' +
        '75 minutes at ~3 seconds per track.\n\n' +
        'The incremental action processes only new tracks and ' +
        'completes in seconds.\n\n' +
        'Start the full rebuild?',
    );
    if (!confirmed) {
      return;
    }

    await startReindex(true);
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
    connectionLost = false;
    refreshState = 'idle';
    if (!announce) {
      announced.add(document_.id);
    }
    render();
    if (watching) {
      schedule(pollIntervalMs);
    } else {
      settleTerminal();
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
    settleTerminal();
  }

  function settleTerminal() {
    if (!job || job.state === 'running') {
      return;
    }
    if (job.state !== 'succeeded') {
      refreshState = 'idle';
      render();
      finished();
      return;
    }

    const mine = job.id;
    refreshState = 'loading';
    render();
    Promise.resolve()
      .then(refreshLibrary)
      .then((refreshed) => {
        if (!job || job.id !== mine || job.state !== 'succeeded') {
          return;
        }
        refreshState = refreshed === false ? 'failed' : 'ready';
        render();
        finished();
      })
      .catch(() => {
        if (!job || job.id !== mine || job.state !== 'succeeded') {
          return;
        }
        refreshState = 'failed';
        render();
        finished();
      });
  }

  function finished() {
    if (!job || job.state === 'running' || announced.has(job.id)) {
      return;
    }
    announced.add(job.id);

    if (job.state === 'succeeded') {
      showinfo(completedTitle(job), completedBody(job, refreshState));
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
    // A start can finish while this mount-time lookup is in flight. Its job id
    // is already the identity we are watching, so an older list must not win.
    if (job) {
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

  return {
    isRunning: running,
    dispose() {
      watching = null;
      window.clearTimeout(timer);
    },
  };
}
