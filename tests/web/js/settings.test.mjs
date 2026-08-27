/* The Settings destination, driven through the shipped module.
 *
 * The XML-path form is instantaneous; reindexing is not. These tests exercise
 * the ordering that source inspection cannot settle: confirmation before an
 * expensive start, poll responses tied to one job id, cancellation records
 * with and without a terminal CANCELLED state, and reattachment after reload.
 */

import { test } from 'node:test';
import assert from 'node:assert/strict';

import { byClass, document, installGlobals, textsByClass, walk } from './dom_shim.mjs';
import {
  buildSettingsDom,
  installFetch,
  resetDom,
  settle,
} from './fixture.mjs';

installGlobals();

const { openModalCount } = await import('../../../src/web/static/js/modal.js');
const {
  cancelledMessage,
  completionMessage,
  mountSettings,
} = await import('../../../src/web/static/js/components/settings.js');

const SETTINGS_KEY = '/api/settings?q=';
const JOBS_KEY = '/api/jobs?q=';
const START_KEY = '/api/jobs/reindex?q=';
const jobKey = (id) => `/api/jobs/${id}?q=`;
const cancelKey = (id) => `/api/jobs/${id}/cancel?q=`;

const STARTED_AT = 1_700_000_000;
let clock = STARTED_AT * 1000;

function resultDoc(overrides = {}) {
  return {
    requested_mode: 'incremental',
    force_full: false,
    status: 'indexed',
    up_to_date: false,
    failed: false,
    total_tracks_indexed: 1534,
    new_tracks_added: 2,
    new_tracks_found: 2,
    ...overrides,
  };
}

function jobDoc(overrides = {}) {
  return {
    id: 'reindex-1',
    kind: 'reindex',
    state: 'running',
    progress: { current: 0, total: 0, message: 'Checking for new tracks' },
    cancel_requested: false,
    started_at: STARTED_AT,
    finished_at: null,
    result: null,
    error: null,
    ...overrides,
  };
}

let fetches = installFetch();
let mounted = null;

async function closeDialogs() {
  for (let guard = 0; guard < 8 && openModalCount() > 0; guard += 1) {
    const panels = byClass(document.body, 'modal__panel');
    const top = panels[panels.length - 1];
    if (!top) break;
    top.dispatch('keydown', { key: 'Escape' });
    await settle();
  }
  assert.equal(openModalCount(), 0, 'a dialog survived the drain');
}

async function mount({ refreshLibrary = async () => true } = {}) {
  await closeDialogs();
  if (mounted) mounted.dispose();
  resetDom();
  fetches = installFetch();
  const dom = buildSettingsDom();
  mounted = mountSettings({
    pollIntervalMs: 1,
    retryIntervalMs: 1,
    now: () => clock,
    refreshLibrary,
  });
  return { dom, view: mounted };
}

async function ready(options = {}) {
  const context = await mount(options);
  await settle();
  fetches.deliver(SETTINGS_KEY, {
    settings: { xml_path: '/old/collection.xml' },
  });
  fetches.deliver(JOBS_KEY, { jobs: [] });
  await settle();
  return context;
}

async function tick(ms = 6) {
  await new Promise((resolve) => setTimeout(resolve, ms));
  await settle();
}

function control(label) {
  const found = walk(document.body).find(
    (node) => node.tagName === 'BUTTON' && node.textContent === label,
  );
  assert.ok(found, `no control labelled ${label}`);
  return found;
}

function postedBody(key) {
  const request = [...fetches.requests].reverse().find((each) => each.key === key);
  assert.ok(request, `nothing was posted to ${key}`);
  return JSON.parse(request.options.body);
}

const dialogTitle = () => textsByClass(document.body, 'message-box__title')[0];
const dialogBody = () => textsByClass(document.body, 'message-box__message')[0];

