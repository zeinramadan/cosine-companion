/* `TrackSelectorDialog` (inventory §2.11), driven through the shipped module.
 *
 * WHAT ONLY RUNNING IT CAN SETTLE
 * ------------------------------
 * :932 records that the dialog opens EMPTY because search implementation A
 * returns `[]` for a blank query. Whether the web dialog opens on a browse
 * instead - and at :931's limit of 100 rather than the palette's 50 - is a
 * question about which REQUEST is made at open, which no source-text check can
 * answer. Same for the tick prefix (:934), which depends on the caller's live
 * set at render time, and for `Add Selected Tracks` with nothing selected
 * (:936), which is decided by a selection state that only exists at runtime.
 *
 * Everything here imports src/web/static/js - no reimplementation.
 */

import { test } from 'node:test';
import assert from 'node:assert/strict';

import { byClass, document, installGlobals, textsByClass, walk } from './dom_shim.mjs';
import { buildExportDom, installFetch, resetDom, settle } from './fixture.mjs';

installGlobals();

let fetches = installFetch();

const { openTrackSelectorDialog, selectionCountText, ALREADY_SELECTED_PREFIX } = await import(
  '../../../src/web/static/js/components/track-selector-dialog.js'
);
const { openModalCount } = await import('../../../src/web/static/js/modal.js');

const BROWSE_KEY = '/api/tracks?q=';
const searchKey = (query) => `/api/tracks/search?q=${query}`;

const TRACKS = [
  { track_id: 'a1', artist: 'Blawan', title: 'Why They Hide', display_name: 'Blawan – Why They Hide' },
  { track_id: 'b2', artist: 'Alva Noto', title: 'Xerrox', display_name: 'Alva Noto – Xerrox' },
  { track_id: 'c3', artist: 'Objekt', title: 'Ganzfeld', display_name: 'Objekt – Ganzfeld' },
];

/* `modal.js`'s stack is module state and outlives one test. A dialog left
 * open would make the NEXT test's `beneath(0)` the stale dialog's root rather
 * than the shell, so the modality assertion would be asking about a node
 * nothing is looking at. Drained here rather than trusted to each test. */
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

/** A fresh document and a fresh fetch double for one test. */
async function fresh() {
  await closeDialogs();
  resetDom();
  fetches = installFetch();
  return buildExportDom();
}

function options() {
  return byClass(document.body, 'picker__option');
}

function panel() {
  return byClass(document.body, 'modal__panel')[0];
}

function control(label) {
  const found = walk(document.body).find(
    (node) => node.tagName === 'BUTTON' && node.textContent === label,
  );
  assert.ok(found, `no control labelled ${label}: ${walk(document.body)
    .filter((node) => node.tagName === 'BUTTON')
    .map((node) => node.textContent)}`);
  return found;
}

function countText() {
  return textsByClass(document.body, 'track-selector__count')[0];
}

function searchField() {
  return document.getElementById('track-selector-search');
}

// ---------------------------------------------------------------------------

test('the three catalogued count strings, and only those', () => {
  // :923 - `0 tracks selected`, `1 track selected`, `{n} tracks selected`.
  assert.equal(selectionCountText(0), '0 tracks selected');
  assert.equal(selectionCountText(1), '1 track selected');
  assert.equal(selectionCountText(2), '2 tracks selected');
  assert.equal(selectionCountText(47), '47 tracks selected');
});

test('the dialog opens on a browse at limit 100, not on nothing', async () => {
  await fresh();
  openTrackSelectorDialog({ alreadySelected: new Set() });
  await settle();

  // DIVERGENCE from :932 (defect #9): implementation A answers a blank query
  // with `[]`, so the Tk dialog opens empty. This asks the browse endpoint.
  const opening = fetches.requests.at(-1);
  assert.equal(opening.path, '/api/tracks');
  // :931 - `limit = 100 if not query else 50`. The number is the contract.
  assert.equal(opening.params.limit, '100');

  fetches.deliver(BROWSE_KEY, { tracks: TRACKS });
  await settle();

  assert.deepEqual(
    options().map((node) => node.textContent),
    ['Blawan – Why They Hide', 'Alva Noto – Xerrox', 'Objekt – Ganzfeld'],
  );
  assert.equal(countText(), '0 tracks selected');
});

