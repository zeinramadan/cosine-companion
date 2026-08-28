/* The Export destination, driven through the shipped module.
 *
 * WHAT ONLY RUNNING IT CAN SETTLE
 * ------------------------------
 * Everything that matters about this screen is a sequence, and none of it is
 * visible in the source:
 *
 * * the two pre-export checks run in a catalogued ORDER (:599 then :601), and
 *   the order is only observable when BOTH conditions are wrong at once;
 * * the progress display is fed by a poll, so what it says depends on which
 *   job document landed and when;
 * * Stop is a request whose answer arrives later, and the completion dialog
 *   has to be raised exactly once for a job however many polls see it;
 * * re-attaching after a reload is a decision made from `GET /api/jobs`
 *   against a registry that outlived the page.
 *
 * Everything here imports src/web/static/js - no reimplementation. The DOM is
 * the documented shim, which can say what the module did and not what a user
 * saw; the visual pass stays manual and the PR description records it.
 */

import { test } from 'node:test';
import assert from 'node:assert/strict';

import { byClass, document, installGlobals, textsByClass, walk } from './dom_shim.mjs';
import {
  buildExportDom,
  installFetch,
  installLocalStorage,
  removeLocalStorage,
  resetDom,
  settle,
} from './fixture.mjs';

installGlobals();

let fetches = installFetch();

const { createStore } = await import('../../../src/web/static/js/store.js');
const { openModalCount } = await import('../../../src/web/static/js/modal.js');
const {
  mountExport,
  selectionInfo,
  selectedRows,
  confirmMessage,
  completionMessage,
  cancelledMessage,
  errorMessage,
  outputDirectoryOf,
  progressPercent,
  formatDuration,
  remainingSeconds,
  DEFAULT_RECOMMENDATIONS,
  RECOMMENDATION_OPTIONS,
  COMBINED_FILENAME,
} = await import('../../../src/web/static/js/components/export.js');

const JOBS_KEY = '/api/jobs?q=';
const LIBRARY_KEY = '/api/library/tracks?q=';
const START_KEY = '/api/jobs/export?q=';
const BROWSE_KEY = '/api/tracks?q=';
const jobKey = (id) => `/api/jobs/${id}?q=`;
const cancelKey = (id) => `/api/jobs/${id}/cancel?q=`;

/* Three tracks whose (artist, title) order is NOT their id order, so a row
 * list that forgot to sort is visibly different from one that did. */
const LIBRARY = [
  { track_id: 'a1', artist: 'Objekt', title: 'Ganzfeld', album: '', key: '8A', bpm: 130 },
  { track_id: 'b2', artist: 'Alva Noto', title: 'Xerrox', album: '', key: '', bpm: 120 },
  { track_id: 'c3', artist: 'blawan', title: 'Why They Hide', album: '', key: '4B', bpm: '' },
];

/* Epoch milliseconds, and the job's `started_at` in seconds beneath it. */
const STARTED_AT = 1_700_000_000;
let clock = STARTED_AT * 1000;

function jobDoc(overrides = {}) {
  return {
    id: 'job-1',
    kind: 'export',
    state: 'running',
    progress: { current: 0, total: 3, message: 'Exporting 3 tracks' },
    cancel_requested: false,
    started_at: STARTED_AT,
    finished_at: null,
    result: null,
    error: null,
    ...overrides,
  };
}

function resultDoc(overrides = {}) {
  return {
    mode: 'per_seed',
    output: '/Users/dj/Desktop/Cosine_Playlists',
    total_tracks: 3,
    successful: 3,
    failed: 0,
    total_recommendations: 75,
    playlists_created: 3,
    cancelled: false,
    ...overrides,
  };
}

// -- harness ----------------------------------------------------------------

let mounted = null;

async function closeDialogs() {
  for (let guard = 0; guard < 8 && openModalCount() > 0; guard += 1) {
    const panels = byClass(document.body, 'modal__panel');
    const top = panels[panels.length - 1];
    if (!top) {
      break;
    }
    top.dispatch('keydown', { key: 'Escape' });
    await settle();
  }
  assert.equal(openModalCount(), 0, 'a dialog survived the drain');
}

/**
 * A fresh destination.
 *
 * `pollIntervalMs` is a millisecond so the poll loop is drivable in a test;
 * the shipped default is half a second and the module exports it. The clock is
 * injected for the same reason `format.js` does not read one: an elapsed-time
 * label computed from the wall clock is a label a test can only assert
 * approximately.
 */
async function mount({ destination = 'export' } = {}) {
  await closeDialogs();
  if (mounted) {
    mounted.dispose();
    mounted = null;
  }
  resetDom();
  fetches = installFetch();
  const dom = buildExportDom();
  const store = createStore({ destination, library: null, libraryError: null });
  mounted = mountExport({
    store,
    pollIntervalMs: 1,
    retryIntervalMs: 1,
    now: () => clock,
  });
  return { dom, store, view: mounted };
}

test('a broken saved index replaces Export’s empty-selection invitation', async () => {
  await closeDialogs();
  if (mounted) {
    mounted.dispose();
    mounted = null;
  }
  resetDom();
  fetches = installFetch();
  const dom = buildExportDom();
  const message =
    'The saved library index is inconsistent and could not be loaded. ' +
    'Open Settings, save the path to a Rekordbox XML export, then choose ' +
    'Rebuild All Embeddings.';
  const store = createStore({
    destination: 'export',
    library: {
      track_count: 0,
      is_empty: true,
      load_error: { code: 'index_load_failed', message },
    },
    libraryError: null,
  });
  mounted = mountExport({
    store,
    pollIntervalMs: 1,
    retryIntervalMs: 1,
    now: () => clock,
  });
  await settle();

  assert.deepEqual(
    fetches.requests.map((request) => request.path),
    ['/api/jobs'],
    'Export fetched a broken index as an empty track list',
  );
  assert.deepEqual(textsByClass(dom.root, 'state__title'), [
    'Library index needs rebuilding',
  ]);
  assert.deepEqual(textsByClass(dom.root, 'state__body'), [message]);
  assert.deepEqual(textsByClass(dom.root, 'exportv__selected-empty'), []);
  assert.deepEqual(textsByClass(dom.root, 'exportv__info'), []);
});

/** Mount, answer the two requests a mount makes, and be ready to export. */
async function ready(options = {}) {
  const context = await mount(options);
  await settle();
  fetches.deliver(JOBS_KEY, { jobs: [] });
  fetches.deliver(LIBRARY_KEY, { tracks: LIBRARY, total: LIBRARY.length });
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
  assert.ok(
    found,
    `no control labelled ${label}: ${walk(document.body)
      .filter((node) => node.tagName === 'BUTTON')
      .map((node) => node.textContent)}`,
  );
  return found;
}

