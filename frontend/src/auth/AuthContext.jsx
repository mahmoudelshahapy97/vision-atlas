import { createContext, useCallback, useContext, useEffect, useMemo, useState } from "react";
import { getRefreshToken, onTokens, onUnauthorized, setTokens } from "../api/client";
import { auth as authApi } from "../api/endpoints";
import { hasRole } from "./roles";
import { getTokens, storeTokens } from "./tokenStore";

const AuthCtx = createContext(null);

export function AuthProvider({ children }) {
  const [user, setUser] = useState(null);
  const [ready, setReady] = useState(false);

  /** A token response from login/register/refresh/change-password, or null to sign out. */
  const store = useCallback((r) => {
    storeTokens(r?.access_token ?? null, r?.refresh_token ?? null);
    setTokens(r?.access_token ?? null, r?.refresh_token ?? null);
    setUser(r?.user ?? null);
  }, []);

  const clear = useCallback(() => store(null), [store]);

  useEffect(() => {
    onUnauthorized(clear);
    onTokens(store);
    const { access, refresh } = getTokens();
    if (!access) {
      setReady(true);
      return;
    }
    setTokens(access, refresh);
    // An expired access token is renewed by the client on the 401.
    authApi
      .me()
      .then(setUser)
      .catch(clear)
      .finally(() => setReady(true));
  }, [clear, store]);

  const login = useCallback(
    async (email, password) => {
      const r = await authApi.login(email, password);
      store(r);
      return r.user;
    },
    [store]
  );

  const register = useCallback(
    async (name, email, password) => {
      const r = await authApi.register(name, email, password);
      store(r);
      return r.user;
    },
    [store]
  );

  /** Ends this session on the server too (best effort), or every session with `everywhere`. */
  const logout = useCallback(
    async ({ everywhere = false } = {}) => {
      const refresh = getRefreshToken();
      try {
        if (everywhere) await authApi.logoutAll();
        else if (refresh) await authApi.logout(refresh);
      } catch {
        /* already signed out server-side, or offline: forget the tokens anyway */
      }
      clear();
    },
    [clear]
  );

  const changePassword = useCallback(
    async (currentPassword, newPassword) => store(await authApi.changePassword(currentPassword, newPassword)),
    [store]
  );

  const value = useMemo(
    () => ({
      user,
      ready,
      login,
      register,
      logout,
      changePassword,
      hasRole: (minimum) => hasRole(user, minimum),
    }),
    [user, ready, login, register, logout, changePassword]
  );
  return <AuthCtx.Provider value={value}>{children}</AuthCtx.Provider>;
}

export function useAuth() {
  const ctx = useContext(AuthCtx);
  if (!ctx) throw new Error("useAuth must be used inside <AuthProvider>.");
  return ctx;
}
