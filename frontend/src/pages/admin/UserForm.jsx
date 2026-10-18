import { useEffect, useState } from "react";
import Alert from "@mui/material/Alert";
import Button from "@mui/material/Button";
import Dialog from "@mui/material/Dialog";
import DialogActions from "@mui/material/DialogActions";
import DialogContent from "@mui/material/DialogContent";
import DialogTitle from "@mui/material/DialogTitle";
import MenuItem from "@mui/material/MenuItem";
import Stack from "@mui/material/Stack";
import TextField from "@mui/material/TextField";

import { users } from "../../api/endpoints";
import { ROLES } from "../../auth/roles";
import { useToast } from "../../components/Toast";

const EMPTY = { email: "", name: "", password: "", role: "user" };

const ROLE_HELP = {
  user: "Runs labs and uploads models. Workspace access is granted per workspace.",
  admin: "Also manages the catalog, every account and every workspace.",
};

/**
 * Create and edit in one dialog: `editing` null means a new account. The
 * password is only set on create; the list's reset action changes it later.
 */
export function UserForm({ open, editing, onClose, onSaved }) {
  const toast = useToast();
  const [form, setForm] = useState(EMPTY);
  const [error, setError] = useState(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    if (!open) return;
    setError(null);
    setForm(editing ? { email: editing.email, name: editing.name, password: "", role: editing.role } : EMPTY);
  }, [open, editing]);

  const set = (key) => (e) => setForm((f) => ({ ...f, [key]: e.target.value }));

  async function submit(e) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      if (editing) {
        await users.update(editing.id, { name: form.name, role: form.role });
        toast(`Saved ${form.name}.`);
      } else {
        await users.create(form);
        toast(`Created ${form.email}.`);
      }
      onSaved();
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  }

  const valid = form.name.trim() && (editing || (form.email && form.password.length >= 8));

  return (
    <Dialog open={open} onClose={busy ? undefined : onClose} maxWidth="xs" fullWidth>
      <form onSubmit={submit} noValidate>
        <DialogTitle>{editing ? `Edit ${editing.name}` : "New account"}</DialogTitle>
        <DialogContent>
          <Stack spacing={2} sx={{ mt: 1 }}>
            {error && <Alert severity="error">{error}</Alert>}
            <TextField
              label="Email"
              type="email"
              value={form.email}
              onChange={set("email")}
              disabled={Boolean(editing)}
              autoFocus={!editing}
              fullWidth
            />
            <TextField label="Name" value={form.name} onChange={set("name")} fullWidth />
            {!editing && (
              <TextField
                label="Password"
                type="password"
                autoComplete="new-password"
                value={form.password}
                onChange={set("password")}
                helperText="At least 8 characters. Share it with the person; they can change it after signing in."
                fullWidth
              />
            )}
            <TextField select label="Role" value={form.role} onChange={set("role")} helperText={ROLE_HELP[form.role]} fullWidth>
              {ROLES.map((r) => (
                <MenuItem key={r} value={r}>
                  {r}
                </MenuItem>
              ))}
            </TextField>
          </Stack>
        </DialogContent>
        <DialogActions sx={{ px: 3, pb: 2 }}>
          <Button onClick={onClose} disabled={busy} color="inherit">
            Cancel
          </Button>
          <Button type="submit" disabled={busy || !valid} variant="contained">
            {busy ? "Saving…" : editing ? "Save" : "Create account"}
          </Button>
        </DialogActions>
      </form>
    </Dialog>
  );
}

export default UserForm;