const generateButton = () => control('🎵 Generate Playlists');
const outputField = () => document.getElementById('export-output');
const perTrackField = () => document.getElementById('export-per-track');
const infoLine = () => byClass(document.body, 'exportv__info')[0];
const progressBlock = () => byClass(document.body, 'exportv__progress')[0];
const outcomeBlock = () => byClass(document.body, 'exportv__outcome')[0];
const dialogTitle = () => textsByClass(document.body, 'message-box__title')[0];
const dialogBody = () => textsByClass(document.body, 'message-box__message')[0];

function radioFor(value) {
  const found = walk(document.body).find(
    (node) => node.tagName === 'INPUT' && node.value === value && node.type === 'radio',
  );
  assert.ok(found, `no radio with value ${value}`);
  return found;
}

function choose(value) {
  const input = radioFor(value);
  input.checked = true;
  input.dispatch('change');
}

function postedBody(key) {
  const posted = [...fetches.requests].reverse().find((each) => each.key === key);
  assert.ok(posted, `nothing was posted to ${key}`);
  return JSON.parse(posted.options.body);
}

// ---------------------------------------------------------------------------
// The catalogued strings, as pure functions
// ---------------------------------------------------------------------------

test('the three selection-info texts and their two tones', () => {
  // :558-562. The `all` count reads the library; the `manual` counts read the
  // selection; and the empty case is the only one that is not a tick.
  assert.deepEqual(selectionInfo('all', 0, 1532), {
    text: '✓ Will generate playlists for all 1532 tracks in your collection',
    tone: 'ok',
  });
  assert.deepEqual(selectionInfo('manual', 3, 1532), {
    text: "✓ 3 track(s) selected • Click '+ Add Tracks' to add more",
    tone: 'ok',
  });
  assert.deepEqual(selectionInfo('manual', 0, 1532), {
    text: "⚠ No tracks selected. Click '+ Add Tracks' to select tracks",
    tone: 'warn',
  });
});

test('selected rows sort case-insensitively and drop ids the library lost', () => {
  const byId = new Map(LIBRARY.map((track) => [track.track_id, track]));
  const rows = selectedRows(new Set(['a1', 'c3', 'b2', 'gone']), byId);

  // :567 - `(artist.lower(), title.lower())`, so a lower-case "blawan" sorts
  // where "Blawan" would and not after every capital.
  assert.deepEqual(
    rows.map((row) => row.text),
    [
      'Alva Noto – Xerrox (120 BPM)',
      'blawan – Why They Hide [4B]',
      'Objekt – Ganzfeld [8A] (130 BPM)',
    ],
  );
  // :569 - an id absent from the library is skipped, not rendered as a blank.
  assert.deepEqual(rows.map((row) => row.track_id), ['b2', 'c3', 'a1']);
});

test('the Confirm Export body is the catalogued one, in both formats', () => {
  // :603-611, newlines included.
  assert.equal(
    confirmMessage({
      format: 'separate',
      count: 1532,
      perTrack: '25',
      outputDir: '/Users/dj/Desktop/Cosine_Playlists',
    }),
    'This will generate separate playlists for 1532 track(s),\n' +
      'with 25 recommendations per track.\n\n' +
      'Output directory: /Users/dj/Desktop/Cosine_Playlists\n\n' +
      'Continue?',
  );
  assert.match(
    confirmMessage({ format: 'combined', count: 2, perTrack: '10', outputDir: '/tmp/x' }),
    /^This will generate a single combined playlist for 2 track\(s\),\n/,
  );
});

test('the Export Complete body is the catalogued one, less the count it cannot make', () => {
  // :620-634 verbatim EXCEPT the opening `Playlists created:` line, which is a
  // filesystem claim this screen has no way to check. See `completionMessage`
  // for why per-seed mode cannot honestly print one; the literal below is the
  // whole body, so re-adding a line here fails rather than merely widening.
  assert.equal(
    completionMessage({
      result: resultDoc(),
      outputDir: '/Users/dj/Desktop/Cosine_Playlists',
    }),
    '✓ Export Complete!\n\n' +
      'Successful: 3\n' +
      'Total recommendations: 75\n' +
      'Failed: 0\n\n' +
      'Location: /Users/dj/Desktop/Cosine_Playlists\n\n' +
      'You can now import these .m3u files into Rekordbox:\n' +
      'File → Import → Playlist → Select .m3u file(s)',
  );
});

test('combined mode has a completion body at all, which is defect #10 fixed', () => {
  // :663 / defect #10: `stats['playlists_created']` raises KeyError in combined
  // mode, so the Tkinter tab shows NO dialog for an export that worked. The
  // wire sends an explicit null instead, and this reads that null rather than
  // indexing into it.
  const written = completionMessage({
    result: resultDoc({
      mode: 'combined',
      output: '/tmp/out/Cosine_Recommendations.m3u',
      playlists_created: null,
      total_recommendations: 40,
    }),
    outputDir: '/tmp/out',
  });
  assert.match(written, /^✓ Export Complete!\n\nPlaylists created: 1 \(one combined playlist\)\n/);
  assert.match(written, /Total recommendations: 40\n/);
  assert.doesNotMatch(written, /null/);

  // Nothing collected means nothing written - `export_single_playlist` only
  // calls `create_m3u_playlist` when it has ids - so the line must not claim a
  // file that is not there.
  const empty = completionMessage({
    result: resultDoc({
      mode: 'combined',
      playlists_created: null,
      total_recommendations: 0,
      successful: 0,
      failed: 3,
    }),
    outputDir: '/tmp/out',
  });
  assert.match(empty, /Playlists created: 0 \(no recommendations, so no file was written\)/);
});

