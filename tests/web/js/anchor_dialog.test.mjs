/* `AddAnchorDialog` - inventory §2.12 - driven through the shipped module.
 *
 * THE ORDER IS THE SUBJECT
 * ------------------------
 * :961-964 is a table of four checks "in this order", and every one of them is
 * reachable at the same time as the ones below it. Nothing selected AND a
 * blank position AND that position already taken is one press of `Add to Set`,
 * and Tkinter answers "No Selection". A test that arranges one fault at a time
 * passes against an implementation that checks them in any order at all, so
 * each case below leaves the LATER faults in place and asserts which message
 * comes out.
 *
 * The other thing only running it can settle: `Add to Set` is not reachable
 * with a selection the user did not make. The Tk listbox has no selection
 * until you click a row, so :961 is live; the ⌘K palette highlights its first
 * result, and had this dialog copied that, "No Selection" would be a string
 * that can never appear.
 */

import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';

import {
  byClass,
  document,
  installGlobals,
  sleep,
  textsByClass,
} from './dom_shim.mjs';
import { buildSetCreatorDom, installFetch, settle } from './fixture.mjs';

installGlobals();

const fetches = installFetch();
const dom = buildSetCreatorDom();

const { openAnchorDialog } = await import(
  '../../../src/web/static/js/components/anchor-dialog.js'
);
const { focusablesWithin } = await import('../../../src/web/static/js/modal.js');

const BROWSE_KEY = '/api/tracks?q=';

const TRACKS = [
  { track_id: 'a1', artist: 'Blawan', title: 'Why They Hide' },
  { track_id: 'b2', artist: 'Alva Noto', title: 'Xerrox' },
  { track_id: 'c3', artist: '', title: 'Reviver' },
];

/* -- the declared contract, read out of the document that declares it ------
 *
 * What these rows render is a DIVERGENCE from :954, not parity with it: Tk
 * builds `{artist} – {title}` unconditionally and this dialog drops a blank
 * field along with the separator. §6.6 declares that, and carries the specimen
 * table below as the statement of what each implementation produces.
 *
 * The table is read rather than restated because an assertion written out here
 * would have the IMPLEMENTATION as its oracle: it would catch the code
 * drifting, and pass in silence if someone decided the dialog should match Tk
 * after all - which is a decision, and the document is where this project
 * records decisions. Reading it means the expectation moves when the DECISION
 * moves, and the suite goes red when only one of the two does.
 */
const INVENTORY = fileURLToPath(
  new URL('../../../docs/UI_FEATURE_INVENTORY.md', import.meta.url),
);

const SPECIMEN_HEADER =
  "| artist | title | Tk's row (`recommendations/search.py:38`) | this dialog's row |";

function contractRows() {
  const body = readFileSync(INVENTORY, 'utf8');
  const start = body.indexOf(SPECIMEN_HEADER);
  assert.notEqual(
    start,
    -1,
    'the §6.6 specimen table for the Add Anchor dialog rows is gone or was reworded; ' +
      'the divergence it declares is what this suite checks against',
  );

  const rows = [];
  // The header line and the `|---|` separator under it.
  for (const line of body.slice(start).split('\n').slice(2)) {
    if (!line.startsWith('|')) {
      break;
    }
    const cells = line.split('|').slice(1, -1).map((cell) => {
      const text = cell.trim();
      // Backticks are the document's quoting, and they are what preserve the
      // leading and trailing spaces that are the whole point of two of these
      // rows. Strip the quoting, keep the spaces.
      return text.startsWith('`') && text.endsWith('`') ? text.slice(1, -1) : text;
    });
    rows.push({ artist: cells[0], title: cells[1], tk: cells[2], web: cells[3] });
  }

  assert.ok(rows.length >= 3, `the specimen table has only ${rows.length} rows`);
  return rows;
}

const CONTRACT_ROWS = contractRows();

/** The specimen table's artist/title pairs as tracks the browse endpoint can return. */
const CONTRACT_TRACKS = CONTRACT_ROWS.map((row, index) => ({
  track_id: `spec${index}`,
  artist: row.artist,
  title: row.title,
}));

