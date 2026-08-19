/* The Explore destination.
 *
 * Implemented against the control list in docs/UI_FEATURE_INVENTORY.md §2.4
 * (lines 315-438). What is reimplemented here, with the inventory line it comes
 * from:
 *
 *   :326  Set Current Track            -> the ⌘K palette
 *   :325  ← Back, disabled at launch   -> history, capacity 20 (:414-421, :1387)
 *   :328  Set Selected as Current      -> click a row to re-seed
 *   :347  double-click to re-seed      -> single click (this is not a listbox)
 *   :335  Score/Cosine/Key/BPM/Artist  -> the sort segmented control (:377-387)
 *   :336  Top-N 10/20/30/50/100/200    -> the Top select, default 50 (:1377)
 *   :338  Top-N re-renders only        -> no refetch on change
 *   :356  the rendered row format      -> artist, title, Camelot, BPM, Cos, Score
 *   :366  Score clamped, Cos NOT       -> format.percentClamped vs format.percent
 *   :370  topk=500, final_top=200      -> the API's defaults (:1378)
 *   :372  all 200 retained, topn shown -> the full list is fetched and kept
 *   :385  sorts apply to all 200       -> sorting happens before truncation
 *   :387  sorts are stable             -> Array.prototype.sort is stable
 *   :1211 the current-track header     -> the seed card
 *   :327  Copy Selected to Clipboard   -> Copy, see the note on it below
 *
 * Anything from §2.4 not in that list is named in the PR description under
 * "Deferred to PR 3b" with its line number. Silent omission is the one thing
 * this PR cannot do: the inventory is the acceptance contract.
 */

import { api, ApiError } from '../api.js';
import {
  bpm as formatBpm,
  displayName,
  element,
  percent,
  percentClamped,
  pill,
  scoreBar,
  stateBlock,
} from '../format.js';

/* Inventory :337 - the exact values the Tkinter combobox offers, and :1377 -
 * the default. */
export const TOP_N_OPTIONS = [10, 20, 30, 50, 100, 200];
export const DEFAULT_TOP_N = 50;

/* Inventory :1387. The oldest entry is dropped on overflow. */
export const HISTORY_CAPACITY = 20;

/* The full computed set is fetched once and kept, so Top-N and every sort are
 * pure re-renders. Inventory :372 - "The full 200 are retained in
 * current_recommendations; only the first topn are rendered." */
const FETCH_LIMIT = 200;

/* Inventory :377-387. The comparison keys and directions are copied exactly,
 * including the two that look wrong and are not:
 *
 *  - Key sorts ASCENDING and lexicographically on the Camelot string, so
 *    "10A" < "1A" < "2A". Comparing with < on strings reproduces Python's str
 *    ordering for these ASCII values; localeCompare would not.
 *  - BPM uses `float(bpm or 0)`, so a missing BPM becomes 0 and sorts LAST
 *    under a descending sort.
 */
export const SORTS = {
  score: { label: 'Score', key: (r) => Number(r.score), direction: -1 },
  cosine: { label: 'Cosine', key: (r) => Number(r.cosine), direction: -1 },
  key: { label: 'Key', key: (r) => String(r.key === null ? '' : r.key), direction: 1 },
  bpm: { label: 'BPM', key: (r) => Number(r.bpm) || 0, direction: -1 },
  artist: { label: 'Artist', key: (r) => String(r.artist || '').toLowerCase(), direction: 1 },
};

export const DEFAULT_SORT = 'cosine';

export function sortRecommendations(recommendations, sortName) {
  const sort = SORTS[sortName] || SORTS[DEFAULT_SORT];
  // A copy: Array.prototype.sort mutates, and the history holds these arrays.
  return [...recommendations].sort((left, right) => {
    const a = sort.key(left);
    const b = sort.key(right);
    if (a < b) return -1 * sort.direction;
    if (a > b) return 1 * sort.direction;
    return 0;
  });
}

