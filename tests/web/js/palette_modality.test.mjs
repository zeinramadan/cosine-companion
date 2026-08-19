/* aria-modal="true" is a claim. This is what has to be true for it.
 *
 * THE DEFECT THIS PINS
 * --------------------
 * index.html:100 declares the palette panel `role="dialog" aria-modal="true"`,
 * which tells assistive technology that everything behind the panel is
 * unreachable. Nothing made that so: Tab walked straight out of the panel into
 * the sidebar, and the background was still in the accessibility tree. A false
 * ARIA claim is worse than none - it is the one thing a screen-reader user
 * cannot check for themselves.
 *
 * Two mechanisms, because one of them is newer than the browsers this may run
 * in: `inert` on the application shell (Safari 15.5+), and a Tab trap that
 * holds even where `inert` is ignored. The panel contains exactly one
 * focusable element - the input - because the result list is driven by
 * aria-activedescendant rather than by focus, so "trap" here means Tab goes
 * nowhere at all.
 */

import { test } from 'node:test';
import assert from 'node:assert/strict';

import { document, installGlobals } from './dom_shim.mjs';
import { buildPaletteDom, installFetch, settle } from './fixture.mjs';

installGlobals();

const fetches = installFetch();
const dom = buildPaletteDom();

const { mountPalette } = await import('../../../src/web/static/js/components/palette.js');

const palette = mountPalette({ onSelect() {} });

async function opened() {
  palette.close();
  await settle();
  palette.open();
  await settle();
  fetches.deliver('/api/tracks?q=', { tracks: [] });
  await settle();
}

test('opening the palette takes the shell out of reach', async () => {
  await opened();

  assert.equal(dom.app.getAttribute('inert'), '', 'the shell is not inert');
  assert.equal(dom.app.getAttribute('aria-hidden'), 'true');
});

test('closing the palette gives the shell back', async () => {
  await opened();
  palette.close();
  await settle();

  assert.equal(dom.app.getAttribute('inert'), null);
  assert.equal(dom.app.getAttribute('aria-hidden'), null);
});

test('the shell is reachable again before focus is restored to it', async () => {
  // Order matters: focus() into an inert subtree is ignored, so restoring
  // focus first and clearing inert second silently loses the caret.
  const outside = dom.trigger;
  document.activeElement = outside;
  const focusedBefore = outside.focused;

  palette.close();
  await settle();
  palette.open();
  await settle();
  fetches.deliver('/api/tracks?q=', { tracks: [] });
  await settle();

  palette.close();
  await settle();

  assert.equal(dom.app.getAttribute('inert'), null);
  assert.ok(outside.focused > focusedBefore, 'focus was not restored to the opener');
});

test('Tab does not leave the panel', async () => {
  await opened();

  for (const shiftKey of [false, true]) {
    let prevented = 0;
    dom.input.dispatch('keydown', {
      key: 'Tab',
      shiftKey,
      preventDefault: () => {
        prevented += 1;
      },
    });

    assert.equal(prevented, 1, `Tab (shift=${shiftKey}) was allowed to move focus`);
    assert.equal(document.activeElement, dom.input);
  }
});
