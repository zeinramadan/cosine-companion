/* `AddAnchorDialog` - inventory §2.12 (lines 944-967).
 *
 * What is reimplemented, with the line it comes from:
 *
 *   :946  modal Toplevel, title `Add Anchor Track`  -> a modal over the shell
 *   :948  `Position in Set:` + entry, BLANK default -> the position field
 *   :949  `Search for Track:` + entry, live filter  -> the search field
 *   :950  `Search Results:` + single-selection list -> the results listbox
 *   :951  `<Double-Button-1>` = Add to Set          -> double-click a row
 *   :952  `Add to Set` and `Cancel`, Cancel rightmost
 *   :954  search implementation A, limit=50, rows `{artist} – {title}`
 *   :961  no selection    -> No Selection / Please select a track.
 *   :962  not an integer  -> Invalid Position / Please enter a valid position number.
 *   :963  below 1         -> Invalid Position / Position must be 1 or greater.
 *   :964  already used    -> Position Taken / ... Replace it?  (No returns here)
 *   :966  no upper bound on the position, and no check against Total Tracks
 *   :967  the same track may be anchored at several positions
 *
 * TWO THINGS THAT LOOK LIKE DETAILS AND ARE NOT
 * ---------------------------------------------
 * Nothing is selected when the list is (re)built. The Tk listbox has no
 * selection until you click one, which is the only reason :961 is reachable at
 * all; the ⌘K palette auto-selects its first row, and copying that here would
 * have made "No Selection" dead code and the check untestable.
 *
 * The four checks run in the catalogued ORDER, and the order is observable:
 * with nothing selected AND a blank position, Tkinter says "No Selection", not
 * "Invalid Position". Each check therefore has to await the one before it.
 *
 * ADDITION: Enter in either text field does what `Add to Set` does. §2.12
 * catalogues no keyboard binding, so this is an addition rather than a
 * reimplementation of one, and it is recorded as such. A modal with a text
 * field that ignores Enter is a modal people press Enter at twice.
 *
 * DIVERGENCE (§6.3): the blank query. Inventory :955 records that the dialog
 * opens EMPTY because search implementation A returns `[]` for a blank query -
 * §4 defect #9. This lists the first 50 tracks instead, through the same browse
 * endpoint the palette uses, for the same reason the palette does: an empty
 * picker is not a starting point. The service is untouched and the defect's
 * characterisation still holds.
 */

import { api } from '../api.js';
import { displayName, element, parseIntegerStrictly } from '../format.js';
import { openModal } from '../modal.js';
import { askyesno, showerror, showwarning } from './message-box.js';

/* The palette's numbers, and for its reasons: a request per keystroke over
 * loopback is still a request per keystroke, and the sequence is bumped by the
 * KEYSTROKE rather than by the request it eventually causes, so a response for
 * a query the user has moved past cannot repaint the list. */
const DEBOUNCE_MS = 120;

/* Inventory :954 - `search_tracks(query, meta_ix, limit=50)`. */
const RESULT_LIMIT = 50;

/**
 * Open the dialog and resolve with `{position, track}`, or `null` if cancelled.
 *
 * `existingAnchors` is the live `{position: anchor}` map, read at the moment
 * `Add to Set` is pressed rather than captured at open, exactly as the Tk
 * dialog holds a reference to the tab's dict (dialogs.py:46).
 */
