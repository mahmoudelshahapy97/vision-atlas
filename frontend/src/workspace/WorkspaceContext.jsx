import { createContext, useCallback, useContext, useEffect, useMemo, useState } from "react";
import { setWorkspace } from "../api/client";
import { workspaces as workspacesApi } from "../api/endpoints";
import { useAuth } from "../auth/AuthContext";
import { hasWsRole } from "../auth/roles";

const KEY = "atlas:workspace";
const WorkspaceCtx = createContext(null);

function readStored() {
  try {
    const v = Number(localStorage.getItem(KEY));
    return Number.isInteger(v) && v > 0 ? v : null;
  } catch {
    return null;
  }
}

/**
 * The signed-in user's workspaces and the active one. The active id is sent
 * with every API call (X-Workspace-Id) and remembered per browser. Pages that
 * show workspace data put `active?.id` in their fetch deps so switching
 * reloads them.
 */
export function WorkspaceProvider({ children }) {
  const { user } = useAuth();
  const [list, setList] = useState(null);
  const [error, setError] = useState(null);
  const [chosenId, setChosenId] = useState(readStored);

  const reload = useCallback(async () => {
    if (!user) {
      setList([]);
      return;
    }
    try {
      setList(await workspacesApi.mine());
      setError(null);
    } catch (e) {
      setError(e);
      setList((l) => l || []);
    }
  }, [user]);

  useEffect(() => {
    setList(null);
    reload();
  }, [reload]);

  const active = useMemo(
    () => (list || []).find((w) => w.id === chosenId) || (list || [])[0] || null,
    [list, chosenId]
  );

  // Set during render, not in an effect: children fetch in their own effects,
  // which run before this provider's, and must already send the header.
  setWorkspace(active?.id ?? null);

  const setActive = useCallback((id) => {
    setChosenId(id);
    try {
      localStorage.setItem(KEY, String(id));
    } catch {
      /* storage blocked: the choice lasts until reload */
    }
  }, []);

  const value = useMemo(
    () => ({
      workspaces: list || [],
      ready: list !== null,
      error,
      active,
      role: active?.my_role || null,
      setActive,
      reload,
      hasWsRole: (minimum) => Boolean(active) && hasWsRole(active.my_role, minimum),
    }),
    [list, error, active, setActive, reload]
  );
  return <WorkspaceCtx.Provider value={value}>{children}</WorkspaceCtx.Provider>;
}

export function useWorkspace() {
  const ctx = useContext(WorkspaceCtx);
  if (!ctx) throw new Error("useWorkspace must be used inside <WorkspaceProvider>.");
  return ctx;
}
