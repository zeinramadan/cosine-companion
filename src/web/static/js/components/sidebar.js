/* The destinations, and which one is showing.
 *
 * Explore and Settings are implemented. The other three are rendered,
 * reachable and clearly labelled rather than hidden.
 */

const VIEW_TITLES = {
  explore: 'Explore',
  'set-creator': 'Set Creator',
  library: 'Library',
  export: 'Export',
  settings: 'Settings',
};

export function mountSidebar({ store }) {
  const nav = document.getElementById('nav');
  const title = document.getElementById('view-title');
  const count = document.getElementById('library-count');
  const items = [...nav.querySelectorAll('[data-destination]')];
  const views = new Map(
    Object.keys(VIEW_TITLES).map((name) => [name, document.getElementById(`view-${name}`)]),
  );

  for (const item of items) {
    item.addEventListener('click', () => {
      store.setState({ destination: item.dataset.destination });
    });
  }

  function render(state) {
    const active = state.destination;

    for (const item of items) {
      const isActive = item.dataset.destination === active;
      if (isActive) {
        item.setAttribute('aria-current', 'page');
      } else {
        item.removeAttribute('aria-current');
      }
    }

    for (const [name, view] of views) {
      view.hidden = name !== active;
    }

    title.textContent = VIEW_TITLES[active] || 'Cosine Companion';

    if (state.library && state.library.load_error) {
      count.textContent = '—';
      return;
    }
    count.textContent =
      state.library && Number.isFinite(state.library.track_count)
        ? state.library.track_count.toLocaleString()
        : '—';
  }

  store.subscribe(render);
  render(store.getState());
}
