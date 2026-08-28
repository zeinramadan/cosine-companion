/* Behavioural coverage for the shipped Library component. */

import { test } from 'node:test';
import assert from 'node:assert/strict';

import {
  buildLibraryDom,
  installFetch,
  installGlobals,
  settle,
} from './fixture.mjs';

installGlobals();

const TRACKS = [
  {
    track_id: 'b', artist: 'Artist B', title: 'Second', album: 'Room',
    key: '9A', bpm: 130, path_local: '/b.mp3',
  },
  {
    track_id: 'a', artist: 'artist a', title: 'First', album: 'Outside',
    key: '8A', bpm: 128, path_local: '/a.mp3',
  },
  {
    track_id: 'c', artist: 'NoSpace', title: 'Third', album: '',
    key: '', bpm: null, path_local: '/c.mp3',
  },
];

const DELETED_TRACKS = [
  { track_id: 'gone-b', artist: 'Rene Wise', title: 'Tizer --skip' },
  { track_id: 'gone-a', artist: 'Blawan', title: 'Toast' },
];

async function mounted({ deletedTracks = DELETED_TRACKS } = {}) {
  const fetches = installFetch();
  const dom = buildLibraryDom();
  const { createStore } = await import('../../../src/web/static/js/store.js');
  const { mountLibrary } = await import(
    '../../../src/web/static/js/components/library.js'
  );
  const store = createStore({
    destination: 'library',
    library: { track_count: 3, is_empty: false },
    seed: null,
  });
  const setCurrentCalls = [];
  const cleared = [];
  mountLibrary({
    store,
    onSetCurrent: (trackId) => setCurrentCalls.push(trackId),
    onClearCurrent: () => cleared.push(true),
  });
  fetches.deliver('/api/library/tracks?q=', { tracks: TRACKS, total: 3 });
  fetches.deliver('/api/library/deleted-tracks?q=', {
    tracks: deletedTracks,
    total: deletedTracks.length,
  });
  await settle();
  return { fetches, store, setCurrentCalls, cleared, ...dom };
}

test('Library renders the exact sorted rows and the untrimmed four-field filter', async () => {
  const view = await mounted();
  const rowTexts = () => view.list.children.map((row) => row.textContent);

  assert.deepEqual(rowTexts(), [
    'artist a – First [8A] (128 BPM)',
    'Artist B – Second [9A] (130 BPM)',
    'NoSpace – Third',
  ]);
  assert.equal(view.stats.textContent, '3 tracks');

  view.input.value = 'room';
  view.input.dispatch('input');
  assert.deepEqual(rowTexts(), ['Artist B – Second [9A] (130 BPM)']);
  assert.equal(view.stats.textContent, '1 of 3 tracks');

  view.input.value = ' ';
  view.input.dispatch('input');
  assert.deepEqual(rowTexts(), [
    'artist a – First [8A] (128 BPM)',
    'Artist B – Second [9A] (130 BPM)',
  ]);

  view.clear.dispatch('click');
  assert.equal(view.input.value, '');
  assert.equal(view.stats.textContent, '3 tracks');
});

test('Library replaces its false zero state with the saved-index diagnosis', async () => {
  const fetches = installFetch();
  const dom = buildLibraryDom();
  const { createStore } = await import('../../../src/web/static/js/store.js');
  const { mountLibrary } = await import(
    '../../../src/web/static/js/components/library.js'
  );
  const message =
    'The saved library index is inconsistent and could not be loaded. ' +
    'Open Settings, save the path to a Rekordbox XML export, then choose ' +
    'Rebuild All Embeddings.';
  const store = createStore({
    destination: 'library',
    library: {
      track_count: 0,
      is_empty: true,
      load_error: { code: 'index_load_failed', message },
    },
    seed: null,
  });

  mountLibrary({ store, onSetCurrent() {}, onClearCurrent() {} });
  await settle();

  assert.deepEqual(fetches.requests, [], 'the broken index was fetched as an empty table');
  assert.equal(dom.content.hidden, true, 'the 0 tracks count is still visible');
  assert.equal(dom.loadError.hidden, false);
  assert.deepEqual(
    dom.loadError.children[0].children.map((child) => child.textContent),
    ['Library index needs rebuilding', message],
  );
});

test('Set as Current takes the first selected row without changing history itself', async () => {
  const view = await mounted();
  const alerts = [];
  window.alert = (message) => alerts.push(message);

  view.setCurrent.dispatch('click');
  assert.deepEqual(alerts, ['Please select a track from the library.']);

  view.list.children[1].children[0].dispatch('click');
  view.setCurrent.dispatch('click');
  assert.deepEqual(view.setCurrentCalls, ['b']);
  assert.equal(view.store.getState().destination, 'explore');
});