test('the Settings destination loads and persists the edited XML path', async () => {
  const { dom } = await mount();

  assert.deepEqual(
    fetches.requests.map((request) => [request.path, request.options.method]),
    [
      ['/api/settings', 'GET'],
      ['/api/jobs', 'GET'],
    ],
  );
  assert.equal(dom.input.disabled, true);

  fetches.deliver(SETTINGS_KEY, {
    settings: { xml_path: '/old/collection.xml' },
  });
  fetches.deliver(JOBS_KEY, { jobs: [] });
  await settle();

  assert.equal(dom.input.value, '/old/collection.xml');
  assert.equal(dom.input.disabled, false);
  assert.equal(dom.submit.disabled, false);

  dom.input.value = '/new/collection.xml';
  dom.form.dispatch('submit');
  await settle();

  assert.deepEqual(postedBody(SETTINGS_KEY), {
    xml_path: '/new/collection.xml',
  });
  assert.equal(dom.input.disabled, true);

  fetches.deliver(SETTINGS_KEY, {
    settings: { xml_path: '/new/collection.xml' },
  });
  await settle();

  assert.equal(dom.input.value, '/new/collection.xml');
  assert.equal(dom.status.textContent, 'Settings saved.');
  assert.equal(dom.status.dataset.state, 'success');
  assert.equal(dom.input.disabled, false);
  assert.equal(dom.submit.disabled, false);
});

test('failed and blank Settings saves retain the existing form behaviour', async () => {
  const { dom } = await ready();

  dom.input.value = '  \t  ';
  const before = fetches.requests.length;
  let prevented = false;
  dom.form.dispatch('submit', {
    preventDefault() {
      prevented = true;
    },
  });
  await settle();
  assert.equal(prevented, true);
  assert.equal(fetches.requests.length, before);
  assert.equal(dom.status.textContent, 'Enter a Rekordbox XML path before saving.');
  assert.equal(dom.status.dataset.state, 'error');
  assert.equal(dom.input.focused, 1);

  dom.input.value = '/new/collection.xml';
  dom.form.dispatch('submit');
  await settle();
  fetches.reject(SETTINGS_KEY);
  await settle();
  assert.equal(dom.status.textContent, 'Could not reach the local server.');
  assert.equal(dom.status.dataset.state, 'error');
  assert.equal(dom.input.disabled, false);
  assert.equal(dom.submit.disabled, false);
});

test('incremental starts immediately with force_full false and disables both choices', async () => {
  const { dom } = await ready();

  dom.incremental.dispatch('click');
  await settle();

  assert.deepEqual(postedBody(START_KEY), { force_full: false });
  assert.equal(dom.incremental.disabled, true);
  assert.equal(dom.full.disabled, true);

  fetches.deliver(START_KEY, { job: jobDoc() });
  await settle();
  assert.equal(mounted.isRunning(), true);
  assert.equal(dom.progress.hidden, false);
  assert.equal(dom.incremental.disabled, true);
  assert.equal(dom.full.disabled, true);
});

test('full rebuild needs a second affirmative click and sends force_full true', async () => {
  const { dom } = await ready();

  dom.full.dispatch('click');
  await settle();

  assert.equal(dialogTitle(), 'Rebuild Every Embedding?');
  assert.match(dialogBody(), /re-embeds every track/);
  assert.match(dialogBody(), /1,532-track library/);
  assert.match(dialogBody(), /75 minutes at ~3 seconds per track/);
  assert.equal(fetches.outstanding(START_KEY), false);

  control('No').dispatch('click');
  await settle();
  assert.equal(fetches.outstanding(START_KEY), false, 'declining still started a rebuild');

  dom.full.dispatch('click');
  await settle();
  control('Yes').dispatch('click');
  await settle();
  assert.deepEqual(postedBody(START_KEY), { force_full: true });
});

test('no_xml_path points to the control that fixes the conflict', async () => {
  const { dom } = await ready();
  dom.incremental.dispatch('click');
  await settle();

  fetches.deliverError(
    START_KEY,
    409,
    'no_xml_path',
    'No Rekordbox XML is configured. Set one in Settings first.',
  );
  await settle();

  assert.equal(dialogTitle(), 'No Collection Configured');
  assert.equal(
    dialogBody(),
    'Set and save a Rekordbox XML path above, then try the index update again.',
  );
});

