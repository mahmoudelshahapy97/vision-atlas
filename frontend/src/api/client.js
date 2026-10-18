// Fetch wrapper for the Atlas API: bearer token, JSON in/out, readable errors.
//
// Requests go to `${API_ORIGIN}/api/...`. API_ORIGIN is empty by default so
// everything is same-origin: Vite proxies /api and /media in development and
// nginx does in the container (see vite.config.js / nginx.conf.template).

export const API_ORIGIN = (import.meta.env.VITE_API_URL || "").replace(/\/$/, "");
export const API_BASE = `${API_ORIGIN}/api`;

export class ApiError extends Error {
  constructor(message, status) {
    super(message);
    this.status = status;
  }
}

let token = null;
let refreshToken = null;
let unauthorizedHandler = null;
let tokensHandler = null;
let refreshing = null;

export function setTokens(access, refresh) {
  token = access;
  refreshToken = refresh;
}

export const getAccessToken = () => token;
export const getRefreshToken = () => refreshToken;

/** Called when a request made with a token comes back 401 and the session
 *  can't be renewed (expired or revoked). Kept as a callback so the API layer
 *  doesn't import the auth context. */
export function onUnauthorized(fn) {
  unauthorizedHandler = fn;
}

/** Called with the /auth/refresh body each time the tokens rotate, so the
 *  auth context can persist them. */
export function onTokens(fn) {
  tokensHandler = fn;
}

/** Absolute URL for media and sample files returned by the API ("/media/...", "/api/lab/samples/..."). */
export function mediaUrl(u) {
  if (!u) return u;
  return /^https?:/.test(u) ? u : API_ORIGIN + u;
}

/** FastAPI error body -> one readable sentence. */
export function errorMessage(data, status) {
  let msg = data?.detail;
  if (Array.isArray(msg)) msg = msg.map((d) => `${d.loc?.slice(-1)[0] ?? "field"}: ${d.msg}`).join("; ");
  return msg || `Request failed (${status}).`;
}

export const isAbort = (e) => e?.name === "AbortError";

/** Trades the refresh token for a new pair. Concurrent 401s share one call:
 *  the refresh token rotates, so a second call with the old one would fail. */
function renewSession() {
  if (!refreshing) {
    const presented = refreshToken;
    refreshing = fetch(`${API_BASE}/auth/refresh`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ refresh_token: presented }),
    })
      .then(async (res) => {
        if (!res.ok) return false;
        const data = await res.json();
        setTokens(data.access_token, data.refresh_token);
        tokensHandler?.(data);
        return true;
      })
      .catch(() => false)
      .finally(() => {
        refreshing = null;
      });
  }
  return refreshing;
}

/** `makeInit()` builds the fetch options with the current token, so a request
 *  that hit an expired access token can be replayed once after a refresh. */
async function send(url, makeInit, retry = true) {
  let res;
  try {
    res = await fetch(url, makeInit());
  } catch (e) {
    if (isAbort(e)) throw e;
    throw new ApiError("Can't reach the server. Check that the backend is running.", 0);
  }
  if (res.status === 401 && token && retry) {
    if (refreshToken && (await renewSession())) return send(url, makeInit, false);
    unauthorizedHandler?.();
  }
  if (res.status === 204) return null;
  const data = await res.json().catch(() => null);
  if (!res.ok) throw new ApiError(errorMessage(data, res.status), res.status);
  return data;
}

function authHeaders() {
  return token ? { Authorization: `Bearer ${token}` } : {};
}

/** JSON request. `path` is relative to /api, e.g. "/projects". Falsy params are left out. */
export async function api(path, { method = "GET", body, params, signal } = {}) {
  let url = API_BASE + path;
  if (params) {
    const sp = new URLSearchParams();
    for (const [k, v] of Object.entries(params)) {
      if (v !== undefined && v !== null && v !== "" && v !== false) sp.set(k, v);
    }
    const s = sp.toString();
    if (s) url += `?${s}`;
  }
  const json = body !== undefined ? JSON.stringify(body) : undefined;
  return send(url, () => ({
    method,
    signal,
    body: json,
    headers: { ...authHeaders(), ...(json !== undefined ? { "Content-Type": "application/json" } : {}) },
  }));
}

/** Multipart POST (uploads). The browser sets the multipart Content-Type. */
export async function apiForm(path, formData) {
  return send(API_BASE + path, () => ({ method: "POST", headers: authHeaders(), body: formData }));
}

/** GET outside the /api prefix, for routes FastAPI mounts on the app root (/health). */
export async function rootGet(path, { signal } = {}) {
  return send(API_ORIGIN + path, () => ({ signal }));
}