/* The debounce is 120 ms of real time, and the palette suite already
 * establishes that faking the clock would test the fake. */
const PAST_DEBOUNCE_MS = 200;

// -- driving the dialog -----------------------------------------------------

function modals() {
  return byClass(dom.modalLayer, 'modal');
}

function dialog() {
  const found = modals()[0];
  assert.ok(found, 'the anchor dialog is not open');
  return found;
}

function topModal() {
  return modals().at(-1) || null;
}

function messageBox() {
  const modal = topModal();
  if (!modal || modal === dialog()) {
    return null;
  }
  return {
    title: textsByClass(modal, 'message-box__title')[0],
    message: textsByClass(modal, 'message-box__message')[0],
    buttons: byClass(modal, 'button').map((button) => button.textContent),
  };
}

async function answer(label) {
  const modal = topModal();
  const button = byClass(modal, 'button').find((node) => node.textContent === label);
  assert.ok(button, `no ${label} button in the top modal`);
  button.dispatch('click');
  await settle();
}

function options() {
  return byClass(dialog(), 'picker__option');
}

function press(label) {
  const button = byClass(dialog(), 'button').find((node) => node.textContent === label);
  assert.ok(button, `no ${label} button in the dialog`);
  button.dispatch('click');
}

function positionField() {
  return document.getElementById('anchor-position');
}

function searchField() {
  return document.getElementById('anchor-search');
}

/** Open the dialog and answer its opening browse request.
 *
 * Returns the pending promise WRAPPED in an object. An `async` function that
 * returns a promise awaits it, so `return answered` here made every caller's
 * `await open()` block until the dialog closed - which is the thing the caller
 * has not done yet. The whole file deadlocked on it.
 */
async function open({ existingAnchors = {}, tracks = TRACKS } = {}) {
  const answered = openAnchorDialog({ existingAnchors });
  await settle();
  fetches.deliver(BROWSE_KEY, { tracks, total: tracks.length });
  await settle();
  return { answered };
}

async function type(text) {
  searchField().value = text;
  searchField().dispatch('input');
  await sleep(PAST_DEBOUNCE_MS);
  await settle();
}

/** A sentinel the answered promise races against, so "still open" is testable. */
const PENDING = Symbol('pending');
async function settled(answered) {
  return Promise.race([answered, Promise.resolve(PENDING)]);
}

// ---------------------------------------------------------------------------
// Opening
// ---------------------------------------------------------------------------

test('the dialog opens on the browse endpoint, not on a blank search', async () => {
  // DIVERGENCE, inventory :955 / §4 defect #9: implementation A returns [] for
  // a blank query, so the Tk dialog opens empty. This lists the first fifty
  // instead, through the endpoint that does not go through search_tracks - the
  // same answer the ⌘K palette gives to the same question.
  const since = fetches.requests.length;
  const answered = openAnchorDialog({ existingAnchors: {} });
  await settle();

  const opening = fetches.requests.slice(since);
  assert.deepEqual(
    opening.map((request) => request.path),
    ['/api/tracks'],
  );
  assert.equal(opening[0].options.method || 'GET', 'GET');

  fetches.deliver(BROWSE_KEY, { tracks: TRACKS, total: 3 });
  await settle();
  assert.equal(options().length, 3);

  press('Cancel');
  assert.equal(await answered, null);
});

test('the rows are the ones §6.6 declares, with a blank field dropped', async () => {
  const { answered } = await open({ tracks: CONTRACT_TRACKS });

  // Closed in a `finally`: a dialog left open by a failed assertion cancels
  // every test after it in this file, which buries the one real failure under
  // two dozen `cancelledByParent` lines.
  try {
    assert.deepEqual(
      options().map((option) => option.textContent),
      CONTRACT_ROWS.map((row) => row.web),
    );

    // And the table still describes a DIVERGENCE rather than parity. Without
    // this the check above would keep passing if someone rewrote the table to
    // say the two implementations agree, without touching either of them.
    const blankArtist = CONTRACT_ROWS.find((row) => row.artist === '');
    assert.ok(blankArtist, 'the table no longer carries a blank-artist specimen');
    assert.notEqual(
      blankArtist.web,
      blankArtist.tk,
      'the table stopped declaring a divergence for a blank artist',
    );
    assert.ok(
      blankArtist.tk.startsWith(' –'),
      `Tk's row for a blank artist should open with the dangling separator, not ${blankArtist.tk}`,
    );
  } finally {
    press('Cancel');
    await answered;
  }
});