test('job_in_progress names the export that is holding the shared lock', async () => {
  const { dom } = await ready();
  dom.incremental.dispatch('click');
  await settle();

  fetches.deliverError(
    START_KEY,
    409,
    'job_in_progress',
    'A export job (export-7) is already running. Wait for it to finish or cancel it first.',
  );
  await settle();

  assert.equal(dialogTitle(), 'Another Job Is Running');
  assert.equal(
    dialogBody(),
    'A export job (export-7) is already running. Wait for it to finish or cancel it first.',
  );
});

test('progress is determinate and Stop says DISCARD before it is pressed', async () => {
  const { dom } = await ready();
  dom.incremental.dispatch('click');
  await settle();
  fetches.deliver(START_KEY, { job: jobDoc() });
  await settle();

  assert.equal(dom.progressLabel.textContent, 'Indexing...');
  assert.equal(dom.progressStatus.textContent, '');
  assert.equal(
    dom.stopNote.textContent,
    'Stopping discards all embeddings computed so far — nothing is committed.',
  );

  await tick();
  clock = (STARTED_AT + 12) * 1000;
  fetches.deliver(jobKey('reindex-1'), {
    job: jobDoc({
      progress: { current: 4, total: 10, message: '[4/10] Objekt - Ganzfeld' },
    }),
  });
  await settle();

  assert.equal(dom.progressFill.style.properties.get('--progress'), '40.0%');
  assert.equal(dom.progressTrack.getAttribute('aria-valuenow'), '40');
  assert.equal(dom.progressTrack.getAttribute('aria-valuetext'), 'Indexing... (4/10) — 40%');
  assert.equal(dom.progressLabel.textContent, 'Indexing... (4/10)');
  assert.equal(dom.progressStatus.textContent, '[4/10] Objekt - Ganzfeld');
  assert.equal(dom.progressTiming.textContent, '12s elapsed · about 18s remaining');
  clock = STARTED_AT * 1000;
});

test('observed cancellation has no result and says every computed embedding was discarded', async () => {
  let refreshes = 0;
  const { dom } = await ready({
    refreshLibrary: async () => {
      refreshes += 1;
      return true;
    },
  });
  dom.incremental.dispatch('click');
  await settle();
  fetches.deliver(START_KEY, { job: jobDoc() });
  await settle();

  dom.stop.dispatch('click');
  await settle();
  assert.deepEqual(postedBody(cancelKey('reindex-1')), {});

  fetches.deliver(cancelKey('reindex-1'), {
    job: jobDoc({ cancel_requested: true }),
  });
  await settle();
  assert.equal(control('Stopping…').disabled, true);
  assert.match(dom.stopNote.textContent, /All embeddings computed so far will be discarded/);

  await tick();
  fetches.deliver(jobKey('reindex-1'), {
    job: jobDoc({
      state: 'cancelled',
      cancel_requested: true,
      finished_at: STARTED_AT + 20,
      result: null,
    }),
  });
  await settle();

  assert.equal(dialogTitle(), 'Reindex Stopped');
  assert.equal(dialogBody(), cancelledMessage());
  assert.match(dialogBody(), /All embeddings computed during this run were discarded/);
  assert.match(dialogBody(), /index is unchanged from before this reindex started/);
  assert.equal(refreshes, 0, 'a discarded run refreshed the shared library summary');
  assert.equal(dom.progress.hidden, true);
  assert.equal(dom.outcome.hidden, false);
  assert.match(dom.outcome.textContent, /Reindex stopped/);
});

