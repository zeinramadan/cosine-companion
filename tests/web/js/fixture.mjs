/* The bits of index.html the components look up by id, plus a fetch double.
 *
 * Built from the shim rather than parsed out of index.html: the ids are the
 * contract between the markup and the modules, and writing them here means a
 * renamed id fails these tests loudly instead of silently mounting nothing.
 */

import { Node, defineGlobal, document, installGlobals, window, withId } from './dom_shim.mjs';

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

/** Build the Settings destination, shell and modal layer. Mirrors index.html. */
export function buildSettingsDom() {
  const app = withId(new Node('div'), 'app');
  const root = withId(new Node('section'), 'view-settings');
  const loadError = withId(new Node('div'), 'settings-load-error');
  loadError.hidden = true;
  const form = withId(new Node('form'), 'settings-form');
  const input = withId(new Node('input'), 'settings-xml-path');
  const submit = withId(new Node('button'), 'settings-submit');
  const status = withId(new Node('p'), 'settings-status');
  form.append(input, submit, status);

  const reindex = withId(new Node('div'), 'settings-reindex');
  const actions = withId(new Node('div'), 'reindex-actions');
  const incremental = withId(new Node('button'), 'reindex-incremental');
  incremental.textContent = 'Index New Tracks';
  const full = withId(new Node('button'), 'reindex-full');
  full.textContent = 'Rebuild All Embeddings';
  actions.append(incremental, full);

  const progress = withId(new Node('div'), 'reindex-progress');
  progress.hidden = true;
  progress.className = 'settings__reindex-progress';
  const progressLabel = withId(new Node('p'), 'reindex-progress-label');
  progressLabel.className = 'progress__label';
  const progressTrack = withId(new Node('div'), 'reindex-progress-track');
  progressTrack.className = 'progress__track';
  const progressFill = withId(new Node('div'), 'reindex-progress-fill');
  progressFill.className = 'progress__fill';
  progressTrack.append(progressFill);
  const progressStatus = withId(new Node('p'), 'reindex-progress-status');
  progressStatus.className = 'progress__status';
  const progressTiming = withId(new Node('p'), 'reindex-progress-timing');
  progressTiming.className = 'progress__timing';
  const progressActions = new Node('div');
  progressActions.className = 'progress__actions';
  const stop = withId(new Node('button'), 'reindex-stop');
  stop.textContent = 'Stop Reindex';
  const stopNote = withId(new Node('p'), 'reindex-stop-note');
  stopNote.className = 'progress__note';
  progressActions.append(stop, stopNote);
  progress.append(
    progressLabel,
    progressTrack,
    progressStatus,
    progressTiming,
    progressActions,
  );

  const outcome = withId(new Node('div'), 'reindex-outcome');
  outcome.hidden = true;
  outcome.className = 'settings__reindex-outcome';
  reindex.append(actions, progress, outcome);
  root.append(loadError, form, reindex);
  app.append(root);

  const modalLayer = withId(new Node('div'), 'modal-layer');
  document.body.append(app, modalLayer);
  return {
    app,
    root,
    loadError,
    modalLayer,
    form,
    input,
    submit,
    status,
    incremental,
    full,
    progress,
    progressLabel,
    progressTrack,
    progressFill,
    progressStatus,
    progressTiming,
    stop,
    stopNote,
    outcome,
  };
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

/** Build the Library destination's fixed controls. Mirrors index.html. */
export function buildLibraryDom() {
  const root = withId(new Node('section'), 'view-library');
  const loadError = withId(new Node('div'), 'library-load-error');
  loadError.hidden = true;
  const content = withId(new Node('div'), 'library-content');
  const input = withId(new Node('input'), 'library-search');
  const clear = withId(new Node('button'), 'library-clear');
  const refresh = withId(new Node('button'), 'library-refresh');
  const remove = withId(new Node('button'), 'library-delete');
  const setCurrent = withId(new Node('button'), 'library-set-current');
  const stats = withId(new Node('p'), 'library-stats');
  const status = withId(new Node('p'), 'library-status');
  const list = withId(new Node('ul'), 'library-tracks');
  const restoreAll = withId(new Node('button'), 'library-restore-all');
  const deletedStatus = withId(new Node('p'), 'library-deleted-status');
  const deletedList = withId(new Node('ul'), 'library-deleted-tracks');
  list.scrollTop = 0;
  content.append(
    input,
    clear,
    refresh,
    remove,
    setCurrent,
    stats,
    status,
    list,
    restoreAll,
    deletedStatus,
    deletedList,
  );
  root.append(loadError, content);
  document.body.append(root);
  return {
    root,
    loadError,
    content,
    input,
    clear,
    refresh,
    remove,
    setCurrent,
    stats,
    status,
    list,
    restoreAll,
    deletedStatus,
    deletedList,
  };
}

/** Build the Export destination's mount point, the shell and the modal layer.
 *
 * The same three-part shape `buildSetCreatorDom` builds, and for the same
 * reason: `#modal-layer` is a SIBLING of `#app`, because `modal.js` makes the
 * shell inert while a dialog is open and a dialog parked inside the shell
 * would go inert along with it.
 */
export function buildExportDom() {
  const app = withId(new Node('div'), 'app');
  const root = withId(new Node('section'), 'view-export');
  app.append(root);

  const modalLayer = withId(new Node('div'), 'modal-layer');

  document.body.append(app, modalLayer);
  return { app, root, modalLayer };
}

/** Build the always-mounted sidebar and its destination targets. Mirrors index.html. */
export function buildSidebarDom() {
  const app = withId(new Node('div'), 'app');
  const nav = withId(new Node('nav'), 'nav');
  const destinations = ['explore', 'set-creator', 'library', 'export', 'settings'];

  for (const destination of destinations) {
    const item = new Node('button');
    item.setAttribute('data-destination', destination);
    item.dataset.destination = destination;
    nav.append(item);
  }

  const footer = new Node('p');
  const count = withId(new Node('span'), 'library-count');
  count.textContent = '—';
  const suffix = new Node('span');
  suffix.textContent = ' tracks indexed';
  footer.append(count, suffix);
  nav.append(footer);

  const main = new Node('main');
  const title = withId(new Node('h1'), 'view-title');
  main.append(title);
  const views = {};
  for (const destination of destinations) {
    const view = withId(new Node('section'), `view-${destination}`);
    views[destination] = view;
    main.append(view);
  }

  app.append(nav, main);
  document.body.append(app);
  return { app, nav, title, count, footer, views };
}

/** Empty the shim's document between mounts. */
export function resetDom() {
  document.body.replaceChildren();
  document.activeElement = null;
}

/** A `window.localStorage` that lives in a Map, plus a way to make it throw.
 *
 * Both halves matter. The remembered output directory is a convenience, and
 * `export.js` wraps every read and write because Safari in a private window
 * throws on the ACCESSOR - so "storage is unavailable" has to be a case the
 * destination survives, not one it is never shown.
 */
export function installLocalStorage({ failing = false } = {}) {
  const store = new Map();
  const backing = {
    getItem: (key) => {
      if (failing) throw new Error('storage is disabled');
      return store.has(key) ? store.get(key) : null;
    },
    setItem: (key, value) => {
      if (failing) throw new Error('storage is disabled');
      store.set(key, String(value));
    },
  };
  window.localStorage = backing;
  return { store, backing };
}

/** Remove the storage double again. */
export function removeLocalStorage() {
  delete window.localStorage;
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
