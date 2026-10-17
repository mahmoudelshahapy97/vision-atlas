import { createContext, useCallback, useContext, useEffect, useMemo, useState } from "react";
import { onUnauthorized, setToken } from "../api/client";
import { auth as authApi } from "../api/endpoints";
import { hasRole } from "./roles";
import { getToken, storeToken } from "./tokenStore";

const AuthCtx = createContext(null);

export function AuthProvider({ children }) {
  const [user, setUser] = useState(null);
  const [ready, setReady] = useState(false);

  const store = useCallback((token, u) => {
    storeToken(token);
    setToken(token);
    setUser(u);
  }, []);

  const logout = useCallback(() => store(null, null), [store]);

  useEffect(() => {
    onUnauthorized(logout);
    const token = getToken();
    if (!token) {
      setReady(true);
      return;
    }
    setToken(token);
    authApi
      .me()
      .then(setUser)
      .catch(() => store(null, null))
      .finally(() => setReady(true));
  }, [logout, store]);

  const login = useCallback(
    async (email, password) => {
      const r = await authApi.login(email, password);
      store(r.access_token, r.user);
      return r.user;
    },
    [store]
  );

  const register = useCallback(
    async (name, email, password) => {
      const r = await authApi.register(name, email, password);
      store(r.access_token, r.user);
      return r.user;
    },
    [store]
  );

  const value = useMemo(
    () => ({ user, ready, login, register, logout, hasRole: (minimum) => hasRole(user, minimum) }),
    [user, ready, login, register, logout]
  );
  return <AuthCtx.Provider value={value}>{children}</AuthCtx.Provider>;
}

export function useAuth() {
  const ctx = useContext(AuthCtx);
  if (!ctx) throw new Error("useAuth must be used inside <AuthProvider>.");
  return ctx;
}
