/* The Set Creator destination, driven through the shipped module.
 *
 * WHAT ONLY RUNNING IT CAN SETTLE
 * ------------------------------
 * Inventory :501-503 catalogues three checks "in order", and the order is
 * OBSERVABLE: with a blank `Total Tracks` and no anchors at all, the Tkinter
 * tab says "Invalid Input", not "No Anchors". A source-text check can see that
 * three messages exist; only running the thing can see which one comes out
 * when two conditions are wrong at once. The same goes for the score suffix
 * (:487), which is decided by two conditions on one row, and for `Export to
 * Clipboard` (:530), which is decided by what a row's display name CONTAINS.
 *
 * Everything here imports src/web/static/js - no reimplementation. The DOM is
 * the documented shim, which can say what the module did and not what a user
 * saw; the visual pass stays manual, and the PR description records it.
 */

import { test } from 'node:test';
import assert from 'node:assert/strict';

import { byClass, clipboard, document, installGlobals, textsByClass, walk } from './dom_shim.mjs';
import { buildSetCreatorDom, installFetch, settle } from './fixture.mjs';

installGlobals();

const fetches = installFetch();
const dom = buildSetCreatorDom();

const { createStore } = await import('../../../src/web/static/js/store.js');
const { wholePercent } = await import('../../../src/web/static/js/format.js');
const { mountSetCreator, scoreSuffix, DEFAULT_TOTAL_TRACKS } = await import(
  '../../../src/web/static/js/components/set-creator.js'
);

const SET_KEY = '/api/set?q=';
const BROWSE_KEY = '/api/tracks?q=';

/* Two tracks, and a generated set built from them. Scores chosen so the
 * rendered percentages are all different and none is a round number. */
const ALPHA = { track_id: 'a1', artist: 'Blawan', title: 'Why They Hide' };
const BETA = { track_id: 'b2', artist: 'Alva Noto', title: 'Xerrox' };

function generatedRow(overrides) {
  return {
    track_id: 'g1',
    position: 1,
    is_anchor: false,
    score: 0.9669962525367737,
    artist: 'Blawan',
    title: 'Why They Hide',
    display_name: 'Blawan – Why They Hide',
    icon: '🤖',
    ...overrides,
  };
}

const SET = [
  generatedRow({ position: 1 }),
  generatedRow({
    track_id: 'a1',
    position: 2,
    is_anchor: true,
    score: 1.0,
    artist: 'Alva Noto',
    title: 'Xerrox',
    display_name: 'Alva Noto – Xerrox',
    icon: '🔒',
  }),
  generatedRow({
    track_id: 'empty_3',
    position: 3,
    score: 0.0,
    artist: 'No suitable track found',
    title: '',
    display_name: 'No suitable track found – (Unknown Title)',
  }),
];

function freshStore() {
  return createStore({ destination: 'set-creator', library: null, libraryError: null });
}

function mount() {
  const store = freshStore();
  const view = mountSetCreator({ store });
  return { store, view };
}

// -- reading the rendered destination ---------------------------------------

function control(label) {
  const found = walk(dom.root).find(
    (node) => node.tagName === 'BUTTON' && node.textContent === label,
  );
  assert.ok(found, `no control labelled ${label}`);
  return found;
}

function totalField() {
  return document.getElementById('set-total-tracks');
}

function statusLine() {
  return textsByClass(dom.root, 'setc__status')[0];
}

function anchorRows() {
  return byClass(dom.root, 'anchors__row');
}

function anchorTexts() {
  return anchorRows().map(
    (row) =>
      `${textsByClass(row, 'anchors__position')[0]} ${textsByClass(row, 'anchors__name')[0]}`,
  );
}

function setRows() {
  return byClass(dom.root, 'setlist__row');
}

/** One rendered set row as the fields inventory :479 names. */
function setRowFields(row) {
  return {
    position: textsByClass(row, 'setlist__position')[0],
    icon: textsByClass(row, 'setlist__icon')[0],
    name: textsByClass(row, 'setlist__name')[0],
    score: textsByClass(row, 'setlist__score')[0],
  };
}

// -- reading and answering a message box ------------------------------------

function topModal() {
  return byClass(dom.modalLayer, 'modal').at(-1) || null;
}

function messageBox() {
  const modal = topModal();
  if (!modal) {
    return null;
  }
  return {
    title: textsByClass(modal, 'message-box__title')[0],
    message: textsByClass(modal, 'message-box__message')[0],
    buttons: byClass(modal, 'button').map((button) => button.textContent),
    modal,
  };
}

async function answer(label) {
  const modal = topModal();
  assert.ok(modal, 'no modal is open');
  const button = byClass(modal, 'button').find((node) => node.textContent === label);
  assert.ok(button, `no ${label} button; have ${byClass(modal, 'button').map((b) => b.textContent)}`);
  button.dispatch('click');
  await settle();
}

