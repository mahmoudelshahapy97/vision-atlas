import { useMemo, useState } from "react";
import { Link as RouterLink, useNavigate, useParams } from "react-router-dom";
import Alert from "@mui/material/Alert";
import Box from "@mui/material/Box";
import Button from "@mui/material/Button";
import Card from "@mui/material/Card";
import CardContent from "@mui/material/CardContent";
import CardHeader from "@mui/material/CardHeader";
import Chip from "@mui/material/Chip";
import Divider from "@mui/material/Divider";
import List from "@mui/material/List";
import ListItem from "@mui/material/ListItem";
import ListItemText from "@mui/material/ListItemText";
import Stack from "@mui/material/Stack";
import Typography from "@mui/material/Typography";
import ArrowBackIcon from "@mui/icons-material/ArrowBack";
import DeleteOutlineIcon from "@mui/icons-material/DeleteOutline";
import EditIcon from "@mui/icons-material/Edit";
import PlayArrowIcon from "@mui/icons-material/PlayArrow";
import StopIcon from "@mui/icons-material/Stop";
import VideocamOffIcon from "@mui/icons-material/VideocamOff";

import { cameras } from "../../api/endpoints";
import { CameraStateChip, Stage, metricLabel } from "../../components/cameras/CameraBits";
import ConfirmDialog from "../../components/ConfirmDialog";
import { ErrorState, Loading } from "../../components/DataStates";
import PageHeader from "../../components/PageHeader";
import { useToast } from "../../components/Toast";
import { useAsync } from "../../hooks/useAsync";
import { useCameraStream } from "../../hooks/useCameraStream";
import { usePolling } from "../../hooks/usePolling";
import { formatDateTime } from "../../utils/format";
import { MONO_FONT } from "../../utils/theme";
import { useWorkspace } from "../../workspace/WorkspaceContext";

const SEVERITY_COLOR = { info: "info", warning: "warning", critical: "error" };

function Row({ label, children }) {
  return (
    <Stack direction="row" justifyContent="space-between" spacing={2} sx={{ py: 0.75 }}>
      <Typography variant="body2" color="text.secondary">{label}</Typography>
      <Typography variant="body2" component="div" sx={{ textAlign: "right", minWidth: 0, overflowWrap: "anywhere" }}>{children}</Typography>
    </Stack>
  );
}