test('success refreshes the sidebar summary before announcing stale destination state', async () => {
  let resolveRefresh;
  let refreshes = 0;
  const refreshLibrary = () => {
    refreshes += 1;
    return new Promise((resolve) => {
      resolveRefresh = resolve;
    });
  };
  const { dom } = await ready({ refreshLibrary });
  dom.incremental.dispatch('click');
  await settle();
  fetches.deliver(START_KEY, { job: jobDoc() });
  await settle();

  await tick();
  fetches.deliver(jobKey('reindex-1'), {
    job: jobDoc({
      state: 'succeeded',
      finished_at: STARTED_AT + 15,
      progress: { current: 2, total: 2, message: '[2/2] New Track' },
      result: resultDoc(),
    }),
  });
  await settle();

  assert.equal(refreshes, 1);
  assert.equal(openModalCount(), 0, 'success was announced before the shared count settled');
  assert.match(dom.outcome.textContent, /Refreshing the sidebar track count/);

  resolveRefresh(true);
  await settle();

  assert.equal(dialogTitle(), 'Reindex complete');
  assert.match(dialogBody(), /✓ Index updated/);
  assert.match(dialogBody(), /Tracks in index: 1534/);
  assert.match(dialogBody(), /sidebar track count has been refreshed/);
  assert.match(dialogBody(), /Library, Explore, Set Creator, or Export/);
  assert.match(dialogBody(), /Reload this page/);
});

test('a failed summary refresh explicitly warns that the sidebar count may be old', async () => {
  const { dom } = await ready({ refreshLibrary: async () => false });
  dom.incremental.dispatch('click');
  await settle();
  fetches.deliver(START_KEY, {
    job: jobDoc({ state: 'succeeded', result: resultDoc() }),
  });
  await settle();

  assert.match(dom.outcome.textContent, /sidebar may still show the old count/);
  assert.match(dom.outcome.textContent, /Reload this page before relying on counts/);
  assert.match(dialogBody(), /sidebar may still show the old count/);
});

test('a stop after the final checkpoint is a succeeded job that committed the complete result', async () => {
  const { dom } = await ready();
  dom.incremental.dispatch('click');
  await settle();
  fetches.deliver(START_KEY, { job: jobDoc() });
  await settle();

  dom.stop.dispatch('click');
  await settle();
  fetches.deliver(cancelKey('reindex-1'), {
    job: jobDoc({
      state: 'succeeded',
      cancel_requested: true,
      finished_at: STARTED_AT + 8,
      result: resultDoc(),
    }),
  });
  await settle();

  assert.equal(dialogTitle(), 'Reindex complete — the stop arrived too late to take effect');
  assert.match(dialogBody(), /stop request arrived after the final cancellation checkpoint/);
  assert.match(dialogBody(), /finished and committed its complete result/);
  assert.match(dom.outcome.textContent, /stop arrived too late to take effect/);
  assert.match(dom.outcome.textContent, /✓ Index updated/);
});

test('up-to-date and no-embeddings results do not falsely claim the index updated', () => {
  const current = completionMessage(
    resultDoc({
      status: 'up_to_date',
      up_to_date: true,
      total_tracks_indexed: 0,
      new_tracks_added: 0,
      new_tracks_found: 0,
    }),
  );
  assert.match(current, /^✓ Index already up to date/);
  assert.doesNotMatch(current, /✓ Index updated\n/);

  const failed = completionMessage(
    resultDoc({
      status: 'no_embeddings',
      failed: true,
      total_tracks_indexed: 0,
      new_tracks_added: 0,
      new_tracks_found: 3,
    }),
  );
  assert.match(failed, /^⚠ Index not updated/);
  assert.match(failed, /No embeddings could be created for the 3 new track\(s\) found/);
  assert.doesNotMatch(failed, /✓ Index updated/);
});

