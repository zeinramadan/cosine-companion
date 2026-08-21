/* `TrackSelectorDialog` - inventory §2.11 (lines 913-941).
 *
 * What is reimplemented, with the line it comes from:
 *
 *   :915  modal Toplevel, title `Select Tracks for Playlist Export`
 *   :918  `Search for tracks:` + entry, FOCUSED on open, live filter
 *   :920  the Ctrl+Click / Shift+Click hint
 *   :921  `Search Results:` label
 *   :922  a multiple-selection results list
 *   :923  the selection-count label and its three texts
 *   :927  `Select All` / `Clear Selection`
 *   :928  `Add Selected Tracks` and `Cancel`, Cancel rightmost
 *   :931  limit=100 for an empty query, limit=50 otherwise
 *   :934  rows already in the export selection are prefixed `✓ `
 *   :936  nothing selected -> No Selection / Please select at least one track.
 *   :938  the ids are UNIONED into the caller's set, never replacing it
 *   :939  Cancel and the close button discard the selection
 *
 * DIVERGENCE (§6.9): the blank query. :932 records that the dialog opens with
 * an EMPTY list, because search implementation A returns `[]` for a blank query
 * (§4 defect #9) - so the `# Initialize with all tracks` intent at
 * `ui/track_selector_dialog.py:129` never happens, and clearing the box empties
 * it again. This browses instead, through the same `/api/tracks` endpoint the
 * ⌘K palette and the Add Anchor dialog already use, and it asks for :931's 100
 * rather than the palette's 50 because that is the limit catalogued for the
 * empty query here. The service is untouched and defect #9's characterisation
 * still holds against it.
 *
 * DIVERGENCE (§6.9): the initial colour of the count label. :923 records that
 * the label opens reading `0 tracks selected` in BLUE and only turns grey once
 * a selection event has fired - the emphatic colour on the emptiest state.
 * Here zero is quiet from the start and any non-zero count is accented, so the
 * colour tracks the number rather than the event history.
 *
 * ADDITION (§6.9): Enter or Space on a focused row toggles it, so the list can
 * be multi-selected without a pointer. §2.11 catalogues no keyboard binding for
 * the list at all, and `role="option"` is a promise a bare `<li>` cannot keep -
 * the reason `listbox.js` exists.
 */

import { api } from '../api.js';
import { displayName, element } from '../format.js';
import { wireListbox } from '../listbox.js';
import { openModal } from '../modal.js';
import { showwarning } from './message-box.js';

/* The palette's number, for the palette's reason: a request per keystroke over
 * loopback is still a request per keystroke. The sequence is bumped by the
 * KEYSTROKE rather than by the request it eventually causes, so a response for
 * a query the user has moved past cannot repaint the list. */
const DEBOUNCE_MS = 120;

/* Inventory :931 - `limit = 100 if not query else 50`. */
export const BROWSE_LIMIT = 100;
export const SEARCH_LIMIT = 50;

/* Inventory :934. Tick plus one space, prefixed to the whole row. */
export const ALREADY_SELECTED_PREFIX = '✓ ';

/** Inventory :923 - the three texts, exactly. */
export function selectionCountText(count) {
  if (count === 0) {
    return '0 tracks selected';
  }
  if (count === 1) {
    return '1 track selected';
  }
  return `${count} tracks selected`;
}

/**
 * Open the dialog and resolve with the chosen track ids, or `null` if cancelled.
 *
 * `alreadySelected` is the live selection - a `Set` of track ids - read at
 * render time so the `✓` prefixes are right, and never written to: :938 says
 * the caller does the union, and the caller is the one that owns the set.
 */
