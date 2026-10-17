import { Navigate, useLocation } from "react-router-dom";
import { useAuth } from "../auth/AuthContext";

/** Signed-out visitors go to /login and come back afterwards; a missing role goes home. */
export default function RequireAuth({ minimum = "user", children }) {
  const { user, hasRole } = useAuth();
  const loc = useLocation();
  if (!user) return <Navigate to={`/login?next=${encodeURIComponent(loc.pathname)}`} replace />;
  if (!hasRole(minimum)) return <Navigate to="/" replace />;
  return children;
}