/* `fetches.requests` accumulates for the whole FILE - one module-level fetch
 * double, many tests - so "how many requests did this action make" has to be
 * measured against a mark taken just before it. Counting the whole array
 * instead passes early in the file and fails later, which is a test that
 * depends on its own position. */
function mark() {
  return fetches.requests.length;
}

function setRequestsSince(since) {
  return fetches.requests.slice(since).filter((request) => request.path === '/api/set');
}

/** Press Generate Set and settle, leaving any message box open for inspection. */
async function pressGenerate() {
  control('Generate Set').dispatch('click');
  await settle();
}

async function typeTotal(value) {
  const field = totalField();
  field.value = value;
  field.dispatch('input');
}

/* Add an anchor by driving the real dialog: press + Add Anchor, answer the
 * browse request, click a row, type a position, press Add to Set. */
async function addAnchor(track, position, index = 0) {
  control('+ Add Anchor').dispatch('click');
  await settle();
  fetches.deliver(BROWSE_KEY, { tracks: [ALPHA, BETA], total: 2 });
  await settle();

  const modal = topModal();
  const options = byClass(modal, 'picker__option');
  assert.ok(options.length > index, 'the picker rendered no options');
  options[index].dispatch('click');

  const positionField = document.getElementById('anchor-position');
  positionField.value = String(position);

  const add = byClass(modal, 'button').find((node) => node.textContent === 'Add to Set');
  add.dispatch('click');
  await settle();
}

// ---------------------------------------------------------------------------
// Defaults and the resting state
// ---------------------------------------------------------------------------

test('the length field starts at "10", as a string', async () => {
  mount();

  assert.equal(DEFAULT_TOTAL_TRACKS, '10', 'inventory :449');
  assert.equal(totalField().value, '10');
  assert.equal(typeof DEFAULT_TOTAL_TRACKS, 'string');
});

test('the resting status is the tab hint, verbatim', async () => {
  mount();

  assert.equal(
    statusLine(),
    "💡 1) Click '+ Add Anchor' and choose a track + it's position in the set. " +
      "2) Set 'Total Tracks'. 3) Click 'Generate Set'. 4) Adjust anchors and regenerate as needed.",
  );
});

test('every catalogued control is on screen', async () => {
  mount();

  for (const label of [
    'Generate Set',
    'Clear Set',
    '+ Add Anchor',
    'Remove',
    'Export to Clipboard',
  ]) {
    control(label);
  }
  const labels = textsByClass(dom.root, 'eyebrow').concat(
    byClass(dom.root, 'field__label').map((node) => node.textContent),
  );
  assert.ok(labels.includes('Total Tracks:'), 'inventory :448');
  assert.ok(labels.includes('Anchor Tracks:'), 'inventory :454');
  assert.ok(labels.includes('Generated Set:'), 'inventory :461');
});

// ---------------------------------------------------------------------------
// Generate Set: the three checks, IN ORDER
// ---------------------------------------------------------------------------

test('a length that is not an integer is refused before anything else is looked at', async () => {
  // BOTH conditions are wrong here - the length is blank AND there are no
  // anchors. Inventory :501 comes first, so the second message must not be the
  // one shown. A test with only one condition wrong cannot tell the orders
  // apart.
  mount();
  await typeTotal('');
  const since = mark();

  await pressGenerate();

  assert.deepEqual(messageBox().title, 'Invalid Input');
  assert.equal(messageBox().message, 'Please enter a valid number for total tracks.');
  assert.deepEqual(messageBox().buttons, ['OK']);
  assert.equal(setRequestsSince(since).length, 0, 'a refused request was still sent');
  await answer('OK');
});

test('"10.0" is not an integer, because int() says so', async () => {
  // `Number("10.0")` is 10 and `parseInt("10.0")` is 10; Python's int() raises.
  // The catalogued check is Python's.
  mount();
  await typeTotal('10.0');

  await pressGenerate();

  assert.equal(messageBox().title, 'Invalid Input');
  await answer('OK');
});

test('no anchors is the second check, not the first', async () => {
  mount();
  await typeTotal('10');

  await pressGenerate();

  assert.equal(messageBox().title, 'No Anchors');
  assert.equal(
    messageBox().message,
    'Please add at least one anchor track before generating a set.',
  );
  await answer('OK');
});

test('a length below the anchor count is the third check', async () => {
  mount();
  await addAnchor(ALPHA, 1);
  await addAnchor(BETA, 2, 1);
  await typeTotal('1');

  await pressGenerate();

  assert.equal(messageBox().title, 'Invalid Configuration');
  assert.equal(
    messageBox().message,
    'Total tracks must be greater than the number of anchor tracks.',
  );
  await answer('OK');
});

