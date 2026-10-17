import { useState } from "react";
import { Link, Navigate, useNavigate, useSearchParams } from "react-router-dom";
import { useAuth } from "../auth/AuthContext";
import { useToast } from "../components/Toast";

/** Sign in and register (mode), shown inside AuthLayout. */
export default function Login({ mode }) {
  const { user, login, register } = useAuth();
  const [sp] = useSearchParams();
  const navigate = useNavigate();
  const toast = useToast();
  const next = sp.get("next")?.startsWith("/") ? sp.get("next") : "/";
  const [form, setForm] = useState({ name: "", email: "", password: "" });
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const isLogin = mode === "login";

  if (user) return <Navigate to={next} replace />;

  const set = (k) => (e) => setForm({ ...form, [k]: e.target.value });

  async function submit(e) {
    e.preventDefault();
    setError("");
    setBusy(true);
    try {
      const u = isLogin ? await login(form.email, form.password) : await register(form.name, form.email, form.password);
      toast(isLogin ? `Welcome back, ${u.name}.` : `Account created. Welcome, ${u.name}.`);
      navigate(next, { replace: true });
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  }

  const other = `${isLogin ? "/register" : "/login"}${next !== "/" ? `?next=${encodeURIComponent(next)}` : ""}`;

  return (
    <form className="panel form" onSubmit={submit} noValidate={false}>
      <h1 className="page-title">{isLogin ? "Sign in" : "Create your account"}</h1>
      <p className="muted">{isLogin ? "Pick up where you left off on your projects." : "Track project status and keep notes for each of the 90 projects."}</p>
      {!isLogin && (
        <label className="field" htmlFor="name">
          <span>Name</span>
          <input id="name" required maxLength={120} value={form.name} onChange={set("name")} autoComplete="name" />
        </label>
      )}
      <label className="field" htmlFor="email">
        <span>Email</span>
        <input id="email" type="email" required value={form.email} onChange={set("email")} autoComplete="email" />
      </label>
      <label className="field" htmlFor="password">
        <span>Password</span>
        <input id="password" type="password" required minLength={isLogin ? 1 : 8} value={form.password}
          onChange={set("password")} autoComplete={isLogin ? "current-password" : "new-password"} />
        {!isLogin && <small className="muted">At least 8 characters.</small>}
      </label>
      {error && <div className="errnote" role="alert">{error}</div>}
      <button className="btn primary" disabled={busy}>{busy ? "Please wait…" : isLogin ? "Sign in" : "Create account"}</button>
      <p className="small muted">
        {isLogin ? "New here? " : "Already have an account? "}
        <Link to={other}>{isLogin ? "Create an account" : "Sign in"}</Link>
      </p>
    </form>
  );
}
