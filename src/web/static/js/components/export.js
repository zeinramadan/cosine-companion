/* The Export destination - inventory §2.6 (lines 537-664).
 *
 * What is reimplemented, with the inventory line it comes from:
 *
 *   :541  title `Export Recommendation Playlists`
 *   :542-543 the description sentence
 *   :545  section `1. Select Tracks`
 *   :549  radio `Selected tracks:` (value `manual`, the default)
 *   :550  `+ Add Tracks` -> TrackSelectorDialog (§2.11)
 *   :551  `Clear All`
 *   :552  the selected-tracks list
 *   :553  radio `All tracks in collection` (value `all`)
 *   :558-562 the three selection-info texts and their two tones
 *   :564-565 the label refreshes on radio, on selection, and on becoming visible
 *   :567-569 rows sorted by (artist.lower(), title.lower()), `{artist} – {title}
 *            [{key}] ({bpm} BPM)`, ids absent from the library skipped
 *   :571  section `2. Configure Playlists`
 *   :575  `Recommendations per track:` 10-50, default 25
 *   :576  `Export format:` separate (default) / combined
 *   :578  section `3. Output Location`
 *   :587  `🎵 Generate Playlists`
 *   :588-592 the progress block, hidden until an export starts, DETERMINATE
 *   :594-598 the two id sources
 *   :599  no tracks    -> No Tracks Selected / Please select tracks to export…
 *   :601  no directory -> No Output Directory / Please select an output directory.
 *   :603-611 the `Confirm Export` question, verbatim
 *   :613  the button is disabled and the progress block appears
 *   :615-618 bar = current/total, `Generating playlists... ({current}/{total})`,
 *            `Current: {artist} - {title}` (a plain hyphen, unlike everywhere else)
 *   :620-634 the `Export Complete` dialog, verbatim
 *   :636  the `Export Error` dialog, verbatim
 *
 * Everything in §2.6 that is NOT here is named with its line number in the PR
 * description. Silent omission is the one thing this PR cannot do.
 *
 * WHY THIS SCREEN IS DIFFERENT FROM THE OTHER FOUR
 * ------------------------------------------------
 * It is the longest-running thing in the application, and the only one with a
 * cancel, so the progress display and the Stop button are the feature and not
 * decoration.
 *
 * HOW LONG IT ACTUALLY TAKES, because :640's number is stale. Inventory :640
 * records ~6.8 minutes for a full-collection export. Measured on this branch
 * against the real 1,532-track library, through the shipped endpoints: **11.9
 * s**, 7.8 ms a seed, 1,532 playlists and 38,300 recommendations written. The
 * figure at :640 predates the transition-vector work, exactly as the 2.76 s
 * set-generation figure at :511-512 did before §6.7 corrected it to 0.064 s.
 * Recorded in §6.9 rather than left as a number this file repeats.
 *
 * None of the design below changes: twelve seconds is still long enough that a
 * frozen window would be wrong, a user can still want it stopped, and a reload
 * can still land in the middle of it. What it does change is the poll budget -
 * at half a second the counter moves about two dozen times over a run, which
 * is a moving bar rather than a slideshow.
 *
 * * The bar is DETERMINATE, because the run knows `i` and `N` and reports both.
 *   §2.13's re-index window showed an indeterminate bar while holding exactly
 *   that pair; this does not repeat it.
 * * Stop really stops (:640 records that the Tkinter tab has no cancel control
 *   at all), and the UI says what a stop leaves behind BEFORE it is pressed as
 *   well as after: partial results are KEPT. That is PR #25's decision, and the
 *   opposite of indexing's, which discards. A user who stops has to know
 *   whether the files in front of them are finished.
 * * The job outlives the page. `JobRegistry` is process-wide and remembers
 *   terminal jobs, so a reload during those seven minutes re-attaches through
 *   `GET /api/jobs` instead of losing the run.
 *
 * POLLING, NOT A STREAM. See `api.js` - the decision is measured and it is not
 * this module's to revisit.
 */

import { api, ApiError } from '../api.js';
import { element, stateBlock } from '../format.js';
import { libraryRowText, sortLibraryTracks } from './library.js';
import { askyesno, showerror, showinfo, showwarning } from './message-box.js';
import { openTrackSelectorDialog } from './track-selector-dialog.js';

/* Inventory :549 and :553 - `tk.StringVar(value="manual")`. */
export const MODE_MANUAL = 'manual';
export const MODE_ALL = 'all';

/* Inventory :575 - the combo's values and its default, which is NOT the API's
 * default (`DEFAULT_RECOMMENDATIONS_PER_TRACK` is 10). The combo is the
 * catalogued control, so 25 is sent explicitly rather than left to the server. */
export const RECOMMENDATION_OPTIONS = ['10', '15', '20', '25', '30', '40', '50'];
export const DEFAULT_RECOMMENDATIONS = '25';

/* Inventory :576 - the two radio values, which are also the API's two modes
 * under different names. `separate` is the tab's word, `per_seed` is the
 * service's; the translation happens once, here. */
export const FORMAT_SEPARATE = 'separate';
export const FORMAT_COMBINED = 'combined';

const API_MODE = {
  [FORMAT_SEPARATE]: 'per_seed',
  [FORMAT_COMBINED]: 'combined',
};

/* Inventory :659 - combined mode's one file, inside the chosen directory. The
 * same literal `web/api.py::COMBINED_EXPORT_FILENAME` builds the path from, so
 * a result document read after a reload can be turned back into the directory
 * the user typed. */
