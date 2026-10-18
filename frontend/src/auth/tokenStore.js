// The access and refresh tokens in localStorage. Storage can be blocked
// (private mode, strict settings); then the session simply lasts until the
// page reloads.

const ACCESS = "atlas.token";
const REFRESH = "atlas.refresh";

function read(key) {
  try {
    return localStorage.getItem(key);
  } catch {
    return null;
  }
}

function write(key, value) {
  try {
    if (value) localStorage.setItem(key, value);
    else localStorage.removeItem(key);
  } catch {
    /* storage blocked: session lasts until reload */
  }
}

export function getTokens() {
  return { access: read(ACCESS), refresh: read(REFRESH) };
}

export function storeTokens(access, refresh) {
  write(ACCESS, access);
  write(REFRESH, refresh);
}
