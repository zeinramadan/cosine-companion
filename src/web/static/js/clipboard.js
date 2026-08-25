/* Putting text on the clipboard, and saying whether it worked.
 *
 * Lifted verbatim out of components/explore.js when the Set Creator's
 * `Export to Clipboard` (inventory :529-533) needed the same two-step. Moved
 * rather than copied: a second copy of a fallback path is a second thing to
 * get wrong, and the fallback is the half that only runs on the host that
 * cannot be tested from node.
 */

/**
 * Copy `text`, returning whether it landed.
 *
 * `navigator.clipboard` needs a secure context; 127.0.0.1 qualifies, so it is
 * the path that runs in practice. The `execCommand` branch is the fallback for
 * a WKWebView that refuses the async API, and the scratch textarea is removed
 * whatever happens.
 */
export async function copyToClipboard(text) {
  if (navigator.clipboard && window.isSecureContext) {
    try {
      await navigator.clipboard.writeText(text);
      return true;
    } catch (error) {
      /* fall through */
    }
  }

  const scratch = document.createElement('textarea');
  scratch.value = text;
  scratch.setAttribute('readonly', '');
  /* Off-screen through a class rather than an inline style, so this
     component's geometry is written in app.css, which is the text the CSS
     checks read. The check that keeps it there -
     test_no_script_puts_css_on_the_page_outside_the_stylesheet - searches
     stripped JavaScript line by line for five literal words, with a per-line
     exemption for a custom-property write; it is not a statement about what
     any script can do. The boundary note in that file lists what those checks
     do and do not establish, and says the list is non-exhaustive. */
  scratch.className = 'clipboard-scratch';
  document.body.append(scratch);
  scratch.select();
  let copied = false;
  try {
    copied = document.execCommand('copy');
  } catch (error) {
    copied = false;
  }
  scratch.remove();
  return copied;
}
