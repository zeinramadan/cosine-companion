/* A survey of which code points the shipped `parseIntegerStrictly` treats as a
 * decimal digit, and of which ones this node build's `\p{Nd}` treats as one.
 *
 * Written for `tests/web/test_integer_parsing_matches_python.py`, which is the
 * half of the comparison that can ask CPython. The point is the BOTH-DIRECTIONS
 * check the corpus alone cannot make: a corpus derived from `unicodedata` can
 * only ever contain digits Python already knows, so it can show that Python's
 * digits are accepted and never that JavaScript's extras are refused.
 *
 * Two arrays on stdout as JSON:
 *
 *   accepted        `[codePoint, value]` for every single character the helper parses
 *   nodeNd          every code point this runtime's `\p{Nd}` matches
 *   unicodeVersion  the Unicode version the shipped table DECLARES itself to be
 *
 * The last one is read from the module's export rather than from the file, so
 * a declaration that was edited without the table being regenerated is still
 * the declaration under test.
 *
 * BEHAVIOUR, not internals. `accepted` is measured by calling the exported
 * function, so it reports what the function does rather than what a table it
 * happens to contain says - a rule that read the table correctly and then used
 * something else would still be caught.
 *
 * Not a `.test.mjs`: it defines no cases and asserts nothing, exactly as
 * `parse_integer_driver.mjs` does not.
 */

import {
  PYTHON_UNICODE_VERSION,
  parseIntegerStrictly,
} from '../../../src/web/static/js/format.js';

const MAX = 0x10ffff;
const SURROGATE_FIRST = 0xd800;
const SURROGATE_LAST = 0xdfff;
const ND = /\p{Nd}/u;

const accepted = [];
const nodeNd = [];

for (let code = 0; code <= MAX; code += 1) {
  if (code >= SURROGATE_FIRST && code <= SURROGATE_LAST) {
    continue; // lone surrogates are not characters; `chr()` has no counterpart
  }
  const character = String.fromCodePoint(code);
  if (ND.test(character)) {
    nodeNd.push(code);
  }
  const parsed = parseIntegerStrictly(character);
  if (parsed !== null) {
    accepted.push([code, parsed]);
  }
}

process.stdout.write(
  JSON.stringify({ accepted, nodeNd, unicodeVersion: PYTHON_UNICODE_VERSION ?? null }),
);
