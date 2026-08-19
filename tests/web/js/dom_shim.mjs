/* A DOM small enough to read, big enough to run the shipped frontend.
 *
 * WHY THIS EXISTS
 * ---------------
 * Two of the defects this PR had to fix were not visible in the source and not
 * reachable from Python: "← Back re-sorts the restored list with the current
 * sort" and "the palette debounce leaves a window where a stale response
 * repaints the list". Both are ORDERING defects between a store, a timer and a
 * promise, and the only honest way to pin an ordering defect is to run the
 * ordering. So these tests import the real, shipped modules - no
 * reimplementation, no copy - and give them just enough browser to run in.
 *
 * WHAT THIS IS NOT
 * ----------------
 * It is not a browser and it is not jsdom. Layout, CSS, event bubbling,
 * capture, focus management and the accessibility tree are all absent. A test
 * written against this can tell you what a module DID; it cannot tell you what
 * the user SAW. The visual pass stays a manual one in WKWebView, and §6.4 of
 * the inventory still says the rendered DOM has no automated test. What is
 * automated here is the handful of behaviours that are pure sequencing.
 *
 * Every method below exists because a line of the shipped frontend calls it.
 * Nothing is here speculatively.
 */

class ClassList {
  constructor(node) {
    this.node = node;
  }
  add(...names) {
    const present = new Set(this.node.className.split(/\s+/).filter(Boolean));
    names.forEach((name) => present.add(name));
    this.node.className = [...present].join(' ');
  }
  remove(...names) {
    const present = new Set(this.node.className.split(/\s+/).filter(Boolean));
    names.forEach((name) => present.delete(name));
    this.node.className = [...present].join(' ');
  }
  contains(name) {
    return this.node.className.split(/\s+/).includes(name);
  }
}

let nodeCounter = 0;

export class Node {
  constructor(tagName) {
    this.tagName = String(tagName).toUpperCase();
    this.children = [];
    this.parentNode = null;
    this.attributes = new Map();
    this.listeners = new Map();
    this.style = { properties: new Map(), setProperty: (n, v) => this.style.properties.set(n, v) };
    this.dataset = {};
    this._className = '';
    this._text = '';
    this._uid = ++nodeCounter;
    this.hidden = false;
    this.disabled = false;
    this.value = '';
    this.title = '';
    this.type = '';
    this.selected = false;
    this.scrolledIntoView = 0;
    this.focused = 0;
  }

  // -- identity ------------------------------------------------------------

  get className() {
    return this._className;
  }
  set className(value) {
    this._className = String(value);
  }
  get classList() {
    return new ClassList(this);
  }
  get id() {
    return this.attributes.get('id') || '';
  }
  set id(value) {
    this.attributes.set('id', String(value));
    REGISTRY.set(String(value), this);
  }

  // -- text ----------------------------------------------------------------

  get textContent() {
    if (this.children.length) {
      return this.children.map((child) => child.textContent).join('');
    }
    return this._text;
  }
  set textContent(value) {
    this._text = value === null || value === undefined ? '' : String(value);
    this.children = [];
  }

  // -- tree ----------------------------------------------------------------

  append(...nodes) {
    for (const node of nodes) {
      if (node === null || node === undefined) continue;
      node.parentNode = this;
      this.children.push(node);
    }
  }
  replaceChildren(...nodes) {
    this.children = [];
    this._text = '';
    this.append(...nodes);
  }
  remove() {
    if (!this.parentNode) return;
    const at = this.parentNode.children.indexOf(this);
    if (at >= 0) this.parentNode.children.splice(at, 1);
    this.parentNode = null;
  }
  contains(other) {
    if (other === this) return true;
    return this.children.some((child) => child.contains(other));
  }

  // -- attributes ----------------------------------------------------------

