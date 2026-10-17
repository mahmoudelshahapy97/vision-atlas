// Mirrors ROLE_LEVEL in backend/app/api/deps.py: a single ladder, so
// "requires user" also admits admin. The backend is the authority; this only
// decides what the console shows.

export const ROLE_LEVEL = { user: 1, admin: 2 };
export const ROLES = Object.keys(ROLE_LEVEL);

export function hasRole(user, minimum) {
  if (!user) return false;
  return (ROLE_LEVEL[user.role] || 0) >= ROLE_LEVEL[minimum];
}
