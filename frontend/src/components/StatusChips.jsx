// Small status markers: project status, level, top pick, progress, lab support, run status.

import { STATUS_COLOR, STATUS_LABEL, SUPPORT_LABEL } from "../utils/constants";

export function LevelBars({ level }) {
  return (
    <span className="lvl" data-l={level} aria-hidden="true">
      <i></i><i></i><i></i>
    </span>
  );
}

export function StatusPill({ status = "idea" }) {
  return <span className={`pill ${status}`}>{STATUS_LABEL[status]}</span>;
}

export function RunStatusPill({ status }) {
  return <span className={`pill ${status === "done" ? "done" : status === "error" ? "err" : "building"}`}>{status}</span>;
}

export function Star() {
  return (
    <svg width="12" height="12" viewBox="0 0 24 24" fill="currentColor" aria-hidden="true">
      <path d="M12 2.5l2.9 6.1 6.6.8-4.9 4.6 1.3 6.6L12 17.3l-5.9 3.3 1.3-6.6L2.5 9.4l6.6-.8z" />
    </svg>
  );
}

export function ProgressBar({ counts, total, label }) {
  return (
    <div className="bar" role="img" aria-label={label}>
      {["done", "building", "planned"].map((k) =>
        counts[k] ? <i key={k} style={{ width: `${(counts[k] / total) * 100}%`, background: STATUS_COLOR[k] }} /> : null
      )}
    </div>
  );
}

const SUPPORT_ICON = {
  ready: "M5 12l5 5L20 7",
  zero_shot: "M4 12h4l3-8 4 16 3-8h2",
  rules: "M4 6h16M4 12h10M4 18h6",
  classical: "M12 3v18M3 12h18",
  baseline: "M4 18h16M7 14l3-3 3 2 4-5",
  custom_model: "M12 4v12M6 10l6 6 6-6M4 20h16",
};

/** Lab readiness. `level` is a support-level object from the API or just its code. */
export function SupportBadge({ level, compact = false }) {
  if (!level) return null;
  const code = level.code || level;
  const label = level.label || SUPPORT_LABEL[code];
  return (
    <span className={`support s-${code} ${compact ? "compact" : ""}`} title={level.description || label}>
      <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"><path d={SUPPORT_ICON[code]} /></svg>
      {label}
    </span>
  );
}