test('a stopped export is told what is still on disk', () => {
  // An ADDITION - §2.6 has no cancel control. PR #25's decision is that partial
  // results are KEPT, which is the opposite of what a cancelled index run does,
  // so the message has to say which of the two this was.
  const partial = cancelledMessage({
    result: resultDoc({ successful: 47, failed: 0, total_tracks: 1532, playlists_created: 47 }),
    outputDir: '/Users/dj/Desktop/Cosine_Playlists',
  });
  assert.match(partial, /Stopped after 47 of 1532 tracks\./);
  // The opening line is where the number belongs: 47 tracks were PROCESSED,
  // which is knowable. How many files that left is not, so the sentence about
  // the directory names it without counting what is in it.
  assert.match(
    partial,
    /The playlists this run wrote are in \/Users\/dj\/Desktop\/Cosine_Playlists and have been KEPT\./,
  );
  // What STOPPING does, which the job protocol settles: the loop breaks at the
  // top, before a write, so a stop lands between tracks. Pinned as a literal
  // sentence because it is the claim, not decoration around one; it was
  // unpinned until a mutation replaced it with "Each one was removed when you
  // stopped." and the suite stayed green.
  //
  // It used to read "Each one is complete", which is a different claim and not
  // this screen's to make - a FAILED write leaves a truncated file, so "every
  // file in that folder is whole" is exactly the filesystem assertion the rest
  // of this module refuses to make. See the zero-branch test below.
  assert.match(
    partial,
    /Stopping never cut one short - the run stops between tracks, never mid-file\./,
  );
  assert.doesNotMatch(
    partial,
    /Each one is complete/,
    `the stopped body is claiming every file in the folder is whole again: ${partial}`,
  );
  assert.match(partial, /Nothing was deleted\./);

  // Combined mode writes AFTER the loop whether or not it was stopped, so a
  // stop leaves a shorter playlist rather than none.
  const combined = cancelledMessage({
    result: resultDoc({
      mode: 'combined',
      successful: 9,
      failed: 0,
      total_tracks: 100,
      playlists_created: null,
      total_recommendations: 210,
    }),
    outputDir: '/tmp/out',
  });
  assert.match(combined, /\/tmp\/out\/Cosine_Recommendations\.m3u and has been KEPT/);
  assert.match(combined, /210 recommendations from the 9 tracks/);

  // `ExportResult.cancelled` is read off the EVENT, not off whether the loop
  // broke, so a stop landing after the last seed marks the job cancelled with
  // everything written. "Cancelled" alone would send the user hunting for
  // files that are all there.
  const late = cancelledMessage({
    result: resultDoc({ successful: 3, failed: 0, total_tracks: 3, playlists_created: 3 }),
    outputDir: '/tmp/out',
  });
  assert.match(late, /^The export had already finished when you stopped it/);
});

test('the Export Error body is the catalogued one', () => {
  // :636.
  assert.equal(
    errorMessage('[Errno 2] No such file or directory'),
    'An error occurred during export:\n\n[Errno 2] No such file or directory',
  );
});

test('the directory comes back out of a combined result path', () => {
  // A reloaded page has no memory of what was typed, so `Location:` has to be
  // recoverable from the result. Per-seed's output IS the directory; combined
  // mode's is the file `_start_export` built inside it.
  assert.equal(
    outputDirectoryOf({ mode: 'per_seed', output: '/Users/dj/Desktop/Cosine_Playlists' }),
    '/Users/dj/Desktop/Cosine_Playlists',
  );
  assert.equal(
    outputDirectoryOf({ mode: 'combined', output: '/tmp/out/Cosine_Recommendations.m3u' }),
    '/tmp/out',
  );
  // A per-seed directory that happens to END with the filename is still the
  // directory: the strip is conditional on the mode.
  assert.equal(
    outputDirectoryOf({ mode: 'per_seed', output: '/tmp/Cosine_Recommendations.m3u' }),
    '/tmp/Cosine_Recommendations.m3u',
  );
  // The literal above is the one `_start_export` builds its path from
  // (`COMBINED_EXPORT_FILENAME`), so the two spellings cannot drift apart
  // without this failing.
  assert.equal(COMBINED_FILENAME, 'Cosine_Recommendations.m3u');
});

test('the progress arithmetic is determinate and cannot divide by zero', () => {
  assert.equal(progressPercent(0, 1532), 0);
  assert.equal(progressPercent(766, 1532), 50);
  assert.equal(progressPercent(1532, 1532), 100);
  // A total of zero is the one case that would render NaN% into the DOM.
  assert.equal(progressPercent(0, 0), 0);
  assert.equal(progressPercent(5, 0), 0);
});

test('durations read as durations and the estimate refuses to guess early', () => {
  assert.equal(formatDuration(0), '0s');
  assert.equal(formatDuration(59), '59s');
  assert.equal(formatDuration(60), '1m 00s');
  assert.equal(formatDuration(408), '6m 48s');

  // Nothing is claimed from zero samples, and nothing at the end.
  assert.equal(remainingSeconds(0, 1532, 10), null);
  assert.equal(remainingSeconds(1532, 1532, 400), null);
  assert.equal(remainingSeconds(10, 100, 0), null);
  // 10 of 100 in 40 s -> 4 s each -> 360 s left.
  assert.equal(remainingSeconds(10, 100, 40), 360);
});

// ---------------------------------------------------------------------------
// The destination, mounted
// ---------------------------------------------------------------------------

test('the destination opens on the catalogued defaults', async () => {
  await ready();

  // :549 - `manual` is the default. :575 - the combo defaults to 25, which is
  // NOT the API's default of 10, so it has to be sent explicitly.
  assert.equal(radioFor('manual').checked, true);
  assert.equal(radioFor('all').checked, false);
  assert.equal(radioFor('separate').checked, true);
  // The literals, not the exported constants. Comparing the rendered control
  // to the constant it was rendered FROM holds however the constant is
  // changed, which is the shape of tautology this suite has already been
  // bitten by once.
  assert.equal(perTrackField().value, '25');
  assert.deepEqual(
    perTrackField().children.map((option) => option.textContent),
    ['10', '15', '20', '25', '30', '40', '50'],
  );
  assert.equal(DEFAULT_RECOMMENDATIONS, '25');
  assert.deepEqual(RECOMMENDATION_OPTIONS, ['10', '15', '20', '25', '30', '40', '50']);

  // :562 - nothing selected is the warning tone.
  assert.equal(infoLine().textContent, "⚠ No tracks selected. Click '+ Add Tracks' to select tracks");
  assert.equal(infoLine().dataset.tone, 'warn');

  // :588 - the progress block is hidden until an export starts.
  assert.equal(progressBlock().hidden, true);
  assert.equal(outcomeBlock().hidden, true);
});

test('the two pre-export checks run in the catalogued order', async () => {
  await ready();
  // Both conditions are wrong: no tracks AND no directory. :599 comes first,
  // and that ordering is the whole reason this is a behavioural test.
  assert.equal(outputField().value, '');

  generateButton().dispatch('click');
  await settle();

  assert.equal(dialogTitle(), 'No Tracks Selected');
  assert.equal(dialogBody(), 'Please select tracks to export playlists for.');
  assert.equal(fetches.outstanding(START_KEY), false, 'a refusal still started an export');

  control('OK').dispatch('click');
  await settle();

  // Fix only the tracks, and the SECOND check is the one that answers.
  choose('all');
  generateButton().dispatch('click');
  await settle();

  assert.equal(dialogTitle(), 'No Output Directory');
  assert.equal(dialogBody(), 'Please select an output directory.');
  assert.equal(fetches.outstanding(START_KEY), false);
});

