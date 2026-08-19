/* The right-hand detail drawer.
 *
 * Shows one track's metadata and the playlists it belongs to. The playlist
 * section replaces PR 3a's stated placeholder: `track.playlists` is now filled
 * in by `web/api.py::_detail` from the two tables
 * `cosine_companion.py import-playlists` writes, and `track.playlist_source`
 * carries the provenance and the staleness verdict beside it.
 *
 * THREE THINGS THIS SECTION HAS TO GET RIGHT
 * ------------------------------------------
 * 1. `null` and `[]` are DIFFERENT. `null` means no playlist data has been
 *    imported and the user is shown how to import it; `[]` means the import
 *    happened and this track is in no playlist. Collapsing them would tell
 *    somebody who has never run the command that their track is in nothing.
 *    Both are reachable: 8 of the 1,532 indexed tracks are in zero playlists.
 *
 * 2. The FULL PATH is rendered, never the leaf name alone. 36 leaf names are
 *    duplicated across 72 of the 141 playlists - `deep techno`, `nibiru`,
 *    `hard 1hr` and 33 others each appear twice under different parents - so a
 *    bare name would show two identical rows with nothing to tell them apart.
 *    Full paths are unique. `folder_path` arrives as a LIST OF SEGMENTS and is
 *    joined HERE, because two folder names in the real export contain a
 *    forward slash (`Collections/Hauls`, `08/2026`) and a pre-joined string
 *    could not be taken apart again. The segments are separate elements with
 *    their own separator, so a slash that is part of a name is not the same
 *    mark as a slash between names.
 *
 * 3. Twenty-one items have to look deliberate. That is the real maximum
 *    (`Fireground - Never Sleep`), against a mean of 3. The list scrolls within
 *    a bounded height and the count is in the heading, so a long membership
 *    reads as a long list rather than as a drawer that has come apart.
 *
 * No `innerHTML` anywhere. Playlist names are user data out of an external
 * file and are exactly the strings that would carry an injection; everything
 * goes through `textContent` via `element()`, and
 * tests/web/test_frontend_conventions.py pins that for every component.
 */

import { api } from '../api.js';
import { bpm, element, pill, stateBlock } from '../format.js';

/* Shown when no playlist tables exist. The command itself comes from the
 * server (`playlist_source.import_command`) whenever there IS a record to read
 * it from; this is the not-imported case, where by definition there is not. */
const IMPORT_COMMAND = 'python src/cosine_companion.py import-playlists';

const NOT_IMPORTED_BODY =
  'No Rekordbox playlists have been imported yet. Run this to add them:';

const EMPTY_BODY = 'In 0 playlists.';

/* The separator drawn BETWEEN segments. A distinct element rather than part of
 * the text, so `Collections/Hauls` - a folder whose own name contains a slash -
 * is visibly a name and not two names. */
const PATH_SEPARATOR = '/';

/* `2026-08-19T...` -> `19 Aug`. Fixed locale, not the user's: this string sits
 * beside a filename in one short provenance line and has to be the same width
 * and the same order wherever the app runs. Anything unparseable yields null
 * and the line simply omits the date rather than rendering "Invalid Date". */
