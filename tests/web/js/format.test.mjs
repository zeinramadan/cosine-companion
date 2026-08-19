/* Rendering helpers. Only the cases that are wrong when nobody looks.
 *
 * `displayName` is the one that matters here. It is not only a visual
 * surface: it is what the row's Copy button puts on the clipboard and what the
 * Details button announces to a screen reader, and this library really does
 * contain tracks with an empty artist ("Skee Mask - Reviver" is one). The
 * visual surfaces already substitute "Unknown artist" for the empty field, so
 * the dangling " – " was invisible on screen and reached the clipboard intact.
 */

import { test } from 'node:test';
import assert from 'node:assert/strict';

import { installGlobals } from './dom_shim.mjs';

installGlobals();

const { displayName, EN_DASH } = await import('../../../src/web/static/js/format.js');

test('both fields present reads artist en-dash title', () => {
  assert.equal(displayName({ artist: 'Skee Mask', title: 'Reviver' }), `Skee Mask ${EN_DASH} Reviver`);
});

test('an empty artist yields the title alone, with no dangling separator', () => {
  assert.equal(displayName({ artist: '', title: 'Reviver' }), 'Reviver');
  assert.equal(displayName({ artist: null, title: 'Reviver' }), 'Reviver');
  assert.equal(displayName({ artist: '   ', title: 'Reviver' }), 'Reviver');
});

test('an empty title yields the artist alone', () => {
  assert.equal(displayName({ artist: 'Skee Mask', title: '' }), 'Skee Mask');
});

test('a supplied display_name is not trusted over the fields it was built from', () => {
  // The API mirrors `search_tracks` and builds `display_name` as
  // `{artist} – {title}` unconditionally, so the record it hands over carries
  // the same dangling separator. Composing locally is what fixes it for every
  // consumer at once.
  assert.equal(
    displayName({ artist: '', title: 'Reviver', display_name: ` ${EN_DASH} Reviver` }),
    'Reviver',
  );
});

test('a record with neither field falls back to whatever it does carry', () => {
  assert.equal(displayName({ display_name: 'Something' }), 'Something');
  assert.equal(displayName({}), 'Untitled');
  assert.equal(displayName(null), 'Untitled');
});