test('a directory of only spaces is blank', async () => {
  await ready();
  choose('all');
  outputField().value = '   ';

  generateButton().dispatch('click');
  await settle();

  // playlist_export_tab.py:366 reads the raw variable, so spaces pass there and
  // then fail at `_path_field` as a 400 seven layers away. Blank is blank.
  assert.equal(dialogTitle(), 'No Output Directory');
});

test('declining the confirmation starts nothing', async () => {
  await ready();
  choose('all');
  outputField().value = '/tmp/out';

  generateButton().dispatch('click');
  await settle();

  assert.equal(dialogTitle(), 'Confirm Export');
  assert.equal(
    dialogBody(),
    confirmMessage({ format: 'separate', count: 3, perTrack: '25', outputDir: '/tmp/out' }),
  );

  control('No').dispatch('click');
  await settle();
  assert.equal(fetches.outstanding(START_KEY), false, 'a declined export was started anyway');
});

test('all-tracks mode omits track_ids; manual mode sends them', async () => {
  await ready();
  choose('all');
  outputField().value = '/tmp/out';
  generateButton().dispatch('click');
  await settle();
  control('Yes').dispatch('click');
  await settle();

  const whole = postedBody(START_KEY);
  // The 1,532-id selection is 14.7 KiB against a 16 KiB body ceiling, so the
  // measured case is exactly the one that does not fit. Absent means "all".
  assert.deepEqual(whole, {
    mode: 'per_seed',
    out_dir: '/tmp/out',
    recommendations_per_track: 25,
  });
  assert.equal('track_ids' in whole, false);

  // Manual mode, combined format, a different count.
  await ready();
  const view = byClass(document.body, 'exportv')[0];
  assert.ok(view);
  control('+ Add Tracks').dispatch('click');
  await settle();
  fetches.deliver(BROWSE_KEY, {
    tracks: LIBRARY.map((track) => ({ ...track, display_name: `${track.artist} – ${track.title}` })),
  });
  await settle();
  byClass(document.body, 'picker__option')[0].dispatch('click', {});
  byClass(document.body, 'picker__option')[2].dispatch('click', { metaKey: true });
  control('Add Selected Tracks').dispatch('click');
  await settle();

  assert.equal(infoLine().textContent, "✓ 2 track(s) selected • Click '+ Add Tracks' to add more");

  choose('combined');
  perTrackField().value = '40';
  outputField().value = '/tmp/out';
  generateButton().dispatch('click');
  await settle();
  control('Yes').dispatch('click');
  await settle();

  assert.deepEqual(postedBody(START_KEY), {
    mode: 'combined',
    out_dir: '/tmp/out',
    recommendations_per_track: 40,
    track_ids: 'a1\nc3',
  });
});

test('progress is determinate and says what it is doing', async () => {
  await ready();
  choose('all');
  outputField().value = '/tmp/out';
  generateButton().dispatch('click');
  await settle();
  control('Yes').dispatch('click');
  await settle();

  fetches.deliver(START_KEY, { job: jobDoc() });
  await settle();

  // :613 - the button is disabled and the progress block appears.
  assert.equal(progressBlock().hidden, false);
  assert.equal(generateButton().disabled, true);
  assert.equal(outputField().disabled, true);
  // :614 - before the first seed is reported there is no count, because the
  // job's own message is "Exporting 3 tracks", which is not a track.
  assert.equal(textsByClass(document.body, 'progress__label')[0], 'Generating playlists...');
  assert.equal(textsByClass(document.body, 'progress__status')[0], '');

  await tick();
  clock = (STARTED_AT + 40) * 1000;
  fetches.deliver(jobKey('job-1'), {
    job: jobDoc({ progress: { current: 1, total: 3, message: 'Blawan - Why They Hide' } }),
  });
  await settle();

  // :615-617 - the bar is a fraction, the label carries i and N, and the status
  // carries the exporter's own `{artist} - {title}` with its plain hyphen.
  const fill = byClass(document.body, 'progress__fill')[0];
  assert.equal(fill.style.properties.get('--progress'), '33.3%');
  const track = byClass(document.body, 'progress__track')[0];
  assert.equal(track.getAttribute('aria-valuenow'), '33');
  assert.equal(track.getAttribute('role'), 'progressbar');
  assert.equal(textsByClass(document.body, 'progress__label')[0], 'Generating playlists... (1/3)');
  assert.equal(
    textsByClass(document.body, 'progress__status')[0],
    'Current: Blawan - Why They Hide',
  );
  // 40 s for one of three, so about 80 s to go. An indeterminate bar could say
  // none of this while the job reported every part of it.
  assert.equal(
    textsByClass(document.body, 'progress__timing')[0],
    '40s elapsed · about 1m 20s remaining',
  );

  clock = STARTED_AT * 1000;
});

test('Stop cancels, and the screen says what a stop leaves behind', async () => {
  await ready();
  choose('all');
  outputField().value = '/tmp/out';
  generateButton().dispatch('click');
  await settle();
  control('Yes').dispatch('click');
  await settle();
  fetches.deliver(START_KEY, { job: jobDoc() });
  await settle();

  // The consequence is stated BEFORE the button is pressed, not only after.
  assert.equal(
    textsByClass(document.body, 'progress__note')[0],
    'Stopping keeps every playlist already written — nothing is deleted.',
  );

  control('Stop Export').dispatch('click');
  await settle();
  assert.ok(fetches.outstanding(cancelKey('job-1')), 'Stop sent no cancel');
  // The endpoint takes no fields, and `{}` is how "no fields" is spelled over a
  // transport that refuses a POST with no Content-Type.
  assert.deepEqual(postedBody(cancelKey('job-1')), {});

  fetches.deliver(cancelKey('job-1'), {
    job: jobDoc({
      cancel_requested: true,
      progress: { current: 2, total: 3, message: 'Objekt - Ganzfeld' },
    }),
  });
  await settle();

  assert.equal(control('Stopping…').disabled, true);
  assert.match(textsByClass(document.body, 'progress__note')[0], /Everything already written is kept\./);

  await tick();
  fetches.deliver(jobKey('job-1'), {
    job: jobDoc({
      state: 'cancelled',
      cancel_requested: true,
      finished_at: STARTED_AT + 90,
      progress: { current: 2, total: 3, message: 'Objekt - Ganzfeld' },
      result: resultDoc({
        cancelled: true,
        successful: 2,
        failed: 0,
        playlists_created: 2,
        output: '/tmp/out',
      }),
    }),
  });
  await settle();

  assert.equal(dialogTitle(), 'Export Stopped');
  assert.match(dialogBody(), /Stopped after 2 of 3 tracks\./);
  assert.match(dialogBody(), /The playlists this run wrote are in \/tmp\/out and have been KEPT\./);

  control('OK').dispatch('click');
  await settle();

  // The progress block goes away (:588 `pack_forget()`), the controls come
  // back, and the account of the run stays on screen.
  assert.equal(progressBlock().hidden, true);
  assert.equal(generateButton().disabled, false);
  assert.equal(outcomeBlock().hidden, false);
  assert.match(outcomeBlock().textContent, /Export stopped/);
  assert.match(outcomeBlock().textContent, /have been KEPT/);
});

