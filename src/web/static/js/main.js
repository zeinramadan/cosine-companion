/* Boot: build the store, mount the shell, load the library.
 *
 * No framework, no build step. This file is loaded as a native ES module and
 * everything it imports is loaded the same way.
 */

import { api } from './api.js';
import { createStore } from './store.js';
import { mountSidebar } from './components/sidebar.js';
import { mountSettings } from './components/settings.js';
import { mountPalette } from './components/palette.js';
import { mountDrawer } from './components/drawer.js';
import { mountExplore, DEFAULT_SORT, DEFAULT_TOP_N } from './components/explore.js';
import { mountSetCreator } from './components/set-creator.js';
import { mountLibrary } from './components/library.js';

const store = createStore({
  destination: 'explore',
  library: null,
  libraryError: null,

  // Explore
  seed: null,
  recommendations: [],
  history: [],
  sort: DEFAULT_SORT,
  topN: DEFAULT_TOP_N,
  exploreStatus: 'idle',
  exploreError: null,

  // Drawer
  detailTrackId: null,
  detail: null,
});

mountSidebar({ store });
mountSettings();
mountDrawer({ store });
// Set Creator keeps its own working state (anchors, length, the generated set);
// the store tells it which destination is showing and whether the library
// loaded, which is all it shares.
mountSetCreator({ store });

const palette = mountPalette({
  onSelect: (track, { details }) => {
    if (details) {
      store.setState({ detailTrackId: track.track_id, detail: null });
      return;
    }
    store.setState({ destination: 'explore' });
    explore.seed(track.track_id);
  },
});

const explore = mountExplore({
  store,
  onPickSeed: () => palette.open(),
  onShowDetail: (trackId) => store.setState({ detailTrackId: trackId, detail: null }),
});

mountLibrary({
  store,
  onSetCurrent: (trackId) => explore.setCurrent(trackId),
  onClearCurrent: () => explore.clearCurrent(),
});

api
  .library()
  .then((library) => store.setState({ library, libraryError: null }))
  .catch((error) => store.setState({ libraryError: error.message }));