function importedOn(value) {
  if (!value) {
    return null;
  }
  const when = new Date(value);
  if (Number.isNaN(when.getTime())) {
    return null;
  }
  return new Intl.DateTimeFormat('en-GB', { day: 'numeric', month: 'short' }).format(when);
}

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

  /* A command the user is meant to type. `code`, not a paragraph: it is a
   * literal, and it is the one thing on the block that must be copied exactly. */
  function commandBlock(command) {
    return element('code', 'command', command);
  }

  /* One playlist: its folder path, then its name, then its size.
   *
   * The name is the prominent line and the folders sit above it in a quieter
   * one. That is what makes two playlists called `hard 1hr` distinguishable at
   * a glance while still leading with the thing the user named. */
  function renderPlaylist(playlist) {
    const segments = Array.isArray(playlist.folder_path) ? playlist.folder_path : [];
    const row = element('li', 'playlist');
    row.title = [...segments, playlist.name].join(` ${PATH_SEPARATOR} `);

    if (segments.length) {
      const path = element('span', 'playlist__path');
      segments.forEach((segment, at) => {
        if (at > 0) {
          const separator = element('span', 'playlist__sep', PATH_SEPARATOR);
          separator.setAttribute('aria-hidden', 'true');
          path.append(separator);
        }
        path.append(element('span', 'playlist__segment', segment));
      });
      row.append(path);
    }

    const line = element('span', 'playlist__line');
    line.append(element('span', 'playlist__name', playlist.name || 'Untitled playlist'));

    /* The playlist's TOTAL size from Rekordbox, not how many of its tracks CoCo
     * has indexed. 153 of the export's 4,669 entries name tracks that are not
     * in the library, so the two numbers genuinely differ and this is the one
     * the user recognises from Rekordbox. */
    const entries = Number(playlist.entries);
    if (Number.isFinite(entries)) {
      const count = element('span', 'playlist__entries', String(entries));
      count.title = `${entries} track${entries === 1 ? '' : 's'} in this playlist`;
      line.append(count);
    }

    row.append(line);
    return row;
  }

  /* "from library_export_190826.xml · imported 19 Aug", per spec §6.4.
   *
   * The basename only. The server never sends the absolute path: it would put
   * a home directory into every screenshot of the drawer and answers nothing
   * the filename does not. */
  function renderProvenance(source) {
    const parts = [];
    if (source.source_name) {
      parts.push(`from ${source.source_name}`);
    }
    const when = importedOn(source.imported_at);
    if (when) {
      parts.push(`imported ${when}`);
    }
    if (!parts.length) {
      return null;
    }
    return element('p', 'provenance', parts.join(' · '));
  }

  /* The staleness prompt. A PROMPT, never an action: spec §6.4 is explicit
   * that the app must not re-import on its own, and the "re-import now" button
   * is PR 3b's work along with the rest of the write surface. This says what
   * changed and names the command that fixes it. */
  function renderStaleness(source) {
    if (!source.stale && !source.source_missing) {
      return [];
    }

    const note = element('div', 'note');
    if (source.reason) {
      note.append(element('p', null, source.reason));
    }
    if (source.stale) {
      note.append(commandBlock(source.import_command || IMPORT_COMMAND));
    }
    return [note];
  }

  function renderPlaylists(track) {
    const section = element('div', 'drawer__section');
    const playlists = track.playlists;
    const source = track.playlist_source || null;

    const heading = element('div', 'section-heading');
    heading.append(element('p', 'eyebrow', 'Playlists'));
    if (Array.isArray(playlists) && playlists.length) {
      heading.append(element('span', 'section-heading__count', String(playlists.length)));
    }
    section.append(heading);

    if (!Array.isArray(playlists)) {
      // null: nothing imported. Not the same as "in no playlists".
      const note = element('div', 'note');
      note.append(element('p', null, NOT_IMPORTED_BODY), commandBlock(IMPORT_COMMAND));
      section.append(note);
      return section;
    }

    if (!playlists.length) {
      section.append(element('p', 'note', EMPTY_BODY));
    } else {
      const list = element('ul', 'playlists');
      for (const playlist of playlists) {
        list.append(renderPlaylist(playlist));
      }
      section.append(list);
    }

    if (source) {
      const provenance = renderProvenance(source);
      if (provenance) {
        section.append(provenance);
      }
      for (const node of renderStaleness(source)) {
        section.append(node);
      }
    }

    return section;
  }

  function renderTrack(track) {
    const body = element('div', 'drawer__body');
    const details = element('div', 'drawer__section');
    details.append(element('p', 'eyebrow', 'Details'), renderFacts(track));
    body.append(details, renderPlaylists(track));

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
