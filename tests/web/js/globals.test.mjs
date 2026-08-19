/* The shim must be able to install itself on a runtime that already has these.
 *
 * THE DEFECT THIS PINS
 * --------------------
 * `installGlobals` assigned straight to `globalThis.navigator`. From node 21
 * the runtime defines that property ITSELF as a getter-only accessor, and in
 * an ES module - which is strict mode - assigning to one throws:
 *
 *   TypeError: Cannot set property navigator of #<Object> which has only a getter
 *
 * The machines this was written on run node 18 and 20, where `navigator` does
 * not exist at all and the assignment was fine. CI runs node 24 and every
 * suite that shims `navigator` failed at import. This test reproduces that
 * condition on ANY node version by installing a getter-only `navigator`
 * first, so the next runtime to add a built-in global cannot break the suite
 * silently on someone else's machine.
 */

import { test } from 'node:test';
import assert from 'node:assert/strict';

// Exactly what node >= 21 does, before the shim gets a chance to.
const sentinel = { userAgent: 'a built-in the runtime owns' };
Object.defineProperty(globalThis, 'navigator', {
  get: () => sentinel,
  configurable: true,
});

assert.equal(globalThis.navigator, sentinel, 'the reproduction did not take');

const { installGlobals, document, window, navigator } = await import('./dom_shim.mjs');

test('installing the shim survives a runtime that already defines the global', () => {
  installGlobals();

  assert.equal(globalThis.navigator, navigator);
  assert.notEqual(globalThis.navigator, sentinel);
});

test('every global the frontend reads is the shim, not the runtime', () => {
  installGlobals();

  assert.equal(globalThis.document, document);
  assert.equal(globalThis.window, window);
  assert.ok(globalThis.navigator.clipboard, 'the clipboard double is missing');
  assert.equal(typeof globalThis.document.createElement, 'function');
});

test('the fetch double replaces whatever fetch the runtime ships', async () => {
  installGlobals();
  const { installFetch } = await import('./fixture.mjs');
  const fetches = installFetch();

  globalThis.fetch(new URL('http://127.0.0.1/api/health'));

  assert.equal(fetches.requests.length, 1);
});
