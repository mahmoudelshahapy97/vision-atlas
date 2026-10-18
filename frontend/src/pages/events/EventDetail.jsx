import { useState } from "react";
import { Link as RouterLink, useParams } from "react-router-dom";
import Box from "@mui/material/Box";
import Button from "@mui/material/Button";
import Card from "@mui/material/Card";
import CardContent from "@mui/material/CardContent";
import Divider from "@mui/material/Divider";
import Stack from "@mui/material/Stack";
import Typography from "@mui/material/Typography";
import ArrowBackIcon from "@mui/icons-material/ArrowBack";
import CheckIcon from "@mui/icons-material/Check";
import DoneAllIcon from "@mui/icons-material/DoneAll";
import DoNotDisturbIcon from "@mui/icons-material/DoNotDisturb";
import ReplayIcon from "@mui/icons-material/Replay";

import { mediaUrl } from "../../api/client";
import { events } from "../../api/endpoints";
import { Stage } from "../../components/cameras/CameraBits";
import { ErrorState, Loading } from "../../components/DataStates";
import { EventStatusChip, SeverityChip, kindLabel } from "../../components/events/EventBits";
import PageHeader from "../../components/PageHeader";
import { useToast } from "../../components/Toast";
import { useAsync } from "../../hooks/useAsync";
import { formatDateTime } from "../../utils/format";
import { useWorkspace } from "../../workspace/WorkspaceContext";

function Row({ label, children }) {
  return (
    <Stack direction="row" justifyContent="space-between" spacing={2} sx={{ py: 0.75 }}>
      <Typography variant="body2" color="text.secondary">{label}</Typography>
      <Typography variant="body2" component="div" sx={{ textAlign: "right", overflowWrap: "anywhere" }}>{children}</Typography>
    </Stack>
  );
}

const ACTIONS = [
  { status: "acknowledged", label: "Acknowledge", icon: <CheckIcon />, when: (s) => s === "open" },
  { status: "resolved", label: "Resolve", icon: <DoneAllIcon />, color: "success", when: (s) => s !== "resolved" },
  { status: "false_positive", label: "False alarm", icon: <DoNotDisturbIcon />, when: (s) => s !== "false_positive" },
  { status: "open", label: "Reopen", icon: <ReplayIcon />, when: (s) => s !== "open" },
];

/** One event: its snapshot, what raised it, and handling. */
export default function EventDetail() {
  const { id } = useParams();
  const toast = useToast();
  const { active, hasWsRole } = useWorkspace();
  const ev = useAsync((o) => (active ? events.get(id, o) : null), [id, active?.id]);
  const [busy, setBusy] = useState(false);
  const e = ev.data;

  if (ev.error) return <ErrorState error={ev.error} onRetry={ev.reload} title="Couldn't load this event" />;
  if (!e) return <Loading />;

  async function set(status) {
    setBusy(true);
    try {
      ev.setData(await events.setStatus(e.id, status));
    } catch (err) {
      toast(err.message, "err");
    } finally {
      setBusy(false);
    }
  }

  const data = Object.entries(e.data || {}).filter(([k]) => k !== "box");

  return (
    <Box>
      <Button component={RouterLink} to="/events" startIcon={<ArrowBackIcon />} color="inherit" size="small" sx={{ mb: 1 }}>
        Events
      </Button>
      <PageHeader
        title={`${kindLabel(e.kind)}: ${e.label}`}
        subtitle={`${e.camera_name} · ${formatDateTime(e.occurred_at)}`}
        actions={
          hasWsRole("operator") &&
          ACTIONS.filter((a) => a.when(e.status)).map((a) => (
            <Button key={a.status} startIcon={a.icon} color={a.color || "inherit"} variant={a.status === "resolved" ? "contained" : "outlined"}
              disabled={busy} onClick={() => set(a.status)}>
              {a.label}
            </Button>
          ))
        }
      />
      <Box sx={{ display: "grid", gap: 2, gridTemplateColumns: { xs: "1fr", lg: "minmax(0, 2fr) minmax(280px, 1fr)" }, alignItems: "start" }}>
        <Card>
          <CardContent>
            <Stage>
              {e.snapshot_url ? (
                <img src={mediaUrl(e.snapshot_url)} alt={`${kindLabel(e.kind)} at ${e.camera_name}`} />
              ) : (
                <Typography variant="body2" sx={{ color: "grey.500" }}>No snapshot (yet).</Typography>
              )}
            </Stage>
          </CardContent>
        </Card>
        <Card>
          <CardContent>
            <Row label="Status"><EventStatusChip status={e.status} /></Row>
            <Row label="Severity"><SeverityChip severity={e.severity} /></Row>
            <Row label="Camera"><Button component={RouterLink} to={`/cameras/${e.camera_id}`} size="small">{e.camera_name}</Button></Row>
            <Row label="Pipeline">{e.pipeline}</Row>
            {e.track_id != null && <Row label="Track">#{e.track_id}</Row>}
            {e.confidence != null && <Row label="Confidence">{e.confidence.toFixed(2)}</Row>}
            {data.map(([k, v]) => (
              <Row key={k} label={k.replace(/_/g, " ")}>{Array.isArray(v) ? v.join(", ") : String(v)}</Row>
            ))}
            {e.handled_at && (
              <>
                <Divider sx={{ my: 1 }} />
                <Row label="Handled by">{e.handled_by_name || "—"}</Row>
                <Row label="Handled at">{formatDateTime(e.handled_at)}</Row>
              </>
            )}
          </CardContent>
        </Card>
      </Box>
    </Box>
  );
}
