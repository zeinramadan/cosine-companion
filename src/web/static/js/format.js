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
  /* A custom property the sheet consumes, not an inline width. The
     stylesheet is the only place this application's geometry is
     written - see test_no_script_puts_css_on_the_page_outside_the_stylesheet. */
  fill.style.setProperty('--score', `${(clamped * 100).toFixed(1)}%`);
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

/**
 * Python's `f"{value:.0%}"`, which is what inventory :487 specifies for the
 * generated-set row's ` ({score:.0%} match)` suffix.
 *
 * NOT `Math.round(value * 100)` and not `.toFixed(0)`. Both round a tie AWAY
 * from zero; Python's float formatting rounds a tie to EVEN. Across 21,215
 * values - 20,000 random plus every thousandth and every two-hundredth of the
 * unit interval - the two disagree on 96 of them, all of the `x.5` form:
 * `0.045` is `4%` in Python and `5%` under both JS roundings. Cosine-derived
 * transition scores land on an exact tie about never, so this is not a bug
 * anyone would have hit; it is one line either way, and the one that matches
 * is not the obvious one. Pinned with those cases by
 * tests/web/js/set_creator.test.mjs.
 *
 * The multiplication is IEEE 754 double arithmetic in both languages, so `x *
 * 100` is bit-identical before either rounds; only the tie rule differs.
 */
export function wholePercent(value) {
  const scaled = Number(value) * 100;
  if (!Number.isFinite(scaled)) {
    return null;
  }
  const below = Math.floor(scaled);
  const remainder = scaled - below;
  if (remainder > 0.5) {
    return below + 1;
  }
  if (remainder < 0.5) {
    return below;
  }
  return below % 2 === 0 ? below : below + 1;
}

/* The characters Python's `int()` strips from the ends of its argument.
 *
 * NOT `String.prototype.trim()`, which differs from it in both directions: it
 * leaves U+0085 NEXT LINE in place, and it strips U+FEFF, which Python does
 * not. Enumerated by running `int()` over every code point rather than written
 * from memory - `tests/web/test_integer_parsing_matches_python.py` re-derives
 * this whole function's answers from CPython, and those two are the characters
 * only such a check would ever find. */
const PYTHON_SPACE =
  '\\t\\n\\v\\f\\r \\u0085\\u00a0\\u1680\\u2000-\\u200a\\u2028\\u2029\\u202f\\u205f\\u3000';
const SURROUNDING_SPACE = new RegExp(`^[${PYTHON_SPACE}]+|[${PYTHON_SPACE}]+$`, 'g');

