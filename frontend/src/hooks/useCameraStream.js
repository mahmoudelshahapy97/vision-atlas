import { useEffect, useRef, useState } from "react";
import { socketUrl } from "../api/client";
import { cameras } from "../api/endpoints";

const RECONNECT_DELAY_MS = 2000;

/**
 * Live annotated frames for one camera over the API's WebSocket
 * (/api/ws/cameras/<id>, see backend/app/api/routes/camera_router.py).
 * Ported from LPR's hook, plus the short-lived token the socket needs
 * (browsers can't send an Authorization header when opening one): a fresh
 * one is minted for every (re)connect.
 *
 * Per frame the server sends a JSON header {type: "frame", width, height, fps,
 * metrics, at} and then the JPEG as one binary message; they are paired by
 * arrival order. With nothing new for a few seconds it sends
 * {type: "status", state, error} instead (stopped, reconnecting, error).
 *
 * Returns { imageSrc, connected, state, error, frame }. imageSrc is an object
 * URL; the previous one is revoked only after the next is on screen.
 */
export function useCameraStream(cameraId, { enabled = true } = {}) {
  const [imageSrc, setImageSrc] = useState(null);
  const [connected, setConnected] = useState(false);
  const [state, setState] = useState(null);
  const [error, setError] = useState(null);
  const [frame, setFrame] = useState(null);
  const urlRef = useRef(null);
  const headerRef = useRef(null);

  useEffect(() => {
    setImageSrc(null);
    setConnected(false);
    setState(null);
    setError(null);
    setFrame(null);
    headerRef.current = null;
    if (urlRef.current) {
      URL.revokeObjectURL(urlRef.current);
      urlRef.current = null;
    }
    if (!enabled || !cameraId) return undefined;

    let alive = true;
    let ws = null;
    let timer = null;

    const retry = () => {
      if (alive) timer = setTimeout(connect, RECONNECT_DELAY_MS);
    };

    async function connect() {
      if (!alive) return;
      let tok;
      try {
        tok = await cameras.liveToken(cameraId);
      } catch (e) {
        if (!alive) return;
        setError(e.status === 404 || e.status === 403 ? "You can't watch this camera." : e.message);
        if (e.status !== 404 && e.status !== 403) retry();
        return;
      }
      if (!alive) return;
      ws = new WebSocket(socketUrl(`${tok.url}?token=${encodeURIComponent(tok.token)}`));
      ws.binaryType = "blob";
      ws.onopen = () => {
        if (!alive) return;
        setConnected(true);
        setError(null);
      };
      ws.onmessage = (event) => {
        if (!alive) return;
        if (typeof event.data === "string") {
          let msg;
          try {
            msg = JSON.parse(event.data);
          } catch {
            return;
          }
          if (msg.type === "frame") {
            headerRef.current = msg;
          } else {
            headerRef.current = null;
            setState(msg.state || null);
            setError(msg.error || null);
          }
          return;
        }
        const header = headerRef.current;
        headerRef.current = null;
        if (!header) return;
        const next = URL.createObjectURL(event.data instanceof Blob ? event.data : new Blob([event.data], { type: "image/jpeg" }));
        const prev = urlRef.current;
        urlRef.current = next;
        setImageSrc(next);
        setFrame(header);
        setState("running");
        setError(null);
        if (prev) URL.revokeObjectURL(prev);
      };
      ws.onclose = (event) => {
        if (!alive) return;
        setConnected(false);
        if (event.code === 4403) {
          setError("You can't watch this camera.");
          return;
        }
        retry();
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
      if (urlRef.current) {
        URL.revokeObjectURL(urlRef.current);
        urlRef.current = null;
      }
    };
  }, [cameraId, enabled]);

  return { imageSrc, connected, state, error, frame };
}

export default useCameraStream;
