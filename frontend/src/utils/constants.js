// Mirrors the backend's enums. The CHECK constraints in database/schema.sql
// are the final authority (user_project.status, inference_run.status).

export const STATUSES = [
  ["idea", "Idea"],
  ["planned", "Planned"],
  ["building", "Building"],
  ["done", "Done"],
];
export const STATUS_LABEL = Object.fromEntries(STATUSES);
export const STATUS_COLOR = { planned: "var(--accent)", building: "var(--build)", done: "var(--done)", idea: "var(--line)" };

export const LEVELS = { 1: "Beginner", 2: "Intermediate", 3: "Advanced" };

// Same codes as SUPPORT_LEVELS in backend/app/services/lab_service.py.
export const SUPPORT_LABEL = {
  ready: "Ready",
  zero_shot: "Zero-shot",
  rules: "Model + rules",
  classical: "Classical CV",
  baseline: "Baseline",
  custom_model: "Bring your model",
};
// Catalog filter order.
export const SUPPORT_FILTERS = [["", "Any"], ["ready", "Ready"], ["classical", "Classical CV"], ["zero_shot", "Zero-shot"],
  ["rules", "Model + rules"], ["baseline", "Baseline"], ["custom_model", "Bring your model"]];

export const RUN_ACTIVE = new Set(["queued", "running"]);
export const isRunActive = (run) => Boolean(run) && RUN_ACTIVE.has(run.status);

// Lab polling intervals.
export const RUN_POLL_MS = 700;
export const RUN_PAGE_POLL_MS = 800;
export const MODEL_DOWNLOAD_POLL_MS = 2000;
