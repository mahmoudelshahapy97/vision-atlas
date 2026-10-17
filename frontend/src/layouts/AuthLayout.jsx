import { Outlet } from "react-router-dom";

/** Narrow centred column for the sign-in and register forms. */
export default function AuthLayout() {
  return (
    <div className="wrap narrow">
      <Outlet />
    </div>
  );
}