/** One camera: the live annotated picture, its health and what the pipeline sees. */
export default function CameraDetail() {
  const { id } = useParams();
  const navigate = useNavigate();
  const toast = useToast();
  const { active, hasWsRole } = useWorkspace();
  const cam = usePolling((opts) => cameras.get(id, opts), { intervalMs: 3000, deps: [id, active?.id], enabled: Boolean(active) });
  const catalogue = useAsync((opts) => (active ? cameras.pipelines(opts) : null), [active?.id]);
  const c = cam.data;
  const running = Boolean(c?.status?.running);
  const stream = useCameraStream(c?.id, { enabled: running });
  const [busy, setBusy] = useState(false);
  const [confirmDelete, setConfirmDelete] = useState(false);
  const pipe = useMemo(() => (catalogue.data?.pipelines || []).find((p) => p.name === c?.pipeline), [catalogue.data, c]);

  if (cam.error && !c) return <ErrorState error={cam.error} onRetry={cam.reload} title="Couldn't load this camera" />;
  if (!c) return <Loading />;

  const st = c.status;
  const metrics = (running && stream.frame?.metrics) || st.metrics || {};

  async function toggle() {
    setBusy(true);
    try {
      cam.setData(c.enabled ? await cameras.stop(c.id) : await cameras.start(c.id));
      toast(c.enabled ? `Stopped ${c.name}.` : `Starting ${c.name}…`);
      cam.reload();
    } catch (e) {
      toast(e.message, "err");
    } finally {
      setBusy(false);
    }
  }

  async function remove() {
    setBusy(true);
    try {
      await cameras.remove(c.id);
      toast(`Deleted ${c.name}.`);
      navigate("/cameras", { replace: true });
    } catch (e) {
      toast(e.message, "err");
      setBusy(false);
    }
  }

  const params = Object.entries(c.params || {}).filter(([k]) => !["zone", "line", "model"].includes(k));

  return (
    <Box>
      <Button component={RouterLink} to="/cameras" startIcon={<ArrowBackIcon />} color="inherit" size="small" sx={{ mb: 1 }}>
        Cameras
      </Button>
      <PageHeader
        title={
          <Stack direction="row" spacing={1.5} alignItems="center" component="span">
            <span>{c.name}</span>
            <CameraStateChip state={st.state} error={st.last_error} />
          </Stack>
        }
        subtitle={[pipe?.title || (c.pipeline ? c.pipeline : "Live view only"), c.location].filter(Boolean).join(" · ")}
        actions={
          <>
            {hasWsRole("operator") && (
              <Button variant={c.enabled ? "outlined" : "contained"} color={c.enabled ? "inherit" : "success"} disabled={busy}
                startIcon={c.enabled ? <StopIcon /> : <PlayArrowIcon />} onClick={toggle}>
                {c.enabled ? "Stop" : "Start"}
              </Button>
            )}
            {hasWsRole("admin") && (
              <>
                <Button component={RouterLink} to={`/cameras/${c.id}/edit`} startIcon={<EditIcon />}>Edit</Button>
                <Button color="error" startIcon={<DeleteOutlineIcon />} onClick={() => setConfirmDelete(true)}>Delete</Button>
              </>
            )}
          </>
        }
      />

      {st.last_error && st.state !== "running" && (
        <Alert severity={st.state === "error" ? "error" : "warning"} sx={{ mb: 2 }}>{st.last_error}</Alert>
      )}

      <Box sx={{ display: "grid", gap: 2, gridTemplateColumns: { xs: "1fr", lg: "minmax(0, 2fr) minmax(300px, 1fr)" }, alignItems: "start" }}>
        <Card>
          <CardContent>
            <Stage>
              {running && stream.imageSrc ? (
                <img src={stream.imageSrc} alt={`Live view of ${c.name}`} />
              ) : (
                <Stack alignItems="center" spacing={1} sx={{ color: "grey.500", textAlign: "center", px: 2 }}>
                  <VideocamOffIcon fontSize="large" />
                  <Typography variant="body2">
                    {running ? stream.error || "Waiting for the first frame…" : "Not running. Start it to see the live picture."}
                  </Typography>
                </Stack>
              )}
            </Stage>
            <Stack direction="row" spacing={1} useFlexGap flexWrap="wrap" sx={{ mt: 1.5 }}>
              {Object.entries(metrics).map(([k, v]) => (
                <Chip key={k} size="small" variant="outlined" label={`${metricLabel(k)}: ${Math.round(v * 10) / 10}`} />
              ))}
              {running && stream.frame && (
                <Typography variant="caption" color="text.secondary" sx={{ ml: "auto", alignSelf: "center" }}>
                  {stream.frame.width}×{stream.frame.height} · {stream.frame.fps} fps
                </Typography>
              )}
            </Stack>
          </CardContent>
        </Card>

        <Stack spacing={2}>
          <Card>
            <CardHeader title="Health" titleTypographyProps={{ variant: "subtitle1", fontWeight: 700 }} sx={{ pb: 0 }} />
            <CardContent>
              <Row label="Connected">{st.connected ? "Yes" : "No"}</Row>
              <Row label="Analysed frames">{st.frames_processed ?? 0}</Row>
              <Row label="Speed">{st.fps ? `${st.fps} fps (target ${c.target_fps})` : `target ${c.target_fps} fps`}</Row>
              <Row label="Reconnects">{st.reconnects ?? 0}{st.supervisor_restarts ? ` · ${st.supervisor_restarts} restarts` : ""}</Row>
              <Row label="Running since">{formatDateTime(st.started_at)}</Row>
              <Row label="Last frame">{formatDateTime(st.last_frame_at)}</Row>
              <Divider sx={{ my: 1 }} />
              <Row label="Source"><Box component="span" sx={{ fontFamily: MONO_FONT, fontSize: 12.5 }}>{c.source_url}</Box></Row>
            </CardContent>
          </Card>

          <Card>
            <CardHeader title="Recent events" subheader="Since the camera last started" titleTypographyProps={{ variant: "subtitle1", fontWeight: 700 }} sx={{ pb: 0 }} />
            <CardContent sx={{ pt: 1 }}>
              {st.recent_events?.length ? (
                <List dense disablePadding>
                  {st.recent_events.slice(0, 8).map((e, i) => (
                    <ListItem key={i} disableGutters secondaryAction={<Chip size="small" color={SEVERITY_COLOR[e.severity]} label={e.severity} />}>
                      <ListItemText
                        primary={`${e.kind.replace(/_/g, " ")}: ${e.label}${e.track_id != null ? ` #${e.track_id}` : ""}`}
                        secondary={formatDateTime(e.at)}
                      />
                    </ListItem>
                  ))}
                </List>
              ) : (
                <Typography variant="body2" color="text.secondary">
                  {pipe && Object.keys(pipe.events || {}).length ? "Nothing yet." : "This pipeline reports numbers, not events."}
                </Typography>
              )}
            </CardContent>
          </Card>

          {params.length > 0 && (
            <Card>
              <CardHeader title="Settings" titleTypographyProps={{ variant: "subtitle1", fontWeight: 700 }} sx={{ pb: 0 }} />
              <CardContent>
                {params.map(([k, v]) => (
                  <Row key={k} label={pipe?.params.find((p) => p.name === k)?.label || k}>
                    {Array.isArray(v) ? v.join(", ") || "all" : String(v)}
                  </Row>
                ))}
              </CardContent>
            </Card>
          )}
        </Stack>
      </Box>

      <ConfirmDialog
        open={confirmDelete}
        title="Delete this camera?"
        description={`${c.name} stops and is removed.`}
        confirmLabel="Delete"
        confirmColor="error"
        busy={busy}
        onConfirm={remove}
        onClose={() => setConfirmDelete(false)}
      />
    </Box>
  );
}