test('typing searches at limit 50', async () => {
  await fresh();
  openTrackSelectorDialog({ alreadySelected: new Set() });
  await settle();
  fetches.deliver(BROWSE_KEY, { tracks: TRACKS });
  await settle();

  searchField().value = 'blawan';
  searchField().dispatch('input');
  await new Promise((resolve) => setTimeout(resolve, 180));

  const search = fetches.requests.at(-1);
  assert.equal(search.path, '/api/tracks/search');
  assert.equal(search.params.limit, '50');
  assert.equal(search.params.q, 'blawan');

  fetches.deliver(searchKey('blawan'), { results: [TRACKS[0]], query: 'blawan' });
  await settle();

  assert.deepEqual(options().map((node) => node.textContent), ['Blawan – Why They Hide']);
});

test('a row already in the export selection carries the tick prefix', async () => {
  await fresh();
  openTrackSelectorDialog({ alreadySelected: new Set(['b2']) });
  await settle();
  fetches.deliver(BROWSE_KEY, { tracks: TRACKS });
  await settle();

  const rows = options();
  // :934 - tick and a space, on the row already chosen and on no other.
  //
  // THE LITERAL, not `${ALREADY_SELECTED_PREFIX}...`. Building the expectation
  // from the constant under test made this a tautology: dropping the space from
  // the prefix changed both sides and the assertion held. Found by mutating the
  // constant and watching the suite stay green.
  assert.equal(rows[1].textContent, '✓ Alva Noto – Xerrox');
  assert.equal(rows[1].dataset.already, 'true');
  assert.equal(rows[0].textContent, 'Blawan – Why They Hide');
  assert.equal(rows[0].dataset.already, undefined);

  // And the exported constant really is what the row was built from, so a
  // consumer reading it gets the string this test just pinned.
  assert.equal(ALREADY_SELECTED_PREFIX, '✓ ');
});

test('Add Selected Tracks with nothing selected raises the catalogued warning', async () => {
  await fresh();
  const answer = openTrackSelectorDialog({ alreadySelected: new Set() });
  await settle();
  fetches.deliver(BROWSE_KEY, { tracks: TRACKS });
  await settle();

  control('Add Selected Tracks').dispatch('click');
  await settle();

  // :936 - a message box OVER the dialog, which must stay put behind it.
  assert.equal(textsByClass(document.body, 'message-box__title')[0], 'No Selection');
  assert.equal(
    textsByClass(document.body, 'message-box__message')[0],
    'Please select at least one track.',
  );

  // The dialog is still open and still resolvable, so this really was a
  // refusal and not a close.
  control('OK').dispatch('click');
  await settle();
  control('Cancel').dispatch('click');
  assert.equal(await answer, null);
});

test('clicking, ctrl-clicking and shift-clicking build the selection', async () => {
  await fresh();
  const answer = openTrackSelectorDialog({ alreadySelected: new Set() });
  await settle();
  fetches.deliver(BROWSE_KEY, { tracks: TRACKS });
  await settle();

  options()[0].dispatch('click', {});
  assert.equal(countText(), '1 track selected');

  // :920 - Ctrl+Click adds one. (⌘-Click does the same; the Library
  // destination reads both modifiers and so does this.)
  options()[2].dispatch('click', { metaKey: true });
  assert.equal(countText(), '2 tracks selected');

  // :920 - Shift+Click takes the range from the last anchor.
  options()[0].dispatch('click', {});
  options()[2].dispatch('click', { shiftKey: true });
  assert.equal(countText(), '3 tracks selected');

  control('Add Selected Tracks').dispatch('click');
  // Row order, so the caller's set grows in the order the list showed.
  assert.deepEqual(await answer, ['a1', 'b2', 'c3']);
});

