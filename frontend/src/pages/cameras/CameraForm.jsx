import { useEffect, useMemo, useRef, useState } from "react";
import { Link as RouterLink, useNavigate, useParams } from "react-router-dom";
import Alert from "@mui/material/Alert";
import Box from "@mui/material/Box";
import Button from "@mui/material/Button";
import Card from "@mui/material/Card";
import Chip from "@mui/material/Chip";
import MenuItem from "@mui/material/MenuItem";
import Slider from "@mui/material/Slider";
import Stack from "@mui/material/Stack";
import TextField from "@mui/material/TextField";
import Typography from "@mui/material/Typography";
import ArrowBackIcon from "@mui/icons-material/ArrowBack";
import PhotoCameraIcon from "@mui/icons-material/PhotoCamera";
import SaveIcon from "@mui/icons-material/Save";

import { cameras } from "../../api/endpoints";
import { Stage } from "../../components/cameras/CameraBits";
import { EmptyState, ErrorState, Loading } from "../../components/DataStates";
import CanvasEditor from "../../components/lab/CanvasEditor";
import ParamForm, { GEOMETRY } from "../../components/lab/ParamForm";
import PageHeader from "../../components/PageHeader";
import { useToast } from "../../components/Toast";
import { useAsync } from "../../hooks/useAsync";
import { useWorkspace } from "../../workspace/WorkspaceContext";

function defaultsFor(pipe) {
  const v = {};
  for (const p of pipe?.params || []) {
    v[p.name] = p.default ?? (["multiselect", "polygons", "points"].includes(p.type) ? [] : null);
  }
  return v;
}

const EMPTY = { name: "", location: "", source_url: "", pipeline: "", target_fps: 5 };

/**
 * Add or edit a camera (workspace admins). The pipeline settings are the
 * lab's own form; zones and lines are drawn on a frame from the camera.
 */
