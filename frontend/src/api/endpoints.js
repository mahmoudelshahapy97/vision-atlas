// One namespace per backend router (backend/app/api/routes/*_router.py), one
// function per route. Pages call these instead of building paths themselves.
// `opts` carries { signal } from useAsync / usePolling.

import { api, apiForm } from "./client";

export const auth = {
  me: (opts) => api("/auth/me", opts),
  login: (email, password) => api("/auth/login", { method: "POST", body: { email, password } }),
  register: (name, email, password) => api("/auth/register", { method: "POST", body: { name, email, password } }),
};

export const catalog = {
  domains: (opts) => api("/domains", opts),
  taskTypes: (opts) => api("/task-types", opts),
  technologies: (limit, opts) => api("/technologies", { params: { limit }, ...opts }),
};

export const projects = {
  list: (params, opts) => api("/projects", { params, ...opts }),
  facets: (params, opts) => api("/projects/facets", { params, ...opts }),
  get: (id, opts) => api(`/projects/${id}`, opts),
  create: (payload) => api("/projects", { method: "POST", body: payload }),
  update: (id, payload) => api(`/projects/${id}`, { method: "PATCH", body: payload }),
  remove: (id) => api(`/projects/${id}`, { method: "DELETE" }),
};

export const progress = {
  set: (projectId, payload) => api(`/projects/${projectId}/progress`, { method: "PUT", body: payload }),
  reset: (projectId) => api(`/projects/${projectId}/progress`, { method: "DELETE" }),
};

export const me = {
  progress: (opts) => api("/me/progress", opts),
  stats: (opts) => api("/me/stats", opts),
};

export const lab = {
  pipelines: (opts) => api("/lab/pipelines", opts),
  supportLevels: (opts) => api("/lab/support-levels", opts),
  forProject: (projectId, opts) => api(`/projects/${projectId}/lab`, opts),
};

export const runs = {
  list: (params, opts) => api("/runs", { params, ...opts }),
  get: (publicId, opts) => api(`/runs/${publicId}`, opts),
  /** FormData: project_id, pipeline, params (JSON), samples (JSON), one file field per input slot. */
  create: (formData) => apiForm("/runs", formData),
  remove: (publicId) => api(`/runs/${publicId}`, { method: "DELETE" }),
};

export const models = {
  list: (opts) => api("/models", opts),
  download: (key) => api(`/models/${key}/download`, { method: "POST" }),
  /** FormData: file (.pt), name, is_public. */
  upload: (formData) => apiForm("/models/upload", formData),
  remove: (id) => api(`/models/custom/${id}`, { method: "DELETE" }),
};

export default { auth, catalog, projects, progress, me, lab, runs, models };
