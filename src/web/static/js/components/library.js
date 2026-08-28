/* The Library destination: browse, filter, select, seed, delete and restore tracks.
 *
 * Inventory §2.7 is intentionally visible in this module. The browser list
 * keeps Tk's artist/title ordering, untrimmed four-field substring filter,
 * exact row text, selection warnings, confirmation copy and terminal status
 * strings. Deletion itself stays in LibrarySession; this is only the adapter.
 */

import { api } from '../api.js';
import { element, stateBlock } from '../format.js';


export function sortLibraryTracks(tracks) {
  return [...tracks].sort((left, right) => {
    const leftArtist = String(left.artist || '').toLowerCase();
    const rightArtist = String(right.artist || '').toLowerCase();
    if (leftArtist < rightArtist) return -1;
    if (leftArtist > rightArtist) return 1;

    const leftTitle = String(left.title || '').toLowerCase();
    const rightTitle = String(right.title || '').toLowerCase();
    if (leftTitle < rightTitle) return -1;
    if (leftTitle > rightTitle) return 1;
    return 0;
  });
}

export function filterLibraryTracks(tracks, query) {
  const needle = String(query).toLowerCase();
  if (!needle) {
    return [...tracks];
  }
  return tracks.filter((track) =>
    ['artist', 'title', 'album', 'key'].some((field) =>
      String(track[field] || '').toLowerCase().includes(needle),
    ),
  );
}

export function libraryRowText(track) {
  const extras = [];
  if (track.key) extras.push(`[${track.key}]`);
  if (track.bpm) extras.push(`(${track.bpm} BPM)`);
  return `${track.artist || ''} – ${track.title || ''} ${extras.join(' ')}`.trim();
}