export const COMBINED_FILENAME = 'Cosine_Recommendations.m3u';

/* Half a second. The measured cost of `GET /api/jobs/{id}` is 0.46 ms, so two
 * calls a second is under a tenth of a per cent of one core, and it is fast
 * enough that the counter moves while a seed is being ranked. */
export const POLL_INTERVAL_MS = 500;

/* After a failed poll. The run is still going on the server; there is no reason
 * to ask four times a second whether the socket came back. */
export const POLL_RETRY_MS = 2000;

/* Where the last output directory is remembered. Not a setting - it never
 * reaches the server, and it exists only because this destination cannot
 * pre-fill the catalogued default (see the `output` field below). */
const OUTPUT_STORAGE_KEY = 'coco.export.output-dir';

/** Inventory :558-562. The text and which of the two tones carries it. */
export function selectionInfo(mode, selectedCount, libraryCount) {
  if (mode === MODE_ALL) {
    return {
      text: `✓ Will generate playlists for all ${libraryCount} tracks in your collection`,
      tone: 'ok',
    };
  }
  if (selectedCount > 0) {
    return {
      text: `✓ ${selectedCount} track(s) selected • Click '+ Add Tracks' to add more`,
      tone: 'ok',
    };
  }
  return {
    text: '⚠ No tracks selected. Click \'+ Add Tracks\' to select tracks',
    tone: 'warn',
  };
}

/**
 * Inventory :567-569 - the selected rows, in the order the list shows them.
 *
 * Sorted by `(artist.lower(), title.lower())` and rendered with
 * `libraryRowText`, which is the Library destination's row builder and produces
 * exactly `{artist} – {title} [{key}] ({bpm} BPM)` with the empty parts dropped
 * and the whole thing trimmed. One builder rather than two: §2.6 and §2.7
 * specify the same string, and two spellings of one format is how they drift.
 *
 * An id the library does not know is SKIPPED, as `update_selected_tracks_display`
 * skips one absent from `meta_ix` (playlist_export_tab.py:269).
 */
export function selectedRows(selectedIds, tracksById) {
  const known = [...selectedIds]
    .map((trackId) => tracksById.get(trackId))
    .filter(Boolean);
  return sortLibraryTracks(known).map((track) => ({
    track_id: track.track_id,
    text: libraryRowText(track),
  }));
}

/** Inventory :603-611, verbatim, newlines and all. */
export function confirmMessage({ format, count, perTrack, outputDir }) {
  const description =
    format === FORMAT_SEPARATE ? 'separate playlists' : 'a single combined playlist';
  return (
    `This will generate ${description} for ${count} track(s),\n` +
    `with ${perTrack} recommendations per track.\n\n` +
    `Output directory: ${outputDir}\n\n` +
    'Continue?'
  );
}

/**
 * The directory a result document was written into.
 *
 * Per-seed mode's `output` IS the directory. Combined mode's is the file inside
 * it, because that is what `_start_export` builds, so the filename comes back
 * off. Needed because a page that reloaded mid-export has no memory of what was
 * typed into the field and the result document is the only record left.
 */
export function outputDirectoryOf(result) {
  const output = String((result && result.output) || '');
  const suffix = `/${COMBINED_FILENAME}`;
  if (result && result.mode === 'combined' && output.endsWith(suffix)) {
    return output.slice(0, -suffix.length);
  }
  return output;
}

/**
 * The one sentence a per-seed run owes the user when a write may have failed.
 *
 * `failed` in per-seed mode is a UNION of three causes and only one of them
 * touches the disk. `export_recommendations_as_playlists` books a `failed` for
 * a track id missing from the metadata index, and again for a seed that ranked
 * no recommendations - neither opens a file - and a third time in the
 * `except Exception` wrapped around `create_m3u_playlist`, which does. That
 * third cause leaves a TRUNCATED file: the writer opens the destination with
 * mode `'w'` and writes `#EXTM3U` before it looks at a single track, so a raise
 * partway through leaves a header-only `.m3u` in the folder the user chose.
 *
 * Nothing on the wire says which of the three it was - `failed` is one integer
 * - so the screen can state the POSSIBILITY and cannot state more. Hence "can
 * still leave" rather than a claim that a partial IS there, and hence an
 * instruction to look rather than a count of what is in the directory, which
 * this screen still cannot see.
 *
 * COMBINED MODE HAS NO CALLER HERE, and not by oversight.
 * `export_single_playlist` increments `failed` only on its two ranking paths;
 * its single `create_m3u_playlist` call sits after the loop, guarded by
 * `if all_recommendations` and wrapped in no `except`, so a raise there
 * propagates out and fails the whole job rather than returning these stats. In
 * combined mode `failed > 0` therefore says nothing at all about the disk, and
 * this caveat would be a warning with no referent.
 */
function partialFileCaveat(outputDir) {
  return (
    'A write that fails partway can still leave an unfinished file behind, so ' +
    `check ${outputDir} before importing from it.`
  );
}