async function copyToClipboard(text) {
  // navigator.clipboard needs a secure context; 127.0.0.1 qualifies. The
  // execCommand path is the fallback for a WKWebView that refuses it.
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
  scratch.style.position = 'fixed';
  scratch.style.opacity = '0';
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

export function mountExplore({ store, onPickSeed, onShowDetail }) {
  const root = document.getElementById('view-explore');
  let inFlight = 0;

  // -- data ---------------------------------------------------------------

  async function loadFor(trackId) {
    const mine = ++inFlight;
    store.setState({ exploreStatus: 'loading', exploreError: null });

    try {
      const body = await api.recommendations(trackId, { limit: FETCH_LIMIT });
      if (mine !== inFlight) {
        return;
      }
      store.setState({
        seed: body.seed,
        recommendations: body.recommendations,
        exploreStatus: 'ready',
        exploreError: null,
      });
    } catch (error) {
      if (mine !== inFlight) {
        return;
      }
      store.setState({
        exploreStatus: 'error',
        exploreError: error instanceof ApiError ? error : new ApiError('unknown', String(error), 0),
      });
    }
  }

  /**
   * Make ``trackId`` the seed.
   *
   * Inventory :416-419 - the current state is pushed to history only when BOTH
   * a seed and a recommendation list already exist, capacity 20, oldest
   * dropped on overflow, and a non-empty history is what enables ← Back.
   */
  function seed(trackId) {
    const state = store.getState();
    const history = [...state.history];

    if (state.seed && state.recommendations && state.recommendations.length) {
      history.push({ seed: state.seed, recommendations: state.recommendations });
      while (history.length > HISTORY_CAPACITY) {
        history.shift();
      }
    }

    store.setState({ history });
    loadFor(trackId);
  }

  /* Inventory :420-421 - going back restores the stored list VERBATIM,
   * including its sort order, without recomputing, and re-renders honouring
   * the CURRENT Top-N. */
  function goBack() {
    const state = store.getState();
    if (!state.history.length) {
      return;
    }
    const history = [...state.history];
    const previous = history.pop();
    inFlight += 1; // any in-flight fetch must not overwrite the restored list
    store.setState({
      history,
      seed: previous.seed,
      recommendations: previous.recommendations,
      exploreStatus: 'ready',
      exploreError: null,
    });
  }

  // -- rendering ----------------------------------------------------------

  function renderSeedCard(state) {
    const card = element('div', 'seed');
    const track = state.seed;

    card.append(
      element('p', 'seed__eyebrow', 'Current track'),
      element('h2', 'seed__title', track.title || 'Untitled'),
      element('p', 'seed__artist', track.artist || 'Unknown artist'),
    );

    const meta = element('div', 'seed__meta');
    meta.append(pill(track.key));

    const bpmFact = element('span', 'seed__fact');
    bpmFact.append(element('span', null, 'BPM'), element('b', null, formatBpm(track.bpm)));
    meta.append(bpmFact);

    if (track.album) {
      const albumFact = element('span', 'seed__fact');
      albumFact.append(element('span', null, 'Album'), element('b', null, track.album));
      meta.append(albumFact);
    }
    card.append(meta);

    const actions = element('div', 'seed__actions');

    const back = element('button', 'button', '← Back');
    back.type = 'button';
    // Inventory :325 / :1397 - disabled at launch, enabled once history is
    // non-empty, disabled again when the last entry is popped.
    back.disabled = state.history.length === 0;
    back.addEventListener('click', goBack);

    const change = element('button', 'button', 'Change seed  ⌘K');
    change.type = 'button';
    change.addEventListener('click', onPickSeed);

    const copy = element('button', 'button', 'Copy');
    copy.type = 'button';
    copy.addEventListener('click', async () => {
      const copied = await copyToClipboard(displayName(track));
      copy.textContent = copied ? 'Copied' : 'Copy failed';
      window.setTimeout(() => {
        copy.textContent = 'Copy';
      }, 1500);
    });

    const details = element('button', 'button button--quiet', 'Details');
    details.type = 'button';
    details.addEventListener('click', () => onShowDetail(track.track_id));

    actions.append(back, change, copy, details);
    card.append(actions);
    return card;
  }

  function renderToolbar(state) {
    const toolbar = element('div', 'toolbar');

    const sortGroup = element('div', 'toolbar__group');
    sortGroup.append(element('span', 'eyebrow', 'Sort by'));

    const segmented = element('div', 'segmented');
    segmented.setAttribute('role', 'group');
    segmented.setAttribute('aria-label', 'Sort recommendations');
    for (const [name, sort] of Object.entries(SORTS)) {
      const option = element('button', 'segmented__option', sort.label);
      option.type = 'button';
      option.setAttribute('aria-pressed', String(state.sort === name));
      option.addEventListener('click', () => store.setState({ sort: name }));
      segmented.append(option);
    }
    sortGroup.append(segmented);

    const topGroup = element('div', 'toolbar__group');
    const label = element('label', 'eyebrow', 'Top');
    label.setAttribute('for', 'explore-top-n');
    const select = element('select', 'select');
    select.id = 'explore-top-n';
    for (const value of TOP_N_OPTIONS) {
      const option = element('option', null, String(value));
      option.value = String(value);
      option.selected = value === state.topN;
      select.append(option);
    }
    // Inventory :338 - selecting a value re-renders the list only; it does not
    // recompute recommendations.
    select.addEventListener('change', () => {
      store.setState({ topN: Number(select.value) });
    });
    topGroup.append(label, select);

    toolbar.append(sortGroup, element('div', 'toolbar__spacer'), topGroup);
    return toolbar;
  }

  function renderRow(recommendation, rank) {
    const row = element('li', 'rec');

    const main = element('button', 'rec__main');
    main.type = 'button';
    main.title = 'Make this the current track';

    main.append(element('span', 'rec__rank', String(rank)));

    const text = element('div', 'rec__text');
    text.append(
      element('div', 'rec__title', recommendation.title || 'Untitled'),
      element('div', 'rec__artist', recommendation.artist || 'Unknown artist'),
    );
    main.append(text, pill(recommendation.key));

    main.append(element('span', 'rec__bpm', formatBpm(recommendation.bpm)));

    // Score is clamped to 0-100 %; Cos is NOT (inventory :365-366). A cosine
    // outside the range means the index is wrong and hiding it would make that
    // invisible.
    main.append(scoreBar(recommendation.score, percentClamped(recommendation.score)));
    const cosine = element('span', 'rec__cosine', `cos ${percent(recommendation.cosine)}`);
    cosine.title = 'Raw cosine similarity, unclamped';
    main.append(cosine);

    main.addEventListener('click', () => seed(recommendation.track_id));

    const info = element('button', 'rec__info', 'ⓘ');
    info.type = 'button';
    info.setAttribute('aria-label', `Details for ${displayName(recommendation)}`);
    info.addEventListener('click', () => onShowDetail(recommendation.track_id));

    row.append(main, info);
    return row;
  }

  function renderList(state) {
    const wrapper = element('div', 'recs');

    // Inventory :385-386 - the sort applies to ALL computed recommendations,
    // then the list is re-rendered truncated to topN. Sorting after truncating
    // would show the best of the first fifty rather than the best fifty.
    const sorted = sortRecommendations(state.recommendations, state.sort);
    const shown = sorted.slice(0, state.topN);

    const caption =
      shown.length === sorted.length
        ? `${shown.length} recommendations`
        : `Showing ${shown.length} of ${sorted.length} recommendations`;
    const historyNote = state.history.length ? ` · ${state.history.length} in history` : '';
    wrapper.append(element('p', 'recs__caption', caption + historyNote));

    const list = element('ul', 'recs__list');
    list.setAttribute('aria-label', 'Recommendations');
    shown.forEach((recommendation, index) => {
      list.append(renderRow(recommendation, index + 1));
    });
    wrapper.append(list);
    return wrapper;
  }

  function renderError(error) {
    if (error.code === 'empty_library') {
      return stateBlock({
        variant: 'error',
        title: 'No index yet',
        body:
          'There is no cosine index to search. Index a Rekordbox collection ' +
          'first — Settings ▸ Update Library in the Tkinter app does this today.',
      });
    }
    if (error.code === 'unknown_track') {
      return stateBlock({
        variant: 'error',
        title: 'That track is not in the index',
        body: error.message,
      });
    }
    return stateBlock({
      variant: 'error',
      title: 'Could not load recommendations',
      body: error.message,
    });
  }

  function renderEmptyPrompt(state) {
    if (state.libraryError) {
      return stateBlock({
        variant: 'error',
        title: 'The library could not be read',
        body: state.libraryError,
      });
    }
    if (state.library && state.library.is_empty) {
      return stateBlock({
        title: 'No index yet',
        body:
          'Index a Rekordbox collection first — Settings ▸ Update Library in ' +
          'the Tkinter app does this today.',
      });
    }

    const open = element('button', 'button button--primary', 'Search tracks  ⌘K');
    open.type = 'button';
    open.addEventListener('click', onPickSeed);
    return stateBlock({
      title: 'Pick a seed track',
      body: 'Everything starts from one track. Press ⌘K to find it.',
      action: open,
    });
  }

  function render(state) {
    if (state.destination !== 'explore') {
      return;
    }

    if (!state.seed) {
      root.replaceChildren(renderEmptyPrompt(state));
      return;
    }

    const view = element('div', 'explore');
    view.append(renderSeedCard(state));

    if (state.exploreStatus === 'loading') {
      view.append(stateBlock({ variant: 'loading', body: 'Ranking the library…' }));
    } else if (state.exploreStatus === 'error') {
      view.append(renderError(state.exploreError));
    } else if (!state.recommendations.length) {
      view.append(
        stateBlock({
          title: 'No recommendations',
          body: 'This track has no embedding in the index, so nothing can be ranked against it.',
        }),
      );
    } else {
      view.append(renderToolbar(state), renderList(state));
    }

    root.replaceChildren(view);
  }

  store.subscribe(render);
  render(store.getState());

  return { seed, goBack };
}