test('nothing is selected when the dialog opens', async () => {
  const { answered } = await open();

  assert.deepEqual(
    options().map((option) => option.getAttribute('aria-selected')),
    ['false', 'false', 'false'],
  );

  press('Cancel');
  await answered;
});

test('typing searches, with the catalogued limit', async () => {
  const { answered } = await open();
  const since = fetches.requests.length;

  await type('xerrox');

  const sent = fetches.requests.slice(since);
  assert.deepEqual(
    sent.map((request) => request.path),
    ['/api/tracks/search'],
  );
  assert.equal(sent[0].query, 'xerrox');
  // Inventory :954 - `search_tracks(query, meta_ix, limit=50)`.
  assert.equal(sent[0].params.limit, '50');
  fetches.deliver('/api/tracks/search?q=xerrox', { results: [TRACKS[1]], query: 'xerrox' });
  await settle();

  assert.deepEqual(
    options().map((option) => option.textContent),
    ['Alva Noto – Xerrox'],
  );

  press('Cancel');
  await answered;
});

test('a new result list drops the selection it can no longer refer to', async () => {
  const { answered } = await open();
  options()[1].dispatch('click');
  assert.equal(options()[1].getAttribute('aria-selected'), 'true');

  await type('blawan');
  fetches.deliver('/api/tracks/search?q=blawan', { results: [TRACKS[0]], query: 'blawan' });
  await settle();

  assert.deepEqual(
    options().map((option) => option.getAttribute('aria-selected')),
    ['false'],
  );

  // ...and Add to Set therefore reports no selection rather than adding the
  // track that used to be at index 1.
  positionField().value = '1';
  press('Add to Set');
  await settle();
  assert.equal(messageBox().title, 'No Selection');
  await answer('OK');

  press('Cancel');
  await answered;
});

// ---------------------------------------------------------------------------
// The four checks, in order
// ---------------------------------------------------------------------------

test('no selection is the first check, even when everything else is wrong too', async () => {
  // Position blank AND (were a track selected) position 1 already taken. The
  // catalogued answer is still "No Selection".
  const { answered } = await open({ existingAnchors: { 1: {} } });
  positionField().value = '';

  press('Add to Set');
  await settle();

  assert.equal(messageBox().title, 'No Selection');
  assert.equal(messageBox().message, 'Please select a track.');
  assert.deepEqual(messageBox().buttons, ['OK']);
  await answer('OK');

  assert.equal(await settled(answered), PENDING, 'the dialog closed on a warning');
  press('Cancel');
  await answered;
});

test('a blank position is the second check, with the position already taken', async () => {
  const { answered } = await open({ existingAnchors: { 1: {} } });
  options()[0].dispatch('click');
  positionField().value = '';

  press('Add to Set');
  await settle();

  assert.equal(messageBox().title, 'Invalid Position');
  assert.equal(messageBox().message, 'Please enter a valid position number.');
  await answer('OK');

  press('Cancel');
  await answered;
});

test('"one" and "1.5" are not positions either', async () => {
  for (const typed of ['one', '1.5', '1e2', '½']) {
    const { answered } = await open();
    options()[0].dispatch('click');
    positionField().value = typed;

    press('Add to Set');
    await settle();

    assert.equal(messageBox().title, 'Invalid Position', `${typed} was accepted`);
    assert.equal(messageBox().message, 'Please enter a valid position number.');
    await answer('OK');

    press('Cancel');
    await answered;
  }
});

