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

async function mounted() {
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

  assert.equal(view.status.textContent, '✅ Deleted 2 tracks from library');
  assert.equal(view.stats.textContent, '1 tracks');
  assert.equal(view.store.getState().library.track_count, 1);
  assert.deepEqual(view.cleared, [true]);
  assert.deepEqual(alerts, []);
});
