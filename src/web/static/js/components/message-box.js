/* `tkinter.messagebox`, as a web modal.
 *
 * Inventory §2.5 and §2.12 specify eight of these by title and body, and the
 * titles and bodies are the contract - "No Anchors" / "Please add at least one
 * anchor track before generating a set." is a catalogued string, not a message
 * this destination gets to reword. So the strings live at their call sites in
 * set-creator.js and anchor-dialog.js, next to the control that raises them,
 * and this module only knows how to put a title, a body and one or two buttons
 * on screen.
 *
 * WHY A MODAL AND NOT AN INLINE BANNER
 * ------------------------------------
 * One of the eight is a QUESTION - `askyesno("Position Taken", "Position {n}
 * already has an anchor track. Replace it?")`, whose "no" branch returns to
 * the dialog (inventory :964). An answer has to be waited for, and a banner
 * cannot be waited for. Rather than split the eight across two mechanisms by
 * temperament, all of them are the modal that the Tkinter ones are; the
 * asymmetry would be harder to justify than the modality.
 *
 * The button labels are Tk's own: OK for the three one-button kinds, Yes and
 * No for the question. Dismissing - Escape, or the backdrop - answers the same
 * way closing the Tk dialog does: `askyesno` is False, and the rest are done.
 */

import { element } from '../format.js';
import { openModal } from '../modal.js';

/* What a dismissal means. `askyesno` returning False on a window-manager close
 * is Tk's behaviour and inventory :964's "declining returns to the dialog"
 * depends on it: dismissing the question must not silently replace an anchor. */
const DISMISS_IS_NO = false;

function box({ title, message, variant, buttons, dismissValue }) {
  return openModal({
    label: title,
    className: `message-box message-box--${variant}`,
    dismissValue,
    build: (close) => {
      const body = element('div', 'message-box__body');
      body.append(
        element('h2', 'message-box__title', title),
        element('p', 'message-box__message', message),
      );

      const actions = element('div', 'message-box__actions');
      for (const { label, value, primary } of buttons) {
        const control = element(
          'button',
          primary ? 'button button--primary' : 'button',
          label,
        );
        control.type = 'button';
        control.addEventListener('click', () => close(value));
        actions.append(control);
      }
      body.append(actions);
      return body;
    },
    // The affirming button, so Enter and Space land on the answer the user is
    // most likely to want and Escape still means the other one.
    initialFocus: (panel) => panel.querySelector('.button--primary'),
  }).answer;
}

function acknowledge(variant) {
  return (title, message) =>
    box({
      title,
      message,
      variant,
      buttons: [{ label: 'OK', value: undefined, primary: true }],
      dismissValue: undefined,
    });
}

/** `messagebox.showerror` - a refusal the user has to correct. */
export const showerror = acknowledge('error');

/** `messagebox.showwarning` - a precondition the user has not met yet. */
export const showwarning = acknowledge('warning');

/** `messagebox.showinfo` - something that worked. */
export const showinfo = acknowledge('info');

/** `messagebox.askyesno` - resolves true for Yes, false for No or a dismissal. */
export function askyesno(title, message) {
  return box({
    title,
    message,
    variant: 'question',
    buttons: [
      { label: 'Yes', value: true, primary: true },
      { label: 'No', value: false, primary: false },
    ],
    dismissValue: DISMISS_IS_NO,
  });
}