test('a finished export raises the completion dialog exactly once', async () => {
  await ready();
  choose('all');
  outputField().value = '/tmp/out';
  generateButton().dispatch('click');
  await settle();
  control('Yes').dispatch('click');
  await settle();
  fetches.deliver(START_KEY, { job: jobDoc() });
  await settle();

  await tick();
  const done = {
    job: jobDoc({
      state: 'succeeded',
      finished_at: STARTED_AT + 120,
      progress: { current: 3, total: 3, message: 'Objekt - Ganzfeld' },
      result: resultDoc({ output: '/tmp/out' }),
    }),
  };
  fetches.deliver(jobKey('job-1'), done);
  await settle();

  assert.equal(dialogTitle(), 'Export Complete');
  assert.equal(
    dialogBody(),
    completionMessage({ result: done.job.result, outputDir: '/tmp/out' }),
  );
  assert.equal(openModalCount(), 1);

  control('OK').dispatch('click');
  await settle();

  // Nothing is polling any more, so a stray answer cannot raise a second one.
  assert.equal(fetches.outstanding(jobKey('job-1')), false);
  await tick(10);
  assert.equal(openModalCount(), 0);
});

test('a combined export raises its completion dialog, MOUNTED - defect #10', async () => {
  /* The defect is "a successful combined export shows NO dialog at all", and
   * only a mounted run can miss it. `completionMessage` is a pure function: it
   * cannot fail to be CALLED, so calling it directly proves the string is
   * right and proves nothing about whether anything reaches it. Everything
   * between the radio and the dialog is what defect #10 lives in - the format
   * the request carries, the mode that comes back, and `finished()` deciding
   * what to raise for it - so all of it runs here.
   *
   * The per-seed twin of this test already existed. That is exactly why this
   * one has to: a mutant that returned early from `finished()` for combined
   * successes ONLY left all 26 tests green, because no mounted test had ever
   * driven a combined job to a terminal state.
   */
  await ready();
  choose('all');
  choose('combined');
  outputField().value = '/tmp/out';
  generateButton().dispatch('click');
  await settle();
  // The confirmation is the combined one, so the run under test really is the
  // combined path and not a per-seed run wearing a combined result.
  assert.match(dialogBody(), /^This will generate a single combined playlist for 3 track\(s\),\n/);
  control('Yes').dispatch('click');
  await settle();
  assert.equal(postedBody(START_KEY).mode, 'combined');

  fetches.deliver(START_KEY, { job: jobDoc({ mode: 'combined' }) });
  await settle();

  await tick();
  /* What the wire really sends for combined mode: `playlists_created` is an
   * explicit null - `web/api.py::_export_result_document` - and the output is
   * the FILE, not the directory. Both are the shape defect #10 tripped over. */
  const done = {
    job: jobDoc({
      state: 'succeeded',
      finished_at: STARTED_AT + 120,
      progress: { current: 3, total: 3, message: 'Objekt - Ganzfeld' },
      result: resultDoc({
        mode: 'combined',
        output: `/tmp/out/${COMBINED_FILENAME}`,
        playlists_created: null,
        total_recommendations: 40,
      }),
    }),
  };
  fetches.deliver(jobKey('job-1'), done);
  await settle();

  // A DIALOG EXISTS. This is the assertion the defect is about; the rest is
  // the dialog being the right one.
  assert.equal(openModalCount(), 1);
  assert.equal(dialogTitle(), 'Export Complete');
  assert.match(dialogBody(), /^✓ Export Complete!\n\nPlaylists created: 1 \(one combined playlist\)\n/);
  // The directory, recovered from the file path - not the file.
  assert.match(dialogBody(), /Location: \/tmp\/out\n/);
  assert.doesNotMatch(dialogBody(), /null/);

  control('OK').dispatch('click');
  await settle();
  assert.equal(openModalCount(), 0);
  assert.equal(generateButton().disabled, false);
});

test('the completion dialog states no per-seed file count, however the service counts', async () => {
  /* NOT an echo of the counter. The job below reports `playlists_created:
   * 9182` against three successful tracks - a document no real export could
   * produce - so that number can only reach the screen one way: by the screen
   * reading the service's playlist counter and printing it. Asserting it is
   * ABSENT fails for any wording that puts that counter in front of a user,
   * which the previous test could not do: it supplied 3 and asserted 3, so
   * every possible value of the counter satisfied it.
   *
   * Why it must be absent at all: `playlists_created` counts write calls that
   * did not raise, and `playlist_filename` gives two seeds with the same
   * "artist - title" the same name, so the writes overwrite. On the real
   * collection the service reports 1532 and the directory holds 1529. A
   * dialog that prints the counter under any label a user reads as a file
   * tally is stating a number the filesystem contradicts.
   */
  await ready();
  choose('all');
  outputField().value = '/tmp/out';
  generateButton().dispatch('click');
  await settle();
  control('Yes').dispatch('click');
  await settle();
  fetches.deliver(START_KEY, { job: jobDoc() });
  await settle();

  await tick();
  fetches.deliver(jobKey('job-1'), {
    job: jobDoc({
      state: 'succeeded',
      finished_at: STARTED_AT + 120,
      progress: { current: 3, total: 3, message: 'Objekt - Ganzfeld' },
      result: resultDoc({ output: '/tmp/out', successful: 3, playlists_created: 9182 }),
    }),
  });
  await settle();

  assert.equal(dialogTitle(), 'Export Complete');
  const body = dialogBody();
  assert.doesNotMatch(body, /9182/, `the service's playlist counter reached the user: ${body}`);
  /* And no other spelling of a tally either - the sentinel alone would miss a
   * line that fabricated a count from `successful` instead. The accounting
   * block is the head of the body, above `Location:`; the catalogued Rekordbox
   * instruction below it says "Playlist" and ".m3u" while claiming nothing, so
   * the check is scoped to where a claim would actually be made. In per-seed
   * mode that block says nothing about playlists at all. */
  assert.match(body, /\nLocation:/, `no Location line to split the accounting block on: ${body}`);
  const accounting = body.split('\nLocation:')[0];
  assert.doesNotMatch(
    accounting,
    /playlist/i,
    `a playlist claim is back in the per-seed accounting block: ${accounting}`,
  );
  // What it does still say - the number that IS knowable, and where to look.
  assert.match(body, /Successful: 3\n/);
  assert.match(body, /Location: \/tmp\/out\n/);
});