/* Every code point THE INTERPRETER THIS APP SHIPS ON calls a decimal digit, as
 * inclusive `[first, last]` runs of consecutive code points.
 *
 * NOT `\p{Nd}`, which is what this used to be. `\p{Nd}` resolves against the
 * Unicode tables of WHICHEVER JavaScript runtime evaluates it, and those are
 * not the tables CPython was built with - node 20 / ICU 78 is Unicode 17.0 and
 * knows 770 decimal digits, against this table's 660. Those 110 extra - Kawi,
 * Nag Mundari, Kirat Rai and nine other blocks - are digits to the browser and
 * `ValueError` to `int()`.
 *
 * NOR THE INTERPRETER THAT RUNS THE TESTS, which is the second thing this was.
 * The first version of this table was generated from CPython 3.10 (unicodedata
 * 13.0, 650 digits) because that is what `.github/workflows/test-macos.yml`
 * sets up. Every `build-*` workflow freezes 3.11, whose unicodedata is 14.0 and
 * which reads ten more code points as digits (Tangsa, U+16AC0..U+16AC9). So the
 * table was correct against an interpreter no user has, and wrong by ten code
 * points against the one in the bundle - it refused a Tangsa ten that the very
 * `int()` shipped beside it returns 10 for. Measured, not recalled:
 *
 *   CPython 3.10.18  unicodedata 13.0.0  650 Nd
 *   CPython 3.11.14  unicodedata 14.0.0  660 Nd   <- what `build-*.yml` freezes
 *   node 20.20 / ICU 78  Unicode 17.0    770 Nd
 *
 * WHAT THE DIVERGENCE COSTS, stated accurately, because it was overstated
 * before. The typed string never reaches Python in this destination: the
 * frontend parses it and `api.js` sends `total_tracks` as a NUMBER, which
 * `api.py:_set_total_tracks` requires to be an `int` already. Nothing here
 * raises ValueError and no request 400s. What breaks is the CONTRACT - the same
 * characters typed into the Tkinter tab, which really does read them with a
 * bare `int()` (`ui/set_creator_tab.py:96`, `ui/dialogs.py:107`), get a
 * different answer from the two destinations. Inventory §2.12 is the acceptance
 * contract for reproducing that tab, so a disagreement with it is the defect,
 * whichever way it points.
 *
 * The table is therefore generated from the SHIPPED interpreter, and
 * `tests/web/test_integer_parsing_matches_python.py` pins both halves: that the
 * table matches this interpreter EXACTLY - membership and value, both
 * directions, no allowance for the ten - and that it is DECLARED for the
 * interpreter every `build-*` workflow freezes. Run that suite on an
 * interpreter older than the declaration and it FAILS rather than narrow what
 * it claims: an allowance for the difference lived there for two rounds and let
 * a wrong table through a green suite each time, once by excusing the ten's
 * absence and once by pinning which ten they are and never their values.
 *
 * 62 runs, 660 code points, `unicodedata.unidata_version` 14.0.0, generated on
 * CPython 3.11.14. Regenerate on whatever `build-*.yml` freezes, and move the
 * declaration below with it - the test reads that export, not this comment. */
export const PYTHON_UNICODE_VERSION = '14.0.0';

const PYTHON_DECIMAL_RUNS = [
  [0x0030, 0x0039], [0x0660, 0x0669], [0x06f0, 0x06f9], [0x07c0, 0x07c9],
  [0x0966, 0x096f], [0x09e6, 0x09ef], [0x0a66, 0x0a6f], [0x0ae6, 0x0aef],
  [0x0b66, 0x0b6f], [0x0be6, 0x0bef], [0x0c66, 0x0c6f], [0x0ce6, 0x0cef],
  [0x0d66, 0x0d6f], [0x0de6, 0x0def], [0x0e50, 0x0e59], [0x0ed0, 0x0ed9],
  [0x0f20, 0x0f29], [0x1040, 0x1049], [0x1090, 0x1099], [0x17e0, 0x17e9],
  [0x1810, 0x1819], [0x1946, 0x194f], [0x19d0, 0x19d9], [0x1a80, 0x1a89],
  [0x1a90, 0x1a99], [0x1b50, 0x1b59], [0x1bb0, 0x1bb9], [0x1c40, 0x1c49],
  [0x1c50, 0x1c59], [0xa620, 0xa629], [0xa8d0, 0xa8d9], [0xa900, 0xa909],
  [0xa9d0, 0xa9d9], [0xa9f0, 0xa9f9], [0xaa50, 0xaa59], [0xabf0, 0xabf9],
  [0xff10, 0xff19], [0x104a0, 0x104a9], [0x10d30, 0x10d39], [0x11066, 0x1106f],
  [0x110f0, 0x110f9], [0x11136, 0x1113f], [0x111d0, 0x111d9], [0x112f0, 0x112f9],
  [0x11450, 0x11459], [0x114d0, 0x114d9], [0x11650, 0x11659], [0x116c0, 0x116c9],
  [0x11730, 0x11739], [0x118e0, 0x118e9], [0x11950, 0x11959], [0x11c50, 0x11c59],
  [0x11d50, 0x11d59], [0x11da0, 0x11da9], [0x16a60, 0x16a69], [0x16ac0, 0x16ac9],
  [0x16b50, 0x16b59], [0x1d7ce, 0x1d7ff], [0x1e140, 0x1e149], [0x1e2f0, 0x1e2f9],
  [0x1e950, 0x1e959], [0x1fbf0, 0x1fbf9],
];

/* The same table as a character class, built from it rather than written
 * beside it: two spellings of one set is how they drift apart. */
