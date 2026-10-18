// One namespace per backend router (backend/app/api/routes/*_router.py), one
// function per route. Pages call these instead of building paths themselves.
// `opts` carries { signal } from useAsync / usePolling.

import { api, apiBlob, apiForm, rootGet } from "./client";

// /health is mounted on the app root, outside the /api prefix.
export const health = {
  live: (opts) => rootGet("/health", opts),
};

export const auth = {
  me: (opts) => api("/auth/me", opts),
  login: (email, password) => api("/auth/login", { method: "POST", body: { email, password } }),
  register: (name, email, password) => api("/auth/register", { method: "POST", body: { name, email, password } }),
  logout: (refreshToken) => api("/auth/logout", { method: "POST", body: { refresh_token: refreshToken } }),
  logoutAll: () => api("/auth/logout-all", { method: "POST" }),
  changePassword: (currentPassword, newPassword) =>
    api("/auth/change-password", {
      method: "POST",
      body: { current_password: currentPassword, new_password: newPassword },
    }),
};

export const users = {
  list: (params, opts) => api("/users", { params, ...opts }),
  get: (id, opts) => api(`/users/${id}`, opts),
  create: (payload) => api("/users", { method: "POST", body: payload }),
  update: (id, payload) => api(`/users/${id}`, { method: "PATCH", body: payload }),
  resetPassword: (id, newPassword) =>
    api(`/users/${id}/reset-password`, { method: "POST", body: { new_password: newPassword } }),
  remove: (id) => api(`/users/${id}`, { method: "DELETE" }),
};

export const workspaces = {
  mine: (opts) => api("/workspaces/mine", opts),
  livePipelines: (opts) => api("/workspaces/pipelines", opts),
  list: (opts) => api("/workspaces", opts),
  get: (id, opts) => api(`/workspaces/${id}`, opts),
  create: (payload) => api("/workspaces", { method: "POST", body: payload }),
  update: (id, payload) => api(`/workspaces/${id}`, { method: "PATCH", body: payload }),
  remove: (id) => api(`/workspaces/${id}`, { method: "DELETE" }),
  members: (id, opts) => api(`/workspaces/${id}/members`, opts),
  addMember: (id, email, role) => api(`/workspaces/${id}/members`, { method: "POST", body: { email, role } }),
  setMemberRole: (id, userId, role) => api(`/workspaces/${id}/members/${userId}`, { method: "PATCH", body: { role } }),
  removeMember: (id, userId) => api(`/workspaces/${id}/members/${userId}`, { method: "DELETE" }),
};

/** Workspace-scoped: the client sends the active workspace (X-Workspace-Id). */
export const cameras = {
  pipelines: (opts) => api("/cameras/pipelines", opts),
  list: (opts) => api("/cameras", opts),
  get: (id, opts) => api(`/cameras/${id}`, opts),
  create: (payload) => api("/cameras", { method: "POST", body: payload }),
  update: (id, payload) => api(`/cameras/${id}`, { method: "PATCH", body: payload }),
  remove: (id) => api(`/cameras/${id}`, { method: "DELETE" }),
  start: (id) => api(`/cameras/${id}/start`, { method: "POST" }),
  stop: (id) => api(`/cameras/${id}/stop`, { method: "POST" }),
  liveToken: (id) => api(`/cameras/${id}/live-token`, { method: "POST" }),
  /** JPEG Blobs */
  snapshot: (id, annotated = false, opts) => apiBlob(`/cameras/${id}/snapshot${annotated ? "?annotated=true" : ""}`, opts),
  preview: (sourceUrl) => apiBlob("/cameras/preview", { method: "POST", body: { source_url: sourceUrl } }),
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
  /** FormData: file (.pt), name, is_public, workspace_id (optional). */
  upload: (formData) => apiForm("/models/upload", formData),
  remove: (id) => api(`/models/custom/${id}`, { method: "DELETE" }),
};

export default { health, auth, users, workspaces, cameras, catalog, projects, progress, me, lab, runs, models };