test('the stopped dialog states no file count either, however the service counts', async () => {
  // The same probe on the other terminal dialog, which called the counter
  // "playlist(s) written" and so carried the same claim.
  const stopped = cancelledMessage({
    result: resultDoc({
      cancelled: true,
      total_tracks: 1532,
      successful: 398,
      failed: 0,
      playlists_created: 9182,
    }),
    outputDir: '/tmp/out',
  });
  assert.doesNotMatch(stopped, /9182/, `the service's playlist counter reached the user: ${stopped}`);
  assert.doesNotMatch(
    stopped,
    /\d+\s*playlist/i,
    `a numbered playlist claim is back in the stopped body: ${stopped}`,
  );
  // The honest number survives, on the thing a stop is actually measured in.
  assert.match(stopped, /Stopped after 398 of 1532 tracks\./);
  assert.match(stopped, /Nothing was deleted\./);

  // Zero is not a count that survives either - see the dedicated test below.
  const none = cancelledMessage({
    result: resultDoc({ cancelled: true, total_tracks: 1532, successful: 0, failed: 1 }),
    outputDir: '/tmp/out',
  });
  assert.doesNotMatch(none, /\d+\s*playlist/i, `a numbered playlist claim reached the zero branch: ${none}`);
});

// Every shape the old claim could come back in. A literal-string check would
// pass the moment someone rewrote the sentence, and the defect is the CLAIM,
// not the wording - "this run left nothing", "no files were written", "the
// folder is empty" are the same assertion three ways.
const ABSENCE_CLAIMS = [
  /left nothing/i,
  /nothing (?:was |had been )?(?:written|created|saved|left)/i,
  /\bno files?\b/i,
  /(?:directory|folder) is empty/i,
  /nothing (?:is )?in \/tmp\/out/i,
];

test('the zero-success stop never claims the directory is empty', () => {
  // BLOCKER, round 3. This branch read "No playlist had been written when you
  // stopped, so this run left nothing in {dir}". The first half is knowable;
  // the second does not follow from it. `create_m3u_playlist` opens the
  // destination with mode 'w' and writes `#EXTM3U` BEFORE it iterates, so a
  // write that raises partway leaves a truncated .m3u behind and the caller's
  // `except Exception` books it as `failed`. `successful === 0` means no write
  // CALL RETURNED - not that nothing was written.
  //
  // The whole sequence is reproduced end to end against the real service in
  // tests/web/test_jobs_real_export.py::test_a_failed_write_leaves_a_partial_playlist_behind:
  // all-zero stats, and a file in the directory.
  const none = cancelledMessage({
    result: resultDoc({ cancelled: true, total_tracks: 1532, successful: 0, failed: 1 }),
    outputDir: '/tmp/out',
  });

  for (const claim of ABSENCE_CLAIMS) {
    assert.doesNotMatch(
      none,
      claim,
      `the zero branch asserts an absence of files again (${claim}): ${none}`,
    );
  }

  // And the claim it does make, which is the screen's to make: nothing
  // finished, so nothing is importable - plus the caveat that replaced the
  // guarantee, and the folder to look in.
  assert.match(none, /No playlist was finished before you stopped/);
  assert.match(none, /nothing from this run to import/);
  assert.match(none, /A write that fails partway can still leave an unfinished file behind/);
  assert.match(none, /check \/tmp\/out before importing from it\./);
});

test('the combined zero branch may still claim the absence, because there it holds', () => {
  // Not an oversight that this one was left alone. `export_single_playlist`
  // guards the write with `if all_recommendations`, so no recommendations
  // means `create_m3u_playlist` is never CALLED - there is no opened handle to
  // leave anything behind. And a raise inside it would propagate out of the
  // service rather than return these stats, so this branch would never render.
  const empty = cancelledMessage({
    result: resultDoc({
      mode: 'combined',
      cancelled: true,
      total_tracks: 100,
      successful: 0,
      failed: 0,
      playlists_created: null,
      total_recommendations: 0,
    }),
    outputDir: '/tmp/out',
  });
  assert.match(empty, /No recommendations had been collected yet, so no playlist file was written\./);
});

// Every shape an honest disclosure of a failed write could take. The blocker
// was an OMISSION rather than a false claim, so the mirror of ABSENCE_CLAIMS
// above is a floor rather than a ceiling: one of these must match. A reworded
// disclosure keeps this green; a deleted one turns it red.
const FAILURE_DISCLOSURES = [
  /did not export/i,
  /\bfail(?:ed|ure|s)?\b/i,
  /unfinished file/i,
  /incomplete/i,
  /truncated/i,
];

