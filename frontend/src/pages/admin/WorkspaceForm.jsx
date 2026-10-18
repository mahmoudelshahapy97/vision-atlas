import { useEffect, useMemo, useState } from "react";
import Alert from "@mui/material/Alert";
import Autocomplete from "@mui/material/Autocomplete";
import Button from "@mui/material/Button";
import Checkbox from "@mui/material/Checkbox";
import Dialog from "@mui/material/Dialog";
import DialogActions from "@mui/material/DialogActions";
import DialogContent from "@mui/material/DialogContent";
import DialogTitle from "@mui/material/DialogTitle";
import FormControlLabel from "@mui/material/FormControlLabel";
import Stack from "@mui/material/Stack";
import TextField from "@mui/material/TextField";

import { lab, workspaces } from "../../api/endpoints";
import { useToast } from "../../components/Toast";
import { useAsync } from "../../hooks/useAsync";

const EMPTY = { name: "", description: "", max_cameras: 16, all: true, pipelines: [] };

/** Create or edit a workspace (system admins). `editing` null means new. */
export function WorkspaceForm({ open, editing, onClose, onSaved }) {
  const toast = useToast();
  const pipelines = useAsync((opts) => (open ? lab.pipelines(opts) : null), [open]);
  const [form, setForm] = useState(EMPTY);
  const [error, setError] = useState(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    if (!open) return;
    setError(null);
    setForm(
      editing
        ? {
            name: editing.name,
            description: editing.description || "",
            max_cameras: editing.max_cameras,
            all: editing.enabled_pipelines == null,
            pipelines: editing.enabled_pipelines || [],
          }
        : EMPTY
    );
  }, [open, editing]);

  const options = useMemo(() => (pipelines.data || []).map((p) => ({ name: p.name, title: p.title })), [pipelines.data]);
  const titleOf = (name) => options.find((o) => o.name === name)?.title || name;

  async function submit(e) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    const body = {
      name: form.name.trim(),
      description: form.description.trim() || null,
      max_cameras: Number(form.max_cameras),
      enabled_pipelines: form.all ? null : form.pipelines,
    };
    try {
      const ws = editing ? await workspaces.update(editing.id, body) : await workspaces.create(body);
      toast(editing ? `Saved ${ws.name}.` : `Created ${ws.name}. Add its members next.`);
      onSaved(ws);
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  }

  const valid = form.name.trim() && Number(form.max_cameras) >= 0 && (form.all || form.pipelines.length > 0);

  return (
    <Dialog open={open} onClose={busy ? undefined : onClose} maxWidth="sm" fullWidth>
      <form onSubmit={submit} noValidate>
        <DialogTitle>{editing ? `Edit ${editing.name}` : "New workspace"}</DialogTitle>
        <DialogContent>
          <Stack spacing={2} sx={{ mt: 1 }}>
            {error && <Alert severity="error">{error}</Alert>}
            <TextField label="Name" value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} autoFocus fullWidth />
            <TextField
              label="Description"
              value={form.description}
              onChange={(e) => setForm({ ...form, description: e.target.value })}
              multiline
              minRows={2}
              fullWidth
            />
            <TextField
              label="Camera limit"
              type="number"
              value={form.max_cameras}
              onChange={(e) => setForm({ ...form, max_cameras: e.target.value })}
              inputProps={{ min: 0, max: 1000 }}
              helperText="Each live camera keeps the model server busy; size this to your hardware."
              sx={{ maxWidth: 260 }}
            />
            <FormControlLabel
              control={<Checkbox checked={form.all} onChange={(e) => setForm({ ...form, all: e.target.checked })} />}
              label="Cameras may run any live pipeline"
            />
            {!form.all && (
              <Autocomplete
                multiple
                options={options.map((o) => o.name)}
                value={form.pipelines}
                onChange={(_, v) => setForm({ ...form, pipelines: v })}
                getOptionLabel={titleOf}
                loading={pipelines.loading}
                renderInput={(params) => <TextField {...params} label="Allowed pipelines" placeholder="Pick pipelines" />}
              />
            )}
          </Stack>
        </DialogContent>
        <DialogActions sx={{ px: 3, pb: 2 }}>
          <Button onClick={onClose} disabled={busy} color="inherit">
            Cancel
          </Button>
          <Button type="submit" disabled={busy || !valid} variant="contained">
            {busy ? "Saving…" : editing ? "Save" : "Create workspace"}
          </Button>
        </DialogActions>
      </form>
    </Dialog>
  );
}

export default WorkspaceForm;