export function openTrackSelectorDialog({ alreadySelected }) {
  let results = [];
  /* Indices into `results`, not track ids: the Tk listbox's selection is by
   * row, `Select All` means "every row on screen", and rebuilding the list
   * clears it (`delete(0, END)`, track_selector_dialog.py:143). */
  let selected = new Set();
  let anchor = null;
  let sequence = 0;
  let debounce = null;

  let list;
  let searchField;
  let countLabel;

  function invalidate() {
    sequence += 1;
    return sequence;
  }

  function renderMessage(text) {
    list.replaceChildren(element('li', 'picker__empty', text));
  }

  function renderCount() {
    const count = selected.size;
    countLabel.textContent = selectionCountText(count);
    // Not a colour set from JavaScript - the stylesheet owns the palette. The
    // attribute says which of the two states this is.
    countLabel.dataset.state = count === 0 ? 'empty' : 'chosen';
  }

  function syncSelection() {
    [...list.children].forEach((option, index) => {
      option.setAttribute('aria-selected', String(selected.has(index)));
    });
    renderCount();
  }

  /* The Library destination's modifier rules (§2.7), because this list has the
   * same `selectmode=EXTENDED` and :920 advertises exactly these two. */
  function choose(index, event = {}) {
    if (event.shiftKey && anchor !== null) {
      const beginning = Math.min(anchor, index);
      const end = Math.max(anchor, index);
      selected = new Set();
      for (let at = beginning; at <= end; at += 1) {
        selected.add(at);
      }
    } else if (event.metaKey || event.ctrlKey) {
      if (selected.has(index)) {
        selected.delete(index);
      } else {
        selected.add(index);
      }
      anchor = index;
    } else {
      selected = new Set([index]);
      anchor = index;
    }
    syncSelection();
  }

  function toggle(index) {
    if (selected.has(index)) {
      selected.delete(index);
    } else {
      selected.add(index);
    }
    anchor = index;
    syncSelection();
  }

  function renderResults() {
    if (!results.length) {
      renderMessage(
        searchField.value.trim()
          ? `No track matches “${searchField.value.trim()}”.`
          : 'This library has no tracks yet.',
      );
      renderCount();
      return;
    }

    const options = results.map((track, index) => {
      // :934 - the tick is part of the row text, as it is in Tk, where the
      // prefix is concatenated onto `display_name` before the insert.
      const name = displayName(track);
      const already = alreadySelected.has(track.track_id);
      const option = element(
        'li',
        'picker__option',
        already ? `${ALREADY_SELECTED_PREFIX}${name}` : name,
      );
      option.setAttribute('role', 'option');
      option.setAttribute('aria-selected', 'false');
      if (already) {
        option.dataset.already = 'true';
      }
      option.addEventListener('click', (event) => choose(index, event));
      return option;
    });

    list.replaceChildren(...options);
    wireListbox(options, {
      selected: null,
      // Arrowing moves the focus without disturbing a multi-selection; Enter
      // and Space are what add and remove.
      onSelect: () => {},
      onActivate: (index) => toggle(index),
    });
    syncSelection();
  }

  async function load(query, mine) {
    const trimmed = query.trim();
    try {
      const body = trimmed
        ? await api.search(trimmed, SEARCH_LIMIT)
        : await api.tracks(BROWSE_LIMIT);
      if (mine !== sequence) {
        return;
      }
      results = trimmed ? body.results : body.tracks;
      // Rebuilding the list drops the selection, as `delete(0, END)` does
      // (track_selector_dialog.py:143). Without this a stale index points at a
      // different track than the one that was highlighted.
      selected = new Set();
      anchor = null;
      renderResults();
    } catch (error) {
      if (mine !== sequence) {
        return;
      }
      results = [];
      selected = new Set();
      anchor = null;
      renderMessage(error.message);
      renderCount();
    }
  }

  function scheduleLoad(query) {
    window.clearTimeout(debounce);
    const mine = invalidate();
    debounce = window.setTimeout(() => load(query, mine), DEBOUNCE_MS);
  }

  let finish = () => {};

  /* :936-938. */
  async function addSelected() {
    if (!selected.size) {
      await showwarning('No Selection', 'Please select at least one track.');
      return;
    }
    // In row order, so the caller's set grows in the order the list showed.
    const chosen = [...selected]
      .sort((left, right) => left - right)
      .map((index) => results[index].track_id);
    finish(chosen);
  }

  const dialog = openModal({
    label: 'Select Tracks for Playlist Export',
    className: 'track-selector',
    dismissValue: null,
    build: (close) => {
      finish = close;

      const body = element('div', 'track-selector__body');
      body.append(
        element('h2', 'track-selector__title', 'Select Tracks for Playlist Export'),
      );

      const searchRow = element('div', 'field');
      const searchLabel = element('label', 'field__label', 'Search for tracks:');
      searchLabel.setAttribute('for', 'track-selector-search');
      searchField = element('input', 'field__input');
      searchField.id = 'track-selector-search';
      searchField.type = 'text';
      searchField.setAttribute('autocomplete', 'off');
      searchField.setAttribute('spellcheck', 'false');
      searchField.setAttribute('placeholder', 'Search artist or title…');
      searchField.addEventListener('input', () => scheduleLoad(searchField.value));
      searchRow.append(searchLabel, searchField);

      // :920, verbatim. ⌘-Click does the same thing as Ctrl+Click here, which
      // is what a macOS user will reach for; the catalogued string is left as
      // it is rather than reworded.
      const hint = element(
        'p',
        'track-selector__hint',
        '💡 Ctrl+Click to select multiple • Shift+Click to select range',
      );

      const resultsRow = element('div', 'field');
      resultsRow.append(element('p', 'field__label', 'Search Results:'));
      list = element('ul', 'picker picker--tall');
      list.setAttribute('role', 'listbox');
      list.setAttribute('aria-label', 'Search results');
      list.setAttribute('aria-multiselectable', 'true');
      resultsRow.append(list);

      countLabel = element('p', 'track-selector__count');
      countLabel.setAttribute('role', 'status');
      countLabel.setAttribute('aria-live', 'polite');

      const quick = element('div', 'track-selector__quick');
      const selectAll = element('button', 'button button--quiet', 'Select All');
      selectAll.type = 'button';
      selectAll.addEventListener('click', () => {
        selected = new Set(results.map((_, index) => index));
        anchor = results.length ? results.length - 1 : null;
        syncSelection();
      });
      const clearSelection = element('button', 'button button--quiet', 'Clear Selection');
      clearSelection.type = 'button';
      clearSelection.addEventListener('click', () => {
        selected = new Set();
        anchor = null;
        syncSelection();
      });
      quick.append(selectAll, clearSelection);

      const actions = element('div', 'track-selector__actions');
      const add = element('button', 'button button--primary', 'Add Selected Tracks');
      add.type = 'button';
      add.addEventListener('click', addSelected);
      const cancel = element('button', 'button', 'Cancel');
      cancel.type = 'button';
      cancel.addEventListener('click', () => close(null));
      // :928 - Cancel sits rightmost. `row-reverse` puts the first child on the
      // right, so Cancel is appended first.
      actions.append(cancel, add);

      body.append(searchRow, hint, resultsRow, countLabel, quick, actions);
      return body;
    },
    // :918 - the entry takes focus on open.
    initialFocus: () => searchField,
  });

  renderMessage('Loading…');
  renderCount();
  load('', invalidate());

  return dialog.answer;
}