test('a negative position reaches the THIRD check, not the second', async () => {
  // The distinction is the whole reason the parser accepts a leading sign:
  // `int("-2")` succeeds in Python, so :962 passes and :963 is what refuses it.
  const { answered } = await open();
  options()[0].dispatch('click');
  positionField().value = '-2';

  press('Add to Set');
  await settle();

  assert.equal(messageBox().title, 'Invalid Position');
  assert.equal(messageBox().message, 'Position must be 1 or greater.');
  await answer('OK');

  press('Cancel');
  await answered;
});

test('zero is below 1', async () => {
  const { answered } = await open();
  options()[0].dispatch('click');
  positionField().value = '0';

  press('Add to Set');
  await settle();

  assert.equal(messageBox().message, 'Position must be 1 or greater.');
  await answer('OK');

  press('Cancel');
  await answered;
});

test('a taken position asks, and declining returns to the dialog', async () => {
  const { answered } = await open({ existingAnchors: { 4: { track_id: 'zz' } } });
  options()[0].dispatch('click');
  positionField().value = '4';

  press('Add to Set');
  await settle();

  assert.equal(messageBox().title, 'Position Taken');
  assert.equal(messageBox().message, 'Position 4 already has an anchor track. Replace it?');
  assert.deepEqual(messageBox().buttons, ['Yes', 'No']);

  await answer('No');

  // :964 - "declining returns to the dialog". Not cancelled, and nothing added.
  assert.equal(await settled(answered), PENDING);
  assert.equal(modals().length, 1, 'the dialog should still be the only modal');
  assert.equal(positionField().value, '4', 'the typed position was thrown away');
  assert.equal(options()[0].getAttribute('aria-selected'), 'true', 'the selection was lost');

  press('Cancel');
  await answered;
});

test('accepting the replacement returns the new anchor', async () => {
  const { answered } = await open({ existingAnchors: { 4: { track_id: 'zz' } } });
  options()[1].dispatch('click');
  positionField().value = '4';

  press('Add to Set');
  await settle();
  await answer('Yes');

  assert.deepEqual(await answered, { position: 4, track: TRACKS[1] });
});

test('an untaken position adds without asking', async () => {
  const { answered } = await open({ existingAnchors: { 4: { track_id: 'zz' } } });
  options()[0].dispatch('click');
  positionField().value = '5';

  press('Add to Set');
  await settle();

  assert.deepEqual(await answered, { position: 5, track: TRACKS[0] });
});

// ---------------------------------------------------------------------------
// The rules the dialog deliberately does NOT have
// ---------------------------------------------------------------------------

test('there is no upper bound on the position', async () => {
  // Inventory :966 - "no upper bound on the position, and no check against the
  // tab's Total Tracks". An anchor past the end of the set is caught by the
  // builder and surfaces as the Generation Error dialog instead (:506-508).
  const { answered } = await open();
  options()[0].dispatch('click');
  positionField().value = '9999';

  press('Add to Set');
  await settle();

  assert.equal(messageBox(), null, 'the dialog refused a position it must accept');
  assert.deepEqual(await answered, { position: 9999, track: TRACKS[0] });
});

test('the same track can be chosen for a second position', async () => {
  // Inventory :967. Position 2 is free, so no question is asked even though
  // the track at position 1 is the same one.
  const { answered } = await open({ existingAnchors: { 1: { track_id: 'a1' } } });
  options()[0].dispatch('click');
  positionField().value = '2';

  press('Add to Set');
  await settle();

  assert.equal(messageBox(), null);
  assert.deepEqual(await answered, { position: 2, track: TRACKS[0] });
});

// ---------------------------------------------------------------------------
// Ways in and out
// ---------------------------------------------------------------------------

test('double-clicking a row is Add to Set', async () => {
  const { answered } = await open();
  positionField().value = '3';

  options()[1].dispatch('dblclick');
  await settle();

  assert.deepEqual(await answered, { position: 3, track: TRACKS[1] });
});

