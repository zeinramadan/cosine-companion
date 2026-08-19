/* ← Back restores the list it stored, in the order it stored it.
 *
 * THE DEFECT THIS PINS (explore.js:152-184, 328-329 before the fix)
 * ----------------------------------------------------------------
 * `history.push({seed, recommendations})` recorded no sort key, and
 * `renderList` sorted a copy with whatever the CURRENT global sort was. So the
 * list that came back from ← Back was the right tracks in the wrong order:
 *
 *   sort seed A by Artist -> re-seed to B -> switch to BPM -> ← Back
 *   ... and A comes back in BPM order.
 *
 * Inventory :420-421 is explicit, and the asymmetry in it is the whole point:
 * "restores the stored recommendation list verbatim (including its sort order)
 * without recomputing ... and re-renders honouring the **current** Top-N
 * value". Sort order is historical. Top-N is current. Both are asserted below.
 *
 * The fix follows the Tkinter model this reimplements
 * (recommendations_tab.py:270 `self.current_recommendations.sort(...)`): the
 * stored list IS the display order, sorting is a state change that reorders
 * it, and rendering only truncates. A history entry therefore carries its
 * order for free, and carries the sort NAME too so the segmented control
 * still says which order you are looking at.
 */

import { test } from 'node:test';
import assert from 'node:assert/strict';

import { installGlobals, textsByClass, walk } from './dom_shim.mjs';
import { buildExploreDom, installFetch, settle } from './fixture.mjs';

installGlobals();

const fetches = installFetch();
const dom = buildExploreDom();

const { createStore } = await import('../../../src/web/static/js/store.js');
const { mountExplore, DEFAULT_SORT, DEFAULT_TOP_N } = await import(
  '../../../src/web/static/js/components/explore.js'
);

/* Three tracks whose cosine, artist and BPM orders are all different, so no
 * assertion below can pass by coincidence. */
const A_RECS = [
  { track_id: 'a1', artist: 'Zoe', title: 'T1', bpm: 120, key: '1A', cosine: 0.9, score: 0.9 },
  { track_id: 'a2', artist: 'Alice', title: 'T2', bpm: 100, key: '2A', cosine: 0.8, score: 0.8 },
  { track_id: 'a3', artist: 'Mick', title: 'T3', bpm: 140, key: '3A', cosine: 0.7, score: 0.7 },
];
const COSINE_ORDER = ['T1', 'T2', 'T3'];
const ARTIST_ORDER = ['T2', 'T3', 'T1']; // Alice, Mick, Zoe
const BPM_ORDER = ['T3', 'T1', 'T2']; // 140, 120, 100

const B_RECS = [
  { track_id: 'b1', artist: 'Nia', title: 'U1', bpm: 128, key: '4A', cosine: 0.5, score: 0.5 },
];

function freshStore() {
  return createStore({
    destination: 'explore',
    library: null,
    libraryError: null,
    seed: null,
    recommendations: [],
    history: [],
    sort: DEFAULT_SORT,
    topN: DEFAULT_TOP_N,
    exploreStatus: 'idle',
    exploreError: null,
    detailTrackId: null,
    detail: null,
  });
}

function rowTitles() {
  return textsByClass(dom.root, 'rec__title');
}

function control(label) {
  const found = walk(dom.root).find(
    (node) => node.classList.contains('segmented__option') && node.textContent === label,
  );
  assert.ok(found, `no sort control labelled ${label}`);
  return found;
}

function pressedSort() {
  return walk(dom.root)
    .filter((node) => node.classList.contains('segmented__option'))
    .filter((node) => node.getAttribute('aria-pressed') === 'true')
    .map((node) => node.textContent);
}

function topNSelect() {
  return document.getElementById('explore-top-n');
}

async function seedWith(explore, trackId, seedTrack, recommendations) {
  explore.seed(trackId);
  await settle();
  fetches.deliver(`/api/tracks/${trackId}/recommendations?q=`, {
    seed: seedTrack,
    recommendations,
  });
  await settle();
}

const SEED_A = { track_id: 'A', artist: 'Seed', title: 'Seed A', key: '1A', bpm: 120 };
const SEED_B = { track_id: 'B', artist: 'Seed', title: 'Seed B', key: '2A', bpm: 128 };

