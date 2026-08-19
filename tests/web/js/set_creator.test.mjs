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

/* The text `renderAnchors` puts up when there are no anchors, named here so
 * `setPlaceholder` can exclude it. Both sections render `setc__empty`, and
 * after `Clear Set` both of them do at once. */
const NO_ANCHORS_TEXT = 'No anchors yet. Add one to fix a track at a position in the set.';

/** The `Generated Set:` section's empty-state line, or undefined. */
function setPlaceholder() {
  return textsByClass(dom.root, 'setc__empty').find((text) => text !== NO_ANCHORS_TEXT);
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
// A generation in flight versus the configuration on screen
//
// Every test above answers the /api/set request BEFORE it presses anything
// else, which is the one ordering in which this class of defect cannot appear.
// These press first and answer afterwards.
// ---------------------------------------------------------------------------

test('Clear Set is not undone by the generation that was already in flight', async () => {
  const { view } = mount();
  await addAnchor(ALPHA, 1);

  await pressGenerate();
  assert.ok(fetches.outstanding(SET_KEY), 'the generation has not been answered yet');

  control('Clear Set').dispatch('click');
  await settle();
  assert.deepEqual(view.state().anchors, {});
  assert.equal(statusLine(), '🧹 Set cleared.');

  // The response the user never waited for.
  fetches.deliver(SET_KEY, { tracks: SET });
  await settle();

  assert.deepEqual(view.state().generatedSet, [], 'the cleared set came back');
  assert.equal(setRows().length, 0);
  assert.deepEqual(view.state().anchors, {});
  assert.equal(statusLine(), '🧹 Set cleared.', 'the cleared status was overwritten');
});

test('a set built for anchors that have since changed is not rendered over the new ones', async () => {
  const { view } = mount();
  await addAnchor(ALPHA, 1);

  await pressGenerate();
  // The anchor the set was requested for is taken out while it is being built.
  anchorRows()[0].dispatch('click');
  control('Remove').dispatch('click');
  await settle();
  await addAnchor(BETA, 3, 1);

  fetches.deliver(SET_KEY, { tracks: SET });
  await settle();

  assert.deepEqual(view.state().generatedSet, [], 'a set for the old anchors was rendered');
  assert.deepEqual(Object.keys(view.state().anchors), ['3']);
  assert.notEqual(statusLine(), '✅ Generated 3-track set successfully!');
});

test('a configuration that changes and changes back leaves the generation valid', async () => {
  // The positive control for the two tests above. A check that discarded every
  // late response would pass both of them and be useless, because the answer
  // that arrives here really is an answer to what is on screen.
  const { view } = mount();
  await addAnchor(ALPHA, 1);

  await pressGenerate();
  anchorRows()[0].dispatch('click');
  control('Remove').dispatch('click');
  await settle();
  await addAnchor(ALPHA, 1);

  fetches.deliver(SET_KEY, { tracks: SET });
  await settle();

  assert.equal(view.state().generatedSet.length, 3);
  assert.equal(statusLine(), '✅ Generated 3-track set successfully!');
});

test('the length retyped as the same number leaves the generation valid', async () => {
  // The other half of the positive control, for the one input that is typed
  // into rather than clicked. The key holds the length AS IT PARSES, so
  // touching the field without changing the number it holds is not a
  // configuration change: `030` is the same thirty, and so is an Arabic-Indic
  // thirty - which is a length this library's owner can type, and which the
  // frontend used to refuse outright.
  const { view } = mount();
  await addAnchor(ALPHA, 1);
  await typeTotal('30');

  await pressGenerate();
  await typeTotal('030');
  await typeTotal('\u0663\u0660');

  fetches.deliver(SET_KEY, { tracks: SET });
  await settle();

  assert.equal(view.state().generatedSet.length, 3, 'a still-valid answer was discarded');
  assert.equal(statusLine(), '✅ Generated 3-track set successfully!');
});

test('the destination stops claiming it is building once the abandoned response lands', async () => {
  const { view } = mount();
  await addAnchor(ALPHA, 1);

  await pressGenerate();
  assert.equal(control('Generate Set').disabled, true, 'a build is in flight');

  control('Clear Set').dispatch('click');
  await settle();
  assert.equal(
    setPlaceholder(),
    'Nothing generated yet. Set a length, add an anchor, then Generate Set.',
    'the cleared destination still said it was building a set',
  );

  fetches.deliver(SET_KEY, { tracks: SET });
  await settle();

  assert.equal(control('Generate Set').disabled, false, 'Generate Set stayed disabled');
  assert.equal(view.state().building, null);
});

/* What `POST /api/set` returns once the anchored track has been deleted on
 * another destination: three tracks, none of them the anchor, and NO anchor on
 * the position that asked for one. `generate_set` places an anchor only
 * `if track_id in meta_ix.index` (recommendations/set_generator.py:55), so the
 * slot is filled by an ordinary generated pick.
 * Pinned on the Python side by
 * `tests/web/test_api_set.py::test_an_anchor_deleted_after_it_was_chosen_takes_the_same_path`,
 * which reaches this response through a real `delete_tracks`. */
const SET_WITHOUT_THE_DELETED_ANCHOR = SET.map((track) =>
  track.is_anchor
    ? {
        ...track,
        track_id: 'g2',
        is_anchor: false,
        score: 0.8412,
        icon: '🤖',
        artist: 'Function',
        title: 'Voiceprint',
        display_name: 'Function – Voiceprint',
      }
    : track,
);

test('an anchor deleted on another destination keeps its row, and the set is where the loss shows', async () => {
  /* §6.6. The anchor row is a capture taken when the anchor was CHOSEN - the
   * artist and title ride along in `anchors` rather than being looked up in
   * `meta_ix` at render time the way set_creator_tab.py:88-90 looks them up -
   * so a DELETE on the Library destination cannot reach it. Tk's row vanishes
   * (:473, "skipped entirely if its track_id is no longer in meta_ix") and this
   * one does not. Declared, not fixed: the drop cannot be inferred from the
   * response, because :967's duplicate anchor produces the identical shape.
   */
  const { view } = mount();
  await addAnchor(ALPHA, 1);

  await pressGenerate();
  fetches.deliver(SET_KEY, { tracks: SET_WITHOUT_THE_DELETED_ANCHOR });
  await settle();

  // The row stays, unchanged, and stays selectable - which is what makes it
  // removable, and is the reason this is the better of the two behaviours.
  assert.deepEqual(anchorTexts(), ['1. Blawan – Why They Hide']);
  assert.deepEqual(Object.keys(view.state().anchors), ['1']);

  // And the set is where the loss is visible: nothing is locked, and the track
  // that was anchored is not in the set at all.
  const rows = setRows().map(setRowFields);
  assert.equal(rows.length, 3);
  assert.deepEqual(
    rows.map((row) => row.icon),
    ['🤖', '🤖', '🤖'],
    'a set built without the anchor still shows a lock',
  );
  assert.ok(
    !view.state().generatedSet.some((track) => track.track_id === ALPHA.track_id),
    'the deleted anchor came back in the set',
  );
  // Nothing says so, in either implementation.
  assert.equal(statusLine(), '✅ Generated 3-track set successfully!');
});

test('a failed regeneration leaves the previous set on screen, as Tk does', async () => {
  // set_creator_tab.py:113 assigns the RESULT of build() to self.generated_set,
  // so a raise never reaches the assignment and never reaches
  // update_set_listbox either: the last good set stays in the listbox behind
  // the "Generation Error" dialog.
  const { view } = mount();
  await addAnchor(ALPHA, 1);
  await pressGenerate();
  fetches.deliver(SET_KEY, { tracks: SET });
  await settle();
  assert.equal(setRows().length, 3);

  await typeTotal('2');
  await pressGenerate();
  fetches.deliverError(
    SET_KEY,
    400,
    'set_generation_failed',
    'Anchor track position exceeds total tracks',
  );
  await settle();
  await answer('OK');

  assert.equal(view.state().generatedSet.length, 3, 'the previous set was thrown away');
  assert.equal(setRows().length, 3);
  assert.equal(statusLine(), '❌ Set generation failed.');
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

test('the anchor rows are reachable and selectable without a mouse', async () => {
  /* Same defect as the picker's: `Remove` (:458) acts on a selection, and a
   * list of unfocusable `role="option"` rows gives a keyboard user no way to
   * make one - so `Remove` was a control they could press and never satisfy. */
  const { view } = mount();
  await addAnchor(ALPHA, 1);
  await addAnchor(BETA, 5, 1);

  assert.deepEqual(
    anchorRows().map((row) => row.getAttribute('tabindex')),
    ['0', '-1'],
    'roving tabindex: one tab stop, not one per anchor',
  );

  anchorRows()[0].dispatch('keydown', { key: 'ArrowDown', preventDefault() {} });

  assert.equal(view.state().selectedAnchor, 5);
  assert.deepEqual(
    anchorRows().map((row) => row.getAttribute('aria-selected')),
    ['false', 'true'],
  );
  assert.equal(document.activeElement, anchorRows()[1]);

  control('Remove').dispatch('click');
  await settle();

  assert.equal(messageBox(), null, 'the keyboard selection was not seen');
  assert.deepEqual(Object.keys(view.state().anchors), ['1']);
});

test('selecting an anchor does not rebuild the destination around it', async () => {
  // If it did, the arrow keys would destroy the node they just focused - and
  // the caret in Total Tracks would be thrown away on every selection.
  const { view } = mount();
  await addAnchor(ALPHA, 1);
  await addAnchor(BETA, 5, 1);

  const before = anchorRows();
  const field = totalField();
  anchorRows()[0].dispatch('keydown', { key: 'ArrowDown', preventDefault() {} });

  assert.equal(anchorRows()[0], before[0], 'the rows were rebuilt');
  assert.equal(totalField(), field, 'the Total Tracks field was rebuilt');
  assert.equal(view.state().selectedAnchor, 5);
});

test('clearing the anchors leaves no stale rows behind to write on', async () => {
  // `renderAnchors` returns early when there is nothing to list, so the cached
  // row nodes have to be dropped at the TOP of it. Kept from the previous
  // render, `selectAnchor` would be setting aria-selected on detached nodes.
  const { view } = mount();
  await addAnchor(ALPHA, 1);
  anchorRows()[0].dispatch('click');
  assert.equal(view.state().selectedAnchor, 1);

  control('Clear Set').dispatch('click');
  await settle();

  assert.equal(anchorRows().length, 0);
  assert.equal(view.state().selectedAnchor, null);

  // Re-adding must produce a row that is itself selectable, not one shadowed
  // by a node from two renders ago.
  await addAnchor(BETA, 4, 1);
  anchorRows()[0].dispatch('keydown', { key: 'Enter', preventDefault() {} });
  assert.equal(view.state().selectedAnchor, 4);
  assert.equal(anchorRows()[0].getAttribute('aria-selected'), 'true');
});

test('Enter on a selected anchor row deselects it', async () => {
  const { view } = mount();
  await addAnchor(ALPHA, 1);

  anchorRows()[0].dispatch('keydown', { key: 'Enter', preventDefault() {} });
  assert.equal(view.state().selectedAnchor, 1);

  anchorRows()[0].dispatch('keydown', { key: 'Enter', preventDefault() {} });
  assert.equal(view.state().selectedAnchor, null, 'a second Enter did not deselect');
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