test('Enter in either text field is Add to Set', async () => {
  // An ADDITION - §2.12 catalogues no keyboard binding. Recorded as such.
  for (const field of [() => positionField(), () => searchField()]) {
    const { answered } = await open();
    options()[0].dispatch('click');
    positionField().value = '6';

    field().dispatch('keydown', { key: 'Enter', preventDefault() {} });
    await settle();

    assert.deepEqual(await answered, { position: 6, track: TRACKS[0] });
  }
});

test('Cancel and Escape both discard the selection', async () => {
  const { answered: cancelled } = await open();
  options()[0].dispatch('click');
  positionField().value = '1';
  press('Cancel');
  assert.equal(await cancelled, null);

  const { answered: escaped } = await open();
  options()[0].dispatch('click');
  positionField().value = '1';
  dialog().querySelector('.modal__panel').dispatch('keydown', { key: 'Escape' });
  assert.equal(await escaped, null);
});

// ---------------------------------------------------------------------------
// Keyboard reach
// ---------------------------------------------------------------------------

test('the result rows are reachable and choosable without a mouse', async () => {
  /* THE DEFECT THIS PINS. The rows shipped as `<li role="option">` with a
   * click handler and nothing else: not in the tab order, no key handling. A
   * keyboard user could reach the position field, the search box, `Add to Set`
   * and `Cancel`, and could never select a track - so the only answer this
   * dialog could give them was "No Selection". `role="option"` is a promise
   * that the row can be chosen, and it was false. */
  const { answered } = await open();

  // Roving tabindex: exactly one row is a tab stop, not fifty.
  assert.deepEqual(
    options().map((option) => option.getAttribute('tabindex')),
    ['0', '-1', '-1'],
  );

  options()[0].dispatch('keydown', { key: 'ArrowDown', preventDefault() {} });
  assert.deepEqual(
    options().map((option) => option.getAttribute('aria-selected')),
    ['false', 'true', 'false'],
    'ArrowDown did not move the selection',
  );
  assert.equal(document.activeElement, options()[1], 'ArrowDown did not move the focus');
  assert.deepEqual(
    options().map((option) => option.getAttribute('tabindex')),
    ['-1', '0', '-1'],
    'the tab stop did not follow the selection',
  );

  options()[1].dispatch('keydown', { key: 'End', preventDefault() {} });
  assert.equal(document.activeElement, options()[2]);

  options()[2].dispatch('keydown', { key: 'ArrowDown', preventDefault() {} });
  assert.equal(document.activeElement, options()[2], 'the selection ran off the end');

  options()[2].dispatch('keydown', { key: 'Home', preventDefault() {} });
  assert.equal(document.activeElement, options()[0]);

  positionField().value = '4';
  options()[0].dispatch('keydown', { key: 'Enter', preventDefault() {} });
  await settle();

  assert.deepEqual(await answered, { position: 4, track: TRACKS[0] });
});

test('the tab trap stops on the list, and only on its one tab stop', async () => {
  /* THE DEFECT THIS PINS, and it was found in Chrome rather than here.
   *
   * `focusablesWithin` knew four tag names. The result rows are
   * `<li tabindex="0">`, so the trap did not merely fail to include them - it
   * calls preventDefault on Tab and moves the caret to the next element it
   * DOES know about, which meant Tab jumped the whole list and landed on
   * `Cancel`. The list was operable by arrow key and unreachable by Tab at the
   * same time, which is worse than either.
   *
   * This shim has no tab order, so what is asserted is the SET the trap walks.
   * The ordering half was verified by driving real key events through CDP in
   * real Chrome and reading back document.activeElement; that pass is in the
   * PR description.
   */
  const { answered } = await open();
  const panel = dialog().querySelector('.modal__panel');

  const stops = focusablesWithin(panel);
  const classes = stops.map((node) => node.className);

  assert.ok(
    classes.some((name) => name.includes('picker__option')),
    `the trap skips the result list entirely: ${JSON.stringify(classes)}`,
  );
  // Exactly ONE row, because the roving tabindex puts the other two at -1. A
  // trap that took every row would need fifty presses of Tab to get past.
  assert.equal(
    stops.filter((node) => node.className.includes('picker__option')).length,
    1,
  );
  // ...and the controls are all still in it.
  assert.deepEqual(
    stops.filter((node) => node.tagName === 'BUTTON').map((node) => node.textContent),
    ['Cancel', 'Add to Set'],
  );
  assert.equal(stops.filter((node) => node.tagName === 'INPUT').length, 2);

  press('Cancel');
  await answered;
});