test('a length EQUAL to the anchor count generates, despite the wording', async () => {
  // Inventory :505 - the message says "greater than" and the check is `<`.
  const { view } = mount();
  await addAnchor(ALPHA, 1);
  await addAnchor(BETA, 2, 1);
  await typeTotal('2');

  await pressGenerate();

  assert.equal(messageBox(), null, 'no dialog should have been raised');
  assert.equal(fetches.outstanding(SET_KEY), true, 'the request was never sent');
  fetches.deliver(SET_KEY, { tracks: SET.slice(0, 2) });
  await settle();
  assert.equal(view.state().generatedSet.length, 2);
});

// ---------------------------------------------------------------------------
// The request, and the four status strings
// ---------------------------------------------------------------------------

test('the request carries the anchor map and the length', async () => {
  mount();
  await addAnchor(ALPHA, 3);
  await typeTotal('6');
  const since = mark();

  await pressGenerate();

  const sent = setRequestsSince(since);
  assert.equal(sent.length, 1);
  assert.equal(sent[0].options.method, 'POST');
  assert.deepEqual(JSON.parse(sent[0].options.body), {
    anchors: { 3: 'a1' },
    total_tracks: 6,
  });

  fetches.deliver(SET_KEY, { tracks: SET });
  await settle();
});

test('the status says generating, then how many tracks it generated', async () => {
  mount();
  await addAnchor(ALPHA, 1);

  await pressGenerate();
  assert.equal(statusLine(), '🎵 Generating set... This may take a moment.');

  fetches.deliver(SET_KEY, { tracks: SET });
  await settle();
  assert.equal(statusLine(), '✅ Generated 3-track set successfully!');
});

test('a refused set shows the generation error and the failure status', async () => {
  mount();
  await addAnchor(ALPHA, 9);
  await typeTotal('4');

  await pressGenerate();
  fetches.deliverError(
    SET_KEY,
    400,
    'set_generation_failed',
    'Anchor track position exceeds total tracks',
  );
  await settle();

  assert.equal(messageBox().title, 'Generation Error');
  assert.equal(
    messageBox().message,
    'Failed to generate set: Anchor track position exceeds total tracks',
  );
  await answer('OK');
  assert.equal(statusLine(), '❌ Set generation failed.');
});

test('Clear Set empties both lists and says so, with no confirmation', async () => {
  const { view } = mount();
  await addAnchor(ALPHA, 1);
  await pressGenerate();
  fetches.deliver(SET_KEY, { tracks: SET });
  await settle();
  assert.equal(anchorRows().length, 1);
  assert.equal(setRows().length, 3);

  control('Clear Set').dispatch('click');
  await settle();

  assert.equal(messageBox(), null, 'inventory :519 - no confirmation');
  assert.equal(anchorRows().length, 0);
  assert.equal(setRows().length, 0);
  assert.equal(statusLine(), '🧹 Set cleared.');
  assert.deepEqual(view.state().anchors, {});
  assert.deepEqual(view.state().generatedSet, []);
});

// ---------------------------------------------------------------------------
// The rendered rows
// ---------------------------------------------------------------------------

test('anchors render as "{position}. {artist} – {title}", ascending', async () => {
  mount();
  await addAnchor(BETA, 7, 1);
  await addAnchor(ALPHA, 2, 0);

  assert.deepEqual(anchorTexts(), [
    '2. Blawan – Why They Hide',
    '7. Alva Noto – Xerrox',
  ]);
});

test('the generated rows carry position, icon, display name and the suffix', async () => {
  mount();
  await addAnchor(ALPHA, 2);
  await pressGenerate();
  fetches.deliver(SET_KEY, { tracks: SET });
  await settle();

  const rows = setRows().map(setRowFields);

  assert.deepEqual(rows[0], {
    position: '1',
    icon: '🤖',
    name: 'Blawan – Why They Hide',
    score: '97% match',
  });
  // Inventory :488 - an anchor carries score 1.0 and never shows it.
  assert.deepEqual(rows[1], {
    position: '2',
    icon: '🔒',
    name: 'Alva Noto – Xerrox',
    score: undefined,
  });
  // Inventory :490-494 - the placeholder, with no suffix because its score is 0.
  assert.deepEqual(rows[2], {
    position: '3',
    icon: '🤖',
    name: 'No suitable track found – (Unknown Title)',
    score: undefined,
  });
});

