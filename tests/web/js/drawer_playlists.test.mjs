/* The drawer's playlist section, run against the module that ships.
 *
 * WHY THIS IS A JAVASCRIPT TEST
 * -----------------------------
 * The five states in the plan's table - not imported, N playlists, zero
 * playlists, XML changed, XML missing - are branches over a payload shape, and
 * the difference between `null` and `[]` is invisible in the source: both are
 * falsey, both are "no playlists" to a careless `if`, and a Python test of the
 * API cannot tell you which screen the user got. So the real drawer is mounted
 * against the ~200-line DOM shim and the rendered tree is read back.
 *
 * What this cannot tell you is what the drawer LOOKED like; the visual pass is
 * still by hand in WKWebView. What it can tell you is which branch ran, that
 * the full path is rendered rather than the leaf name, and that a playlist
 * name containing markup arrives as text.
 */

import { test } from 'node:test';
import assert from 'node:assert/strict';

import { Node, byClass, installGlobals, textsByClass, walk, withId } from './dom_shim.mjs';
import { installFetch, settle } from './fixture.mjs';

installGlobals();

const fetches = installFetch();

/** Mirrors index.html: #drawer is a sibling of #app. */
const app = withId(new Node('div'), 'app');
const drawer = withId(new Node('aside'), 'drawer');
globalThis.document.body.append(app, drawer);

const { createStore } = await import('../../../src/web/static/js/store.js');
const { mountDrawer } = await import(
  '../../../src/web/static/js/components/drawer.js'
);

const BASE_TRACK = {
  track_id: 'f01',
  artist: 'Fireground',
  title: 'Never Sleep',
  album: 'Album',
  bpm: 132,
  key: '8A',
  path_local: '/music/never-sleep.mp3',
};

const FRESH_SOURCE = {
  source_name: 'library_export_190826.xml',
  imported_at: '2026-08-19T14:30:00+00:00',
  playlist_count: 141,
  entry_count: 4669,
  stale: false,
  source_missing: false,
  reason: '',
  import_command: 'python src/cosine_companion.py import-playlists',
};

/* Two of the real 21 that `Fireground - Never Sleep` belongs to. They share a
 * leaf name under different parents, which is the case the full path exists
 * for, and one of the folders has a slash IN ITS NAME. */
const TWO_WITH_A_SHARED_LEAF = [
  {
    playlist_id: 'p1',
    name: 'Hardgroove + Minimal Grooves',
    folder_path: ['timo&co', 'biscuit (funk)'],
    entries: 44,
  },
  {
    playlist_id: 'p2',
    name: 'Hardgroove + Minimal Grooves',
    folder_path: ['Mischief', 'Collections/Hauls', 'biscuit (funk)'],
    entries: 44,
  },
];

/** Mount fresh, open a track, and hand back the rendered drawer. */
function show(track) {
  const store = createStore({ detailTrackId: null, detail: null });
  mountDrawer({ store });
  store.setState({ detailTrackId: track.track_id, detail: track });
  return drawer;
}

/** The playlist section: the second `.drawer__section`, after Details. */
function playlistSection(root) {
  return byClass(root, 'drawer__section')[1];
}

function rows(root) {
  return byClass(playlistSection(root), 'playlist');
}

test('a track with no import shows the call to action, not "in 0 playlists"', () => {
  const root = show({ ...BASE_TRACK, playlists: null, playlist_source: null });
  const section = playlistSection(root);

  assert.equal(rows(root).length, 0);
  assert.match(section.textContent, /No Rekordbox playlists have been imported yet/);
  assert.doesNotMatch(section.textContent, /In 0 playlists/);
  assert.deepEqual(textsByClass(section, 'command'), [
    'python src/cosine_companion.py import-playlists',
  ]);
});

test('a track in zero playlists says so, and says nothing about importing', () => {
  const root = show({
    ...BASE_TRACK,
    playlists: [],
    playlist_source: FRESH_SOURCE,
  });
  const section = playlistSection(root);

  assert.equal(rows(root).length, 0);
  assert.match(section.textContent, /In 0 playlists/);
  assert.doesNotMatch(section.textContent, /have been imported yet/);
  // Provenance is still shown: the user imported, this track is simply in none.
  assert.match(section.textContent, /library_export_190826\.xml/);
});

test('null and [] are different screens', () => {
  const notImported = show({
    ...BASE_TRACK,
    playlists: null,
    playlist_source: null,
  }).textContent;
  const inNone = show({
    ...BASE_TRACK,
    playlists: [],
    playlist_source: FRESH_SOURCE,
  }).textContent;

  assert.notEqual(notImported, inNone);
});

test('the full path is rendered, not the leaf name', () => {
  const root = show({
    ...BASE_TRACK,
    playlists: TWO_WITH_A_SHARED_LEAF,
    playlist_source: FRESH_SOURCE,
  });

  const [first, second] = rows(root);
  assert.deepEqual(textsByClass(first, 'playlist__segment'), [
    'timo&co',
    'biscuit (funk)',
  ]);
  assert.deepEqual(textsByClass(second, 'playlist__segment'), [
    'Mischief',
    'Collections/Hauls',
    'biscuit (funk)',
  ]);
  assert.deepEqual(textsByClass(first, 'playlist__name'), [
    'Hardgroove + Minimal Grooves',
  ]);
});