export function openAnchorDialog({ existingAnchors }) {
  let results = [];
  let selected = null;
  let sequence = 0;
  let debounce = null;

  let list;
  let positionField;
  let searchField;

  function invalidate() {
    sequence += 1;
    return sequence;
  }

  function renderMessage(text) {
    list.replaceChildren(element('li', 'picker__empty', text));
  }

  function syncSelection() {
    [...list.children].forEach((option, index) => {
      option.setAttribute('aria-selected', String(index === selected));
    });
  }

  function renderResults() {
    if (!results.length) {
      renderMessage(
        searchField.value.trim()
          ? `No track matches “${searchField.value.trim()}”.`
          : 'This library has no tracks yet.',
      );
      return;
    }

    list.replaceChildren(
      ...results.map((track, index) => {
        // Inventory :954 and §3.1 - one line, `{artist} – {title}`.
        const option = element('li', 'picker__option', displayName(track));
        option.setAttribute('role', 'option');
        option.setAttribute('aria-selected', 'false');
        option.addEventListener('click', () => {
          selected = index;
          syncSelection();
        });
        option.addEventListener('dblclick', () => {
          selected = index;
          syncSelection();
          add();
        });
        return option;
      }),
    );
    syncSelection();
  }

  async function load(query, mine) {
    const trimmed = query.trim();
    try {
      const body = trimmed
        ? await api.search(trimmed, RESULT_LIMIT)
        : await api.tracks(RESULT_LIMIT);
      if (mine !== sequence) {
        return;
      }
      results = trimmed ? body.results : body.tracks;
      // Rebuilding the list drops the selection, as `delete(0, END)` does
      // (dialogs.py:86). Without this a stale index could point at a different
      // track than the one that is highlighted.
      selected = null;
      renderResults();
    } catch (error) {
      if (mine !== sequence) {
        return;
      }
      results = [];
      selected = null;
      renderMessage(error.message);
    }
  }

  function scheduleLoad(query) {
    window.clearTimeout(debounce);
    const mine = invalidate();
    debounce = window.setTimeout(() => load(query, mine), DEBOUNCE_MS);
  }

  let finish = () => {};

  /* Inventory :957-964, in order. Each check awaits the one before it, because
   * a message box is a promise and the order is what is catalogued. */
  async function add() {
    if (selected === null || !results[selected]) {
      await showwarning('No Selection', 'Please select a track.');
      return;
    }

    const position = parseIntegerStrictly(positionField.value);
    if (position === null) {
      await showerror('Invalid Position', 'Please enter a valid position number.');
      return;
    }
    if (position < 1) {
      await showerror('Invalid Position', 'Position must be 1 or greater.');
      return;
    }

    // :966 - no upper bound, and nothing here consults `Total Tracks`. An
    // anchor past the end is caught by the builder instead and surfaces as the
    // `Generation Error` dialog (:506-508).
    if (Object.prototype.hasOwnProperty.call(existingAnchors, position)) {
      const replace = await askyesno(
        'Position Taken',
        `Position ${position} already has an anchor track. Replace it?`,
      );
      if (!replace) {
        // :964 - "declining returns to the dialog". Not cancelled: the dialog
        // stays open with the same selection and the same typed position.
        return;
      }
    }

    finish({ position, track: results[selected] });
  }

  /* An ADDITION, not a catalogued binding - see the header. */
  function submitOnEnter(event) {
    if (event.key !== 'Enter') {
      return;
    }
    event.preventDefault();
    add();
  }

  const dialog = openModal({
    label: 'Add Anchor Track',
    className: 'anchor-dialog',
    dismissValue: null,
    build: (close) => {
      finish = close;

      const body = element('div', 'anchor-dialog__body');
      body.append(element('h2', 'anchor-dialog__title', 'Add Anchor Track'));

      const positionRow = element('div', 'field field--inline');
      const positionLabel = element('label', 'field__label', 'Position in Set:');
      positionLabel.setAttribute('for', 'anchor-position');
      positionField = element('input', 'field__input field__input--narrow');
      positionField.id = 'anchor-position';
      positionField.type = 'text';
      positionField.setAttribute('autocomplete', 'off');
      positionField.setAttribute('inputmode', 'numeric');
      // :948 - blank by default. Not pre-filled with the next free slot: the
      // dialog does not know the set's length and :966 says it must not care.
      positionField.value = '';
      positionField.addEventListener('keydown', submitOnEnter);
      positionRow.append(positionLabel, positionField);

      const searchRow = element('div', 'field');
      const searchLabel = element('label', 'field__label', 'Search for Track:');
      searchLabel.setAttribute('for', 'anchor-search');
      searchField = element('input', 'field__input');
      searchField.id = 'anchor-search';
      searchField.type = 'text';
      searchField.setAttribute('autocomplete', 'off');
      searchField.setAttribute('spellcheck', 'false');
      searchField.setAttribute('placeholder', 'Search artist or title…');
      searchField.addEventListener('input', () => scheduleLoad(searchField.value));
      searchField.addEventListener('keydown', submitOnEnter);
      searchRow.append(searchLabel, searchField);

      const resultsRow = element('div', 'field');
      resultsRow.append(element('p', 'field__label', 'Search Results:'));
      list = element('ul', 'picker');
      list.setAttribute('role', 'listbox');
      list.setAttribute('aria-label', 'Search results');
      resultsRow.append(list);

      const actions = element('div', 'anchor-dialog__actions');
      const addButton = element('button', 'button button--primary', 'Add to Set');
      addButton.type = 'button';
      addButton.addEventListener('click', add);
      const cancel = element('button', 'button', 'Cancel');
      cancel.type = 'button';
      cancel.addEventListener('click', () => close(null));
      // :952 - Cancel sits rightmost. `row-reverse` in the stylesheet puts the
      // first child on the right, so Cancel is appended first.
      actions.append(cancel, addButton);

      body.append(positionRow, searchRow, resultsRow, actions);
      return body;
    },
    initialFocus: () => searchField,
  });

  renderMessage('Loading…');
  load('', invalidate());

  return dialog.answer;
}
