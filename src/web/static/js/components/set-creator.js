/* The Set Creator destination.
 *
 * Implemented against the control list in docs/UI_FEATURE_INVENTORY.md §2.5
 * (lines 441-533). What is reimplemented here, with the inventory line it comes
 * from:
 *
 *   :448-449 `Total Tracks:` + entry, default "10" -> the total field
 *   :450  `Generate Set`                -> the primary button
 *   :451  `Clear Set`                   -> the button beside it
 *   :454  `Anchor Tracks:` label        -> the anchor section heading
 *   :455  `+ Add Anchor`                -> opens AddAnchorDialog (§2.12)
 *   :457  the anchor listbox            -> a single-selection anchor list
 *   :458  `Remove`                      -> removes the selected anchor
 *   :461  `Generated Set:` label        -> the set section heading
 *   :462  the set listbox               -> the generated rows
 *   :463  `Export to Clipboard`         -> the button below them
 *   :471  `{position}. {artist} – {title}` -> the anchor row
 *   :479-489 `[{position:2d}] {icon} {display_name}{score_text}` -> the set row
 *   :490-495 the unfillable placeholder row
 *   :501-503 the three pre-generation checks, IN ORDER
 *   :506-508 `Generation Error` for what the builder rejects
 *   :510-514 the four status-bar strings
 *   :518  `Clear Set` clears both lists, no confirmation
 *   :523  `Remove` with no selection
 *   :529-533 `Export to Clipboard`, excluding unfillable rows
 *   :271  the tab's default status hint (§2.2)
 *
 * Anything from §2.5 not in that list is named in the PR description with its
 * line number. Silent omission is the one thing this PR cannot do.
 *
 * STATE LIVES HERE, NOT IN THE STORE
 * ----------------------------------
 * Unlike Explore, whose seed and recommendation list the drawer and the palette
 * both reach for, nothing outside this destination reads an anchor or a
 * generated row. So the working state is a closure, as the palette's is, and
 * the store is subscribed to only for what is genuinely shared: which
 * destination is showing, and whether the library loaded. That keeps `main.js`
 * - which another branch is editing at the same time - down to an import and a
 * mount call, with no state keys of its own to collide over.
 *
 * The state survives navigating away and back, which is what a Tk notebook tab
 * does.
 */

import { api, ApiError } from '../api.js';
import { copyToClipboard } from '../clipboard.js';
import { element, stateBlock, wholePercent, parseIntegerStrictly } from '../format.js';
import { wireListbox } from '../listbox.js';
import { openAnchorDialog } from './anchor-dialog.js';
import { firstRunGuidance } from './library-guidance.js';
import { showerror, showinfo, showwarning } from './message-box.js';

/* Inventory :449 - `tk.StringVar(value="10")`. A STRING, not a number: :501's
 * first check is "not an integer", which only exists because the entry holds
 * whatever was typed into it. */
export const DEFAULT_TOTAL_TRACKS = '10';

/* Inventory :271 - `get_hint_for_tab`'s Set Creator entry (app.py:130-132),
 * verbatim including its "it's". A catalogued string is catalogued as it is,
 * and the PR description flags the typo rather than quietly correcting it. */
const DEFAULT_HINT =
  "💡 1) Click '+ Add Anchor' and choose a track + it's position in the set. " +
  "2) Set 'Total Tracks'. 3) Click 'Generate Set'. 4) Adjust anchors and regenerate as needed.";

/* Inventory :510-514. Four strings, and the status bar is the only place any
 * of them appears. */
const STATUS_GENERATING = '🎵 Generating set... This may take a moment.';
const STATUS_FAILED = '❌ Set generation failed.';
const STATUS_CLEARED = '🧹 Set cleared.';
const statusGenerated = (count) => `✅ Generated ${count}-track set successfully!`;

/* Inventory :530-531 - the marker that keeps an unfillable row off the
 * clipboard. Matched as a SUBSTRING of the rendered display name, which is what
 * set_creator_tab.py:152 does, rather than by testing the id for `empty_`: the
 * catalogued rule is about the name. */
const UNFILLABLE_MARKER = 'No suitable track found';

/* What a row says once the build has told us its track is gone.
 *
 * The row is kept rather than removed - see `droppedAnchorPositions` for why -
 * so it has to stop reading as a live anchor. Without this an anchor row saying
 * "track X is anchored at position 4" sits directly above a set with an
 * ordinary generated track at position 4, and the row is simply false. */
