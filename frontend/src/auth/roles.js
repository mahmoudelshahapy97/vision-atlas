// Mirrors ROLE_LEVEL in backend/app/api/deps.py: a single ladder, so
// "requires user" also admits admin. The backend is the authority; this only
// decides what the console shows.

export const ROLE_LEVEL = { user: 1, admin: 2 };
export const ROLES = Object.keys(ROLE_LEVEL);

export function hasRole(user, minimum) {
  if (!user) return false;
  return (ROLE_LEVEL[user.role] || 0) >= ROLE_LEVEL[minimum];
}

// Mirrors WS_ROLE_LEVEL in backend/app/services/workspace_service.py. A
// system admin acts as workspace admin everywhere (the API says so in my_role).
export const WS_ROLE_LEVEL = { viewer: 1, operator: 2, admin: 3 };
export const WS_ROLES = Object.keys(WS_ROLE_LEVEL);

export function hasWsRole(role, minimum) {
  return (WS_ROLE_LEVEL[role] || 0) >= WS_ROLE_LEVEL[minimum];
}