test('two playlists with the same leaf name do not render identically', () => {
  const root = show({
    ...BASE_TRACK,
    playlists: TWO_WITH_A_SHARED_LEAF,
    playlist_source: FRESH_SOURCE,
  });

  const [first, second] = rows(root);
  assert.equal(
    textsByClass(first, 'playlist__name')[0],
    textsByClass(second, 'playlist__name')[0],
    'the fixture is meant to share a leaf name',
  );
  assert.notEqual(first.textContent, second.textContent);
  assert.notEqual(first.title, second.title);
});

test('a folder name containing a slash stays one segment', () => {
  const root = show({
    ...BASE_TRACK,
    playlists: [TWO_WITH_A_SHARED_LEAF[1]],
    playlist_source: FRESH_SOURCE,
  });

  const segments = textsByClass(rows(root)[0], 'playlist__segment');
  assert.ok(segments.includes('Collections/Hauls'));
  assert.ok(!segments.includes('Collections'));
  assert.ok(!segments.includes('Hauls'));
  // Two segments, two names, ONE separator between them and the third.
  assert.equal(byClass(rows(root)[0], 'playlist__sep').length, segments.length - 1);
});

test('a top-level playlist renders no path line at all', () => {
  const root = show({
    ...BASE_TRACK,
    playlists: [
      { playlist_id: 'p3', name: 'favorite tracks', folder_path: [], entries: 285 },
    ],
    playlist_source: FRESH_SOURCE,
  });

  const row = rows(root)[0];
  assert.equal(byClass(row, 'playlist__path').length, 0);
  assert.deepEqual(textsByClass(row, 'playlist__name'), ['favorite tracks']);
  assert.equal(row.title, 'favorite tracks');
});

test('twenty-one playlists all render, and the count is in the heading', () => {
  const many = Array.from({ length: 21 }, (_, at) => ({
    playlist_id: `p${at}`,
    name: `playlist ${at}`,
    folder_path: ['Mischief', 'Collections/Hauls'],
    entries: at,
  }));
  const root = show({
    ...BASE_TRACK,
    playlists: many,
    playlist_source: FRESH_SOURCE,
  });

  assert.equal(rows(root).length, 21);
  assert.deepEqual(textsByClass(playlistSection(root), 'section-heading__count'), ['21']);
});

test("the entry count shown is the playlist's total size", () => {
  const root = show({
    ...BASE_TRACK,
    playlists: TWO_WITH_A_SHARED_LEAF,
    playlist_source: FRESH_SOURCE,
  });

  assert.deepEqual(textsByClass(rows(root)[0], 'playlist__entries'), ['44']);
});

test('provenance reads "from <file> · imported <day> <month>"', () => {
  const root = show({
    ...BASE_TRACK,
    playlists: TWO_WITH_A_SHARED_LEAF,
    playlist_source: FRESH_SOURCE,
  });

  assert.deepEqual(textsByClass(playlistSection(root), 'provenance'), [
    'from library_export_190826.xml · imported 19 Aug',
  ]);
});

test('an unparseable imported_at drops the date rather than rendering NaN', () => {
  const root = show({
    ...BASE_TRACK,
    playlists: TWO_WITH_A_SHARED_LEAF,
    playlist_source: { ...FRESH_SOURCE, imported_at: 'not a date' },
  });

  assert.deepEqual(textsByClass(playlistSection(root), 'provenance'), [
    'from library_export_190826.xml',
  ]);
});

test('a stale source prompts with the command and still lists the playlists', () => {
  const root = show({
    ...BASE_TRACK,
    playlists: TWO_WITH_A_SHARED_LEAF,
    playlist_source: {
      ...FRESH_SOURCE,
      stale: true,
      reason:
        'library_export_190826.xml has changed since these playlists were ' +
        'imported. Run  python src/cosine_companion.py import-playlists  to ' +
        'update them.',
    },
  });
  const section = playlistSection(root);

  assert.equal(rows(root).length, 2, 'a stale prompt must not hide the data');
  assert.match(section.textContent, /has changed since these playlists were imported/);
  assert.deepEqual(textsByClass(section, 'command'), [
    'python src/cosine_companion.py import-playlists',
  ]);
});

test('a missing source shows the note without offering a re-import', () => {
  const root = show({
    ...BASE_TRACK,
    playlists: TWO_WITH_A_SHARED_LEAF,
    playlist_source: {
      ...FRESH_SOURCE,
      source_missing: true,
      reason:
        'library_export_190826.xml is no longer at the path it was imported ' +
        'from, so its playlists cannot be checked for changes.',
    },
  });
  const section = playlistSection(root);

  assert.equal(rows(root).length, 2);
  assert.match(section.textContent, /no longer at the path it was imported from/);
  // No command: re-importing from a file that is gone would fail.
  assert.deepEqual(textsByClass(section, 'command'), []);
});

