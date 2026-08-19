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
 * Responses are sequenced. Typing fast means several searches in flight, and
 * without a sequence number a slow early one can land after a fast later one
 * and repaint the list with results for a query the user has moved past.
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

  let results = [];
  let cursor = 0;
  let sequence = 0;
  let debounce = null;
  let restoreFocusTo = null;

  // -- data ---------------------------------------------------------------

  async function load(query) {
    const mine = ++sequence;
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
    debounce = window.setTimeout(() => load(query), DEBOUNCE_MS);
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
    input.value = '';
    results = [];
    renderMessage('Loading…');
    input.focus();
    load('');
  }

  function close() {
    if (root.hidden) {
      return;
    }
    root.hidden = true;
    window.clearTimeout(debounce);
    // Invalidate anything in flight so it cannot repaint a closed palette.
    sequence += 1;
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
