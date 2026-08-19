/* The ⌘K palette must never show results for a query the user has moved past.
 *
 * THE DEFECT THIS PINS (palette.js:38-66 before the fix)
 * -----------------------------------------------------
 * `sequence` was incremented inside `load()`, and `load()` only runs after the
 * 120 ms debounce. So the guard `mine !== sequence` compared two REQUESTS, and
 * a keystroke that had not yet produced a request invalidated nothing:
 *
 *   t=0    type "a"            debounce timer set for t=120
 *   t=120  load("a") runs      mine = 1, sequence = 1, request goes out
 *   t=150  type "b"            timer reset for t=270; sequence STILL 1
 *   t=200  the "a" response lands -> mine === sequence -> RENDERED
 *          ...while the input reads "ab" and the user is about to press Enter.
 *
 * The reviewer reproduced exactly that by executing the shipped module:
 * {"input":"ab","displayedTitle":"OLD A RESULT","requestsStarted":2}.
 *
 * The fix invalidates on INPUT rather than on request start, so the window
 * closes at the keystroke instead of at the next request.
 */

import { test } from 'node:test';
import assert from 'node:assert/strict';

import { installGlobals, textsByClass, sleep } from './dom_shim.mjs';
import { buildPaletteDom, installFetch, settle } from './fixture.mjs';

installGlobals();

const fetches = installFetch();
const dom = buildPaletteDom();

// Imported AFTER the globals exist: api.js reads window.location at import.
const { mountPalette } = await import('../../../src/web/static/js/components/palette.js');

const DEBOUNCE_MS = 120;
/** Comfortably past the debounce, so the request has definitely gone out. */
const PAST_DEBOUNCE = DEBOUNCE_MS + 120;

const chosen = [];
const palette = mountPalette({ onSelect: (track) => chosen.push(track) });

function type(value) {
  dom.input.value = value;
  dom.input.dispatch('input');
}

function displayedTitles() {
  return textsByClass(dom.list, 'palette__title');
}

/** A palette freshly opened on its blank-query browse, with nothing in flight. */
async function reopen(browseTracks = []) {
  palette.close();
  await settle();
  palette.open();
  await settle();
  fetches.deliver('/api/tracks?q=', { tracks: browseTracks });
  await settle();
  chosen.length = 0;
}

test('a response for a superseded query never reaches the list', async () => {
  await reopen([{ track_id: 'b0', artist: 'B', title: 'BROWSE' }]);
  assert.deepEqual(displayedTitles(), ['BROWSE'], 'the blank-query browse should render');

  // The user types "a"; its request goes out.
  type('a');
  await sleep(PAST_DEBOUNCE);
  assert.ok(
    fetches.outstanding('/api/tracks/search?q=a'),
    `the "a" search should be in flight; in flight: ${fetches.keys()}`,
  );

  // The user types "b" BEFORE the "a" response lands. This keystroke is the
  // moment "a" stops being the current query.
  type('ab');
  await settle();

  // Now the slow "a" response arrives.
  fetches.deliver('/api/tracks/search?q=a', {
    results: [{ track_id: 'a0', artist: 'A', title: 'OLD A RESULT' }],
  });
  await settle();

  assert.equal(dom.input.value, 'ab');
  assert.ok(
    !displayedTitles().includes('OLD A RESULT'),
    `the list shows results for "a" while the input reads "ab": ${JSON.stringify({
      input: dom.input.value,
      displayed: displayedTitles(),
      requestsStarted: fetches.requests.length,
    })}`,
  );
});

test('pressing Enter in that window cannot select the superseded track', async () => {
  // The same sequence, ending in the keypress the defect actually costs you.
  await reopen();

  type('a');
  await sleep(PAST_DEBOUNCE);
  type('ab');
  await settle();
  fetches.deliver('/api/tracks/search?q=a', {
    results: [{ track_id: 'a0', artist: 'A', title: 'OLD A RESULT' }],
  });
  await settle();

  dom.input.dispatch('keydown', { key: 'Enter', shiftKey: false });

  assert.deepEqual(
    chosen.map((track) => track.title),
    [],
    'Enter selected a track from the superseded query',
  );
});

test('the current query still renders once its own response lands', async () => {
  // The guard must not be so eager that nothing ever renders.
  await reopen();

  type('zz');
  await sleep(PAST_DEBOUNCE);
  fetches.deliver('/api/tracks/search?q=zz', {
    results: [{ track_id: 'z0', artist: 'Z', title: 'CURRENT RESULT' }],
  });
  await settle();

  assert.deepEqual(displayedTitles(), ['CURRENT RESULT']);
});

test('the blank-query browse still renders when the palette is opened', async () => {
  await reopen([{ track_id: 'b1', artist: 'B', title: 'FIRST PAGE' }]);

  assert.deepEqual(displayedTitles(), ['FIRST PAGE']);
});
