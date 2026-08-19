/* The bits of index.html the components look up by id, plus a fetch double.
 *
 * Built from the shim rather than parsed out of index.html: the ids are the
 * contract between the markup and the modules, and writing them here means a
 * renamed id fails these tests loudly instead of silently mounting nothing.
 */

import { Node, defineGlobal, document, installGlobals, withId } from './dom_shim.mjs';

/** Build the palette's markup. Mirrors index.html:99-123. */
export function buildPaletteDom() {
  const root = withId(new Node('div'), 'palette');
  root.className = 'palette';
  root.hidden = true;

  const panel = new Node('div');
  panel.className = 'palette__panel';

  const input = withId(new Node('input'), 'palette-input');
  input.className = 'palette__input';

  const list = withId(new Node('ul'), 'palette-results');
  list.className = 'palette__results';

  panel.append(input, list);
  root.append(panel);

  const trigger = withId(new Node('button'), 'search-trigger');

  const app = withId(new Node('div'), 'app');

  document.body.append(app, root, trigger);
  return { root, panel, input, list, trigger, app };
}

/** Build the Explore destination's mount point. Mirrors index.html:59. */
export function buildExploreDom() {
  const root = withId(new Node('section'), 'view-explore');
  document.body.append(root);
  return { root };
}

/* -- a fetch whose responses the test hands out by hand -------------------
 *
 * Deterministic on purpose. Sequencing bugs are about which response lands
 * while which input is current, and a test that raced two real timers to
 * establish that would be a test that sometimes agrees with the code.
 */

export function installFetch() {
  const requests = [];
  const pending = new Map();

  // defineGlobal, not assignment: `fetch` is a runtime-owned global too, and
  // the node-21 `navigator` breakage is the same shape of risk here.
  defineGlobal('fetch', (url) => {
    const path = url.pathname;
    const query = url.searchParams.get('q') || '';
    const key = `${path}?q=${query}`;
    requests.push({ path, query, key });
    return new Promise((resolve, reject) => {
      pending.set(key, { resolve, reject });
    });
  });

  return {
    requests,
    /** Whether a request is outstanding for this key. */
    outstanding: (key) => pending.has(key),
    keys: () => [...pending.keys()],
    /** Answer one outstanding request with a body. */
    deliver(key, body) {
      const waiting = pending.get(key);
      if (!waiting) {
        throw new Error(`no outstanding request for ${key}; have ${[...pending.keys()]}`);
      }
      pending.delete(key);
      waiting.resolve({ ok: true, status: 200, json: async () => body });
    },
  };
}

/** Let every already-resolved promise run its continuations. */
export async function settle() {
  for (let turn = 0; turn < 8; turn += 1) {
    await Promise.resolve();
  }
  await new Promise((resolve) => globalThis.setImmediate(resolve));
  for (let turn = 0; turn < 8; turn += 1) {
    await Promise.resolve();
  }
}

export { installGlobals };