test('a failed job shows the server error and restores the actions', async () => {
  const { dom } = await ready();
  dom.incremental.dispatch('click');
  await settle();
  fetches.deliver(START_KEY, { job: jobDoc() });
  await settle();

  await tick();
  fetches.deliver(jobKey('reindex-1'), {
    job: jobDoc({
      state: 'failed',
      finished_at: STARTED_AT + 2,
      error: 'The XML file could not be read.',
    }),
  });
  await settle();

  assert.equal(dialogTitle(), 'Reindex Error');
  assert.equal(dialogBody(), 'The XML file could not be read.');
  assert.equal(dom.incremental.disabled, false);
  assert.equal(dom.full.disabled, false);
  assert.match(dom.outcome.textContent, /Reindex failed/);
});

test('a reload reattaches to the newest reindex job, ignoring a newer export record', async () => {
  const { dom } = await mount();
  await settle();
  fetches.deliver(SETTINGS_KEY, {
    settings: { xml_path: '/old/collection.xml' },
  });
  fetches.deliver(JOBS_KEY, {
    jobs: [
      jobDoc({ id: 'export-9', kind: 'export' }),
      jobDoc({
        id: 'reindex-8',
        progress: { current: 812, total: 1532, message: '[812/1532] Blawan' },
      }),
      jobDoc({ id: 'reindex-old', state: 'cancelled', cancel_requested: true }),
    ],
  });
  await settle();

  assert.equal(mounted.isRunning(), true);
  assert.equal(dom.progress.hidden, false);
  assert.equal(dom.progressLabel.textContent, 'Indexing... (812/1532)');

  await tick();
  assert.ok(fetches.outstanding(jobKey('reindex-8')), 'the reattached id was not polled');
  assert.equal(fetches.outstanding(jobKey('export-9')), false, 'Settings attached to export');
});

test('a terminal job found on reload gets an outcome panel but no surprise dialog', async () => {
  const { dom } = await mount();
  await settle();
  fetches.deliver(SETTINGS_KEY, {
    settings: { xml_path: '/old/collection.xml' },
  });
  fetches.deliver(JOBS_KEY, {
    jobs: [
      jobDoc({
        id: 'reindex-ended',
        state: 'cancelled',
        cancel_requested: true,
        finished_at: STARTED_AT + 100,
      }),
    ],
  });
  await settle();

  assert.equal(openModalCount(), 0);
  assert.equal(dom.outcome.hidden, false);
  assert.match(dom.outcome.textContent, /Reindex stopped/);
  assert.match(dom.outcome.textContent, /computed during this run were discarded/);
  assert.equal(dom.incremental.disabled, false);
});

test('the accepted job id wins over an older mount-time list response', async () => {
  const { dom } = await mount();
  await settle();
  fetches.deliver(SETTINGS_KEY, {
    settings: { xml_path: '/old/collection.xml' },
  });

  dom.incremental.dispatch('click');
  await settle();
  fetches.deliver(START_KEY, { job: jobDoc({ id: 'reindex-new' }) });
  await settle();

  fetches.deliver(JOBS_KEY, {
    jobs: [jobDoc({ id: 'reindex-old', progress: { current: 9, total: 10, message: 'Old' } })],
  });
  await settle();
  await tick();

  assert.ok(fetches.outstanding(jobKey('reindex-new')), 'the accepted job id was replaced');
  assert.equal(fetches.outstanding(jobKey('reindex-old')), false);
});

test('a lost poll keeps retrying and says the server-side reindex continues', async () => {
  const { dom } = await ready();
  dom.incremental.dispatch('click');
  await settle();
  fetches.deliver(START_KEY, { job: jobDoc() });
  await settle();

  await tick();
  fetches.reject(jobKey('reindex-1'));
  await settle();

  assert.match(dom.outcome.textContent, /Lost contact with the local server/);
  assert.match(dom.outcome.textContent, /reindex keeps going without this page/);

  await tick();
  assert.ok(fetches.outstanding(jobKey('reindex-1')), 'polling stopped after one network error');
  fetches.deliver(jobKey('reindex-1'), {
    job: jobDoc({ progress: { current: 1, total: 2, message: 'Back online' } }),
  });
  await settle();
  assert.equal(dom.outcome.hidden, true);
});