test('a fresh source shows no prompt at all', () => {
  const root = show({
    ...BASE_TRACK,
    playlists: TWO_WITH_A_SHARED_LEAF,
    playlist_source: FRESH_SOURCE,
  });

  assert.equal(byClass(playlistSection(root), 'note').length, 0);
});

test('a playlist name carrying markup arrives as text, never as nodes', () => {
  /* Playlist names are user data out of an external file. This one would be a
   * script tag if any of this went through innerHTML. */
  const hostile = '<img src=x onerror="alert(1)">';
  const root = show({
    ...BASE_TRACK,
    playlists: [
      { playlist_id: 'p9', name: hostile, folder_path: [hostile], entries: 1 },
    ],
    playlist_source: FRESH_SOURCE,
  });

  const row = rows(root)[0];
  assert.equal(textsByClass(row, 'playlist__name')[0], hostile);
  assert.equal(textsByClass(row, 'playlist__segment')[0], hostile);
  // Nothing in the subtree became an element of its own.
  assert.deepEqual(
    walk(row).map((node) => node.tagName).filter((tag) => tag === 'IMG'),
    [],
  );
});

test('an absent playlist_source does not break the list', () => {
  /* Defensive: the field is always sent, but a drawer that throws on a payload
   * shape is a drawer that shows nothing at all. */
  const root = show({ ...BASE_TRACK, playlists: TWO_WITH_A_SHARED_LEAF });

  assert.equal(rows(root).length, 2);
  assert.equal(byClass(playlistSection(root), 'provenance').length, 0);
});

test('the details section is still rendered above the playlists', () => {
  const root = show({
    ...BASE_TRACK,
    playlists: TWO_WITH_A_SHARED_LEAF,
    playlist_source: FRESH_SOURCE,
  });

  const sections = byClass(root, 'drawer__section');
  assert.equal(sections.length, 2);
  assert.match(sections[0].textContent, /Details/);
  assert.match(sections[0].textContent, /\/music\/never-sleep\.mp3/);
  assert.match(sections[1].textContent, /Playlists/);
});

test('the drawer still fetches when the store has no detail yet', async () => {
  const store = createStore({ detailTrackId: null, detail: null });
  mountDrawer({ store });
  const before = fetches.requests.length;

  store.setState({ detailTrackId: 'f77' });
  await settle();

  assert.equal(fetches.requests.length, before + 1);
  assert.equal(fetches.requests.at(-1).path, '/api/tracks/f77');
});

/* -- what the drawer ASKS FOR, not what its source says ------------------
 *
 * The Python convention test beside this one greps drawer.js for the string
 * "/api/playlists". That is a source-text check and it says so; it cannot
 * catch a drawer that builds the path at runtime, and a mutant that appended
 *
 *     fetch(new URL('/api/pl' + 'aylists', location.origin))
 *
 * after rendering left it, and all eighteen tests here, green. This is the
 * behavioural half: every request the mounted drawer actually makes, across
 * every one of the five playlist states, has to be the track-detail request it
 * already had. The playlist data rides on that payload; no route was added for
 * it and none may be called.
 */

/** `/api/tracks/<id>` and nothing else - not `/api/tracks/<id>/playlists`. */
const TRACK_DETAIL = /^\/api\/tracks\/[^/]+$/;

const EVERY_PLAYLIST_STATE = [
  { playlists: null, playlist_source: null },
  { playlists: [], playlist_source: FRESH_SOURCE },
  { playlists: TWO_WITH_A_SHARED_LEAF, playlist_source: FRESH_SOURCE },
  {
    playlists: TWO_WITH_A_SHARED_LEAF,
    playlist_source: { ...FRESH_SOURCE, stale: true, reason: 'has changed' },
  },
  {
    playlists: TWO_WITH_A_SHARED_LEAF,
    playlist_source: { ...FRESH_SOURCE, source_missing: true, reason: 'is gone' },
  },
];

test('no playlist state makes the drawer call any endpoint but track detail', async () => {
  const before = fetches.requests.length;

  for (const state of EVERY_PLAYLIST_STATE) {
    show({ ...BASE_TRACK, ...state });
    await settle();
  }

  const made = fetches.requests.slice(before);
  const offending = made.filter((request) => !TRACK_DETAIL.test(request.path));
  assert.deepEqual(
    offending.map((request) => request.path),
    [],
    'the drawer requested something other than track detail',
  );
});

test('opening a track requests its detail and nothing else', async () => {
  const before = fetches.requests.length;
  const store = createStore({ detailTrackId: null, detail: null });
  mountDrawer({ store });

  store.setState({ detailTrackId: 'f42' });
  await settle();
  fetches.deliver('/api/tracks/f42?q=', {
    track: { ...BASE_TRACK, track_id: 'f42', playlists: TWO_WITH_A_SHARED_LEAF, playlist_source: FRESH_SOURCE },
  });
  await settle();

  // Rendered from the payload, and no second request went out for it.
  assert.equal(rows(drawer).length, 2);
  assert.deepEqual(
    fetches.requests.slice(before).map((request) => request.path),
    ['/api/tracks/f42'],
  );
});
