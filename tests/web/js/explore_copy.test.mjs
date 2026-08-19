/* Copy operates on a RECOMMENDATION, which is what the inventory documents.
 *
 * THE DEFECT THIS PINS
 * --------------------
 * Inventory :423-429 catalogues `Copy Selected to Clipboard` as acting on the
 * SELECTED RECOMMENDATION (no selection -> a silent no-op). The web UI's only
 * Copy button copied the SEED. §6.3 recorded the FORMATTING divergence
 * ({artist} – {title} rather than the title alone) and said nothing about the
 * TARGET divergence, and §6.2 :1555 claimed both context-menu items - one of
 * which is Copy to Clipboard - "exist as controls". They did not.
 *
 * Re-seeding to a row and then copying is not a substitute: it pushes to
 * history and recomputes the whole list.
 *
 * So each row gets its own Copy. The seed card keeps one too - it is a useful
 * affordance and it costs nothing - but it is recorded as an ADDITION in §6.3
 * rather than as the thing :327 asks for.
 */

import { test } from 'node:test';
import assert from 'node:assert/strict';

import { clipboard, installGlobals, walk } from './dom_shim.mjs';
import { buildExploreDom, installFetch, settle } from './fixture.mjs';

installGlobals();

const fetches = installFetch();
const dom = buildExploreDom();

const { createStore } = await import('../../../src/web/static/js/store.js');
const { mountExplore, DEFAULT_SORT, DEFAULT_TOP_N } = await import(
  '../../../src/web/static/js/components/explore.js'
);
const { EN_DASH } = await import('../../../src/web/static/js/format.js');

const RECS = [
  { track_id: 'a1', artist: 'Zoe', title: 'T1', bpm: 120, key: '1A', cosine: 0.9, score: 0.9 },
  { track_id: 'a2', artist: 'Alice', title: 'T2', bpm: 100, key: '2A', cosine: 0.8, score: 0.8 },
  // The real shape of the defect item 11 fixes: this library has tracks whose
  // artist field is empty, and the clipboard is where that showed.
  { track_id: 'a3', artist: '', title: 'Reviver', bpm: 140, key: '3A', cosine: 0.7, score: 0.7 },
];
const SEED = { track_id: 'A', artist: 'Seed Artist', title: 'Seed Title', key: '1A', bpm: 120 };

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

async function mounted() {
  const store = freshStore();
  const explore = mountExplore({ store, onPickSeed() {}, onShowDetail() {} });
  explore.seed('A');
  await settle();
  fetches.deliver('/api/tracks/A/recommendations?q=', { seed: SEED, recommendations: RECS });
  await settle();
  clipboard.written.length = 0;
  return { store, explore };
}

function rowCopyButtons() {
  return walk(dom.root).filter((node) => node.classList.contains('rec__copy'));
}

test('every rendered recommendation has its own Copy control', async () => {
  await mounted();

  assert.equal(rowCopyButtons().length, RECS.length);
});

test('copying a row copies that row, not the seed', async () => {
  await mounted();

  rowCopyButtons()[1].dispatch('click');
  await settle();

  assert.deepEqual(clipboard.written, [`Alice ${EN_DASH} T2`]);
});

test('copying a row with no artist has no dangling separator', async () => {
  await mounted();

  rowCopyButtons()[2].dispatch('click');
  await settle();

  assert.deepEqual(clipboard.written, ['Reviver']);
});

test('copying a row does not re-seed, recompute or touch history', async () => {
  const { store } = await mounted();
  const before = store.getState();
  const requestsBefore = fetches.requests.length;

  rowCopyButtons()[0].dispatch('click');
  await settle();

  const after = store.getState();
  assert.equal(after.seed, before.seed, 'copying changed the seed');
  assert.equal(after.recommendations, before.recommendations, 'copying recomputed the list');
  assert.deepEqual(after.history, before.history, 'copying pushed to history');
  assert.equal(fetches.requests.length, requestsBefore, 'copying issued a request');
});

test('the Copy control names the track it copies', async () => {
  await mounted();

  assert.deepEqual(
    rowCopyButtons().map((node) => node.getAttribute('aria-label')),
    [`Copy Zoe ${EN_DASH} T1`, `Copy Alice ${EN_DASH} T2`, 'Copy Reviver'],
  );
});

test('the seed card still has its own Copy, and it copies the seed', async () => {
  await mounted();

  const seedCopy = walk(dom.root).find(
    (node) => node.classList.contains('seed__copy'),
  );
  assert.ok(seedCopy, 'the seed card lost its Copy button');

  seedCopy.dispatch('click');
  await settle();

  assert.deepEqual(clipboard.written, [`Seed Artist ${EN_DASH} Seed Title`]);
});
