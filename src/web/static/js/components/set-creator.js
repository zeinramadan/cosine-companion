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
import { openAnchorDialog } from './anchor-dialog.js';
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
  let generating = false;

  // -- actions ------------------------------------------------------------

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

    generating = true;
    status = STATUS_GENERATING;
    render();

    const request = {};
    for (const [position, anchor] of Object.entries(anchors)) {
      request[position] = anchor.track_id;
    }

    try {
      const body = await api.generateSet(request, total);
      generatedSet = body.tracks;
      status = statusGenerated(generatedSet.length);
    } catch (error) {
      // :507-508 - "Failed to generate set: {error}". The message is the
      // service's own, carried over the wire by `set_generation_failed`.
      generatedSet = [];
      status = STATUS_FAILED;
      generating = false;
      render();
      await showerror('Generation Error', `Failed to generate set: ${messageFor(error)}`);
      return;
    }

    generating = false;
    render();
  }

  function messageFor(error) {
    return error instanceof ApiError ? error.message : String(error);
  }

  /* Inventory :518-519. No confirmation, and the status says so. */
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
    generateButton.disabled = generating;
    generateButton.addEventListener('click', generate);

    const clearButton = element('button', 'button', 'Clear Set');
    clearButton.type = 'button';
    clearButton.addEventListener('click', clearSet);

    row.append(label, field, generateButton, clearButton);
    return row;
  }

  function renderAnchors() {
    const section = element('section', 'setc__section');

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
    for (const position of positions) {
      const anchor = anchors[position];
      // Inventory :471 - `{position}. {artist} – {title}`.
      const row = element('li', 'anchors__row');
      row.setAttribute('role', 'option');
      row.setAttribute('aria-selected', String(selectedAnchor === position));
      row.append(
        element('span', 'anchors__position', `${position}.`),
        element('span', 'anchors__name', anchorName(anchor)),
      );
      row.addEventListener('click', () => {
        selectedAnchor = selectedAnchor === position ? null : position;
        render();
      });
      list.append(row);
    }
    section.append(list);
    return section;
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
          generating
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
      body:
        'There is no cosine index to build a set from. Index a Rekordbox ' +
        'collection first — Settings ▸ Update Library in the Tkinter app does this today.',
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
    }),
  };
}
