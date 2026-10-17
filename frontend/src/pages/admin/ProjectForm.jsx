import { useEffect, useState } from "react";
import { Link as RouterLink, useNavigate, useParams } from "react-router-dom";
import Alert from "@mui/material/Alert";
import Box from "@mui/material/Box";
import Button from "@mui/material/Button";
import Card from "@mui/material/Card";
import CardContent from "@mui/material/CardContent";
import Checkbox from "@mui/material/Checkbox";
import FormControlLabel from "@mui/material/FormControlLabel";
import MenuItem from "@mui/material/MenuItem";
import Stack from "@mui/material/Stack";
import TextField from "@mui/material/TextField";
import ArrowBackIcon from "@mui/icons-material/ArrowBack";

import { catalog, projects } from "../../api/endpoints";
import { ErrorState } from "../../components/DataStates";
import PageHeader from "../../components/PageHeader";
import { useToast } from "../../components/Toast";
import { useAsync } from "../../hooks/useAsync";
import { LEVELS } from "../../utils/constants";
import { pad } from "../../utils/format";

const EMPTY = {
  title: "", description: "", domain_code: "", task_type_code: "", level: 2,
  technologies: "", is_pick: false, pick_reason: "", caution: "",
};

export default function ProjectForm() {
  const { id } = useParams();
  const editing = Boolean(id);
  const navigate = useNavigate();
  const toast = useToast();
  const domains = useAsync((opts) => catalog.domains(opts), []);
  const tasks = useAsync((opts) => catalog.taskTypes(opts), []);
  const existing = useAsync((opts) => (editing ? projects.get(id, opts) : Promise.resolve(null)), [id]);
  const [form, setForm] = useState(EMPTY);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    const p = existing.data;
    if (!p) return;
    setForm({
      title: p.title, description: p.description, domain_code: p.domain.code, task_type_code: p.task_type.code,
      level: p.level, technologies: p.technologies.join(", "), is_pick: p.is_pick,
      pick_reason: p.pick_reason || "", caution: p.caution || "",
    });
  }, [existing.data]);

  const set = (k) => (e) => setForm({ ...form, [k]: e.target.type === "checkbox" ? e.target.checked : e.target.value });

  async function submit(e) {
    e.preventDefault();
    setError("");
    if (!form.domain_code || !form.task_type_code) return setError("Choose a domain and a task type.");
    setBusy(true);
    const body = {
      ...form,
      level: Number(form.level),
      technologies: form.technologies.split(",").map((t) => t.trim()).filter(Boolean),
      pick_reason: form.is_pick ? form.pick_reason : "",
    };
    try {
      const saved = editing ? await projects.update(id, body) : await projects.create(body);
      toast(editing ? `Saved #${pad(saved.id)}.` : `Created #${pad(saved.id)} ${saved.title}.`);
      navigate("/admin");
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <Box sx={{ maxWidth: 820 }}>
      <Button component={RouterLink} to="/admin" startIcon={<ArrowBackIcon />} size="small" sx={{ mb: 2 }}>Back to projects</Button>
      <PageHeader
        title={editing ? `Edit project #${pad(id)}` : "New project"}
        subtitle={editing ? existing.data?.title : "Add a project to the catalog."}
      />
      <ErrorState error={existing.error} onRetry={existing.reload} />
      <Card>
        <CardContent>
          <Stack component="form" onSubmit={submit} spacing={2.5}>
            <TextField label="Title" required inputProps={{ minLength: 3, maxLength: 200 }} value={form.title} onChange={set("title")} fullWidth />
            <TextField label="Description" required inputProps={{ minLength: 3 }} multiline minRows={3} value={form.description} onChange={set("description")} fullWidth />
            <Stack direction={{ xs: "column", sm: "row" }} spacing={2}>
              <TextField select label="Domain" required value={form.domain_code} onChange={set("domain_code")} fullWidth>
                {(domains.data || []).map((d) => <MenuItem key={d.code} value={d.code}>{d.name}</MenuItem>)}
              </TextField>
              <TextField select label="Task type" required value={form.task_type_code} onChange={set("task_type_code")} fullWidth>
                {(tasks.data || []).map((t) => <MenuItem key={t.code} value={t.code}>{t.name}</MenuItem>)}
              </TextField>
              <TextField select label="Level" value={form.level} onChange={set("level")} fullWidth>
                {Object.entries(LEVELS).map(([k, l]) => <MenuItem key={k} value={Number(k)}>{l}</MenuItem>)}
              </TextField>
            </Stack>
            <TextField label="Technologies" value={form.technologies} onChange={set("technologies")} placeholder="YOLO, OpenCV, PyTorch" helperText="Separate with commas." fullWidth />
            <FormControlLabel control={<Checkbox checked={form.is_pick} onChange={set("is_pick")} />} label="Mark as a top pick" />
            {form.is_pick && (
              <TextField label="Why it is a top pick" multiline minRows={2} value={form.pick_reason} onChange={set("pick_reason")} fullWidth />
            )}
            <TextField
              label="Caution note (optional)"
              multiline
              minRows={2}
              value={form.caution}
              onChange={set("caution")}
              placeholder="Shown on the project, e.g. for medical or biometric data"
              fullWidth
            />
            {error && <Alert severity="error">{error}</Alert>}
            <Stack direction="row" spacing={1}>
              <Button type="submit" variant="contained" disabled={busy}>{busy ? "Saving…" : editing ? "Save changes" : "Create project"}</Button>
              <Button component={RouterLink} to="/admin" color="inherit">Cancel</Button>
            </Stack>
          </Stack>
        </CardContent>
      </Card>
    </Box>
  );
}
