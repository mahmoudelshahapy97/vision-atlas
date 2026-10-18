import { createContext, useContext, useEffect, useMemo, useRef, useState } from "react";
import { socketUrl } from "../api/client";
import { events as eventsApi } from "../api/endpoints";
import { useAuth } from "../auth/AuthContext";
import { kindLabel } from "../components/events/EventBits";
import { useToast } from "../components/Toast";
import { useWorkspace } from "../workspace/WorkspaceContext";

const AlertsCtx = createContext({ recent: [], version: 0, connected: false });
const MAX_RECENT = 30;
const TOAST_GAP_MS = 5000; // a busy zone raises an event every few seconds; toast each camera+kind at most this often

/**
 * One app-wide WebSocket per active workspace (/api/ws/alerts/<id>, ported
 * from no-entry-zone's useAlerts): a toast for each new warning or critical
 * event, and { recent, version } for pages that show events. `version`
 * changes on every message, so a page can put it in its fetch deps and
 * refresh. Reconnects with backoff; a fresh token is minted each time.
 */
export function AlertsProvider({ children }) {
  const { user } = useAuth();
  const { active } = useWorkspace();
  const toast = useToast();
  const toastRef = useRef(toast);
  toastRef.current = toast;
  const [recent, setRecent] = useState([]);
  const [version, setVersion] = useState(0);
  const [connected, setConnected] = useState(false);
  const wid = user && active?.is_active ? active.id : null;

  useEffect(() => {
    setRecent([]);
    setConnected(false);
    if (!wid) return undefined;
    let alive = true;
    let ws = null;
    let timer = null;
    let attempt = 0;
    const lastToast = new Map();

    const retry = () => {
      if (!alive) return;
      attempt += 1;
      timer = setTimeout(connect, Math.min(30000, 1000 * 2 ** Math.min(attempt, 5)));
    };

    async function connect() {
      if (!alive) return;
      let tok;
      try {
        tok = await eventsApi.alertsToken();
      } catch (e) {
        if (e.status !== 403 && e.status !== 404) retry();
        return;
      }
      if (!alive) return;
      ws = new WebSocket(socketUrl(`${tok.url}?token=${encodeURIComponent(tok.token)}`));
      ws.onopen = () => {
        attempt = 0;
        if (alive) setConnected(true);
      };
      ws.onmessage = (m) => {
        if (!alive) return;
        let msg;
        try {
          msg = JSON.parse(m.data);
        } catch {
          return;
        }
        if (msg.type === "event") {
          const ev = msg.event;
          setRecent((r) => [ev, ...r].slice(0, MAX_RECENT));
          setVersion((v) => v + 1);
          const k = `${ev.camera_id}:${ev.kind}`;
          if (ev.severity !== "info" && Date.now() - (lastToast.get(k) || 0) > TOAST_GAP_MS) {
            lastToast.set(k, Date.now());
            toastRef.current(`${kindLabel(ev.kind)}: ${ev.label} at ${ev.camera_name}`, ev.severity === "critical" ? "error" : "warning");
          }
        } else if (msg.type === "status") {
          setRecent((r) => r.map((e) => (e.id === msg.id ? { ...e, status: msg.status } : e)));
          setVersion((v) => v + 1);
        }
      };
      ws.onclose = (e) => {
        if (!alive) return;
        setConnected(false);
        if (e.code !== 4403) retry();
      };
    }

    connect();
    return () => {
      alive = false;
      clearTimeout(timer);
      if (ws) {
        ws.onopen = ws.onmessage = ws.onclose = null;
        ws.close();
      }
    };
  }, [wid]);

  const value = useMemo(() => ({ recent, version, connected }), [recent, version, connected]);
  return <AlertsCtx.Provider value={value}>{children}</AlertsCtx.Provider>;
}

export const useAlerts = () => useContext(AlertsCtx);
