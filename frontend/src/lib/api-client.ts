import axios from 'axios';

// Calls the FastAPI backend directly rather than through Next.js's rewrite
// proxy: `next dev`'s internal proxy for external rewrite destinations has
// its own hardcoded timeout (~20s) independent of this client's timeout
// below, and tearing down that proxied connection on a slow backend call
// crashes the whole Next.js dev server process. A real repository ingest
// routinely runs well past that, so the browser talks to the backend host
// directly instead.
//
// When no explicit override is set, resolve the backend host from whatever
// host the page was loaded from (so this keeps working when the frontend is
// opened from another device on the LAN, not just from localhost).
// The backend mounts every route under this prefix (see API_V1_STR in
// backend/src/core/config.py). The old rewrite's destination pattern baked
// this in silently; now that the browser calls the backend directly, it has
// to be part of the base URL since every service call uses a bare path
// like '/ingest' or '/query'.
const API_V1_PREFIX = '/api/v1';

function resolveApiBaseUrl(): string {
  if (process.env.NEXT_PUBLIC_API_URL) return process.env.NEXT_PUBLIC_API_URL;
  if (typeof window !== 'undefined') return `http://${window.location.hostname}:8000${API_V1_PREFIX}`;
  return `http://localhost:8000${API_V1_PREFIX}`;
}

const API_BASE_URL = resolveApiBaseUrl();

// Same host resolution as the REST client, just over ws(s):// instead of
// http(s):// - used by the chat feature's streaming websocket connection.
export const API_WS_BASE_URL = API_BASE_URL.replace(/^http/, 'ws');

export const apiClient = axios.create({
  baseURL: API_BASE_URL,
  headers: {
    'Content-Type': 'application/json',
  },
  // Ingesting a real repository (clone + chunk + Gemini embeddings, rate-limited
  // in small batches with inter-batch delays) can take several minutes for
  // non-trivial codebases, so this needs to be well above a typical request timeout.
  timeout: 600000, // 10 minutes
});

// Interceptor for response handling and unified error format
apiClient.interceptors.response.use(
  (response) => response,
  (error) => {
    const message = error.response?.data?.detail || error.message || 'An unexpected error occurred';
    return Promise.reject(new Error(message));
  }
);