test('the two rules that hide the suffix are one condition, not two special cases', async () => {
  // Inventory :487 - "shown ONLY for non-anchors with score > 0".
  assert.equal(scoreSuffix({ is_anchor: true, score: 1.0 }), '');
  assert.equal(scoreSuffix({ is_anchor: false, score: 0.0 }), '');
  assert.equal(scoreSuffix({ is_anchor: false, score: -0.2 }), '');
  assert.equal(scoreSuffix({ is_anchor: false, score: 0.5 }), '50% match');
  // A cosine above 1 renders above 100 %, per :489. It is not clamped.
  assert.equal(scoreSuffix({ is_anchor: false, score: 1.4 }), '140% match');
});

test('the percentage rounds the way Python’s .0% rounds, not the way JS does', async () => {
  // Every one of these is a tie after `x * 100`. Python rounds a tie to EVEN;
  // `Math.round` and `.toFixed(0)` round away from zero, and would give the
  // second number in each pair.
  const ties = [
    [0.005, 0],
    [0.045, 4],
    [0.125, 12],
    [0.135, 14],
    [0.145, 14],
    [0.235, 24],
    [0.855, 86],
    [0.965, 96],
    [0.995, 100],
  ];
  for (const [value, expected] of ties) {
    assert.equal(wholePercent(value), expected, `${value} should render as ${expected}%`);
    assert.notEqual(
      wholePercent(value),
      Math.round(value * 100) === expected ? -1 : Math.round(value * 100),
      `${value} must not use Math.round`,
    );
  }
  // ...and it still agrees on everything that is not a tie.
  assert.equal(wholePercent(0.9669962525367737), 97);
  assert.equal(wholePercent(0.9391191601753237), 94);
});

// ---------------------------------------------------------------------------
// Remove
// ---------------------------------------------------------------------------

test('Remove with nothing selected warns and removes nothing', async () => {
  mount();
  await addAnchor(ALPHA, 1);

  control('Remove').dispatch('click');
  await settle();

  assert.equal(messageBox().title, 'No Selection');
  assert.equal(messageBox().message, 'Please select an anchor track to remove.');
  await answer('OK');
  assert.equal(anchorRows().length, 1, 'the anchor was removed anyway');
});

test('Remove takes out the selected anchor and only that one', async () => {
  const { view } = mount();
  await addAnchor(ALPHA, 1);
  await addAnchor(BETA, 5, 1);

  anchorRows()[1].dispatch('click');
  await settle();
  control('Remove').dispatch('click');
  await settle();

  assert.equal(messageBox(), null);
  assert.deepEqual(Object.keys(view.state().anchors), ['1']);
  assert.deepEqual(anchorTexts(), ['1. Blawan – Why They Hide']);
});

// ---------------------------------------------------------------------------
// Export to Clipboard
// ---------------------------------------------------------------------------

test('Export with no generated set warns and copies nothing', async () => {
  mount();
  const before = clipboard.written.length;

  control('Export to Clipboard').dispatch('click');
  await settle();

  assert.equal(messageBox().title, 'No Set');
  assert.equal(messageBox().message, 'Please generate a set first.');
  await answer('OK');
  assert.equal(clipboard.written.length, before, 'nothing should have been copied');
});

test('Export copies one display name per line and leaves the unfillable row out', async () => {
  mount();
  await addAnchor(ALPHA, 2);
  await pressGenerate();
  fetches.deliver(SET_KEY, { tracks: SET });
  await settle();

  control('Export to Clipboard').dispatch('click');
  await settle();

  // Inventory :530-533 - no positions, no icons, no scores, and the
  // "No suitable track found" row excluded. Three rows in, two lines out.
  assert.equal(clipboard.written.at(-1), 'Blawan – Why They Hide\nAlva Noto – Xerrox');
  assert.equal(messageBox().title, 'Exported');
  assert.equal(messageBox().message, 'Copied 2 tracks to clipboard!');
  await answer('OK');
});

// ---------------------------------------------------------------------------
// Modality
// ---------------------------------------------------------------------------

test('a message box makes the shell inert, and clearing it comes before focus', async () => {
  mount();

  control('Export to Clipboard').dispatch('click');
  await settle();

  assert.equal(dom.app.hasAttribute('inert'), true, 'the shell is still reachable');
  assert.equal(dom.app.getAttribute('aria-hidden'), 'true');

  await answer('OK');

  assert.equal(dom.app.hasAttribute('inert'), false);
  assert.equal(dom.app.hasAttribute('aria-hidden'), false);
});

test('the destination renders nothing while another destination is showing', async () => {
  const { store } = mount();
  assert.ok(dom.root.children.length, 'the destination did not render at all');

  const before = dom.root.children.length;
  store.setState({ destination: 'explore' });

  // render() returns early rather than clearing: switching away must not throw
  // away the anchors, which is what a Tk notebook tab does.
  assert.equal(dom.root.children.length, before);
});
