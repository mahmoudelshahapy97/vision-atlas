// Display formatting shared across pages.

/** 7 -> "07": project numbers are always two digits. */
export const pad = (n) => String(n).padStart(2, "0");

export const formatDate = (value) => (value ? new Date(value).toLocaleDateString() : "—");
export const formatDateTime = (value) => (value ? new Date(value).toLocaleString() : "—");

/** 1234 -> "1.2 s" */
export const formatDurationMs = (ms) => (ms ? `${(ms / 1000).toFixed(1)} s` : "…");

/** bytes -> "12.3 MB" */
export const formatMegabytes = (bytes) => `${(bytes / 1048576).toFixed(1)} MB`;
