import { useState } from "react";
import { Link as RouterLink, Navigate, useNavigate, useSearchParams } from "react-router-dom";
import Alert from "@mui/material/Alert";
import Button from "@mui/material/Button";
import Link from "@mui/material/Link";
import Stack from "@mui/material/Stack";
import TextField from "@mui/material/TextField";
import Typography from "@mui/material/Typography";
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
    <Stack component="form" onSubmit={submit} spacing={2.5}>
      <div>
        <Typography variant="h6" component="h1">{isLogin ? "Sign in" : "Create your account"}</Typography>
        <Typography variant="body2" color="text.secondary">
          {isLogin ? "Pick up where you left off on your projects." : "Track project status, keep notes and save your lab runs."}
        </Typography>
      </div>
      {error && <Alert severity="error">{error}</Alert>}
      {!isLogin && (
        <TextField label="Name" required inputProps={{ maxLength: 120 }} value={form.name} onChange={set("name")} autoComplete="name" autoFocus fullWidth />
      )}
      <TextField label="Email" type="email" required value={form.email} onChange={set("email")} autoComplete="email" autoFocus={isLogin} fullWidth />
      <TextField
        label="Password"
        type="password"
        required
        inputProps={{ minLength: isLogin ? 1 : 8 }}
        value={form.password}
        onChange={set("password")}
        autoComplete={isLogin ? "current-password" : "new-password"}
        helperText={isLogin ? undefined : "At least 8 characters."}
        fullWidth
      />
      <Button type="submit" variant="contained" size="large" disabled={busy} fullWidth>
        {busy ? "Please wait…" : isLogin ? "Sign in" : "Create account"}
      </Button>
      <Typography variant="body2" color="text.secondary" align="center">
        {isLogin ? "New here? " : "Already have an account? "}
        <Link component={RouterLink} to={other}>{isLogin ? "Create an account" : "Sign in"}</Link>
      </Typography>
    </Stack>
  );
}
