/* Keyboard operation for the two lists this destination renders.
 *
 * THE DEFECT THIS EXISTS TO FIX
 * -----------------------------
 * Both lists shipped as `<ul role="listbox">` full of `<li role="option">`
 * with click handlers and nothing else. `role="option"` is a promise that the
 * thing can be chosen; a bare `<li>` is not in the tab order and takes no keys,
 * so the promise was false in the one place it mattered most: the Add Anchor
 * dialog. A keyboard user could reach the position field, the search box,
 * `Add to Set` and `Cancel` - and could never select a track, so the only
 * answer that dialog could give them was "No Selection".
 *
 * The palette does not need this because its options are driven by
 * `aria-activedescendant` from a text input that is itself focusable. These
 * lists have no such input beside them, so they carry the focus themselves.
 *
 * ROVING TABINDEX, not `tabindex="0"` on every row. A set may hold up to
 * MAX_SET_TRACKS anchors and the picker shows fifty results; making each one a
 * tab stop would mean fifty presses of Tab to get past the list. Exactly one
 * option is in the tab order - the selected one, or the first - and the arrow
 * keys move both the focus and the selection from there, which is the
 * single-select listbox pattern browsers and screen readers already expect.
 */

/** Clamp `wanted` into `[0, length)`. */
function within(wanted, length) {
  return Math.min(Math.max(wanted, 0), length - 1);
}

/**
 * Make freshly built `options` operable by keyboard.
 *
 * Call it after the options are in the DOM and every time they are rebuilt -
 * the handlers live on the option nodes, so a rebuilt list cannot be left
 * carrying a handler that closes over a stale index.
 *
 * `onSelect(index)` must NOT rebuild the list. Moving the selection has to
 * leave these nodes in place or the focus this function just moved is
 * destroyed by the re-render; both callers update `aria-selected` in place for
 * that reason. `onActivate` may do anything, including close the dialog.
 */
export function wireListbox(options, { selected, onSelect, onActivate } = {}) {
  if (!options.length) {
    return;
  }

  const resting = within(selected === null || selected === undefined ? 0 : selected, options.length);

  function moveTo(wanted) {
    const next = within(wanted, options.length);
    if (onSelect) {
      onSelect(next);
    }
    options.forEach((option, index) => {
      option.setAttribute('tabindex', index === next ? '0' : '-1');
    });
    const target = options[next];
    if (target && typeof target.focus === 'function') {
      target.focus();
    }
    if (target && typeof target.scrollIntoView === 'function') {
      target.scrollIntoView({ block: 'nearest' });
    }
  }

  options.forEach((option, index) => {
    option.setAttribute('tabindex', index === resting ? '0' : '-1');

    option.addEventListener('keydown', (event) => {
      switch (event.key) {
        case 'ArrowDown':
          event.preventDefault();
          moveTo(index + 1);
          break;
        case 'ArrowUp':
          event.preventDefault();
          moveTo(index - 1);
          break;
        case 'Home':
          event.preventDefault();
          moveTo(0);
          break;
        case 'End':
          event.preventDefault();
          moveTo(options.length - 1);
          break;
        case 'Enter':
        case ' ':
          event.preventDefault();
          if (onActivate) {
            onActivate(index);
          } else if (onSelect) {
            onSelect(index);
          }
          break;
        default:
          break;
      }
    });
  });
}