/**
 * Inventory :620-634 - the `Export Complete` body.
 *
 * DEFECT #10, FIXED HERE. The catalogued body reads `stats['playlists_created']`
 * and combined mode's legacy stats dict has no such key, so the Tkinter tab
 * raises `KeyError` and shows NO dialog at all - a completed export that says
 * nothing. The API does not reproduce the trap: `_export_result_document` sends
 * an explicit `null` for combined mode. So this renders that line from what the
 * mode actually produced, and every other line is the catalogued one.
 *
 * THE PER-SEED COUNT LINE IS GONE, and its absence is the point. `Playlists
 * created: N` is a claim about the FILESYSTEM, and nothing on this wire counts
 * files. `playlist_exporter.py:171-173` increments `successful` and
 * `playlists_created` on adjacent lines inside one `try`, and every other path
 * increments only `failed` - so in per-seed mode the two counters are the same
 * number by construction, and the dialog was printing one measurement twice
 * with the second copy wearing a filesystem label. What that number counts is
 * WRITE CALLS THAT DID NOT RAISE. Where each write lands is decided by
 * `playlist_filename(artist, title)`, whose own docstring says two seeds that
 * sanitise to the same name "overwrite each other silently" - so N writes leave
 * N files only if the N names are distinct. On the real collection they are
 * not: 1532 writes, 1529 files. The screen cannot see the directory, so it no
 * longer says anything about how many things are in it. `Successful:` keeps
 * the number, under the label that is true of it - seeds processed - and
 * `Location:` names the folder the user can look in.
 *
 * Combined mode KEEPS its line, because there the count is knowable rather
 * than guessed: one run writes one fixed filename, so the answer is 1, or 0
 * when there was nothing to write. That line is also what defect #10 is about,
 * and removing it would remove the fix.
 *
 * ROUND 4, asked whether this body has the omission that made the stopped
 * dialog a blocker. IT DOES NOT: `Failed:` is a line of its own and always
 * was, so a completed run with failures discloses them. What it did not say is
 * what that number means for the disk, and the two lines under it tell the
 * user to import "these .m3u files" - which in per-seed mode can include the
 * header-only file a raised write left behind. Disclosing the count and then
 * inviting an unqualified import is the weaker form of the same defect, so it
 * ends with `partialFileCaveat` when per-seed mode reports a failure. The
 * clean body is untouched, and pinned as a whole literal by
 * `tests/web/js/export.test.mjs`.
 */
export function completionMessage({ result, outputDir }) {
  const combined = result.mode === 'combined';
  const created = combined
    ? result.total_recommendations > 0
      ? 'Playlists created: 1 (one combined playlist)\n'
      : 'Playlists created: 0 (no recommendations, so no file was written)\n'
    : '';

  return (
    '✓ Export Complete!\n\n' +
    created +
    `Successful: ${result.successful}\n` +
    `Total recommendations: ${result.total_recommendations}\n` +
    `Failed: ${result.failed}\n\n` +
    `Location: ${outputDir}\n\n` +
    'You can now import these .m3u files into Rekordbox:\n' +
    'File → Import → Playlist → Select .m3u file(s)' +
    (combined || !(result.failed > 0) ? '' : `\n\n${partialFileCaveat(outputDir)}`)
  );
}

/**
 * What a stopped export left on disk. An ADDITION - §2.6 has no cancel control.
 *
 * PARTIAL RESULTS ARE KEPT, and saying so is the whole reason this string
 * exists. `web/api.py::_export_result_document` sets out why: per-seed mode
 * writes one `.m3u` per seed and breaks at the TOP of the loop, so a stop lands
 * between seeds and never mid-file; combined mode accumulates in memory and
 * writes once after the loop whether or not it was stopped, so a stop produces
 * a SHORTER playlist rather than none. Deleting either would mean a Stop button
 * removing files from a directory the user chose. The files stay and the
 * accounting is honest about what they are.
 *
 * "A stop never lands mid-file" is NOT the same claim as "every file in the
 * directory is complete", and only the first one is this screen's to make. A
 * FAILED write leaves a partial file: `create_m3u_playlist` opens the path with
 * mode `'w'` and writes `#EXTM3U` before it looks at a single track, so a raise
 * partway through leaves a truncated `.m3u` on disk, and the caller's
 * `except Exception` books it as `failed` and moves on. Nothing about that
 * reaches the wire. So the sentence is about what STOPPING does, which the job
 * protocol settles, and says nothing about what is in the folder, which it
 * cannot see.
 *
 * THAT SCOPING WAS NOT ENOUGH, round 4. A correctly scoped true sentence can
 * still mislead by what it leaves out. Driven for real - `successful=1,
 * failed=1, cancelled=true, total_tracks=3` - the directory held one complete
 * playlist and one header-only partial, and this branch rendered the KEPT
 * sentence and the mid-file sentence and NOTHING ELSE. The failure was never
 * mentioned. A user reading a reassurance about the folder they are being
 * pointed at will import from it, and one of those files is not importable.
 * Being silent about the failure is not the same as declining to make a
 * filesystem claim: the count of failures is on the wire, it is this screen's
 * to report, and the zero branch was already reporting the consequence. So
 * `failed > 0` now gets the disclosure and `partialFileCaveat`, which is the
 * same sentence the zero branch says, now said in one place instead of two.
 *
 * The "already finished" branch is not padding. `ExportResult.cancelled` is
 * read off the cancel event, not off whether the loop broke, so a stop that
 * lands after the last seed marks the job cancelled with every playlist
 * written. Told "cancelled" and nothing else, a user would go looking for
 * missing files that are all there.
 *
 * PER-SEED CARRIES NO FILE COUNT, for the reason `completionMessage` sets out:
 * `playlists_created` counts write calls, not files, and this screen cannot
 * see the directory. The opening line already gives the honest number - tracks
 * PROCESSED, which is what a stop is measured in - so nothing is lost. NO count
 * survives, zero included. This branch used to read "so this run left nothing
 * in {dir}", on the reasoning that `successful === 0` means no write call ever
 * returned and therefore nothing was written. The second half does not follow.
 * Reproduced: the first seed's write raises after the header, the stop is seen
 * before the second seed, the stats come back `successful=0, failed=1,
 * playlists_created=0` - and one truncated `.m3u` is sitting in the directory.
 * `successful === 0` means no write CALL RETURNED. It does not mean nothing was
 * written, and the difference is a file the user would import.
 *
 * So the branch states the thing it can prove - nothing finished, so there is
 * nothing to import - and hands the user the caveat instead of a guarantee.
 * COMBINED's zero branch is left alone because there the reasoning does hold:
 * `export_single_playlist` guards the write with `if all_recommendations`, so
 * no recommendations means `create_m3u_playlist` is never CALLED, and a raise
 * inside it would propagate and fail the job rather than return these stats.
 *
 * If the writer is ever made atomic - write to a temporary path and rename -
 * this branch can go back to claiming the absence, and
 * `tests/web/test_jobs_real_export.py::test_a_failed_write_leaves_a_partial_playlist_behind`
 * is what will tell you so by turning red.
 */