test('a stop that had failures says so, instead of only reassuring about stopping', () => {
  // BLOCKER, round 4. Reproduced against the real service in
  // tests/web/test_jobs_real_export.py: `successful=1, failed=1,
  // cancelled=true, total_tracks=3` left ONE complete 9-line playlist and ONE
  // header-only partial in the directory. This branch rendered only "The
  // playlists this run wrote are in {dir} and have been KEPT. Stopping never
  // cut one short - the run stops between tracks, never mid-file."
  //
  // Every word of that is true. It is still misleading, because the failure is
  // never mentioned AT ALL: the user is pointed at a folder and reassured
  // about it while one of the files in it is unsafe to import. The causal
  // claim was correctly scoped to what stopping does; the BODY was not scoped
  // to what the run did.
  const mixed = cancelledMessage({
    result: resultDoc({
      cancelled: true,
      total_tracks: 3,
      successful: 1,
      failed: 1,
      playlists_created: 1,
    }),
    outputDir: '/tmp/out',
  });

  // The rewording-proof floor, checked FIRST so a mutation that rewords the
  // disclosure is visibly caught by the literals below rather than by this.
  // The defect is the SILENCE, so the property is that the body says something
  // about the failure, in any of the shapes an honest one could take.
  assert.ok(
    FAILURE_DISCLOSURES.some((claim) => claim.test(mixed)),
    `the stopped body says nothing whatever about the failed track: ${mixed}`,
  );

  // The disclosure that was missing, as it is actually worded.
  assert.match(mixed, /1 of the tracks processed did not export\./);
  // ...and what it means for the folder the sentence before it just named.
  // Same hedge and the same sentence as the zero branch, for the same reason:
  // `failed` is one integer over three causes and only one of them opens a
  // file, so a POSSIBILITY is the most this screen can honestly state.
  assert.match(mixed, /A write that fails partway can still leave an unfinished file behind/);
  assert.match(mixed, /check \/tmp\/out before importing from it\./);

  // The true causal sentence SURVIVES - the fix is a scope, not a deletion.
  // Partial results are still kept and the user still needs to know that.
  assert.match(
    mixed,
    /Stopping never cut one short - the run stops between tracks, never mid-file\./,
  );

  // The defect shape itself, independent of how the disclosure is worded: the
  // reassurance must not be the last thing the body says. Reword the two
  // sentences above and this stays green; delete them and it goes red.
  assert.doesNotMatch(
    mixed,
    /never mid-file\.\n\nNothing was deleted\.$/,
    `the stopped body reassures about the folder and stops, with the failure never mentioned: ${mixed}`,
  );

  // Nothing failed means nothing to warn about, so a clean stop is unchanged.
  const clean = cancelledMessage({
    result: resultDoc({
      cancelled: true,
      total_tracks: 3,
      successful: 2,
      failed: 0,
      playlists_created: 2,
    }),
    outputDir: '/tmp/out',
  });
  assert.doesNotMatch(clean, /unfinished file/, `a clean stop is being warned about: ${clean}`);
  assert.doesNotMatch(clean, /did not export/, `a clean stop is being warned about: ${clean}`);

  // Combined mode gets no caveat, and that is a finding rather than an
  // omission. `export_single_playlist` increments `failed` only on its two
  // ranking paths; its single `create_m3u_playlist` call sits AFTER the loop,
  // guarded by `if all_recommendations` and wrapped in no `except`, so a raise
  // there propagates out and fails the JOB rather than returning these stats.
  // `failed > 0` in combined mode says nothing about the disk, and a warning
  // about unfinished files would have no referent.
  const combinedMixed = cancelledMessage({
    result: resultDoc({
      mode: 'combined',
      cancelled: true,
      total_tracks: 3,
      successful: 1,
      failed: 2,
      playlists_created: null,
      total_recommendations: 12,
    }),
    outputDir: '/tmp/out',
  });
  assert.doesNotMatch(
    combinedMixed,
    /unfinished file/,
    `a caveat with nothing behind it reached combined mode: ${combinedMixed}`,
  );
});

test('the completion body qualifies its import instruction when a write failed', () => {
  // Found by auditing the COMPLETED dialog for the blocker above. It does NOT
  // have the same omission: `Failed: ${result.failed}` is its own line, so the
  // failure is disclosed and always was. What it did not say is what that
  // number means for the disk - and the lines right after it tell the user to
  // import "these .m3u files", which in per-seed mode can include the
  // header-only file a raised write left behind. The count without the
  // consequence is the weaker version of the same defect, so it gets the same
  // sentence.
  const withFailure = completionMessage({
    result: resultDoc({ successful: 2, failed: 1, total_tracks: 3, playlists_created: 2 }),
    outputDir: '/tmp/out',
  });
  assert.match(withFailure, /Failed: 1\n/);
  assert.match(
    withFailure,
    /A write that fails partway can still leave an unfinished file behind, so check \/tmp\/out before importing from it\.$/,
    `the completion body invites an unqualified import with a failed write in the run: ${withFailure}`,
  );

  // The clean per-seed body is pinned as a whole literal by "the completion
  // body states no playlist count" above, so a caveat leaking into a run with
  // no failures fails there rather than here.

  // Combined mode, again with no caller - see `partialFileCaveat`.
  const combined = completionMessage({
    result: resultDoc({
      mode: 'combined',
      successful: 1,
      failed: 2,
      playlists_created: null,
      total_recommendations: 12,
    }),
    outputDir: '/tmp/out',
  });
  assert.doesNotMatch(
    combined,
    /unfinished file/,
    `a caveat with nothing behind it reached the combined completion body: ${combined}`,
  );
});

test('a failed export raises the catalogued error dialog', async () => {
  await ready();
  choose('all');
  outputField().value = '/tmp/out';
  generateButton().dispatch('click');
  await settle();
  control('Yes').dispatch('click');
  await settle();
  fetches.deliver(START_KEY, { job: jobDoc() });
  await settle();

  await tick();
  fetches.deliver(jobKey('job-1'), {
    job: jobDoc({
      state: 'failed',
      finished_at: STARTED_AT + 3,
      error: "[Errno 2] No such file or directory: '/nope'",
    }),
  });
  await settle();

  // :636.
  assert.equal(dialogTitle(), 'Export Error');
  assert.equal(
    dialogBody(),
    "An error occurred during export:\n\n[Errno 2] No such file or directory: '/nope'",
  );
  control('OK').dispatch('click');
  await settle();
  assert.equal(generateButton().disabled, false);
});

test('a 409 names the run that is holding the lock instead of failing silently', async () => {
  await ready();
  choose('all');
  outputField().value = '/tmp/out';
  generateButton().dispatch('click');
  await settle();
  control('Yes').dispatch('click');
  await settle();

  fetches.deliverError(
    START_KEY,
    409,
    'job_in_progress',
    'the export job job-0 is still running',
  );
  await settle();

  assert.equal(dialogTitle(), 'Export Already Running');
  assert.equal(dialogBody(), 'the export job job-0 is still running');

  control('OK').dispatch('click');
  await settle();

  // And it goes and finds that run, so the screen shows what refused it.
  assert.ok(fetches.outstanding(JOBS_KEY), 'the refusal did not look for the running job');
  fetches.deliver(JOBS_KEY, { jobs: [jobDoc({ id: 'job-0' })] });
  await settle();
  assert.equal(progressBlock().hidden, false);
});