  setAttribute(name, value) {
    this.attributes.set(name, String(value));
    if (name === 'id') REGISTRY.set(String(value), this);
  }
  getAttribute(name) {
    return this.attributes.has(name) ? this.attributes.get(name) : null;
  }
  removeAttribute(name) {
    this.attributes.delete(name);
  }
  hasAttribute(name) {
    return this.attributes.has(name);
  }

  // -- events --------------------------------------------------------------

  addEventListener(type, handler) {
    if (!this.listeners.has(type)) this.listeners.set(type, []);
    this.listeners.get(type).push(handler);
  }
  /** Fire the handlers registered on THIS node. There is no bubbling. */
  dispatch(type, event = {}) {
    const payload = { type, target: this, preventDefault() {}, ...event };
    for (const handler of this.listeners.get(type) || []) {
      handler(payload);
    }
    return payload;
  }

  // -- things the frontend calls that do nothing here -----------------------

  scrollIntoView() {
    this.scrolledIntoView += 1;
  }
  focus() {
    this.focused += 1;
    document.activeElement = this;
  }
  select() {}

  // -- querying (class, id and attribute selectors only) --------------------

  matches(selector) {
    if (selector.startsWith('.')) return this.classList.contains(selector.slice(1));
    if (selector.startsWith('#')) return this.id === selector.slice(1);
    if (selector.startsWith('[') && selector.endsWith(']')) {
      return this.attributes.has(selector.slice(1, -1));
    }
    return this.tagName === selector.toUpperCase();
  }
  querySelectorAll(selector) {
    const found = [];
    for (const child of this.children) {
      if (child.matches(selector)) found.push(child);
      found.push(...child.querySelectorAll(selector));
    }
    return found;
  }
  querySelector(selector) {
    return this.querySelectorAll(selector)[0] || null;
  }
}

const REGISTRY = new Map();

export const document = {
  activeElement: null,
  body: new Node('body'),
  createElement: (tag) => new Node(tag),
  getElementById: (id) => REGISTRY.get(id) || null,
  execCommand: () => true,
};

/** Register a node under an id so getElementById finds it. */
export function withId(node, id) {
  node.id = id;
  return node;
}

/** Every node in the subtree, self first. */
export function walk(node, found = []) {
  found.push(node);
  for (const child of node.children) walk(child, found);
  return found;
}

/** Every node in the subtree carrying ``className``. */
export function byClass(node, className) {
  return walk(node).filter((each) => each.classList.contains(className));
}

/** ``textContent`` of every node in the subtree carrying ``className``. */
export function textsByClass(node, className) {
  return byClass(node, className).map((each) => each.textContent);
}

/* -- the window ----------------------------------------------------------
 *
 * Real timers, because the palette's debounce is measured in real
 * milliseconds and faking the clock would test the fake. The waits in these
 * tests are therefore genuine sleeps, and they are short.
 */

export const clipboard = { written: [] };

export const window = {
  setTimeout: (...args) => globalThis.setTimeout(...args),
  clearTimeout: (...args) => globalThis.clearTimeout(...args),
  addEventListener(type, handler) {
    if (!this.listeners.has(type)) this.listeners.set(type, []);
    this.listeners.get(type).push(handler);
  },
  dispatch(type, event = {}) {
    const payload = { type, preventDefault() {}, ...event };
    for (const handler of this.listeners.get(type) || []) handler(payload);
    return payload;
  },
  listeners: new Map(),
  isSecureContext: true,
  location: { search: '?key=test-token', pathname: '/', origin: 'http://127.0.0.1:9' },
  history: { replaceState() {} },
};

export const navigator = {
  clipboard: {
    writeText: async (text) => {
      clipboard.written.push(text);
    },
  },
};

/** Install the shim as globals. Must run BEFORE any frontend module is imported. */
export function installGlobals() {
  globalThis.document = document;
  globalThis.window = window;
  globalThis.navigator = navigator;
  globalThis.HTMLElement = Node;
}

export function sleep(ms) {
  return new Promise((resolve) => globalThis.setTimeout(resolve, ms));
}
