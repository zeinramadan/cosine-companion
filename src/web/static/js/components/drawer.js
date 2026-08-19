/* The right-hand detail drawer.
 *
 * Shows one track's metadata and, per the spec, the place playlist membership
 * will live. That section renders a stated placeholder and nothing else: there
 * is no playlist endpoint yet, `track.playlists` comes back explicitly null,
 * and inventing folder paths here would put a fiction in front of the user in
 * the one PR whose job is to prove the surface is honest.
 */

import { api } from '../api.js';
import { bpm, element, pill, stateBlock } from '../format.js';

const PLAYLIST_PLACEHOLDER = 'Playlist membership arrives in the next update.';

export function mountDrawer({ store }) {
  const root = document.getElementById('drawer');
  const app = document.getElementById('app');
  let requested = 0;

  function close() {
    store.setState({ detailTrackId: null, detail: null });
  }

  function renderHeader(track) {
    const header = element('div', 'drawer__header');
    const heading = element('div', 'drawer__heading');
    heading.append(
      element('h2', 'drawer__title', track.title || 'Untitled'),
      element('p', 'drawer__artist', track.artist || 'Unknown artist'),
    );

    const dismiss = element('button', 'button button--quiet', '✕');
    dismiss.type = 'button';
    dismiss.setAttribute('aria-label', 'Close track details');
    dismiss.addEventListener('click', close);

    header.append(heading, dismiss);
    return header;
  }

  function renderFacts(track) {
    const facts = element('dl', 'facts');

    const rows = [
      ['Album', track.album || '—'],
      ['BPM', bpm(track.bpm)],
    ];

    for (const [label, value] of rows) {
      facts.append(element('dt', null, label), element('dd', null, value));
    }

    facts.append(element('dt', null, 'Key'));
    const keyCell = element('dd');
    keyCell.append(pill(track.key));
    facts.append(keyCell);

    facts.append(element('dt', null, 'Track ID'), element('dd', null, track.track_id));

    facts.append(element('dt', null, 'File'));
    const pathCell = element('dd', 'is-path', track.path_local || '—');
    facts.append(pathCell);

    return facts;
  }

  function renderPlaylists() {
    const section = element('div', 'drawer__section');
    section.append(
      element('p', 'eyebrow', 'Playlists'),
      element('p', 'note', PLAYLIST_PLACEHOLDER),
    );
    return section;
  }

  function renderTrack(track) {
    const body = element('div', 'drawer__body');
    const details = element('div', 'drawer__section');
    details.append(element('p', 'eyebrow', 'Details'), renderFacts(track));
    body.append(details, renderPlaylists());

    root.replaceChildren(renderHeader(track), body);
  }

  async function fetchDetail(trackId) {
    const mine = ++requested;
    root.replaceChildren(stateBlock({ variant: 'loading', body: 'Loading track…' }));

    try {
      const body = await api.track(trackId);
      if (mine !== requested) {
        return;
      }
      store.setState({ detail: body.track });
    } catch (error) {
      if (mine !== requested) {
        return;
      }
      root.replaceChildren(
        stateBlock({
          variant: 'error',
          title: 'Could not load this track',
          body: error.message,
        }),
      );
    }
  }

  function render(state) {
    const open = Boolean(state.detailTrackId);
    root.hidden = !open;
    app.dataset.drawer = open ? 'open' : 'closed';

    if (!open) {
      root.replaceChildren();
      return;
    }

    if (state.detail && state.detail.track_id === state.detailTrackId) {
      renderTrack(state.detail);
      return;
    }

    fetchDetail(state.detailTrackId);
  }

  store.subscribe(render);
  render(store.getState());

  window.addEventListener('keydown', (event) => {
    if (event.key === 'Escape' && !root.hidden) {
      close();
    }
  });
}
