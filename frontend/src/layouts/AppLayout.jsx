import { Link, NavLink, Outlet } from "react-router-dom";
import { useAuth } from "../auth/AuthContext";
import ThemeToggle from "../components/ThemeToggle";

// `minimum` is a role from auth/roles.js; items without one are public.
const NAV_ITEMS = [
  { to: "/", label: "Catalog", end: true },
  { to: "/board", label: "My board", minimum: "user" },
  { to: "/runs", label: "My runs", minimum: "user" },
  { to: "/models", label: "Models" },
  { to: "/admin", label: "Admin", minimum: "admin" },
];

function Brand() {
  return (
    <Link to="/" className="brandmark" aria-label="Vision Project Atlas home">
      <svg width="22" height="22" viewBox="0 0 32 32" aria-hidden="true">
        <path d="M3 10V3h7M22 3h7v7M29 22v7h-7M10 29H3v-7" fill="none" stroke="var(--box)" strokeWidth="3" />
        <circle cx="16" cy="16" r="5" fill="var(--accent)" />
      </svg>
      <span>Vision Atlas</span>
    </Link>
  );
}

/** Top navigation shared by every page, then the routed page. */
export default function AppLayout() {
  const { user, logout, hasRole } = useAuth();
  return (
    <>
      <nav className="topnav">
        <div className="topnav-inner">
          <Brand />
          <div className="navlinks">
            {NAV_ITEMS.filter((item) => !item.minimum || hasRole(item.minimum)).map((item) => (
              <NavLink key={item.to} to={item.to} end={item.end}>{item.label}</NavLink>
            ))}
          </div>
          <div className="navright">
            <ThemeToggle />
            {user ? (
              <>
                <span className="who" title={user.email}>{user.name}</span>
                <button className="btn ghost sm" onClick={logout}>Sign out</button>
              </>
            ) : (
              <>
                <Link className="btn ghost sm" to="/login">Sign in</Link>
                <Link className="btn primary sm hide-sm" to="/register">Create account</Link>
              </>
            )}
          </div>
        </div>
      </nav>
      <Outlet />
    </>
  );
}
