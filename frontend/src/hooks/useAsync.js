import { useCallback, useEffect, useRef, useState } from "react";
import { isAbort } from "../api/client";

/**
 * Runs `loader({ signal })` whenever deps change and returns { data, error, loading, reload, setData }.
 * Keeps the previous data while reloading, and aborts the previous request when deps change
 * or the component unmounts.
 */
export function useAsync(loader, deps = []) {
  const [state, setState] = useState({ data: null, error: null, loading: true });
  const [tick, setTick] = useState(0);
  const loaderRef = useRef(loader);
  loaderRef.current = loader;

  useEffect(() => {
    const ctrl = new AbortController();
    setState((s) => ({ ...s, loading: true, error: null }));
    Promise.resolve(loaderRef.current({ signal: ctrl.signal }))
      .then((data) => !ctrl.signal.aborted && setState({ data, error: null, loading: false }))
      .catch((error) => {
        if (ctrl.signal.aborted || isAbort(error)) return;
        setState((s) => ({ data: s.data, error, loading: false }));
      });
    return () => ctrl.abort();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [...deps, tick]);

  const reload = useCallback(() => setTick((t) => t + 1), []);
  const setData = useCallback((data) => setState((s) => ({ ...s, data })), []);
  return { ...state, reload, setData };
}

export default useAsync;