test('a control taken out of the tab order stays out of it', async () => {
  // The negative half of the same rule: an explicit tabindex wins over the tag
  // in BOTH directions, or "tabindex=-1" would stop meaning anything.
  const { answered } = await open();
  const panel = dialog().querySelector('.modal__panel');
  const cancel = focusablesWithin(panel).find((node) => node.textContent === 'Cancel');

  cancel.setAttribute('tabindex', '-1');

  assert.ok(
    !focusablesWithin(panel).includes(cancel),
    'a tabindex="-1" button is still being trapped onto',
  );

  cancel.removeAttribute('tabindex');
  press('Cancel');
  await answered;
});

test('Space chooses a row too', async () => {
  const { answered } = await open();
  options()[1].dispatch('keydown', { key: 'ArrowDown', preventDefault() {} });
  positionField().value = '2';

  options()[1].dispatch('keydown', { key: ' ', preventDefault() {} });
  await settle();

  assert.deepEqual(await answered, { position: 2, track: TRACKS[1] });
});

test('a keyboard selection is what "No Selection" stops being about', async () => {
  // The check is still live - it is reachable by never touching the list - but
  // it must not be the ONLY thing a keyboard user can reach.
  const { answered } = await open();
  positionField().value = '1';

  options()[0].dispatch('keydown', { key: 'ArrowDown', preventDefault() {} });
  press('Add to Set');
  await settle();

  assert.equal(messageBox(), null, 'a keyboard selection was not seen');
  assert.deepEqual(await answered, { position: 1, track: TRACKS[1] });
});

// ---------------------------------------------------------------------------
// Modality, and the stacking the message boxes need
// ---------------------------------------------------------------------------

test('the shell is inert while the dialog is open and reachable after it closes', async () => {
  const { answered } = await open();

  assert.equal(dom.app.hasAttribute('inert'), true);
  assert.equal(dom.app.getAttribute('aria-hidden'), 'true');

  press('Cancel');
  await answered;

  assert.equal(dom.app.hasAttribute('inert'), false);
  assert.equal(dom.app.hasAttribute('aria-hidden'), false);
});

test('a message box over the dialog makes the DIALOG inert too, then gives it back', async () => {
  // This is what makes the stack a stack. With a single global flag, the
  // warning would leave the dialog underneath fully tabbable - which is the
  // one thing `aria-modal="true"` on the warning says is not so.
  const { answered } = await open();

  press('Add to Set'); // nothing selected -> a warning on top of the dialog
  await settle();

  assert.equal(modals().length, 2);
  assert.equal(dialog().hasAttribute('inert'), true, 'the dialog is still reachable');
  assert.equal(dom.app.hasAttribute('inert'), true, 'the shell became reachable again');

  await answer('OK');

  assert.equal(modals().length, 1);
  assert.equal(dialog().hasAttribute('inert'), false, 'the dialog was left inert');
  assert.equal(dom.app.hasAttribute('inert'), true, 'the shell must stay inert');

  press('Cancel');
  await answered;

  assert.equal(dom.app.hasAttribute('inert'), false);
});

test('focus lands in the search field, and comes back out to whatever opened it', async () => {
  const opener = document.createElement('button');
  dom.app.append(opener);
  opener.focus();
  assert.equal(document.activeElement, opener);

  const { answered } = await open();
  assert.equal(document.activeElement, searchField());

  press('Cancel');
  await answered;

  // Restored, which is only possible because `inert` was cleared FIRST - the
  // opener lives inside the shell, and a focus() into an inert subtree is
  // dropped on the floor. The shim honours that deliberately.
  assert.equal(document.activeElement, opener);
});
