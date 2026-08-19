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
  settings: () => request('/api/settings'),
  updateSettings: (xmlPath) =>
    request('/api/settings', {}, { method: 'POST', body: { xml_path: xmlPath } }),
  tracks: (limit = 50) => request('/api/tracks', { limit }),
  search: (q, limit = 50) => request('/api/tracks/search', { q, limit }),
  track: (trackId) => request(`/api/tracks/${encodeURIComponent(trackId)}`),
  recommendations: (trackId, { limit } = {}) =>
    request(`/api/tracks/${encodeURIComponent(trackId)}/recommendations`, { limit }),
};
