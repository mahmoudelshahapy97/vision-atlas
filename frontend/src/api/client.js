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
let unauthorizedHandler = null;

export function setToken(t) {
  token = t;
}

/** Called when a request made with a token comes back 401 (expired or revoked session).
 *  Kept as a callback so the API layer doesn't import the auth context. */
export function onUnauthorized(fn) {
  unauthorizedHandler = fn;
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

async function send(url, init) {
  let res;
  try {
    res = await fetch(url, init);
  } catch (e) {
    if (isAbort(e)) throw e;
    throw new ApiError("Can't reach the server. Check that the backend is running.", 0);
  }
  if (res.status === 204) return null;
  const data = await res.json().catch(() => null);
  if (!res.ok) {
    if (res.status === 401 && token && unauthorizedHandler) unauthorizedHandler();
    throw new ApiError(errorMessage(data, res.status), res.status);
  }
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
  const headers = authHeaders();
  if (body !== undefined) headers["Content-Type"] = "application/json";
  return send(url, { method, headers, signal, body: body !== undefined ? JSON.stringify(body) : undefined });
}

/** Multipart POST (uploads). The browser sets the multipart Content-Type. */
export async function apiForm(path, formData) {
  return send(API_BASE + path, { method: "POST", headers: authHeaders(), body: formData });
}