test('Select All and Clear Selection act on every visible row', async () => {
  await fresh();
  openTrackSelectorDialog({ alreadySelected: new Set() });
  await settle();
  fetches.deliver(BROWSE_KEY, { tracks: TRACKS });
  await settle();

  control('Select All').dispatch('click');
  assert.equal(countText(), '3 tracks selected');
  assert.deepEqual(
    options().map((node) => node.getAttribute('aria-selected')),
    ['true', 'true', 'true'],
  );

  control('Clear Selection').dispatch('click');
  assert.equal(countText(), '0 tracks selected');
  assert.deepEqual(
    options().map((node) => node.getAttribute('aria-selected')),
    ['false', 'false', 'false'],
  );
});

test('Enter on a focused row toggles it, so the list works without a pointer', async () => {
  await fresh();
  const answer = openTrackSelectorDialog({ alreadySelected: new Set() });
  await settle();
  fetches.deliver(BROWSE_KEY, { tracks: TRACKS });
  await settle();

  // An ADDITION: §2.11 catalogues no keyboard binding for the list, and
  // `role="option"` on a bare <li> is a promise nothing keeps.
  options()[1].dispatch('keydown', { key: 'Enter' });
  assert.equal(countText(), '1 track selected');
  options()[1].dispatch('keydown', { key: 'Enter' });
  assert.equal(countText(), '0 tracks selected');

  options()[1].dispatch('keydown', { key: ' ' });
  control('Add Selected Tracks').dispatch('click');
  assert.deepEqual(await answer, ['b2']);
});

test('rebuilding the list drops the selection rather than keeping a stale index', async () => {
  await fresh();
  openTrackSelectorDialog({ alreadySelected: new Set() });
  await settle();
  fetches.deliver(BROWSE_KEY, { tracks: TRACKS });
  await settle();

  control('Select All').dispatch('click');
  assert.equal(countText(), '3 tracks selected');

  searchField().value = 'objekt';
  searchField().dispatch('input');
  await new Promise((resolve) => setTimeout(resolve, 180));
  fetches.deliver(searchKey('objekt'), { results: [TRACKS[2]], query: 'objekt' });
  await settle();

  // `delete(0, END)` clears the Tk listbox's selection too. Without this an
  // index of 2 would point at a list that now has one row.
  assert.equal(countText(), '0 tracks selected');
  assert.equal(options().length, 1);
});

test('Cancel discards, and the dialog never writes to the caller set', async () => {
  await fresh();
  const alreadySelected = new Set(['b2']);
  const answer = openTrackSelectorDialog({ alreadySelected });
  await settle();
  fetches.deliver(BROWSE_KEY, { tracks: TRACKS });
  await settle();

  options()[0].dispatch('click', {});
  control('Cancel').dispatch('click');

  // :939 - Cancel discards. :938 - the UNION is the caller's job, so this set
  // is untouched either way.
  assert.equal(await answer, null);
  assert.deepEqual([...alreadySelected], ['b2']);
});

test('the dialog is modal: the shell below it goes inert', async () => {
  const dom = await fresh();
  const answer = openTrackSelectorDialog({ alreadySelected: new Set() });
  await settle();
  fetches.deliver(BROWSE_KEY, { tracks: TRACKS });
  await settle();

  assert.equal(dom.app.getAttribute('inert'), '');
  assert.equal(dom.app.getAttribute('aria-hidden'), 'true');

  // Escape closes it, and the shell comes back.
  panel().dispatch('keydown', { key: 'Escape' });
  assert.equal(await answer, null);
  assert.equal(dom.app.getAttribute('inert'), null);
});

test('a failed search shows the error instead of an empty list', async () => {
  await fresh();
  openTrackSelectorDialog({ alreadySelected: new Set() });
  await settle();
  fetches.deliverError(BROWSE_KEY, 409, 'empty_library', 'This library has no index yet.');
  await settle();

  assert.deepEqual(textsByClass(document.body, 'picker__empty'), [
    'This library has no index yet.',
  ]);
  assert.equal(options().length, 0);
});