test('Delete Selected confirms exact copy, writes once, refreshes and clears the seed', async () => {
  const view = await mounted();
  const confirmations = [];
  const alerts = [];
  window.alert = (message) => alerts.push(message);
  window.confirm = (message) => confirmations.push(message) && true;
  view.store.setState({ seed: { track_id: 'b' } });

  view.list.children[1].children[0].dispatch('click');
  view.list.children[2].children[0].dispatch('click', { ctrlKey: true });
  view.remove.dispatch('click');
  await settle();

  assert.deepEqual(confirmations, [
    'Delete 2 selected tracks from your library?\n\n' +
      "This will remove them from recommendations but won't delete the audio files.",
  ]);
  const write = view.fetches.requests.at(-1);
  assert.equal(write.path, '/api/library/tracks/delete');
  assert.equal(write.options.method, 'POST');
  assert.deepEqual(JSON.parse(write.options.body), { track_ids: 'b\nc' });

  view.fetches.deliver('/api/library/tracks/delete?q=', {
    deleted: 2,
    track_ids: ['b', 'c'],
    library: { track_count: 1, is_empty: false },
  });
  await settle();
  assert.equal(view.fetches.requests.at(-1).path, '/api/library/tracks');

  view.fetches.deliver('/api/library/tracks?q=', {
    tracks: [TRACKS[1]],
    total: 1,
  });
  await settle();
  view.fetches.deliver('/api/library/deleted-tracks?q=', {
    tracks: [...DELETED_TRACKS, TRACKS[0], TRACKS[2]],
    total: 4,
  });
  await settle();

  assert.equal(view.status.textContent, '✅ Deleted 2 tracks from library');
  assert.equal(view.stats.textContent, '1 tracks');
  assert.equal(view.store.getState().library.track_count, 1);
  assert.deepEqual(view.cleared, [true]);
  assert.deepEqual(alerts, []);
});

test('Deleted tracks show artist, title and id instead of an undiscoverable exclusion', async () => {
  const view = await mounted();

  assert.deepEqual(
    view.deletedList.children.map((row) => row.textContent),
    [
      'Blawan – ToastTrack ID: gone-aRestore for Reindex',
      'Rene Wise – Tizer --skipTrack ID: gone-bRestore for Reindex',
    ],
  );
  assert.equal(view.restoreAll.disabled, false);
});

test('Restoring one only removes its exclusion and directs the user to reindex', async () => {
  const view = await mounted();
  const confirmations = [];
  window.confirm = (message) => confirmations.push(message) && true;

  view.deletedList.children[1].children[1].dispatch('click');
  await settle();

  assert.deepEqual(confirmations, [
    'Restore Rene Wise – Tizer --skip for reindexing?\n\n' +
      'This only removes the deletion exclusion. The track will not return to ' +
      'the library until you run Index New Tracks.',
  ]);
  const write = view.fetches.requests.at(-1);
  assert.equal(write.path, '/api/library/deleted-tracks/restore');
  assert.equal(write.options.method, 'POST');
  assert.deepEqual(JSON.parse(write.options.body), { track_ids: 'gone-b' });

  view.fetches.deliver('/api/library/deleted-tracks/restore?q=', {
    removed_from_deleted: 1,
    track_ids: ['gone-b'],
    remaining: 1,
    reindex_required: true,
  });
  await settle();

  assert.deepEqual(
    view.deletedList.children.map((row) => row.textContent),
    ['Blawan – ToastTrack ID: gone-aRestore for Reindex'],
  );
  assert.equal(
    view.deletedStatus.textContent,
    '✅ Track is eligible for indexing again. ' +
      'Run Index New Tracks to add it back to the library.',
  );
});

test('Restore All uses the same mutation and still denies immediate library recovery', async () => {
  const view = await mounted();
  const confirmations = [];
  window.confirm = (message) => confirmations.push(message) && true;

  view.restoreAll.dispatch('click');
  await settle();

  assert.deepEqual(confirmations, [
    'Restore 2 deleted tracks for reindexing?\n\n' +
      'This only removes the deletion exclusion. The tracks will not return to ' +
      'the library until you run Index New Tracks.',
  ]);
  const write = view.fetches.requests.at(-1);
  assert.equal(write.path, '/api/library/deleted-tracks/restore');
  assert.deepEqual(JSON.parse(write.options.body), {
    track_ids: 'gone-a\ngone-b',
  });

  view.fetches.deliver('/api/library/deleted-tracks/restore?q=', {
    removed_from_deleted: 2,
    track_ids: ['gone-a', 'gone-b'],
    remaining: 0,
    reindex_required: true,
  });
  await settle();

  assert.equal(view.deletedList.textContent, 'No tracks are excluded from indexing.');
  assert.equal(view.restoreAll.disabled, true);
  assert.equal(
    view.deletedStatus.textContent,
    '✅ Tracks are eligible for indexing again. ' +
      'Run Index New Tracks to add them back to the library.',
  );
});