export function mountLibrary({ store, onSetCurrent, onClearCurrent }) {
  const root = document.getElementById('view-library');
  const content = root.querySelector('#library-content');
  const loadError = root.querySelector('#library-load-error');
  const input = document.getElementById('library-search');
  const clear = document.getElementById('library-clear');
  const refresh = document.getElementById('library-refresh');
  const remove = document.getElementById('library-delete');
  const setCurrent = document.getElementById('library-set-current');
  const stats = document.getElementById('library-stats');
  const status = document.getElementById('library-status');
  const list = document.getElementById('library-tracks');
  const deletedList = document.getElementById('library-deleted-tracks');
  const deletedStatus = document.getElementById('library-deleted-status');
  const restoreAll = document.getElementById('library-restore-all');

  let tracks = [];
  let filtered = [];
  let deletedTracks = [];
  let selected = new Set();
  let anchor = null;
  let loading = false;
  let deletedBusy = false;
  let blockedByLoadError = false;

  function renderAvailability(state) {
    if (state.library && state.library.load_error) {
      blockedByLoadError = true;
      content.hidden = true;
      loadError.hidden = false;
      loadError.replaceChildren(
        stateBlock({
          variant: 'error',
          title: 'Library index needs rebuilding',
          body: state.library.load_error.message,
        }),
      );
      return;
    }

    loadError.hidden = true;
    loadError.replaceChildren();
    content.hidden = false;
    if (blockedByLoadError) {
      blockedByLoadError = false;
      load();
      loadDeleted();
    }
  }

  function report(message, state = 'idle') {
    status.textContent = message;
    status.dataset.state = state;
  }

  function reportDeleted(message, state = 'idle') {
    deletedStatus.textContent = message;
    deletedStatus.dataset.state = state;
  }

  function renderStats() {
    stats.textContent =
      tracks.length === filtered.length
        ? `${tracks.length} tracks`
        : `${filtered.length} of ${tracks.length} tracks`;
  }

  function choose(index, event = {}) {
    const trackId = filtered[index].track_id;
    if (event.shiftKey && anchor !== null) {
      const beginning = Math.min(anchor, index);
      const end = Math.max(anchor, index);
      selected = new Set(
        filtered.slice(beginning, end + 1).map((track) => track.track_id),
      );
    } else if (event.metaKey || event.ctrlKey) {
      selected = new Set(selected);
      if (selected.has(trackId)) {
        selected.delete(trackId);
      } else {
        selected.add(trackId);
      }
      anchor = index;
    } else {
      selected = new Set([trackId]);
      anchor = index;
    }
    renderList();
  }

  function firstSelectedTrack() {
    return filtered.find((track) => selected.has(track.track_id)) || null;
  }

  function setSelectedAsCurrent() {
    const track = firstSelectedTrack();
    if (!track) {
      window.alert('Please select a track from the library.');
      return;
    }
    store.setState({ destination: 'explore' });
    onSetCurrent(track.track_id);
  }

  function renderList(scrollTo = null) {
    const rows = filtered.map((track, index) => {
      const row = element('li', 'library-row');
      const option = element('button', 'library-row__option', libraryRowText(track));
      option.type = 'button';
      option.setAttribute('role', 'option');
      option.setAttribute('aria-selected', String(selected.has(track.track_id)));
      option.addEventListener('click', (event) => choose(index, event));
      option.addEventListener('dblclick', () => setSelectedAsCurrent());
      row.append(option);
      return row;
    });
    list.replaceChildren(...rows);
    renderStats();

    if (scrollTo !== null && rows[scrollTo]) {
      rows[scrollTo].scrollIntoView({ block: 'start' });
    }
  }

  function applyFilter() {
    filtered = filterLibraryTracks(tracks, input.value);
    selected = new Set();
    anchor = null;
    renderList();
  }

  async function load({ scrollTo = null, preserveStatus = false } = {}) {
    if (loading) return;
    loading = true;
    input.disabled = true;
    clear.disabled = true;
    refresh.disabled = true;
    remove.disabled = true;
    setCurrent.disabled = true;
    if (!preserveStatus) report('Loading library…');

    try {
      const body = await api.libraryTracks();
      tracks = sortLibraryTracks(body.tracks || []);
      filtered = filterLibraryTracks(tracks, input.value);
      selected = new Set();
      anchor = null;
      renderList(scrollTo);
      if (!preserveStatus) report('');
    } catch (error) {
      report(`❌ Error loading library: ${error.message}`, 'error');
    } finally {
      loading = false;
      input.disabled = false;
      clear.disabled = false;
      refresh.disabled = false;
      remove.disabled = false;
      setCurrent.disabled = false;
    }
  }

  function renderDeletedList() {
    restoreAll.disabled = deletedBusy || deletedTracks.length === 0;
    if (!deletedTracks.length) {
      deletedList.replaceChildren(
        element('li', 'library__deleted-empty', 'No tracks are excluded from indexing.'),
      );
      return;
    }

    const rows = deletedTracks.map((track) => {
      const row = element('li', 'library__deleted-row');
      const identity = element('div', 'library__deleted-identity');
      identity.append(
        element(
          'p',
          'library__deleted-name',
          `${track.artist || ''} – ${track.title || ''}`,
        ),
        element('p', 'library__deleted-id', `Track ID: ${track.track_id}`),
      );
      const restore = element('button', 'button', 'Restore for Reindex');
      restore.type = 'button';
      restore.disabled = deletedBusy;
      restore.addEventListener('click', () => restoreDeleted([track]));
      row.append(identity, restore);
      return row;
    });
    deletedList.replaceChildren(...rows);
  }

  async function loadDeleted({ preserveStatus = false } = {}) {
    if (deletedBusy) return;
    deletedBusy = true;
    renderDeletedList();
    if (!preserveStatus) reportDeleted('Loading deleted tracks…');

    try {
      const body = await api.deletedLibraryTracks();
      deletedTracks = sortLibraryTracks(body.tracks || []);
      if (!preserveStatus) reportDeleted('');
    } catch (error) {
      reportDeleted(`❌ Error loading deleted tracks: ${error.message}`, 'error');
    } finally {
      deletedBusy = false;
      renderDeletedList();
    }
  }

  function restoreConfirmation(chosen) {
    const target = chosen.length === 1
      ? `${chosen[0].artist || ''} – ${chosen[0].title || ''}`
      : `${chosen.length} deleted tracks`;
    const subject = chosen.length === 1 ? 'The track' : 'The tracks';
    return (
      `Restore ${target} for reindexing?\n\n` +
      `This only removes the deletion exclusion. ${subject} will not return to ` +
      'the library until you run Index New Tracks.'
    );
  }

  async function restoreDeleted(chosen) {
    if (!chosen.length || !window.confirm(restoreConfirmation(chosen))) return;

    deletedBusy = true;
    renderDeletedList();
    reportDeleted('Removing deletion exclusions…');
    const restoredIds = new Set(chosen.map((track) => track.track_id));
    try {
      const body = await api.restoreDeletedLibraryTracks([...restoredIds]);
      deletedTracks = deletedTracks.filter(
        (track) => !restoredIds.has(track.track_id),
      );
      const subject = body.removed_from_deleted === 1 ? 'Track is' : 'Tracks are';
      const object = body.removed_from_deleted === 1 ? 'it' : 'them';
      reportDeleted(
        `✅ ${subject} eligible for indexing again. ` +
        `Run Index New Tracks to add ${object} back to the library.`,
        'success',
      );
    } catch (error) {
      window.alert(`Failed to restore deleted tracks: ${error.message}`);
      reportDeleted('❌ Error restoring deleted tracks', 'error');
    } finally {
      deletedBusy = false;
      renderDeletedList();
    }
  }

  function selectedTracks() {
    return filtered.filter((track) => selected.has(track.track_id));
  }

  function confirmationFor(chosen) {
    if (chosen.length === 1) {
      return (
        `Delete this track from your library?\n\n${chosen[0].artist || ''} – ` +
        `${chosen[0].title || ''}\n\nThis will remove it from recommendations ` +
        `but won't delete the audio file.`
      );
    }
    return (
      `Delete ${chosen.length} selected tracks from your library?\n\n` +
      `This will remove them from recommendations but won't delete the audio files.`
    );
  }

  async function deleteSelected() {
    const chosen = selectedTracks();
    if (!chosen.length) {
      window.alert('Please select tracks to delete.');
      return;
    }
    if (!window.confirm(confirmationFor(chosen))) {
      return;
    }

    const scrollTop = Number(list.scrollTop) || 0;
    const rowHeight = list.children.length
      ? Number(list.children[0].offsetHeight) || 1
      : 1;
    const firstVisible = Math.max(0, Math.floor(scrollTop / rowHeight));
    const deletedIds = new Set(chosen.map((track) => track.track_id));
    const deletedAbove = filtered
      .slice(0, firstVisible)
      .filter((track) => deletedIds.has(track.track_id)).length;

    remove.disabled = true;
    setCurrent.disabled = true;
    report('Deleting tracks…');
    try {
      const body = await api.deleteLibraryTracks([...deletedIds]);
      if (body.deleted > 0) {
        report(`✅ Deleted ${body.deleted} tracks from library`, 'success');
        const current = store.getState().library || {};
        store.setState({ library: { ...current, ...body.library } });
        if (
          store.getState().seed &&
          deletedIds.has(store.getState().seed.track_id)
        ) {
          onClearCurrent();
        }
        await load({
          scrollTo: Math.max(0, firstVisible - deletedAbove),
          preserveStatus: true,
        });
        await loadDeleted();
      } else {
        report('❌ No tracks were deleted', 'error');
      }
    } catch (error) {
      window.alert(`Failed to delete tracks: ${error.message}`);
      report('❌ Error deleting tracks', 'error');
    } finally {
      remove.disabled = false;
      setCurrent.disabled = false;
    }
  }

  input.addEventListener('input', applyFilter);
  clear.addEventListener('click', () => {
    input.value = '';
    applyFilter();
  });
  refresh.addEventListener('click', () => {
    load();
    loadDeleted();
  });
  setCurrent.addEventListener('click', setSelectedAsCurrent);
  remove.addEventListener('click', deleteSelected);
  restoreAll.addEventListener('click', () => restoreDeleted(deletedTracks));

  const unsubscribe = store.subscribe(renderAvailability);
  renderAvailability(store.getState());
  if (!blockedByLoadError) {
    load();
    loadDeleted();
  }
  return {
    load,
    loadDeleted,
    deleteSelected,
    restoreDeleted,
    setSelectedAsCurrent,
    dispose: unsubscribe,
  };
}
