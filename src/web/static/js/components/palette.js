/* The persistent ⌘K track search.
 *
 * Two behaviours worth naming:
 *
 * With an EMPTY query it lists the first fifty tracks rather than nothing. The
 * Tkinter selector dialogs open with an empty list and only fill in once you
 * type, which contradicts their own `# Initialize with all tracks` comment -
 * inventory defect #9. That defect is characterised against the *service*, and
 * the service is untouched; this is a different surface answering the same
 * question better, through /api/tracks rather than through search_tracks.
 *
 * Responses are sequenced, and the sequence is bumped by the KEYSTROKE rather
 * than by the request it eventually causes. Bumping it inside `load` looks
 * equivalent and is not, because `load` runs 120 ms late:
 *
 *   t=0    type "a"       debounce timer set for t=120
 *   t=120  load("a")      mine = 1, sequence = 1, request goes out
 *   t=150  type "b"       timer reset for t=270 - but sequence is still 1
 *   t=200  "a" responds   mine === sequence, so it RENDERS results for "a"
 *                         while the input reads "ab" and Enter is one
 *                         keypress away from choosing the wrong track.
 *
 * Every keystroke is the moment the previous query stops being current, so
 * that is where the invalidation belongs. Pinned by
 * tests/web/js/palette_sequencing.test.mjs.
 */

import { api } from '../api.js';
import { displayName, element } from '../format.js';

const DEBOUNCE_MS = 120;
const RESULT_LIMIT = 50;

