/* Rendering helpers shared by the palette, the drawer and the Explore list.
 *
 * The two that matter are the Camelot pill and the score bar, and both exist
 * because a bare number is a poor answer to a question a DJ asks by eye.
 */

/* U+2013. Everything user-facing in a list uses it (inventory §3.1), and the
 * API builds its display names the same way. */
export const EN_DASH = '–';

const CAMELOT = /^(\d{1,2})([AB])$/i;

/**
 * Split a Camelot key into what the pill needs to draw itself.
 *
 * hue = (n - 1) * 30 walks the twelve wheel positions around the colour
 * circle, so harmonic neighbours (n ± 1) are adjacent in hue as well as in
 * number. Anything unparseable renders as a neutral pill reading "?" rather
 * than being dropped: a missing key is information.
 */
export function camelot(key) {
  const match = typeof key === 'string' ? key.trim().match(CAMELOT) : null;
  if (!match) {
    return { text: key ? String(key) : '?', hue: null, mode: null, unknown: true };
  }

  const position = Number(match[1]);
  if (!Number.isInteger(position) || position < 1 || position > 12) {
    return { text: String(key), hue: null, mode: null, unknown: true };
  }

  const letter = match[2].toUpperCase();
  return {
    text: `${position}${letter}`,
    hue: (position - 1) * 30,
    mode: letter === 'B' ? 'major' : 'minor',
    unknown: false,
  };
}

/** A Camelot pill. Always carries its own text, so hue is never the only signal. */
export function pill(key) {
  const parsed = camelot(key);
  const element = document.createElement('span');
  element.className = 'pill';
  element.textContent = parsed.text;

  if (parsed.unknown) {
    element.dataset.unknown = 'true';
    element.title = 'No key recorded for this track';
  } else {
    element.style.setProperty('--camelot-hue', `${parsed.hue}deg`);
    element.dataset.mode = parsed.mode;
    element.title = `Camelot ${parsed.text} (${parsed.mode})`;
  }

  return element;
}

/**
 * A proportional bar plus the number it represents.
 *
 * Both, not either: the bar carries the comparison down a list and the number
 * carries the value. The bar is aria-hidden because the figure beside it is
 * already the accessible answer.
 */
export function scoreBar(fraction, label) {
  const clamped = Math.max(0, Math.min(1, Number(fraction) || 0));

  const wrapper = document.createElement('div');
  wrapper.className = 'score';

  const track = document.createElement('div');
  track.className = 'score__track';
  track.setAttribute('aria-hidden', 'true');

  const fill = document.createElement('div');
  fill.className = 'score__fill';
  fill.style.width = `${(clamped * 100).toFixed(1)}%`;
  track.append(fill);

  const value = document.createElement('span');
  value.className = 'score__value';
  value.textContent = label !== undefined ? label : percent(fraction);

  wrapper.append(track, value);
  return wrapper;
}

/** `0.7241` -> `72.4%`. Unclamped, deliberately: see percentClamped. */
export function percent(value) {
  const number = Number(value);
  if (!Number.isFinite(number)) {
    return '—';
  }
  return `${(number * 100).toFixed(1)}%`;
}

/**
 * The Explore tab clamps its Score to 0-100 % and does NOT clamp its Cos
 * (inventory §2.4, "Rendered row format"). That asymmetry is preserved: a
 * cosine outside [0, 1] means something is wrong with the index and hiding it
 * behind a clamp would make it invisible.
 */
export function percentClamped(value) {
  const number = Number(value);
  if (!Number.isFinite(number)) {
    return '—';
  }
  return `${(Math.max(0, Math.min(1, number)) * 100).toFixed(1)}%`;
}

/** BPM is a float64 column, so it always renders with a decimal (`128.0`). */
export function bpm(value) {
  const number = Number(value);
  if (value === null || value === undefined || !Number.isFinite(number)) {
    return '—';
  }
  return number.toFixed(1);
}

/**
 * One track as a line of text: `{artist} – {title}`, joining only what is
 * there.
 *
 * This is not only a visual helper. It is what the row's Copy button puts on
 * the clipboard and what the Details button announces, and this library really
 * contains tracks with an empty artist - "Skee Mask - Reviver" is one, where
 * the artist field is blank. The unconditional join produced " – Reviver" for
 * those: invisible on screen, because the visual surfaces substitute "Unknown
 * artist" for the empty field themselves, and intact in the clipboard.
 *
 * `display_name` is a LAST resort rather than the first choice, and that is
 * deliberate. `services.recommendations.search.search_tracks` builds it as
 * `{artist} – {title}` unconditionally and `web/api.py::_summary` mirrors that
 * shape on purpose, so the supplied string carries the same dangling
 * separator. Composing from the fields fixes every consumer at once instead of
 * once per surface; the supplied value is still used when a record carries
 * nothing else.
 */
export function displayName(track) {
  const artist = String((track && track.artist) || '').trim();
  const title = String((track && track.title) || '').trim();
  const parts = [artist, title].filter(Boolean);

  if (parts.length) {
    return parts.join(` ${EN_DASH} `);
  }
  const supplied = track && track.display_name;
  return supplied ? String(supplied) : 'Untitled';
}

/** Replace an element's children in one call. */
export function replaceChildren(element, ...children) {
  element.replaceChildren(...children);
  return element;
}

export function element(tag, className, text) {
  const node = document.createElement(tag);
  if (className) {
    node.className = className;
  }
  if (text !== undefined && text !== null) {
    node.textContent = String(text);
  }
  return node;
}

/** A titled empty / error / loading block. */
export function stateBlock({ title, body, variant, action }) {
  const wrapper = element('div', variant ? `state state--${variant}` : 'state');
  if (variant === 'loading') {
    wrapper.append(element('div', 'spinner'));
  }
  if (title) {
    wrapper.append(element('p', 'state__title', title));
  }
  if (body) {
    wrapper.append(element('p', 'state__body', body));
  }
  if (action) {
    wrapper.append(action);
  }
  return wrapper;
}
