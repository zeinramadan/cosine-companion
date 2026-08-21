/* A pipe from `tests/web/test_integer_parsing_matches_python.py` to the shipped
 * `parseIntegerStrictly`.
 *
 * Reads a JSON array of strings on stdin and writes a JSON array of answers on
 * stdout - the parsed value AS A STRING, or `null` where the function refused
 * the input. Strings, because the comparison on the other side is with Python's
 * `int()` and a JSON number would put a float64 between the two of them.
 *
 * Not a `.test.mjs`: it defines no cases and asserts nothing. The assertions are
 * Python's, because Python is the oracle - the contract this function
 * implements is `int()`, and the only way to check that is to ask `int()`.
 */

import { parseIntegerStrictly } from '../../../src/web/static/js/format.js';

const input = await new Promise((resolve, reject) => {
  let text = '';
  process.stdin.setEncoding('utf8');
  process.stdin.on('data', (chunk) => {
    text += chunk;
  });
  process.stdin.on('end', () => resolve(text));
  process.stdin.on('error', reject);
});

const answers = JSON.parse(input).map((value) => {
  const parsed = parseIntegerStrictly(value);
  return parsed === null ? null : String(parsed);
});

process.stdout.write(JSON.stringify(answers));