export default function CameraForm() {
  const { id } = useParams();
  const editing = Boolean(id);
  const navigate = useNavigate();
  const toast = useToast();
  const { active, hasWsRole } = useWorkspace();
  const catalogue = useAsync((opts) => (active ? cameras.pipelines(opts) : null), [active?.id]);
  const existing = useAsync((opts) => (editing && active ? cameras.get(id, opts) : null), [id, active?.id]);

  const [form, setForm] = useState(EMPTY);
  const [values, setValues] = useState({});
  const [activeGeo, setActiveGeo] = useState(null);
  const [bg, setBg] = useState(null);
  const [previewing, setPreviewing] = useState(false);
  const [error, setError] = useState(null);
  const [saving, setSaving] = useState(false);
  const loadedFor = useRef(null);

  const pipelines = catalogue.data?.pipelines || [];
  const pipe = useMemo(() => pipelines.find((p) => p.name === form.pipeline) || null, [pipelines, form.pipeline]);
  const geoParams = (pipe?.params || []).filter((p) => GEOMETRY.has(p.type));

  // Fill the form once the camera (when editing) has loaded.
  useEffect(() => {
    const c = existing.data;
    if (!c || loadedFor.current === c.id) return;
    loadedFor.current = c.id;
    setForm({ name: c.name, location: c.location || "", source_url: c.source_url, pipeline: c.pipeline || "", target_fps: c.target_fps });
    setValues(c.params || {});
    showFrame(() => cameras.snapshot(c.id));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [existing.data]);

  useEffect(() => () => bg && URL.revokeObjectURL(bg), [bg]);

  async function showFrame(load) {
    setPreviewing(true);
    try {
      const blob = await load();
      setBg(URL.createObjectURL(blob));
    } catch (e) {
      toast(e.message, "err");
    } finally {
      setPreviewing(false);
    }
  }

  function preview() {
    const unchanged = editing && existing.data && form.source_url === existing.data.source_url;
    showFrame(() => (unchanged ? cameras.snapshot(existing.data.id) : cameras.preview(form.source_url.trim())));
  }

  function choosePipeline(name) {
    setForm((f) => ({ ...f, pipeline: name }));
    setActiveGeo(null);
    const next = pipelines.find((p) => p.name === name);
    setValues(editing && existing.data?.pipeline === name ? existing.data.params : defaultsFor(next));
  }

  async function submit(e) {
    e.preventDefault();
    setSaving(true);
    setError(null);
    const body = {
      name: form.name.trim(),
      location: form.location.trim() || null,
      source_url: form.source_url.trim(),
      pipeline: form.pipeline || null,
      params: form.pipeline ? values : {},
      target_fps: Number(form.target_fps),
    };
    try {
      const c = editing ? await cameras.update(id, body) : await cameras.create(body);
      toast(editing ? `Saved ${c.name}${c.enabled ? "; it restarts with the new settings" : ""}.` : `Added ${c.name}. Start it to go live.`);
      navigate(`/cameras/${c.id}`);
    } catch (err) {
      setError(err.message);
      setSaving(false);
    }
  }

  if (!active) return <EmptyState title="No workspace yet" description="Cameras belong to a workspace." />;
  if (!hasWsRole("admin")) return <EmptyState title="Workspace admins only" description="Ask a workspace admin to add or change cameras." />;
  if (catalogue.error) return <ErrorState error={catalogue.error} onRetry={catalogue.reload} />;
  if (existing.error) return <ErrorState error={existing.error} onRetry={existing.reload} title="Couldn't load this camera" />;
  if (!catalogue.data || (editing && !existing.data)) return <Loading />;

  const valid = form.name.trim() && form.source_url.trim();

  return (
    <Box component="form" onSubmit={submit} noValidate>
      <Button component={RouterLink} to={editing ? `/cameras/${id}` : "/cameras"} startIcon={<ArrowBackIcon />} color="inherit" size="small" sx={{ mb: 1 }}>
        {editing ? form.name || "Camera" : "Cameras"}
      </Button>
      <PageHeader
        title={editing ? "Edit camera" : "Add camera"}
        subtitle={`In ${active.name}. ${catalogue.data.live_now} of ${catalogue.data.max_live_cameras} live slots on this server are in use.`}
        actions={
          <Button type="submit" variant="contained" startIcon={<SaveIcon />} disabled={saving || !valid}>
            {saving ? "Saving…" : editing ? "Save" : "Add camera"}
          </Button>
        }
      />
      {error && <Alert severity="error" sx={{ mb: 2 }}>{error}</Alert>}

      <Box sx={{ display: "grid", gap: 2, gridTemplateColumns: { xs: "1fr", md: "minmax(0, 3fr) minmax(320px, 2fr)" }, alignItems: "start" }}>
        <Card sx={{ p: 2 }}>
          <Stack spacing={1.5}>
            <Stack direction="row" justifyContent="space-between" alignItems="center" spacing={1}>
              <Typography variant="subtitle1" sx={{ fontWeight: 700 }}>Picture</Typography>
              <Button size="small" variant="outlined" startIcon={<PhotoCameraIcon />} onClick={preview} disabled={previewing || !form.source_url.trim()}>
                {previewing ? "Connecting…" : bg ? "New frame" : "Load a frame"}
              </Button>
            </Stack>
            {bg && geoParams.length > 0 ? (
              <CanvasEditor src={bg} params={geoParams} values={values} active={activeGeo} onChange={(k, v) => setValues((s) => ({ ...s, [k]: v }))} />
            ) : (
              <Stage>
                {bg ? (
                  <img src={bg} alt="A frame from the camera" />
                ) : (
                  <Typography variant="body2" sx={{ color: "grey.500", px: 3, textAlign: "center" }}>
                    Load a frame to check the source{geoParams.length ? " and draw on it" : ""}.
                  </Typography>
                )}
              </Stage>
            )}
          </Stack>
        </Card>

        <Card sx={{ p: 2 }}>
          <Stack spacing={2.25}>
            <TextField label="Name" value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} required fullWidth autoFocus={!editing} />
            <TextField label="Location" value={form.location} onChange={(e) => setForm({ ...form, location: e.target.value })} placeholder="Gate 2, loading dock" fullWidth />
            <Box>
              <TextField
                label="Source"
                value={form.source_url}
                onChange={(e) => setForm({ ...form, source_url: e.target.value })}
                placeholder="rtsp://user:password@192.168.1.20:554/stream1"
                helperText="RTSP or HTTP stream, file:<name> from camera-files/, or a sample video."
                required
                fullWidth
                inputProps={{ spellCheck: false }}
              />
              <Stack direction="row" spacing={0.75} useFlexGap flexWrap="wrap" sx={{ mt: 1 }}>
                {catalogue.data.samples.map((s) => (
                  <Chip key={s} size="small" variant="outlined" label={`sample:${s}`} onClick={() => setForm({ ...form, source_url: `sample:${s}` })} />
                ))}
              </Stack>
            </Box>
            <TextField select label="Pipeline" value={form.pipeline} onChange={(e) => choosePipeline(e.target.value)}
              SelectProps={{ displayEmpty: true }} InputLabelProps={{ shrink: true }} helperText={pipe?.description || "Just the live picture, nothing analysed."} fullWidth>
              <MenuItem value="">Live view only</MenuItem>
              {pipelines.map((p) => (
                <MenuItem key={p.name} value={p.name}>{p.title}</MenuItem>
              ))}
            </TextField>
            {pipe && (
              <ParamForm tab={pipe} values={values} setValue={(k, v) => setValues((s) => ({ ...s, [k]: v }))}
                activeGeo={activeGeo} setActiveGeo={setActiveGeo} hasImage={Boolean(bg)} />
            )}
            <Box>
              <Typography variant="body2" sx={{ fontWeight: 600 }} id="fps-label">Frames analysed per second: {form.target_fps}</Typography>
              <Slider aria-labelledby="fps-label" value={Number(form.target_fps)} min={1} max={15} step={1} marks
                onChange={(_, v) => setForm({ ...form, target_fps: v })} />
              <Typography variant="caption" color="text.secondary">
                Each frame is a model call. 2–5 is plenty for people and vehicles; more needs a GPU model server.
              </Typography>
            </Box>
          </Stack>
        </Card>
      </Box>
    </Box>
  );
}