test('back restores the historical sort order, not the current one', async () => {
  const store = freshStore();
  const explore = mountExplore({ store, onPickSeed() {}, onShowDetail() {} });

  await seedWith(explore, 'A', SEED_A, A_RECS);
  assert.deepEqual(rowTitles(), COSINE_ORDER, 'a fresh list arrives in cosine order');

  control('Artist').dispatch('click');
  assert.deepEqual(rowTitles(), ARTIST_ORDER, 'sorting by Artist reorders the list');

  await seedWith(explore, 'B', SEED_B, B_RECS);
  assert.deepEqual(rowTitles(), ['U1']);

  control('BPM').dispatch('click');

  explore.goBack();

  assert.deepEqual(
    rowTitles(),
    ARTIST_ORDER,
    'A came back in the CURRENT sort order instead of the one it was stored in',
  );
});

test('the segmented control says which order you are looking at', async () => {
  const store = freshStore();
  const explore = mountExplore({ store, onPickSeed() {}, onShowDetail() {} });

  await seedWith(explore, 'A', SEED_A, A_RECS);
  control('Artist').dispatch('click');
  await seedWith(explore, 'B', SEED_B, B_RECS);
  control('BPM').dispatch('click');

  explore.goBack();

  assert.deepEqual(pressedSort(), ['Artist']);
});

test('back honours the CURRENT Top-N, not the stored one', async () => {
  const store = freshStore();
  const explore = mountExplore({ store, onPickSeed() {}, onShowDetail() {} });

  await seedWith(explore, 'A', SEED_A, A_RECS);
  control('Artist').dispatch('click');
  await seedWith(explore, 'B', SEED_B, B_RECS);

  // Change Top-N while B is showing; going back must respect the new value.
  const select = topNSelect();
  select.value = '2';
  select.dispatch('change');

  explore.goBack();

  assert.equal(store.getState().topN, 2);
  assert.deepEqual(
    rowTitles(),
    ARTIST_ORDER.slice(0, 2),
    'the restored list must be truncated to the CURRENT Top-N',
  );
});

test('sorting after going back still works', async () => {
  // The restored order is historical, not frozen.
  const store = freshStore();
  const explore = mountExplore({ store, onPickSeed() {}, onShowDetail() {} });

  await seedWith(explore, 'A', SEED_A, A_RECS);
  control('Artist').dispatch('click');
  await seedWith(explore, 'B', SEED_B, B_RECS);
  explore.goBack();

  control('BPM').dispatch('click');

  assert.deepEqual(rowTitles(), BPM_ORDER);
});

test('a fresh computation is not reordered by the sort left over from before', async () => {
  // recommendations_tab.py:236-243 - refresh_suggestions REPLACES
  // current_recommendations with what ExploreSession returned, in cosine
  // order, and does not reapply the last sort. The segmented control has to
  // agree with the list it is sitting above.
  const store = freshStore();
  const explore = mountExplore({ store, onPickSeed() {}, onShowDetail() {} });

  await seedWith(explore, 'A', SEED_A, A_RECS);
  control('Artist').dispatch('click');

  await seedWith(explore, 'B', SEED_B, A_RECS);

  assert.deepEqual(rowTitles(), COSINE_ORDER);
  assert.deepEqual(pressedSort(), ['Cosine']);
});

test('history is still capped at twenty', async () => {
  const store = freshStore();
  const explore = mountExplore({ store, onPickSeed() {}, onShowDetail() {} });

  for (let index = 0; index < 25; index += 1) {
    await seedWith(explore, `S${index}`, { ...SEED_A, track_id: `S${index}` }, A_RECS);
  }

  assert.equal(store.getState().history.length, 20);
});

test('a sort considers every computed row, not just the visible ones', async () => {
  // Inventory :385-386 - "Sorts apply to all 200 computed recommendations,
  // then the list is re-rendered truncated to topn". Sorting after truncating
  // would show the best of the first N rather than the best N, and with a
  // small Top-N the two differ by which tracks appear at all.
  const store = freshStore();
  const explore = mountExplore({ store, onPickSeed() {}, onShowDetail() {} });

  await seedWith(explore, 'A', SEED_A, A_RECS);

  const select = topNSelect();
  select.value = '1';
  select.dispatch('change');
  assert.deepEqual(rowTitles(), [COSINE_ORDER[0]], 'only one row should be shown');

  control('Artist').dispatch('click');

  // T2 (Alice) is LAST by cosine among the three and first by artist. It can
  // only be the single visible row if the sort saw all three.
  assert.deepEqual(rowTitles(), [ARTIST_ORDER[0]]);
  assert.equal(store.getState().recommendations.length, A_RECS.length, 'rows were dropped, not just hidden');
});
