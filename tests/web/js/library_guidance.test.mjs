/* The shipped destinations render the shared first-run and recovery copy. */

import { test } from 'node:test';
import assert from 'node:assert/strict';

import { installGlobals, textsByClass } from './dom_shim.mjs';
import {
  buildExploreDom,
  buildSetCreatorDom,
  installFetch,
  resetDom,
  settle,
} from './fixture.mjs';

installGlobals();

const { createStore } = await import('../../../src/web/static/js/store.js');
const { mountExplore, DEFAULT_SORT, DEFAULT_TOP_N } = await import(
  '../../../src/web/static/js/components/explore.js'
);
const { mountSetCreator } = await import(
  '../../../src/web/static/js/components/set-creator.js'
);
const { FIRST_RUN_GUIDANCE } = await import(
  '../../../src/web/static/js/components/library-guidance.js'
);

function exploreStore(library) {
  return createStore({
    destination: 'explore',
    library,
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

function stateCopy(root) {
  return {
    title: textsByClass(root, 'state__title')[0],
    body: textsByClass(root, 'state__body')[0],
  };
}

test('Explore first run explains the Rekordbox export and the web Settings route', () => {
  resetDom();
  const { root } = buildExploreDom();
  const store = exploreStore({ track_count: 0, is_empty: true });
  mountExplore({ store, onPickSeed() {}, onShowDetail() {} });

  assert.deepEqual(stateCopy(root), {
    title: 'No index yet',
    body: `There is no cosine index to search. ${FIRST_RUN_GUIDANCE}`,
  });
});

test('Explore empty-library API errors give the same working route', async () => {
  resetDom();
  const fetches = installFetch();
  const { root } = buildExploreDom();
  const store = exploreStore({ track_count: 1, is_empty: false });
  store.setState({
    seed: { track_id: 'old', artist: 'Artist', title: 'Track', bpm: 120, key: '1A' },
  });
  const explore = mountExplore({ store, onPickSeed() {}, onShowDetail() {} });

  explore.setCurrent('missing');
  await settle();
  fetches.deliverError(
    '/api/tracks/missing/recommendations?q=',
    409,
    'empty_library',
    'The library has no index.',
  );
  await settle();

  assert.deepEqual(stateCopy(root), {
    title: 'No index yet',
    body: `There is no cosine index to search. ${FIRST_RUN_GUIDANCE}`,
  });
});

test('Set Creator first run explains the Rekordbox export and the web Settings route', () => {
  resetDom();
  const { root } = buildSetCreatorDom();
  const store = createStore({
    destination: 'set-creator',
    library: { track_count: 0, is_empty: true },
    libraryError: null,
  });
  mountSetCreator({ store });

  assert.deepEqual(stateCopy(root), {
    title: 'No index yet',
    body: `There is no cosine index to build a set from. ${FIRST_RUN_GUIDANCE}`,
  });
});

for (const destination of ['explore', 'set-creator']) {
  test(`${destination} surfaces an actionable inconsistent-index diagnosis`, () => {
    resetDom();
    const message =
      'The saved library index is inconsistent and could not be loaded. ' +
      'Open Settings, save the path to a Rekordbox XML export, then choose ' +
      'Rebuild All Embeddings.';
    const library = {
      track_count: 0,
      is_empty: true,
      load_error: { code: 'index_load_failed', message },
    };
    let root;
    if (destination === 'explore') {
      ({ root } = buildExploreDom());
      mountExplore({ store: exploreStore(library), onPickSeed() {}, onShowDetail() {} });
    } else {
      ({ root } = buildSetCreatorDom());
      mountSetCreator({
        store: createStore({ destination, library, libraryError: null }),
      });
    }

    assert.deepEqual(stateCopy(root), {
      title: 'Library index needs rebuilding',
      body: message,
    });
  });
}
