// Loading, error and empty states, so every page shows them the same way.

export function Loading({ label = "Loading…" }) {
  return <div className="boot">{label}</div>;
}

export function ErrorNote({ error, onRetry }) {
  if (!error) return null;
  return (
    <div className="errnote" role="alert">
      <span>{error.message}</span>
      {onRetry && <button className="linkbtn" onClick={onRetry}>Try again</button>}
    </div>
  );
}

export function EmptyState({ title, children }) {
  return (
    <div className="empty">
      <strong>{title}</strong>
      {children}
    </div>
  );
}

/** Placeholder cards while the first page of results loads. */
export function SkeletonCards({ count = 6 }) {
  return Array.from({ length: count }, (_, i) => <div key={i} className="card skeleton" aria-hidden="true" />);
}