const DROPPED_ANCHOR_NOTE = '⚠️ no longer in the library — this anchor was not used';

/**
 * The score suffix, or `''`.
 *
 * Inventory :487-489. Shown ONLY for a non-anchor with a score above zero.
 * Anchors carry `score=1.0` and never show it, and the unfillable placeholder
 * carries `0.0` and so does not either - which is why the row at :490 has no
 * suffix even though it is not an anchor. Both exclusions come from this one
 * condition; neither is special-cased anywhere.
 */
export function scoreSuffix(track) {
  if (track.is_anchor || !(Number(track.score) > 0)) {
    return '';
  }
  return `${wholePercent(track.score)}% match`;
}

export function mountSetCreator({ store }) {
  const root = document.getElementById('view-set-creator');

  /* `{position: {track_id, artist, title}}`. set_creator_tab.py:54 holds a
   * bare `Dict[int, str]` and looks the artist and title up in `meta_ix` at
   * render time; the artist and title ride along here instead, captured from
   * the search result the anchor was chosen from. The consequence for :473 -
   * "skipped entirely if its track_id is no longer in meta_ix" - is in the PR
   * description. */
  let anchors = {};
  let totalTracks = DEFAULT_TOTAL_TRACKS;
  let generatedSet = [];
  let status = DEFAULT_HINT;
  let selectedAnchor = null;

  /* The configuration key of the generation in flight, or `null`.
   *
   * A generated set is written only if the configuration it was built FROM is
   * still the configuration on screen. `Clear Set` is what made that a defect
   * rather than a nicety: it emptied both lists while a generation was in
   * flight, and the set came back when the response landed - anchors and all,
   * over the top of "Set cleared.". The same window let an anchor change
   * produce a set that no longer matched the rows above it.
   *
   * Explore and the palette solve this shape with a sequence counter
   * (explore.js:151, palette.js:47). The oracle here is the CONFIGURATION
   * ITSELF rather than a counter, because a counter has a bump site and this
   * project has already paid for getting one wrong: PR #14 fixed a palette bug
   * where the sequence was bumped when the REQUEST STARTED instead of when the
   * INPUT CHANGED, leaving a window in which a response for a query the user
   * had moved past was still considered current. `configurationKey()` reads
   * the anchors and the length that are on screen at the moment the answer
   * arrives, so there is no bump site to forget, to place late, or to
   * reintroduce - including for `Total Tracks`, which is typed into and
   * deliberately does not re-render.
   *
   * Holding the KEY rather than a boolean also means the "a set is being
   * built" flag and the staleness check cannot disagree about which build is
   * current: `building === configurationKey()` is one expression, used by both.
   */
  let building = null;

  /* The rendered anchor rows, so selecting one can update `aria-selected` in
   * place. A full re-render would destroy the node the arrow keys just focused,
   * which is the whole reason the roving tabindex in `listbox.js` works. */
  let anchorRowNodes = [];

  // -- actions ------------------------------------------------------------

  /* Everything a generated set depends on, as one comparable value: the
   * anchors in position order and the length AS IT PARSES. Not a hash and not
   * an identity - two configurations that would produce the same set compare
   * equal, which is what makes remove-then-re-add-the-same-anchor leave an
   * in-flight generation valid rather than throwing away a correct answer.
   *
   * The length goes through `parseIntegerStrictly` rather than in raw, for the
   * same reason: `30`, `030` and an Arabic-Indic thirty are one configuration,
   * and touching the field without changing the number it holds should not
   * discard an answer that is still correct. `null` for a length that does not
   * parse is a value like any other - a build cannot have been started from
   * one, so a key holding it can only ever compare unequal.
   *
   * WHAT THE KEY DOES NOT COVER: THE LIBRARY. Declared, not fixed.
   * The key covers every input of the REQUEST - `POST /api/set` takes exactly
   * `anchors` and `total_tracks` (`web/api.py:325-339`) and both are in here,
   * with no component-local seed, sort or exclusion hiding behind them. It
   * covers none of the SERVER STATE the answer also depends on. The generated
   * set is a function of the library too, and the library is mutable: the
   * sibling Library destination's DELETE lands on the same session this build
   * is reading.
   *
   * So a refresh on the Library destination while a generation is outstanding
   * leaves the anchors and the length untouched, the key compares EQUAL, and a
   * set built against a library that no longer exists is accepted and
   * rendered. A counter would not have caught it either - this is not the bug
   * PR #14 fixed, it is a different input missing from the oracle entirely.
   *
   * It cannot be closed from here. The response is `{tracks: [...]}` and
   * carries no library identity, and `GET /api/library` exposes `track_count`
   * but no revision - and a count is not a revision, because a delete followed
   * by a reindex can restore it. The robust form is this semantic key PLUS a
   * library revision, or explicit invalidation when the library mutates; the
   * first needs new response surface and the second needs the sibling PR's
   * delete path, and this PR owns neither.
   *
   * Inventory §6.6 records it together with the SetBuilder snapshot window,
   * because they are one defect wearing two hats: the library can change under
   * an in-flight operation and nothing notices. Both are fixed in the
   * follow-up that gives `LibrarySession` an atomically published snapshot. */
  function configurationKey() {
    return JSON.stringify([
      anchorPositions().map((position) => [position, anchors[position].track_id]),
      parseIntegerStrictly(totalTracks),
    ]);
  }

  /* Which of the anchors we ASKED for the build did not honour.
   *
   * THE TWO CASES ARE DISTINGUISHABLE FROM THE RESPONSE AS IT STANDS, and an
   * earlier version of this destination said they were not. It declined to
   * touch the row on the grounds that a deleted anchor and :967's
   * duplicate-anchor case "produce the identical shape", so any frontend rule
   * would remove the wrong row. Probed against the real endpoint on the
   * twelve-track fixture, over five tracks, they are not identical at all:
   *
   *   duplicate {1: f01, 4: f01} -> 4 tracks, positions [1, 2, 3, 5]
   *                                 position 4 ABSENT
   *   deleted   {1: f06, 4: f01} -> 5 tracks, positions [1, 2, 3, 4, 5]
   *                                 position 1 PRESENT, f02, is_anchor false
   *
   * `generate_set` drops a deleted anchor and lets an ordinary pick FILL the
   * slot, while its de-duplication pass filters the assembled list and takes
   * the slot away with the row (`set_generator.py:176-187`). So a requested
   * position that came back OCCUPIED BY SOMETHING ELSE is a dropped anchor, and
   * a requested position that is MISSING ENTIRELY is the duplicate. The two
   * differ in the response length as well, which is a second, independent
   * signal; the position rule alone is enough and is the one used here.
   *
   * No new API field, and no guessing.
   */
  function droppedAnchorPositions(request, tracks) {
    const filledPositions = new Set(tracks.map((track) => Number(track.position)));
    const anchoredIds = new Set(
      tracks.filter((track) => track.is_anchor).map((track) => track.track_id),
    );
    const dropped = [];
    for (const [position, trackId] of Object.entries(request)) {
      if (!filledPositions.has(Number(position))) {
        // The slot is GONE, not reassigned: the de-duplication case, which
        // filters the assembled list instead of refilling the position. The
        // track is still in the library and the row is still true.
        continue;
      }
      if (anchoredIds.has(trackId)) {
        // PLACED - either at the position we asked for, which is the ordinary
        // case, or at the one occurrence de-duplication kept, which is :967's.
        // Both mean the library still has the track, so the row is still true.
        //
        // This one check covers both because a deleted track is dropped at
        // EVERY position at once (`set_generator.py:55` tests `meta_ix.index`
        // once per anchor), so an id anchored anywhere in the answer cannot be
        // a deleted one. A separate `row is exactly our anchor` fast path was
        // written here first and removed: it is strictly subsumed by this, and
        // a mutation disabling it survived the whole suite - a branch no test
        // can reach is a branch that will be wrong silently.
        continue;
      }
      dropped.push(Number(position));
    }
    return dropped;
  }

  async function addAnchor() {
    const chosen = await openAnchorDialog({ existingAnchors: anchors });
    if (!chosen) {
      return;
    }
    anchors = {
      ...anchors,
      [chosen.position]: {
        track_id: chosen.track.track_id,
        artist: chosen.track.artist || '',
        title: chosen.track.title || '',
      },
    };
    render();
  }

  /* Inventory :523-525. The Tk version parses the position back out of the row
   * text by splitting on the first `.`; this keeps the position on the row, so
   * the parse - and its silently-ignored failure, which the row format makes
   * unreachable either way - has nothing to do. Same observable behaviour. */
  async function removeAnchor() {
    if (selectedAnchor === null || !(selectedAnchor in anchors)) {
      await showwarning('No Selection', 'Please select an anchor track to remove.');
      return;
    }
    const remaining = { ...anchors };
    delete remaining[selectedAnchor];
    anchors = remaining;
    selectedAnchor = null;
    render();
    focusAnchorControl('Remove');
  }

  /* After a re-render the node that had focus is gone, so the caret would land
   * back at the top of the document. Putting it on the named control keeps a
   * keyboard user where they were working. */
  function focusAnchorControl(label) {
    const control = [...root.querySelectorAll('button')].find(
      (button) => button.textContent.trim() === label,
    );
    if (control && typeof control.focus === 'function') {
      control.focus();
    }
  }

  /* Inventory :501-503, in the catalogued order, then :506-508 for whatever the
   * builder itself rejects. The order is observable: with a blank Total Tracks
   * AND no anchors, the message is "Invalid Input", not "No Anchors". */
  async function generate() {
    const total = parseIntegerStrictly(totalTracks);
    if (total === null) {
      await showerror('Invalid Input', 'Please enter a valid number for total tracks.');
      return;
    }

    const positions = Object.keys(anchors);
    if (!positions.length) {
      await showwarning(
        'No Anchors',
        'Please add at least one anchor track before generating a set.',
      );
      return;
    }

    // :505 - the message says *greater than* and the check is `<`, so a total
    // EQUAL to the anchor count generates. Preserved, wording and all.
    if (total < positions.length) {
      await showerror(
        'Invalid Configuration',
        'Total tracks must be greater than the number of anchor tracks.',
      );
      return;
    }

    // Captured BEFORE the await, so what comes back can be compared against
    // what the screen says when it does.
    const requested = configurationKey();
    building = requested;
    status = STATUS_GENERATING;
    render();

    const request = {};
    for (const [position, anchor] of Object.entries(anchors)) {
      request[position] = anchor.track_id;
    }

    let body;
    try {
      body = await api.generateSet(request, total);
    } catch (error) {
      building = null;
      if (requested !== configurationKey()) {
        render();
        return;
      }
      // :507-508 - "Failed to generate set: {error}". The message is the
      // service's own, carried over the wire by `set_generation_failed`.
      //
      // The previously generated set is LEFT on screen. Tk assigns the result
      // of `build()` to `self.generated_set` (set_creator_tab.py:113), so a
      // raise never reaches the assignment and never reaches
      // `update_set_listbox` either: the last good set stays in the listbox
      // behind the "Generation Error" dialog. Clearing it here would lose a set
      // the user still has, because a regenerate they asked for failed.
      status = STATUS_FAILED;
      render();
      await showerror('Generation Error', `Failed to generate set: ${messageFor(error)}`);
      return;
    }

    building = null;
    if (requested !== configurationKey()) {
      // The anchors or the length changed while this was in flight, so this
      // set answers a question the screen is no longer asking. Nothing is
      // written and nothing is said - the action that changed the
      // configuration has already had its say - but the render puts
      // `Generate Set` back within reach.
      render();
      return;
    }
    generatedSet = body.tracks;

    // Only here. A failed build and an abandoned one say nothing about which
    // anchors the library still has, so neither may mark a row - and a mark
    // already on a row survives until a build that HONOURS that anchor clears
    // it, which re-adding the track at the same position also does, because
    // `addAnchor` writes a fresh anchor object.
    const dropped = new Set(droppedAnchorPositions(request, body.tracks));
    anchors = Object.fromEntries(
      Object.entries(anchors).map(([position, anchor]) => [
        position,
        { ...anchor, dropped: dropped.has(Number(position)) },
      ]),
    );

    status = statusGenerated(generatedSet.length);
    render();
  }

  function messageFor(error) {
    return error instanceof ApiError ? error.message : String(error);
  }

  /* Inventory :518-519. No confirmation, and the status says so.
   *
   * Nothing here has to cancel or invalidate a generation in flight. Emptying
   * the anchors changes `configurationKey()`, and that is the whole of the
   * check the response is measured against when it lands. */
  function clearSet() {
    anchors = {};
    generatedSet = [];
    selectedAnchor = null;
    status = STATUS_CLEARED;
    render();
  }

  /* Inventory :529-533. One display name per line, no positions, icons or
   * scores, and the unfillable rows left out. */
  async function exportSet() {
    if (!generatedSet.length) {
      await showwarning('No Set', 'Please generate a set first.');
      return;
    }

    const lines = generatedSet
      .map((track) => track.display_name)
      .filter((name) => name && !name.includes(UNFILLABLE_MARKER));

    await copyToClipboard(lines.join('\n'));
    await showinfo('Exported', `Copied ${lines.length} tracks to clipboard!`);
  }

  // -- rendering ----------------------------------------------------------

  /** Inventory :473 - ascending position order. */
  function anchorPositions() {
    return Object.keys(anchors)
      .map(Number)
      .sort((left, right) => left - right);
  }

  function renderConfiguration() {
    const row = element('div', 'setc__config');

    const label = element('label', 'field__label', 'Total Tracks:');
    label.setAttribute('for', 'set-total-tracks');
    const field = element('input', 'field__input field__input--narrow');
    field.id = 'set-total-tracks';
    field.type = 'text';
    field.setAttribute('autocomplete', 'off');
    field.setAttribute('inputmode', 'numeric');
    field.value = totalTracks;
    // Held as typed. Re-rendering on every keystroke would rebuild the field
    // and lose the caret, and there is nothing on screen that depends on the
    // value until Generate reads it.
    field.addEventListener('input', () => {
      totalTracks = field.value;
    });

    const generateButton = element('button', 'button button--primary', 'Generate Set');
    generateButton.type = 'button';
    // While a build is in flight, and only then. Not `building ===
    // configurationKey()`: that would let a second generation start whenever
    // the configuration had moved on, and two in-flight builds mean two places
    // that clear `building`.
    generateButton.disabled = building !== null;
    generateButton.addEventListener('click', generate);

    const clearButton = element('button', 'button', 'Clear Set');
    clearButton.type = 'button';
    clearButton.addEventListener('click', clearSet);

    row.append(label, field, generateButton, clearButton);
    return row;
  }

  function renderAnchors() {
    const section = element('section', 'setc__section');
    // Dropped first, not rebuilt at the end: the empty-list branch below
    // returns early, and leaving the previous render's rows here would have
    // `selectAnchor` writing aria-selected onto detached nodes.
    anchorRowNodes = [];

    const heading = element('div', 'setc__heading');
    heading.append(element('p', 'eyebrow', 'Anchor Tracks:'));

    const add = element('button', 'button button--primary', '+ Add Anchor');
    add.type = 'button';
    add.addEventListener('click', addAnchor);

    const remove = element('button', 'button', 'Remove');
    remove.type = 'button';
    remove.addEventListener('click', removeAnchor);

    const controls = element('div', 'setc__heading-actions');
    controls.append(add, remove);
    heading.append(controls);
    section.append(heading);

    const positions = anchorPositions();
    if (!positions.length) {
      section.append(
        element(
          'p',
          'setc__empty',
          'No anchors yet. Add one to fix a track at a position in the set.',
        ),
      );
      return section;
    }

    const list = element('ul', 'anchors');
    list.setAttribute('role', 'listbox');
    list.setAttribute('aria-label', 'Anchor tracks');

    anchorRowNodes = positions.map((position) => {
      const anchor = anchors[position];
      // Inventory :471 - `{position}. {artist} – {title}`.
      const row = element('li', 'anchors__row');
      row.dataset.position = String(position);
      row.setAttribute('role', 'option');
      row.setAttribute('aria-selected', String(selectedAnchor === position));
      row.append(
        element('span', 'anchors__position', `${position}.`),
        element('span', 'anchors__name', anchorName(anchor)),
      );
      if (anchor.dropped) {
        // Marked, not removed and not disabled. Removing it would take away the
        // only record of what the user had chosen, and disabling it would take
        // away the `Remove` that clears it; the note is in the row text, so it
        // reaches a screen reader through the option's accessible name rather
        // than through colour alone.
        row.dataset.dropped = 'true';
        row.append(element('span', 'anchors__dropped', DROPPED_ANCHOR_NOTE));
      }
      row.addEventListener('click', () => {
        // Clicking the selected row deselects it, so `Remove` can be put back
        // into its no-selection state without removing anything.
        selectAnchor(selectedAnchor === position ? null : position);
      });
      return row;
    });

    list.append(...anchorRowNodes);
    // Keyboard reach for a list that calls itself a listbox. Without it
    // `Remove` (:458) is a control a keyboard user can press and never satisfy.
    wireListbox(anchorRowNodes, {
      selected: positions.indexOf(selectedAnchor),
      onSelect: (index) => selectAnchor(positions[index]),
      onActivate: (index) =>
        selectAnchor(selectedAnchor === positions[index] ? null : positions[index]),
    });
    section.append(list);
    return section;
  }

  /* Selection is NOT a re-render. Rebuilding the destination on every arrow
   * key would throw away the focused node and the caret in `Total Tracks`
   * along with it; only the rows' `aria-selected` actually changes. */
  function selectAnchor(position) {
    selectedAnchor = position === undefined ? null : position;
    for (const row of anchorRowNodes) {
      row.setAttribute(
        'aria-selected',
        String(Number(row.dataset.position) === selectedAnchor),
      );
    }
  }

  /* `{artist} – {title}` with the en dash of §3.1, built the way
   * `update_anchor_listbox` builds it (set_creator_tab.py:90) - unconditionally,
   * so a track with no artist shows the leading separator exactly as Tk does.
   * This is NOT `format.displayName`, which drops the separator; that helper
   * exists for the clipboard, where a dangling dash is not visible and is
   * wrong, and this row is the catalogued string. */
  function anchorName(anchor) {
    return `${anchor.artist} – ${anchor.title}`;
  }

  function renderSet() {
    const section = element('section', 'setc__section');
    section.append(element('p', 'eyebrow', 'Generated Set:'));

    if (!generatedSet.length) {
      section.append(
        element(
          'p',
          'setc__empty',
          // The build in flight, if there is one, has to be a build of what is
          // on screen for this to be true. After `Clear Set` there is still a
          // request outstanding and it is no longer about anything the user
          // can see, so this reads as the resting text.
          building === configurationKey()
            ? 'Building the set…'
            : 'Nothing generated yet. Set a length, add an anchor, then Generate Set.',
        ),
      );
      return section;
    }

    const list = element('ol', 'setlist');
    list.setAttribute('aria-label', 'Generated set');
    for (const track of generatedSet) {
      list.append(renderSetRow(track));
    }
    section.append(list);
    return section;
  }

  /* Inventory :479-495. The fields of the catalogued row, laid out rather than
   * padded into a fixed-width string: the position is right-aligned in its own
   * column (which is what `{position:2d}` buys on screen), the icon is the
   * `🔒`/`🤖` the API sent, the name is `display_name` verbatim, and the suffix
   * follows :487's rule exactly. */
  function renderSetRow(track) {
    const row = element('li', 'setlist__row');
    if (track.is_anchor) {
      row.dataset.anchor = 'true';
    }

    row.append(
      element('span', 'setlist__position', String(track.position)),
      element('span', 'setlist__icon', track.icon),
      element('span', 'setlist__name', track.display_name),
    );

    const suffix = scoreSuffix(track);
    if (suffix) {
      row.append(element('span', 'setlist__score', suffix));
    }
    return row;
  }

  function renderExport() {
    const actions = element('div', 'setc__actions');
    const button = element('button', 'button', 'Export to Clipboard');
    button.type = 'button';
    button.addEventListener('click', exportSet);
    actions.append(button);
    return actions;
  }

  function renderStatus() {
    const line = element('p', 'setc__status', status);
    line.setAttribute('role', 'status');
    line.setAttribute('aria-live', 'polite');
    return line;
  }

  function renderUnavailable(state) {
    if (state.libraryError) {
      return stateBlock({
        variant: 'error',
        title: 'The library could not be read',
        body: state.libraryError,
      });
    }
    return stateBlock({
      title: 'No index yet',
      body: firstRunGuidance('There is no cosine index to build a set from.'),
    });
  }

  function render() {
    const state = store.getState();
    if (state.destination !== 'set-creator') {
      return;
    }

    if (state.libraryError || (state.library && state.library.is_empty)) {
      root.replaceChildren(renderUnavailable(state));
      return;
    }

    const view = element('div', 'setc');
    view.append(
      renderConfiguration(),
      renderAnchors(),
      renderSet(),
      renderExport(),
      renderStatus(),
    );
    root.replaceChildren(view);
  }

  // `render` returns early for any other destination, so this is the whole of
  // "show me when I am the one showing".
  store.subscribe(render);
  render();

  return {
    render,
    // For the behavioural suite: the working state, read-only.
    state: () => ({
      anchors: { ...anchors },
      totalTracks,
      generatedSet: [...generatedSet],
      status,
      selectedAnchor,
      // The configuration the in-flight generation was started from, or null.
      building,
    }),
  };
}
