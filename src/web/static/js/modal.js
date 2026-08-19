/* The modal layer: what makes `aria-modal` true rather than decorative.
 *
 * The Set Creator needs two modal surfaces that the Explore destination did
 * not - `AddAnchorDialog` (inventory §2.12, `transient` + `grab_set`) and the
 * `messagebox` calls §2.5 and §2.12 make from inside it. Both are modal in
 * Tkinter, and the second OPENS OVER THE FIRST: `Add to Set` with nothing
 * selected raises a warning on top of a dialog that must stay put behind it
 * (inventory :961-964).
 *
 * So this is a STACK, not a flag. Each open pushes; what is underneath - the
 * shell for the first, the dialog below for the second - goes `inert`, and
 * closing restores exactly one level. The palette (components/palette.js)
 * predates this and manages its own single level inline; it is left alone
 * because a shared abstraction is not worth editing a file another branch is
 * not expecting to change.
 *
 * THE THREE THINGS THAT MAKE MODALITY REAL
 * ----------------------------------------
 * 1. `inert` on everything below, which removes it from the tab order AND
 *    from the accessibility tree. `aria-hidden` goes on beside it for the
 *    browsers that have not shipped `inert`.
 * 2. A Tab trap, because `inert` is what SHOULD be enough and a focus trap is
 *    what is enough today. Unlike the palette, these dialogs hold several
 *    focusable controls, so the trap cycles rather than pinning one element.
 * 3. Focus restored to whatever opened the dialog, and restored AFTER the
 *    inert attribute is cleared - `focus()` into an inert subtree is dropped
 *    on the floor, which is how "restore, then clear" silently loses the
 *    caret. tests/web/js/dom_shim.mjs honours that, deliberately, so the two
 *    orderings do not produce identical results in a test.
 *
 * Escape closes the top level only.
 */

const LAYER_ID = 'modal-layer';
const SHELL_ID = 'app';

/* Elements a browser will focus by default. Enumerated rather than queried
 * with a selector so this walk works identically against the test shim, whose
 * `querySelectorAll` understands class, id and attribute selectors only. */
const FOCUSABLE_TAGS = new Set(['BUTTON', 'INPUT', 'SELECT', 'TEXTAREA']);

/**
 * Whether the tab trap should stop on `node`.
 *
 * AN EXPLICIT `tabindex` WINS OVER THE TAG, IN BOTH DIRECTIONS, and getting
 * that wrong was a real defect rather than a theoretical one. The anchor
 * dialog's result rows are `<li role="option" tabindex="0">` - a listbox with
 * a roving tabindex, so exactly one row is a tab stop. A trap that only knew
 * about the four form tags did not merely fail to include them: it called
 * preventDefault on Tab and moved the caret to the NEXT element it did know
 * about, so Tab in the real browser jumped the whole list and landed on
 * `Cancel`. The list was keyboard-operable and unreachable at the same time.
 *
 * Found in the manual pass in Chrome; the DOM shim has no tab order to get
 * wrong, so no test written against it could have shown this.
 *
 * The negative case matters as much: a `<button tabindex="-1">` is deliberately
 * out of the tab order and the trap has to respect that too.
 */
function isTabStop(node) {
  if (node.disabled) {
    return false;
  }
  const declared = node.getAttribute ? node.getAttribute('tabindex') : null;
  if (declared !== null && declared !== undefined && declared !== '') {
    return Number(declared) >= 0;
  }
  return FOCUSABLE_TAGS.has(node.tagName);
}

/** Every focusable descendant of `node`, in tree order. */
export function focusablesWithin(node, found = []) {
  for (const child of node.children || []) {
    if (isTabStop(child)) {
      found.push(child);
    }
    focusablesWithin(child, found);
  }
  return found;
}

/* One entry per open modal, outermost first. */
const stack = [];

function layer() {
  return document.getElementById(LAYER_ID);
}

function shell() {
  return document.getElementById(SHELL_ID);
}

function setInert(node, inert) {
  if (!node) {
    return;
  }
  if (inert) {
    node.setAttribute('inert', '');
    node.setAttribute('aria-hidden', 'true');
  } else {
    node.removeAttribute('inert');
    node.removeAttribute('aria-hidden');
  }
}

/** The thing directly beneath `depth`: the dialog below it, or the shell. */
function beneath(depth) {
  return depth === 0 ? shell() : stack[depth - 1].root;
}

export function openModalCount() {
  return stack.length;
}

/**
 * Open a modal.
 *
 * `build(close)` returns the node to show; `close(value)` resolves the promise
 * this returns, which is how `askyesno` hands back a Yes or a No and how the
 * anchor dialog hands back the anchor it was asked for.
 *
 * `initialFocus` names which control should hold the caret on open - the
 * search box for the anchor dialog, the confirming button for a message box -
 * and falls back to the first focusable in the dialog.
 */
export function openModal({ label, className, build, initialFocus, dismissValue }) {
  const host = layer();
  const root = document.createElement('div');
  root.className = className ? `modal ${className}` : 'modal';

  const panel = document.createElement('div');
  panel.className = 'modal__panel';
  panel.setAttribute('role', 'dialog');
  panel.setAttribute('aria-modal', 'true');
  if (label) {
    panel.setAttribute('aria-label', label);
  }
  root.append(panel);

  let settle;
  const answer = new Promise((resolve) => {
    settle = resolve;
  });

  const entry = {
    root,
    panel,
    restoreFocusTo: document.activeElement,
    settled: false,
  };

  function close(value) {
    if (entry.settled) {
      return;
    }
    entry.settled = true;

    const depth = stack.indexOf(entry);
    if (depth >= 0) {
      stack.splice(depth, 1);
    }
    root.remove();

    // Clear inert BEFORE restoring focus: a focus() into an inert subtree is
    // ignored, and whatever opened this dialog is inside the subtree that was
    // made inert when it opened.
    setInert(beneath(stack.length), false);

    if (entry.restoreFocusTo && typeof entry.restoreFocusTo.focus === 'function') {
      entry.restoreFocusTo.focus();
    }
    settle(value);
  }

  panel.append(build(close));

  // Everything below goes inert as this one goes up, so a second dialog takes
  // the first out of reach exactly as it takes the shell out of reach.
  setInert(beneath(stack.length), true);
  stack.push(entry);
  host.append(root);

  const focusable = focusablesWithin(panel);
  const wanted =
    (typeof initialFocus === 'function' ? initialFocus(panel) : initialFocus) ||
    focusable[0];
  if (wanted && typeof wanted.focus === 'function') {
    wanted.focus();
  }

  panel.addEventListener('keydown', (event) => {
    if (event.key === 'Escape') {
      event.preventDefault();
      close(dismissValue);
      return;
    }
    if (event.key !== 'Tab') {
      return;
    }
    // The trap. `inert` below should already make this unnecessary; it is here
    // because "should" and "does, in every browser that runs this" differ.
    const cycle = focusablesWithin(panel);
    if (!cycle.length) {
      event.preventDefault();
      return;
    }
    const at = cycle.indexOf(document.activeElement);
    const step = event.shiftKey ? -1 : 1;
    const next = cycle[(at + step + cycle.length) % cycle.length];
    if (at === -1 || next) {
      event.preventDefault();
      (at === -1 ? cycle[0] : next).focus();
    }
  });

  // Clicking the backdrop dismisses; clicking inside the panel must not.
  root.addEventListener('mousedown', (event) => {
    if (!panel.contains(event.target)) {
      close(dismissValue);
    }
  });

  return { answer, close, root, panel };
}
