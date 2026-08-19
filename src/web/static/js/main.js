/* Boot: build the store, mount the shell, load the library.
 *
 * No framework, no build step. This file is loaded as a native ES module and
 * everything it imports is loaded the same way.
 */

import { api } from './api.js';
import { createStore } from './store.js';
import { element, stateBlock } from './format.js';
import { mountSidebar } from './components/sidebar.js';
import { mountPalette } from './components/palette.js';
import { mountDrawer } from './components/drawer.js';

const store = createStore({
  destination: 'explore',
  library: null,
  libraryError: null,
  detailTrackId: null,
  detail: null,
});

const explore = document.getElementById('view-explore');

function renderExplorePrompt(state) {
  if (state.destination !== 'explore') {
    return;
  }

  if (state.libraryError) {
    explore.replaceChildren(
      stateBlock({
        variant: 'error',
        title: 'The library could not be read',
        body: state.libraryError,
      }),
    );
    return;
  }

  if (state.library && state.library.is_empty) {
    explore.replaceChildren(
      stateBlock({
        title: 'No index yet',
        body:
          'Index a Rekordbox collection first — the Tkinter app’s Settings ▸ ' +
          'Update Library does this today.',
      }),
    );
    return;
  }

  const open = element('button', 'button button--primary', 'Search tracks  ⌘K');
  open.type = 'button';
  open.addEventListener('click', () => palette.open());

  explore.replaceChildren(
    stateBlock({
      title: 'Pick a seed track',
      body: 'Everything starts from one track. Press ⌘K to find it.',
      action: open,
    }),
  );
}

mountSidebar({ store });
mountDrawer({ store });

const palette = mountPalette({
  onSelect: (track) => {
    store.setState({ detailTrackId: track.track_id, detail: null });
  },
});

store.subscribe(renderExplorePrompt);
renderExplorePrompt(store.getState());

api
  .library()
  .then((library) => store.setState({ library, libraryError: null }))
  .catch((error) => store.setState({ libraryError: error.message }));
