/* The one place that talks to the local server.
 *
 * The token arrives in the page URL - the server opens the window at
 * `/?key=<token>` because the static shell has to load before it can present
 * anything. This module reads it once, moves it to the X-Coco-Token header for
 * every subsequent call, and strips it out of the visible URL so it does not
 * end up in a screenshot or a copied address.
 *
 * Errors are typed. Every non-2xx response from the API carries
 * `{"error": {"code", "message"}}`, and the code is what the UI branches on -
 * `empty_library` is a different screen from `unknown_track`, and neither is a
 * network failure.
 */

const TOKEN_PARAM = 'key';
const TOKEN_HEADER = 'X-Coco-Token';

export class ApiError extends Error {
  constructor(code, message, status) {
    super(message);
    this.name = 'ApiError';
    this.code = code;
    this.status = status;
  }
}

function readTokenFromLocation() {
  const params = new URLSearchParams(window.location.search);
  const token = params.get(TOKEN_PARAM) || '';

  if (token) {
    params.delete(TOKEN_PARAM);
    const rest = params.toString();
    window.history.replaceState(
      {},
      '',
      window.location.pathname + (rest ? `?${rest}` : ''),
    );
  }

  return token;
}

const token = readTokenFromLocation();

async function request(path, params = {}, options = {}) {
  const url = new URL(path, window.location.origin);
  for (const [name, value] of Object.entries(params)) {
    if (value !== undefined && value !== null) {
      url.searchParams.set(name, String(value));
    }
  }

  const headers = { [TOKEN_HEADER]: token };
  const init = {
    method: options.method || 'GET',
    headers,
    cache: 'no-store',
  };
  if (options.body !== undefined) {
    headers['Content-Type'] = 'application/json';
    init.body = JSON.stringify(options.body);
  }

  let response;
  try {
    response = await fetch(url, init);
  } catch (cause) {
    throw new ApiError('network', 'Could not reach the local server.', 0);
  }

  let body = null;
  try {
    body = await response.json();
  } catch (cause) {
    body = null;
  }

  if (!response.ok) {
    const error = (body && body.error) || {};
    throw new ApiError(
      error.code || 'unknown',
      error.message || `The request failed (HTTP ${response.status}).`,
      response.status,
    );
  }

  return body;
}

export const api = {
  health: () => request('/api/health'),
  library: () => request('/api/library'),
  libraryTracks: () => request('/api/library/tracks'),
  deleteLibraryTracks: (trackIds) =>
    request('/api/library/tracks/delete', {}, {
      method: 'POST',
      body: { track_ids: trackIds.join('\n') },
    }),
  settings: () => request('/api/settings'),
  updateSettings: (xmlPath) =>
    request('/api/settings', {}, { method: 'POST', body: { xml_path: xmlPath } }),
  tracks: (limit = 50) => request('/api/tracks', { limit }),
  search: (q, limit = 50) => request('/api/tracks/search', { q, limit }),
  track: (trackId) => request(`/api/tracks/${encodeURIComponent(trackId)}`),
  recommendations: (trackId, { limit } = {}) =>
    request(`/api/tracks/${encodeURIComponent(trackId)}/recommendations`, { limit }),
  // POST, because the request is a `{position: track_id}` MAP plus a length and
  // a query string has no encoding for a mapping. Nothing is stored: the set is
  // computed and returned.
  generateSet: (anchors, totalTracks) =>
    request(
      '/api/set',
      {},
      { method: 'POST', body: { anchors, total_tracks: totalTracks } },
    ),

  /* -- long-running work ---------------------------------------------------
   *
   * POLLING, not a stream, and the decision was measured rather than assumed.
   * A streaming response cannot go through `server.py`'s `_send`, which takes
   * complete bytes and sets a Content-Length from them, so an SSE channel
   * would mean a second emission path reimplementing HEAD elision and framing
   * for one endpoint. `GET /api/jobs/{id}` costs 0.46 ms a call.
   */

  /** Every remembered job, newest first. What a reloaded page re-attaches from. */
  jobs: () => request('/api/jobs'),

  /** One job. The document `web/api.py::_job_document` builds. */
  job: (jobId) => request(`/api/jobs/${encodeURIComponent(jobId)}`),

  /**
   * Start an export. 202 with the accepted job, or 409 if one is running.
   *
   * `trackIds` is OMITTED for the whole library rather than sent in full, and
   * that is the endpoint's own instruction (`web/api.py::_export_track_ids`):
   * the real 1,532-id selection is 14.7 KiB newline-delimited against a fixed
   * 16 KiB body ceiling, so the common case does not fit. Absent means "every
   * track", resolved server-side against the one snapshot the run executes on.
   */
  startExport: ({ mode, outDir, recommendationsPerTrack, trackIds }) => {
    const payload = {
      mode,
      out_dir: outDir,
      recommendations_per_track: recommendationsPerTrack,
    };
    if (trackIds) {
      payload.track_ids = trackIds.join('\n');
    }
    return request('/api/jobs/export', {}, { method: 'POST', body: payload });
  },

  /**
   * Ask a job to stop. 200 whether or not it was still running.
   *
   * The body is `{}` rather than absent. `server.py` refuses a POST with no
   * `Content-Type: application/json` (415) and cannot parse an empty payload
   * (400), so "no fields" has to be spelled as an empty object; `_cancel_job`
   * accepts exactly that and refuses anything with fields in it.
   */
  cancelJob: (jobId) =>
    request(`/api/jobs/${encodeURIComponent(jobId)}/cancel`, {}, {
      method: 'POST',
      body: {},
    }),
};
