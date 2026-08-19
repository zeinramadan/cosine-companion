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

  // INSIDE the shell, because that is where it is: index.html:51 puts
  // #search-trigger in the header of #app (index.html:12), and the palette is
  // a SIBLING of #app (index.html:99). Getting this wrong is not cosmetic - a
  // trigger parked outside the shell is never inert, so `close()` restoring
  // focus to it succeeds whether or not `inert` was cleared first, and the
  // ordering test below it silently stops testing anything. It did: the
  // production ordering was mutated and all four cases still passed.
  const app = withId(new Node('div'), 'app');
  const trigger = withId(new Node('button'), 'search-trigger');
  app.append(trigger);

  document.body.append(app, root);
  return { root, panel, input, list, trigger, app };
}

/** Build the Explore destination's mount point. Mirrors index.html:59. */
export function buildExploreDom() {
  const root = withId(new Node('section'), 'view-explore');
  document.body.append(root);
  return { root };
}

/** Build the Settings form's mount points. Mirrors index.html. */
export function buildSettingsDom() {
  const form = withId(new Node('form'), 'settings-form');
  const input = withId(new Node('input'), 'settings-xml-path');
  const submit = withId(new Node('button'), 'settings-submit');
  const status = withId(new Node('p'), 'settings-status');
  form.append(input, submit, status);
  document.body.append(form);
  return { form, input, submit, status };
}

/** Build the Set Creator's mount point, the shell and the modal layer.
 *
 * Mirrors index.html: `#view-set-creator` inside `#app`, and `#modal-layer` as
 * a SIBLING of the shell. The sibling relationship is the whole mechanism -
 * `modal.js` makes `#app` inert while a dialog is open, and a dialog parked
 * inside the shell would make itself inert along with everything else.
 */
export function buildSetCreatorDom() {
  const app = withId(new Node('div'), 'app');
  const root = withId(new Node('section'), 'view-set-creator');
  app.append(root);

  const modalLayer = withId(new Node('div'), 'modal-layer');

  document.body.append(app, modalLayer);
  return { app, root, modalLayer };
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
  defineGlobal('fetch', (url, options = {}) => {
    const path = url.pathname;
    const query = url.searchParams.get('q') || '';
    const key = `${path}?q=${query}`;
    // Every parameter, not only `q`: the caps are part of the contract too
    // (`search_tracks(..., limit=50)`, inventory :954), and a test cannot
    // assert one it was never handed.
    const params = Object.fromEntries(url.searchParams.entries());
    requests.push({ path, query, params, key, options });
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
    /** Answer one outstanding request with a non-2xx status and an API error.
     *
     * `deliver` always resolves `ok: true`, so without this the only failure a
     * test could stage is a dropped connection - and the message the UI shows
     * for a refused set ("Failed to generate set: {error}", inventory :507) is
     * the SERVER'S message, which only reaches the frontend down this path.
     */
    deliverError(key, status, code, message) {
      const waiting = pending.get(key);
      if (!waiting) {
        throw new Error(`no outstanding request for ${key}; have ${[...pending.keys()]}`);
      }
      pending.delete(key);
      waiting.resolve({
        ok: false,
        status,
        json: async () => ({ error: { code, message } }),
      });
    },
    /** Fail one outstanding request as a network error. */
    reject(key, error = new Error('network failure')) {
      const waiting = pending.get(key);
      if (!waiting) {
        throw new Error(`no outstanding request for ${key}; have ${[...pending.keys()]}`);
      }
      pending.delete(key);
      waiting.reject(error);
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