const PYTHON_DIGIT = `[${PYTHON_DECIMAL_RUNS.map(
  ([first, last]) => `\\u{${first.toString(16)}}-\\u{${last.toString(16)}}`,
).join('')}]`;

/* Python's decimal-literal grammar: an optional sign, then digits carrying
 * single underscores BETWEEN them - never leading, never trailing, never
 * doubled. */
const PYTHON_INTEGER = new RegExp(
  `^([+-]?)(${PYTHON_DIGIT}(?:_?${PYTHON_DIGIT})*)$`,
  'u',
);

/** The value of one Unicode decimal digit, an Arabic-Indic seven as readily as `7`. */
function decimalValue(character) {
  const code = character.codePointAt(0);
  // Decimal digits are laid out in blocks of ten whose first member is the
  // zero, and consecutive blocks can be adjacent - U+1D7CE..U+1D7FF is five of
  // them with no gap, which is why one run can be fifty long - so the offset is
  // taken from the start of the run and reduced modulo ten.
  //
  // The run is found in THIS table, not by walking back over `\p{Nd}`, which is
  // what this did before. That walk asked the runtime where the block began,
  // and a runtime that knows a digit block CPython does not could have walked
  // out of one run into another and returned the wrong VALUE for a perfectly
  // ordinary digit. It does not happen on node 20 - no node-only run abuts a
  // CPython run start, checked - but it was luck, not design.
  for (const [first, last] of PYTHON_DECIMAL_RUNS) {
    if (code >= first && code <= last) {
      return (code - first) % 10;
    }
  }
  // Unreachable: PYTHON_INTEGER matched, so every character came from the table.
  return Number.NaN;
}

/**
 * `int(text)` as Python performs it, or `null` when it would raise ValueError.
 *
 * Both `Total Tracks` (inventory :501) and `Position in Set` (:962) are read
 * with a bare `int()` whose ValueError is the branch that raises the dialog, so
 * what counts as "not an integer" is Python's answer and not JavaScript's.
 * `Number()` accepts `"3.0"`, `""` and `"0x10"`; `parseInt` accepts `"3 apples"`
 * and `"3.9"`. Python accepts none of those, and it DOES accept surrounding
 * whitespace and a leading sign.
 *
 * THE CONTRACT IS PYTHON'S, INCLUDING THE PARTS THAT LOOK LIKE QUIRKS.
 * An earlier version of this function said exactly that and then implemented
 * `/^[+-]?\d+$/`, which is JavaScript's answer wearing Python's description: it
 * refused `"1_0"`, which `int()` reads as 10, and it refused every non-ASCII
 * decimal digit. The second one is not hypothetical here. `int()` reads an
 * Arabic-Indic ten as 10, an Arabic keyboard layout on macOS is what produces
 * those digits when you type a ten, and this library's owner has one - so the
 * narrow version answered "Please enter a valid number for total tracks." to a
 * length the Tkinter tab would have generated without comment. Both are fixed
 * by reading the grammar `int()` reads.
 *
 * The one place it still stops short of `int()` is magnitude: Python's integers
 * are unbounded and these arrive as a JavaScript number, so a value past
 * `Number.MAX_SAFE_INTEGER` loses precision. `Number.parseInt` did too, and
 * both are some fifteen orders of magnitude past `MAX_SET_TRACKS`.
 *
 * The sign matters for the ORDER of §2.12's checks: `"-2"` has to parse so the
 * next rule can reject it as "Position must be 1 or greater" (:963) rather than
 * this one rejecting it as "not a valid position number" (:962).
 */
export function parseIntegerStrictly(text) {
  const stripped = String(text === null || text === undefined ? '' : text).replace(
    SURROUNDING_SPACE,
    '',
  );
  const match = PYTHON_INTEGER.exec(stripped);
  if (!match) {
    return null;
  }

  let value = 0;
  // By code point, so an astral digit such as U+1D7CE counts as one character.
  for (const character of match[2]) {
    if (character !== '_') {
      value = value * 10 + decimalValue(character);
    }
  }
  return match[1] === '-' ? -value : value;
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