test('a reload mid-export re-attaches to the running job', async () => {
  // THE POINT OF THE REGISTRY. `JobRegistry` outlives the request that made it,
  // so an export started seven minutes ago survives a ⌘R - but the page has
  // lost the id it was given, which is why GET /api/jobs exists. Nothing in
  // this test starts an export: the run predates the mount.
  await mount({ destination: 'explore' });
  await settle();

  assert.ok(fetches.outstanding(JOBS_KEY), 'a fresh page did not look for a running job');
  fetches.deliver(JOBS_KEY, {
    jobs: [
      jobDoc({ progress: { current: 812, total: 1532, message: 'Blawan - Why They Hide' } }),
      jobDoc({ id: 'older', state: 'succeeded', result: resultDoc() }),
    ],
  });
  await settle();

  assert.equal(mounted.isRunning(), true);
  assert.equal(progressBlock().hidden, false);
  assert.equal(
    textsByClass(document.body, 'progress__label')[0],
    'Generating playlists... (812/1532)',
  );

  // And it goes on polling the job it found, so the completion dialog still
  // arrives for a run this page never started.
  await tick();
  assert.ok(fetches.outstanding(jobKey('job-1')), 'the re-attached job is not being polled');
  fetches.deliver(jobKey('job-1'), {
    job: jobDoc({
      state: 'succeeded',
      finished_at: STARTED_AT + 408,
      progress: { current: 1532, total: 1532, message: 'Objekt - Ganzfeld' },
      result: resultDoc({ total_tracks: 1532, successful: 1532, playlists_created: 1532 }),
    }),
  });
  await settle();

  assert.equal(dialogTitle(), 'Export Complete');
  control('OK').dispatch('click');
  await settle();
});

test('a job that ended before this page existed gets the panel and no dialog', async () => {
  await mount({ destination: 'export' });
  await settle();
  fetches.deliver(JOBS_KEY, {
    jobs: [
      jobDoc({
        id: 'ended',
        state: 'cancelled',
        cancel_requested: true,
        finished_at: STARTED_AT + 200,
        result: resultDoc({
          cancelled: true,
          successful: 47,
          total_tracks: 1532,
          playlists_created: 47,
          output: '/Users/dj/Desktop/Cosine_Playlists',
        }),
      }),
    ],
  });
  fetches.deliver(LIBRARY_KEY, { tracks: LIBRARY, total: LIBRARY.length });
  await settle();

  // A modal raised on load for a run nobody was watching is a surprise; the
  // account of it is not.
  assert.equal(openModalCount(), 0);
  assert.equal(outcomeBlock().hidden, false);
  assert.match(outcomeBlock().textContent, /Export stopped/);
  assert.match(outcomeBlock().textContent, /The playlists this run wrote are in/);
  assert.match(outcomeBlock().textContent, /Cosine_Playlists and have been KEPT/);
  assert.equal(generateButton().disabled, false);
});

test('a lost connection keeps asking and says the run is unaffected', async () => {
  await ready();
  choose('all');
  outputField().value = '/tmp/out';
  generateButton().dispatch('click');
  await settle();
  control('Yes').dispatch('click');
  await settle();
  fetches.deliver(START_KEY, { job: jobDoc() });
  await settle();

  await tick();
  fetches.reject(jobKey('job-1'));
  await settle();

  assert.equal(outcomeBlock().hidden, false);
  assert.match(outcomeBlock().textContent, /Lost contact with the local server/);
  assert.match(outcomeBlock().textContent, /the export keeps going without this page/);

  // It is still asking, and one good answer clears the notice.
  await tick();
  assert.ok(fetches.outstanding(jobKey('job-1')), 'it gave up on a job that is still running');
  fetches.deliver(jobKey('job-1'), {
    job: jobDoc({ progress: { current: 2, total: 3, message: 'Objekt - Ganzfeld' } }),
  });
  await settle();
  assert.equal(outcomeBlock().hidden, true);
});

test('the output directory is remembered, and survives storage that throws', async () => {
  const storage = installLocalStorage();
  try {
    await ready();
    choose('all');
    outputField().value = '/Users/dj/Desktop/Cosine_Playlists';
    generateButton().dispatch('click');
    await settle();
    control('Yes').dispatch('click');
    await settle();

    assert.equal(
      storage.store.get('coco.export.output-dir'),
      '/Users/dj/Desktop/Cosine_Playlists',
    );

    // The next page load starts on it, which is what makes a field with no
    // catalogued default usable more than once.
    await ready();
    assert.equal(outputField().value, '/Users/dj/Desktop/Cosine_Playlists');
  } finally {
    removeLocalStorage();
  }

  // Safari in a private window throws on the accessor itself. A forgotten path
  // is an inconvenience; a destination that fails to mount is not.
  installLocalStorage({ failing: true });
  try {
    await ready();
    assert.equal(outputField().value, '');
    assert.equal(byClass(document.body, 'exportv').length, 1);
  } finally {
    removeLocalStorage();
  }
});

test('a library that will not load says so instead of showing a count of zero', async () => {
  await mount({ destination: 'export' });
  await settle();
  fetches.deliver(JOBS_KEY, { jobs: [] });
  fetches.deliverError(LIBRARY_KEY, 409, 'empty_library', 'This library has no index yet.');
  await settle();

  assert.equal(infoLine().textContent, '⚠ This library has no index yet.');
  assert.equal(infoLine().dataset.tone, 'warn');
  // And Generate stays out of reach rather than warning about no tracks.
  assert.equal(generateButton().disabled, true);
});

test('the selected list can drop one row without losing the rest', async () => {
  await ready();
  control('+ Add Tracks').dispatch('click');
  await settle();
  fetches.deliver(BROWSE_KEY, {
    tracks: LIBRARY.map((track) => ({ ...track, display_name: `${track.artist} – ${track.title}` })),
  });
  await settle();
  control('Select All').dispatch('click');
  control('Add Selected Tracks').dispatch('click');
  await settle();

  assert.equal(byClass(document.body, 'exportv__row').length, 3);

  // An ADDITION: :552 records that the Tk listbox has no per-row remove and
  // that selecting a row in it does nothing at all, so `Clear All` was the only
  // undo and one mis-added track cost the whole selection.
  byClass(document.body, 'exportv__row-remove')[0].dispatch('click');
  await settle();

  assert.deepEqual(
    textsByClass(document.body, 'exportv__row-text'),
    ['blawan – Why They Hide [4B]', 'Objekt – Ganzfeld [8A] (130 BPM)'],
  );
  assert.equal(infoLine().textContent, "✓ 2 track(s) selected • Click '+ Add Tracks' to add more");

  control('Clear All').dispatch('click');
  await settle();
  assert.equal(byClass(document.body, 'exportv__row').length, 0);
  assert.equal(infoLine().dataset.tone, 'warn');
});
