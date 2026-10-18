import { useEffect, useState } from "react";
import Alert from "@mui/material/Alert";
import Button from "@mui/material/Button";
import Dialog from "@mui/material/Dialog";
import DialogActions from "@mui/material/DialogActions";
import DialogContent from "@mui/material/DialogContent";
import DialogContentText from "@mui/material/DialogContentText";
import DialogTitle from "@mui/material/DialogTitle";
import Stack from "@mui/material/Stack";
import TextField from "@mui/material/TextField";

/**
 * New-password dialog. With `requireCurrent` it is "change my password"
 * (asks for the current one); without, it is an admin's reset.
 * `onSubmit(newPassword, currentPassword)` may throw; its message is shown.
 */
export function PasswordDialog({ open, title, description, requireCurrent = false, submitLabel = "Save", onSubmit, onClose }) {
  const [current, setCurrent] = useState("");
  const [next, setNext] = useState("");
  const [repeat, setRepeat] = useState("");
  const [error, setError] = useState(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    if (open) {
      setCurrent("");
      setNext("");
      setRepeat("");
      setError(null);
    }
  }, [open]);

  const mismatch = repeat && next !== repeat;
  const valid = next.length >= 8 && next === repeat && (!requireCurrent || current);

  async function submit(e) {
    e.preventDefault();
    if (!valid) return;
    setBusy(true);
    setError(null);
    try {
      await onSubmit(next, current);
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <Dialog open={open} onClose={busy ? undefined : onClose} maxWidth="xs" fullWidth>
      <form onSubmit={submit} noValidate>
        <DialogTitle>{title}</DialogTitle>
        <DialogContent>
          {description && <DialogContentText sx={{ mb: 2 }}>{description}</DialogContentText>}
          <Stack spacing={2} sx={{ mt: description ? 0 : 1 }}>
            {error && <Alert severity="error">{error}</Alert>}
            {requireCurrent && (
              <TextField
                label="Current password"
                type="password"
                autoComplete="current-password"
                value={current}
                onChange={(e) => setCurrent(e.target.value)}
                autoFocus
                fullWidth
              />
            )}
            <TextField
              label="New password"
              type="password"
              autoComplete="new-password"
              value={next}
              onChange={(e) => setNext(e.target.value)}
              helperText="At least 8 characters."
              autoFocus={!requireCurrent}
              fullWidth
            />
            <TextField
              label="Repeat new password"
              type="password"
              autoComplete="new-password"
              value={repeat}
              onChange={(e) => setRepeat(e.target.value)}
              error={Boolean(mismatch)}
              helperText={mismatch ? "The passwords don't match." : " "}
              fullWidth
            />
          </Stack>
        </DialogContent>
        <DialogActions sx={{ px: 3, pb: 2 }}>
          <Button onClick={onClose} disabled={busy} color="inherit">
            Cancel
          </Button>
          <Button type="submit" disabled={busy || !valid} variant="contained">
            {busy ? "Saving…" : submitLabel}
          </Button>
        </DialogActions>
      </form>
    </Dialog>
  );
}

export default PasswordDialog;