export function mountPalette({ onSelect }) {
  const root = document.getElementById('palette');
  const panel = root.querySelector('.palette__panel');
  const input = document.getElementById('palette-input');
  const list = document.getElementById('palette-results');
  const trigger = document.getElementById('search-trigger');
  /* The application shell. The palette is a SIBLING of it in index.html, which
   * is what lets the whole shell be taken out of reach while the panel is
   * open. */
  const shell = document.getElementById('app');

  let results = [];
  let cursor = 0;
  let sequence = 0;
  let debounce = null;
  let restoreFocusTo = null;

  // -- data ---------------------------------------------------------------

  /** Invalidate every response still in flight. Returns the new ticket. */
  function invalidate() {
    sequence += 1;
    return sequence;
  }

  async function load(query, mine) {
    const trimmed = query.trim();

    try {
      const body = trimmed
        ? await api.search(trimmed, RESULT_LIMIT)
        : await api.tracks(RESULT_LIMIT);

      // A stale response for a query the user has already moved past.
      if (mine !== sequence) {
        return;
      }
      results = trimmed ? body.results : body.tracks;
      cursor = 0;
      renderResults();
    } catch (error) {
      if (mine !== sequence) {
        return;
      }
      results = [];
      renderMessage(error.message);
    }
  }

  function scheduleLoad(query) {
    window.clearTimeout(debounce);
    // Here, not inside load(): the keystroke is what makes the previous query
    // stale, and it happens DEBOUNCE_MS before the next request exists.
    const mine = invalidate();
    debounce = window.setTimeout(() => load(query, mine), DEBOUNCE_MS);
  }

  // -- rendering ----------------------------------------------------------

  function renderMessage(text) {
    list.replaceChildren(element('li', 'palette__empty', text));
    input.removeAttribute('aria-activedescendant');
  }

  function renderResults() {
    if (!results.length) {
      renderMessage(
        input.value.trim()
          ? `No track matches “${input.value.trim()}”.`
          : 'This library has no tracks yet.',
      );
      return;
    }

    const options = results.map((track, index) => {
      const option = element('li');
      option.id = `palette-option-${index}`;
      option.className = 'palette__option';
      option.setAttribute('role', 'option');
      option.setAttribute('aria-selected', String(index === cursor));

      const text = element('div', 'palette__text');
      text.append(
        element('div', 'palette__title', track.title || displayName(track)),
        element('div', 'palette__artist', track.artist || ''),
      );
      option.append(text);

      option.addEventListener('click', (event) => {
        cursor = index;
        choose(event.shiftKey);
      });
      option.addEventListener('mousemove', () => {
        if (cursor !== index) {
          cursor = index;
          syncSelection();
        }
      });

      return option;
    });

    list.replaceChildren(...options);
    syncSelection();
  }

  function syncSelection() {
    const options = [...list.children];
    options.forEach((option, index) => {
      option.setAttribute('aria-selected', String(index === cursor));
    });
    const active = options[cursor];
    if (active) {
      input.setAttribute('aria-activedescendant', active.id);
      active.scrollIntoView({ block: 'nearest' });
    }
  }

  // -- interaction --------------------------------------------------------

  function move(delta) {
    if (!results.length) {
      return;
    }
    cursor = (cursor + delta + results.length) % results.length;
    syncSelection();
  }

  function choose(wantsDetails) {
    const track = results[cursor];
    if (!track) {
      return;
    }
    close();
    onSelect(track, { details: Boolean(wantsDetails) });
  }

  function open() {
    if (!root.hidden) {
      return;
    }
    restoreFocusTo = document.activeElement;
    root.hidden = false;
    // The panel declares role="dialog" aria-modal="true" (index.html:100),
    // which tells assistive technology that everything behind it is
    // unreachable. These two lines are what make that claim true rather than
    // decorative: `inert` removes the shell from the tab order AND from the
    // accessibility tree, and aria-hidden covers the browsers that do not
    // implement inert yet. The Tab case in the keydown handler below is the
    // belt to this pair of braces.
    if (shell) {
      shell.setAttribute('inert', '');
      shell.setAttribute('aria-hidden', 'true');
    }
    input.value = '';
    results = [];
    renderMessage('Loading…');
    input.focus();
    load('', invalidate());
  }

  function close() {
    if (root.hidden) {
      return;
    }
    root.hidden = true;
    window.clearTimeout(debounce);
    // Invalidate anything in flight so it cannot repaint a closed palette.
    invalidate();
    // BEFORE restoring focus, not after: focus() into an inert subtree is
    // ignored, and the control that opened the palette lives inside the shell.
    if (shell) {
      shell.removeAttribute('inert');
      shell.removeAttribute('aria-hidden');
    }
    if (restoreFocusTo && typeof restoreFocusTo.focus === 'function') {
      restoreFocusTo.focus();
    }
  }

  input.addEventListener('input', () => scheduleLoad(input.value));

  input.addEventListener('keydown', (event) => {
    switch (event.key) {
      case 'ArrowDown':
        event.preventDefault();
        move(1);
        break;
      case 'ArrowUp':
        event.preventDefault();
        move(-1);
        break;
      case 'Home':
        event.preventDefault();
        cursor = 0;
        syncSelection();
        break;
      case 'End':
        event.preventDefault();
        cursor = Math.max(0, results.length - 1);
        syncSelection();
        break;
      case 'Enter':
        event.preventDefault();
        choose(event.shiftKey);
        break;
      case 'Escape':
        event.preventDefault();
        close();
        break;
      case 'Tab':
        // The trap. The panel holds exactly ONE focusable element - this input
        // - because the results are a listbox driven by aria-activedescendant
        // rather than by focus. So trapping Tab means sending it nowhere,
        // forwards or backwards, and the focus() is what recovers if anything
        // else has taken it in the meantime.
        event.preventDefault();
        input.focus();
        break;
      default:
        break;
    }
  });

  // Clicking the backdrop closes; clicking inside the panel must not.
  root.addEventListener('mousedown', (event) => {
    if (!panel.contains(event.target)) {
      close();
    }
  });

  trigger.addEventListener('click', open);

  window.addEventListener('keydown', (event) => {
    if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === 'k') {
      event.preventDefault();
      if (root.hidden) {
        open();
      } else {
        close();
      }
      return;
    }
    if (event.key === 'Escape' && !root.hidden) {
      event.preventDefault();
      close();
    }
  });

  return { open, close };
}