export function cancelledMessage({ result, outputDir }) {
  const combined = result.mode === 'combined';
  const processed = result.successful + result.failed;
  const finished = processed >= result.total_tracks;

  const opening = finished
    ? 'The export had already finished when you stopped it, so nothing was cut short.\n\n'
    : `Stopped after ${processed} of ${result.total_tracks} tracks.\n\n`;

  const written = combined
    ? result.total_recommendations > 0
      ? `The combined playlist was written to ${outputDir}/${COMBINED_FILENAME} and has been KEPT. ` +
        `It holds ${result.total_recommendations} recommendations from the ` +
        `${result.successful} tracks that were processed.`
      : 'No recommendations had been collected yet, so no playlist file was written.'
    : result.successful > 0
      ? `The playlists this run wrote are in ${outputDir} and have been KEPT. ` +
        'Stopping never cut one short - the run stops between tracks, never mid-file.' +
        (result.failed > 0
          ? `\n\n${result.failed} of the tracks processed did not export. ` +
            partialFileCaveat(outputDir)
          : '')
      : 'No playlist was finished before you stopped, so there is nothing from this ' +
        `run to import. ${partialFileCaveat(outputDir)}`;

  return `${opening}${written}\n\nNothing was deleted.`;
}

/** Inventory :636. */
export function errorMessage(reason) {
  return `An error occurred during export:\n\n${reason}`;
}

/** `47` of `1532` as a percentage, and 0 rather than NaN for a total of zero. */
export function progressPercent(current, total) {
  if (!(total > 0)) {
    return 0;
  }
  return Math.max(0, Math.min(100, (current / total) * 100));
}

/** `154` -> `2m 34s`. Whole seconds; this is a duration, not a stopwatch. */
export function formatDuration(seconds) {
  const whole = Math.max(0, Math.floor(Number(seconds) || 0));
  const minutes = Math.floor(whole / 60);
  const rest = whole % 60;
  if (minutes === 0) {
    return `${rest}s`;
  }
  return `${minutes}m ${String(rest).padStart(2, '0')}s`;
}

/**
 * Seconds still to go, or `null` when there is not enough to say.
 *
 * A flat extrapolation from the seeds already done. It is honest about being an
 * estimate in the label rather than in a comment, and it says nothing at all
 * until one seed has finished - one sample of a seven-minute run is not a rate.
 */
export function remainingSeconds(current, total, elapsedSeconds) {
  if (!(current > 0) || !(total > current) || !(elapsedSeconds > 0)) {
    return null;
  }
  return (elapsedSeconds / current) * (total - current);
}

/* Reading and writing the remembered directory can BOTH throw - Safari in a
 * private window throws on the accessor itself - and neither is worth a
 * message. A forgotten path is an inconvenience; a destination that fails to
 * mount is not. */
function rememberedOutput() {
  try {
    return (window.localStorage && window.localStorage.getItem(OUTPUT_STORAGE_KEY)) || '';
  } catch (error) {
    return '';
  }
}

function rememberOutput(value) {
  try {
    if (window.localStorage) {
      window.localStorage.setItem(OUTPUT_STORAGE_KEY, value);
    }
  } catch (error) {
    /* not worth a message */
  }
}

