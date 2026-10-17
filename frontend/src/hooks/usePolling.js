import { useCallback, useEffect, useRef, useState } from "react";
import { isAbort } from "../api/client";

/**
 * Loads `fetcher({ signal })`, then again every `intervalMs` while `keepPolling(data)` is true.
 * Returns { data, error, loading, reload, setData }.
 *
 * - The next request is scheduled after the previous response, so slow responses never pile up.
 * - Nothing is fetched while `enabled` is false; changing `deps` starts over.
 * - An error stops the loop (shown through `error`) until reload() or a deps change.
 * - While the tab is hidden the request is skipped but the loop stays alive.
 */
export function usePolling(fetcher, { intervalMs = 5000, enabled = true, deps = [], keepPolling = () => true } = {}) {
  const [state, setState] = useState({ data: null, error: null, loading: enabled });
  const [tick, setTick] = useState(0);
  const fetcherRef = useRef(fetcher);
  const keepRef = useRef(keepPolling);
  fetcherRef.current = fetcher;
  keepRef.current = keepPolling;

  useEffect(() => {
    if (!enabled) {
      setState((s) => ({ ...s, loading: false }));
      return undefined;
    }
    const ctrl = new AbortController();
    let timer;
    const schedule = () => {
      timer = setTimeout(run, intervalMs);
    };
    const run = async () => {
      if (document.hidden) return schedule();
      try {
        const data = await fetcherRef.current({ signal: ctrl.signal });
        if (ctrl.signal.aborted) return;
        setState({ data, error: null, loading: false });
        if (keepRef.current(data)) schedule();
      } catch (error) {
        if (ctrl.signal.aborted || isAbort(error)) return;
        setState((s) => ({ data: s.data, error, loading: false }));
      }
    };
    setState((s) => ({ ...s, loading: true, error: null }));
    run();
    return () => {
      ctrl.abort();
      clearTimeout(timer);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [enabled, intervalMs, tick, ...deps]);

  const reload = useCallback(() => setTick((t) => t + 1), []);
  const setData = useCallback((data) => setState((s) => ({ ...s, data })), []);
  return { ...state, reload, setData };
}

export default usePolling;
