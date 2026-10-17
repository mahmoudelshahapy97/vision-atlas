// The access token in localStorage. Storage can be blocked (private mode,
// strict settings); then the session simply lasts until the page reloads.

const KEY = "atlas.token";

export function getToken() {
  try {
    return localStorage.getItem(KEY);
  } catch {
    return null;
  }
}

export function storeToken(token) {
  try {
    if (token) localStorage.setItem(KEY, token);
    else localStorage.removeItem(KEY);
  } catch {
    /* storage blocked: session lasts until reload */
  }
}