export function mountExport({
  store,
  pollIntervalMs = POLL_INTERVAL_MS,
  retryIntervalMs = POLL_RETRY_MS,
  now = () => Date.now(),
}) {
  const root = document.getElementById('view-export');

  /* Working state, in a closure for the reason set-creator.js gives: nothing
   * outside this destination reads a selection or a job, so putting them in
   * the store would only give another branch keys to collide over. */
  let mode = MODE_MANUAL;
  let selectedIds = new Set();
  let tracks = [];
  let tracksById = new Map();
  let libraryState = 'idle';
  let libraryError = null;
  let blockedByLoadError = false;

  /* The latest job document, and whether we are still asking about it. */
  let job = null;
  let watching = null;
  let timer = null;
  let connectionLost = false;
  /* Job ids whose terminal dialog has already been shown, so a re-render or a
   * late poll cannot raise it twice - and so a job that finished before this
   * page existed never raises one at all. */
  const announced = new Set();
  /* What was typed into the field when the run was started. The result document
   * carries the path too, but only this knows what the user asked for before
   * the server normalised it. */
  let startedWith = '';

  // -- the DOM, built once ---------------------------------------------------
  //
  // Built once and updated in place rather than re-rendered from state. Three
  // of the controls here are typed or selected INTO - the directory, the
  // per-track count, the mode - and a wholesale re-render either destroys the
  // caret or has to restore it, which is a bug waiting for a slow typist.

  const view = element('div', 'exportv');

  const intro = element('div', 'exportv__intro');
  intro.append(
    element('p', 'eyebrow', 'Playlist export'),
    element('h2', 'exportv__title', 'Export Recommendation Playlists'),
    element(
      'p',
      'exportv__description',
      'Generate .m3u playlists with track recommendations that can be imported into Rekordbox.',
    ),
  );

  // -- 1. Select Tracks ------------------------------------------------------

  const selectSection = element('section', 'exportv__section');
  selectSection.append(element('h3', 'exportv__heading', '1. Select Tracks'));

  const modeRow = element('div', 'exportv__mode');

  function radio(name, value, labelText, onChange) {
    const wrapper = element('label', 'radio');
    const input = element('input', 'radio__input');
    input.type = 'radio';
    input.name = name;
    input.value = value;
    input.addEventListener('change', () => {
      if (input.checked) {
        onChange(value);
      }
    });
    wrapper.append(input, element('span', 'radio__label', labelText));
    return { wrapper, input };
  }

  const manualRadio = radio('export-mode', MODE_MANUAL, 'Selected tracks:', (value) => {
    mode = value;
    renderSelection();
  });
  const allRadio = radio('export-mode', MODE_ALL, 'All tracks in collection', (value) => {
    mode = value;
    renderSelection();
  });
  manualRadio.input.checked = true;

  const addTracks = element('button', 'button button--primary', '+ Add Tracks');
  addTracks.type = 'button';
  addTracks.addEventListener('click', addTracksClicked);

  const clearAll = element('button', 'button', 'Clear All');
  clearAll.type = 'button';
  clearAll.addEventListener('click', () => {
    selectedIds = new Set();
    renderSelection();
  });

  modeRow.append(manualRadio.wrapper, addTracks, clearAll);

  const selectedList = element('ul', 'exportv__selected');
  selectedList.setAttribute('aria-label', 'Selected tracks');

  const selectionNote = element('p', 'exportv__info');
  selectionNote.setAttribute('role', 'status');
  selectionNote.setAttribute('aria-live', 'polite');

  selectSection.append(modeRow, selectedList, allRadio.wrapper, selectionNote);

  // -- 2. Configure Playlists ------------------------------------------------

  const configSection = element('section', 'exportv__section');
  configSection.append(element('h3', 'exportv__heading', '2. Configure Playlists'));

  const perTrackRow = element('div', 'field field--inline');
  const perTrackLabel = element('label', 'field__label', 'Recommendations per track:');
  perTrackLabel.setAttribute('for', 'export-per-track');
  const perTrackSelect = element('select', 'select');
  perTrackSelect.id = 'export-per-track';
  for (const value of RECOMMENDATION_OPTIONS) {
    const option = element('option', null, value);
    option.value = value;
    option.selected = value === DEFAULT_RECOMMENDATIONS;
    perTrackSelect.append(option);
  }
  perTrackSelect.value = DEFAULT_RECOMMENDATIONS;
  perTrackRow.append(perTrackLabel, perTrackSelect);

  const formatRow = element('div', 'exportv__formats');
  formatRow.setAttribute('role', 'group');
  formatRow.setAttribute('aria-label', 'Export format');
  formatRow.append(element('p', 'field__label', 'Export format:'));
  let format = FORMAT_SEPARATE;
  const separateRadio = radio(
    'export-format',
    FORMAT_SEPARATE,
    'Separate playlist per track',
    (value) => {
      format = value;
    },
  );
  const combinedRadio = radio(
    'export-format',
    FORMAT_COMBINED,
    'Single combined playlist',
    (value) => {
      format = value;
    },
  );
  separateRadio.input.checked = true;
  formatRow.append(separateRadio.wrapper, combinedRadio.wrapper);

  configSection.append(perTrackRow, formatRow);

  // -- 3. Output Location ----------------------------------------------------

  const outputSection = element('section', 'exportv__section');
  outputSection.append(element('h3', 'exportv__heading', '3. Output Location'));

  const outputRow = element('div', 'field');
  const outputLabel = element('label', 'field__label', 'Output directory');
  outputLabel.setAttribute('for', 'export-output');
  const outputField = element('input', 'field__input');
  outputField.id = 'export-output';
  outputField.type = 'text';
  outputField.setAttribute('autocomplete', 'off');
  outputField.setAttribute('spellcheck', 'false');
  // :604's default is `~/Desktop/Cosine_Playlists`, EXPANDED from `Path.home()`.
  // Nothing on the wire carries a home directory - `GET /api/library` has the
  // data directory and the XML path, neither of which is it - and sending a
  // literal `~` would have the exporter create a directory called `~` beside
  // the server process. So the shape is offered as a placeholder, the field
  // starts on whatever was used last, and the omission is in the PR
  // description. `Browse...` (:606) has no browser equivalent at all.
  outputField.setAttribute('placeholder', '/Users/you/Desktop/Cosine_Playlists');
  outputField.value = rememberedOutput();
  outputRow.append(outputLabel, outputField);

  outputSection.append(
    outputRow,
    element(
      'p',
      'exportv__hint',
      'Type the full path. Separate mode creates the directory if it is missing; ' +
        `combined mode writes ${COMBINED_FILENAME} into a directory that must already exist.`,
    ),
  );

  // -- action, progress, outcome --------------------------------------------

  const actions = element('div', 'exportv__actions');
  const generate = element('button', 'button button--primary', '🎵 Generate Playlists');
  generate.type = 'button';
  generate.addEventListener('click', generateClicked);
  actions.append(generate);

  /* :588 - hidden until an export starts, and `pack_forget()` on completion.
   * `hidden` is the same statement in the same place. */
  const progress = element('div', 'exportv__progress');
  progress.hidden = true;

  const progressLabel = element('p', 'progress__label');
  const progressTrack = element('div', 'progress__track');
  progressTrack.setAttribute('role', 'progressbar');
  progressTrack.setAttribute('aria-valuemin', '0');
  progressTrack.setAttribute('aria-valuemax', '100');
  const progressFill = element('div', 'progress__fill');
  progressTrack.append(progressFill);
  const progressStatus = element('p', 'progress__status');
  const progressTiming = element('p', 'progress__timing');

  const stop = element('button', 'button button--danger', 'Stop Export');
  stop.type = 'button';
  stop.addEventListener('click', stopClicked);
  const stopNote = element(
    'p',
    'progress__note',
    'Stopping keeps every playlist already written — nothing is deleted.',
  );
  const stopRow = element('div', 'progress__actions');
  stopRow.append(stop, stopNote);

  progress.append(progressLabel, progressTrack, progressStatus, progressTiming, stopRow);

  /* The outcome panel. NOT a substitute for the catalogued dialogs (:620, :636)
   * - it is what a reloaded page has instead of them. The registry remembers
   * eight finished jobs, so an export that ended while the window was closed
   * still has an account of itself; a modal raised on load for a job the user
   * has not been watching would be a surprise, and this is not. */
  const outcome = element('div', 'exportv__outcome');
  outcome.hidden = true;

  view.append(intro, selectSection, configSection, outputSection, actions, progress, outcome);
  root.replaceChildren(view);

  // -- behaviour -------------------------------------------------------------

  function libraryCount() {
    return tracks.length;
  }

  /* The directory a job wrote into: the result document's, because that is the
   * only record a reloaded page has, falling back to what was typed when this
   * page is the one that started it and the job failed before producing a
   * result at all. */
  function directoryFor(document_) {
    return outputDirectoryOf(document_ && document_.result) || startedWith;
  }

  function renderSelectedRows() {
    const rows = selectedRows(selectedIds, tracksById);
    if (!rows.length) {
      selectedList.replaceChildren(
        element(
          'li',
          'exportv__selected-empty',
          mode === MODE_ALL
            ? 'Every track in the collection will be exported.'
            : 'No tracks chosen yet.',
        ),
      );
      return;
    }
    selectedList.replaceChildren(
      ...rows.map((row) => {
        const item = element('li', 'exportv__row');
        item.append(element('span', 'exportv__row-text', row.text));
        // ADDITION (:552 records that the Tk listbox has no per-row remove and
        // that selecting a row there does nothing at all). A list whose only
        // undo is `Clear All` makes one mis-added track cost the whole
        // selection, and a row that looks selectable and is not is the false
        // promise `listbox.js` exists to stop making.
        const remove = element('button', 'exportv__row-remove', '✕');
        remove.type = 'button';
        remove.setAttribute('aria-label', `Remove ${row.text}`);
        remove.addEventListener('click', () => {
          selectedIds = new Set(selectedIds);
          selectedIds.delete(row.track_id);
          renderSelection();
        });
        item.append(remove);
        return item;
      }),
    );
  }

  /* :564-565 - refreshed when a radio is clicked, when the selection changes,
   * and whenever this destination becomes visible. One function, called from
   * all three, so the three cannot drift. */
  function renderSelection() {
    manualRadio.input.checked = mode === MODE_MANUAL;
    allRadio.input.checked = mode === MODE_ALL;

    // A library that would not load is reported in the place the count would
    // otherwise be, rather than under a count of zero that reads like an empty
    // collection.
    const info =
      libraryState === 'error'
        ? { text: `⚠ ${libraryError}`, tone: 'warn' }
        : selectionInfo(mode, selectedIds.size, libraryCount());
    selectionNote.textContent = info.text;
    selectionNote.dataset.tone = info.tone;

    renderSelectedRows();
    renderControls();
  }

  function running() {
    return Boolean(job && job.state === 'running');
  }

  function renderControls() {
    const busy = running();
    const ready = libraryState === 'ready';
    generate.disabled = busy || !ready;
    addTracks.disabled = busy || !ready;
    clearAll.disabled = busy;
    manualRadio.input.disabled = busy;
    allRadio.input.disabled = busy;
    separateRadio.input.disabled = busy;
    combinedRadio.input.disabled = busy;
    perTrackSelect.disabled = busy;
    outputField.disabled = busy;
  }

  function renderProgress() {
    if (!running()) {
      progress.hidden = true;
      return;
    }
    progress.hidden = false;

    const { current, total, message } = job.progress;
    const percent = progressPercent(current, total);

    // :616 - the count appears once the first seed has been reported. Before
    // that the job's own message is "Exporting N tracks", which is not a track.
    progressLabel.textContent =
      current > 0
        ? `Generating playlists... (${current}/${total})`
        : 'Generating playlists...';

    progressFill.style.setProperty('--progress', `${percent.toFixed(1)}%`);
    progressTrack.setAttribute('aria-valuenow', String(Math.round(percent)));
    progressTrack.setAttribute('aria-valuetext', `${progressLabel.textContent} — ${Math.round(percent)}%`);

    // :617 - `Current: {artist} - {title}`, a plain hyphen. The string is the
    // exporter's own (`playlist_exporter.py:147`), carried through the job
    // record untouched.
    progressStatus.textContent = current > 0 ? `Current: ${message}` : '';

    const elapsed = job.started_at ? now() / 1000 - job.started_at : 0;
    const left = remainingSeconds(current, total, elapsed);
    progressTiming.textContent =
      left === null
        ? `${formatDuration(elapsed)} elapsed`
        : `${formatDuration(elapsed)} elapsed · about ${formatDuration(left)} remaining`;

    stop.disabled = Boolean(job.cancel_requested);
    stop.textContent = job.cancel_requested ? 'Stopping…' : 'Stop Export';
    stopNote.textContent = job.cancel_requested
      ? 'Stopping after the track being written. Everything already written is kept.'
      : 'Stopping keeps every playlist already written — nothing is deleted.';
  }

  function renderOutcome() {
    if (!job || job.state === 'running') {
      if (!connectionLost) {
        outcome.hidden = true;
        return;
      }
    }

    const lines = [];
    let title = '';

    if (job && job.state === 'succeeded') {
      title = job.cancel_requested
        ? 'Export complete — the stop arrived too late to take effect'
        : 'Export complete';
      lines.push(completionMessage({ result: job.result, outputDir: directoryFor(job) }));
    } else if (job && job.state === 'cancelled') {
      title = 'Export stopped';
      lines.push(cancelledMessage({ result: job.result, outputDir: directoryFor(job) }));
    } else if (job && job.state === 'failed') {
      title = 'Export failed';
      lines.push(errorMessage(job.error));
    }

    if (connectionLost) {
      title = title || 'Export running';
      lines.push('Lost contact with the local server. Still trying — the export keeps going without this page.');
    }

    if (!lines.length) {
      outcome.hidden = true;
      return;
    }

    outcome.hidden = false;
    outcome.replaceChildren(
      element('p', 'eyebrow', title),
      element('p', 'exportv__outcome-body', lines.join('\n\n')),
    );
  }

  function render() {
    renderSelection();
    renderProgress();
    renderOutcome();
  }

  // -- the library table -----------------------------------------------------

  async function loadLibrary() {
    if (libraryState === 'loading' || libraryState === 'ready') {
      return;
    }
    libraryState = 'loading';
    libraryError = null;
    renderControls();
    try {
      const body = await api.libraryTracks();
      tracks = body.tracks || [];
      tracksById = new Map(tracks.map((track) => [track.track_id, track]));
      libraryState = 'ready';
    } catch (error) {
      libraryState = 'error';
      libraryError = error.message;
      tracks = [];
      tracksById = new Map();
    }
    render();
  }

  // -- the dialog ------------------------------------------------------------

  async function addTracksClicked() {
    const chosen = await openTrackSelectorDialog({ alreadySelected: selectedIds });
    if (!chosen) {
      // :939 - Cancel and the close button discard the selection.
      return;
    }
    // :938 - UNIONED into the existing set, never replacing it.
    const next = new Set(selectedIds);
    for (const trackId of chosen) {
      next.add(trackId);
    }
    selectedIds = next;
    renderSelection();
  }

  // -- starting, watching, stopping -----------------------------------------

  /* :594-598. `all` sends nothing and lets the endpoint resolve the whole
   * library against the snapshot the run executes on; `manual` sends the ids.
   *
   * The Tk tab's `all` branch reads `meta` rather than `meta_ix` and so counts
   * and exports a collection that deletion has left stale (defect #14). Neither
   * half of that is reachable here: the count comes from
   * `GET /api/library/tracks`, which reads `meta_ix`, and the export resolves
   * ids server-side from a `meta_ix` snapshot. The label and the run still
   * agree with each other; they now also agree with the library.
   */
  function exportTrackIds() {
    return mode === MODE_ALL ? null : [...selectedIds];
  }

  async function generateClicked() {
    const trackIds = exportTrackIds();
    const count = trackIds === null ? libraryCount() : trackIds.length;

    // :599, then :601, in that order - the order is observable, because with
    // no tracks AND no directory Tkinter says "No Tracks Selected".
    if (!count) {
      await showwarning(
        'No Tracks Selected',
        'Please select tracks to export playlists for.',
      );
      return;
    }

    // Trimmed, unlike `if not output_dir` at playlist_export_tab.py:366, which
    // reads the raw variable: a field holding only spaces passes there and then
    // fails at `_path_field` as a 400. Blank is blank.
    const outputDir = outputField.value.trim();
    if (!outputDir) {
      await showwarning('No Output Directory', 'Please select an output directory.');
      return;
    }

    const perTrack = perTrackSelect.value;
    const confirmed = await askyesno(
      'Confirm Export',
      confirmMessage({ format, count, perTrack, outputDir }),
    );
    if (!confirmed) {
      return;
    }

    startedWith = outputDir;
    rememberOutput(outputDir);

    try {
      const body = await api.startExport({
        mode: API_MODE[format],
        outDir: outputDir,
        recommendationsPerTrack: Number(perTrack),
        trackIds,
      });
      attach(body.job, { announce: true });
    } catch (error) {
      if (error instanceof ApiError && error.code === 'job_in_progress') {
        // One job at a time is the registry's rule, not a failure of this
        // request. The message names the job that is holding the lock.
        await showwarning('Export Already Running', error.message);
        // Find it, so the screen shows the run that refused this one.
        reattach();
        return;
      }
      await showerror('Export Error', errorMessage(error.message));
    }
  }

  async function stopClicked() {
    if (!watching) {
      return;
    }
    stop.disabled = true;
    try {
      const body = await api.cancelJob(watching);
      observe(body.job);
    } catch (error) {
      stop.disabled = false;
      await showerror('Export Error', errorMessage(error.message));
    }
  }

  function attach(document_, { announce }) {
    job = document_;
    watching = document_.state === 'running' ? document_.id : null;
    if (!announce) {
      announced.add(document_.id);
    }
    render();
    if (watching) {
      schedule(pollIntervalMs);
    } else {
      finished();
    }
  }

  function schedule(delay) {
    window.clearTimeout(timer);
    timer = window.setTimeout(poll, delay);
  }

  async function poll() {
    if (!watching) {
      return;
    }
    const mine = watching;
    try {
      const body = await api.job(mine);
      if (watching !== mine) {
        return;
      }
      connectionLost = false;
      observe(body.job);
    } catch (error) {
      if (watching !== mine) {
        return;
      }
      // The run is on the server and does not need this page. Say so, keep
      // asking, and ask less often.
      connectionLost = true;
      render();
      schedule(retryIntervalMs);
    }
  }

  function observe(document_) {
    job = document_;
    if (document_.state === 'running') {
      watching = document_.id;
      render();
      schedule(pollIntervalMs);
      return;
    }
    watching = null;
    window.clearTimeout(timer);
    render();
    finished();
  }

  function finished() {
    if (!job || job.state === 'running' || announced.has(job.id)) {
      return;
    }
    announced.add(job.id);
    const outputDir = directoryFor(job);

    if (job.state === 'succeeded') {
      // :620-634. Combined mode reaches this too, which is defect #10 fixed.
      const body = completionMessage({ result: job.result, outputDir });
      showinfo(
        'Export Complete',
        job.cancel_requested
          ? `${body}\n\nYour stop arrived after the last track, so the export finished in full.`
          : body,
      );
      return;
    }
    if (job.state === 'cancelled') {
      showinfo('Export Stopped', cancelledMessage({ result: job.result, outputDir }));
      return;
    }
    // :636.
    showerror('Export Error', errorMessage(job.error));
  }

  /**
   * Find a job this page did not start. Called at mount.
   *
   * THIS IS WHAT MAKES A RELOAD SURVIVABLE. `JobRegistry` outlives the request
   * that created it, so an export started seven minutes ago is still running
   * after ⌘R - but the page has lost the id it was given, which is exactly why
   * `GET /api/jobs` exists. A terminal job found this way is shown in the
   * outcome panel and NOT announced: its dialog belongs to the page that was
   * watching when it ended.
   */
  async function reattach() {
    let body;
    try {
      body = await api.jobs();
    } catch (error) {
      return;
    }
    const exports = (body.jobs || []).filter((each) => each.kind === 'export');
    if (!exports.length) {
      return;
    }
    // Newest first (`JobRegistry.all`), so the first is the one to show.
    const latest = exports[0];
    attach(latest, { announce: latest.state === 'running' });
  }

  /* The library table is fetched when this destination first becomes visible,
   * not at mount: it is 1,532 rows on the real collection and a page that
   * never opens Export should not pay for them. The job lookup below is the
   * opposite - it happens at mount whatever is showing, because a run that
   * survived a reload has to be found again before anyone navigates. */
  function syncTo(state) {
    if (state.destination !== 'export') {
      return;
    }
    if (state.library && state.library.load_error) {
      blockedByLoadError = true;
      libraryState = 'error';
      libraryError = state.library.load_error.message;
      root.replaceChildren(
        stateBlock({
          variant: 'error',
          title: 'Library index needs rebuilding',
          body: state.library.load_error.message,
        }),
      );
      renderControls();
      return;
    }
    if (blockedByLoadError) {
      blockedByLoadError = false;
      libraryState = 'idle';
      libraryError = null;
    }
    root.replaceChildren(view);
    loadLibrary();
    // :565 - the label is refreshed whenever this becomes visible.
    renderSelection();
  }

  const unsubscribe = store.subscribe(syncTo);

  render();
  syncTo(store.getState());
  reattach();

  return {
    /** Whether this destination is watching a run right now. */
    isRunning: running,
    /**
     * Stop watching and let go of the store.
     *
     * The page never calls this - the window closing is what ends a session -
     * but a poll loop that outlives its mount is a timer nothing can stop, and
     * a module with no way to take one down cannot be tested twice in one
     * process without the first mount's timer firing into the second's DOM.
     */
    dispose() {
      watching = null;
      window.clearTimeout(timer);
      unsubscribe();
    },
  };
}
