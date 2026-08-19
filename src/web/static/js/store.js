/* A forty-line observable. There is no framework in this application.
 *
 * Components subscribe and re-render from `getState()`. `setState` merges a
 * patch and notifies, and it does nothing at all when no key actually changed -
 * without that guard, a component that writes back what it just read loops.
 */

export function createStore(initialState) {
  let state = { ...initialState };
  const listeners = new Set();

  function getState() {
    return state;
  }

  function setState(patch) {
    const next = typeof patch === 'function' ? patch(state) : patch;

    const changed = Object.keys(next).some(
      (key) => !Object.is(state[key], next[key]),
    );
    if (!changed) {
      return state;
    }

    state = { ...state, ...next };
    // Copied first: a listener may unsubscribe during notification.
    for (const listener of [...listeners]) {
      listener(state);
    }
    return state;
  }

  function subscribe(listener) {
    listeners.add(listener);
    return () => listeners.delete(listener);
  }

  return { getState, setState, subscribe };
}
