// Mirrors the backend's enums. The CHECK constraints in database/schema.sql
// are the final authority (user_project.status, inference_run.status).

export const STATUSES = [
  ["idea", "Idea"],
  ["planned", "Planned"],
  ["building", "Building"],
  ["done", "Done"],
];
export const STATUS_LABEL = Object.fromEntries(STATUSES);
// MUI palette keys ("default" is the neutral outlined chip).
export const STATUS_COLOR = { idea: "default", planned: "primary", building: "warning", done: "success" };

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
export const SUPPORT_COLOR = {
  ready: "success",
  zero_shot: "secondary",
  rules: "primary",
  classical: "info",
  baseline: "warning",
  custom_model: "error",
};
// Catalog filter order.
export const SUPPORT_FILTERS = [["", "Any"], ["ready", "Ready"], ["classical", "Classical CV"], ["zero_shot", "Zero-shot"],
  ["rules", "Model + rules"], ["baseline", "Baseline"], ["custom_model", "Bring your model"]];

export const RUN_ACTIVE = new Set(["queued", "running"]);
export const RUN_STATUS_COLOR = { queued: "default", running: "warning", done: "success", error: "error" };
export const isRunActive = (run) => Boolean(run) && RUN_ACTIVE.has(run.status);

// Lab polling intervals.
export const RUN_POLL_MS = 700;
export const RUN_PAGE_POLL_MS = 800;
// The run history re-polls only while one of its runs is queued or running.
export const RUN_LIST_POLL_MS = 3000;
export const MODEL_DOWNLOAD_POLL_MS = 2000;
