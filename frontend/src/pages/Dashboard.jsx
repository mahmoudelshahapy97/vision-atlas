import { Link as RouterLink } from "react-router-dom";
import Box from "@mui/material/Box";
import Button from "@mui/material/Button";
import Card from "@mui/material/Card";
import CardActionArea from "@mui/material/CardActionArea";
import CardContent from "@mui/material/CardContent";
import CardHeader from "@mui/material/CardHeader";
import Chip from "@mui/material/Chip";
import IconButton from "@mui/material/IconButton";
import List from "@mui/material/List";
import ListItem from "@mui/material/ListItem";
import ListItemButton from "@mui/material/ListItemButton";
import Skeleton from "@mui/material/Skeleton";
import Stack from "@mui/material/Stack";
import Tooltip from "@mui/material/Tooltip";
import Typography from "@mui/material/Typography";
import CheckIcon from "@mui/icons-material/Check";
import NotificationsActiveIcon from "@mui/icons-material/NotificationsActive";
import ReportIcon from "@mui/icons-material/Report";
import ScheduleIcon from "@mui/icons-material/Schedule";
import VideocamIcon from "@mui/icons-material/Videocam";

import { cameras, events } from "../api/endpoints";
import { CameraStateChip, metricSummary } from "../components/cameras/CameraBits";
import { EmptyState, ErrorState } from "../components/DataStates";
import { EventStatusChip, SeverityChip, Snapshot, kindLabel } from "../components/events/EventBits";
import PageHeader from "../components/PageHeader";
import StatCard from "../components/StatCard";
import { useToast } from "../components/Toast";
import { useAlerts } from "../hooks/useAlerts";
import { usePolling } from "../hooks/usePolling";
import { formatDateTime } from "../utils/format";
import { useWorkspace } from "../workspace/WorkspaceContext";

function ago(value) {
  if (!value) return "never";
  const s = Math.max(0, (Date.now() - new Date(value).getTime()) / 1000);
  if (s < 60) return "just now";
  if (s < 3600) return `${Math.round(s / 60)} min ago`;
  if (s < 86400) return `${Math.round(s / 3600)} h ago`;
  return `${Math.round(s / 86400)} d ago`;
}

/** The active workspace at a glance: camera health, open events, the latest alerts. */
export default function Dashboard() {
  const toast = useToast();
  const { active, hasWsRole } = useWorkspace();
  const { recent: pushed, version, connected } = useAlerts();
  const wid = active?.id;
  const on = Boolean(wid);
  // `version` changes with every pushed alert, so the numbers follow at once.
  const stats = usePolling((o) => events.stats(o), { intervalMs: 30000, deps: [wid, version], enabled: on });
  const cams = usePolling((o) => cameras.list(o), { intervalMs: 5000, deps: [wid], enabled: on });
  const latest = usePolling((o) => events.list({ per_page: 8 }, o), { intervalMs: 30000, deps: [wid, version], enabled: on });

  if (!active) {
    return (
      <EmptyState
        title="No workspace yet"
        description="The dashboard shows a workspace's cameras and events. Ask an admin to add you to one."
      />
    );
  }

  async function acknowledge(e) {
    try {
      await events.setStatus(e.id, "acknowledged");
      latest.reload();
      stats.reload();
    } catch (err) {
      toast(err.message, "err");
    }
  }

  const s = stats.data;
  const camRows = cams.data || [];

  return (
    <Box>
      <PageHeader
        title="Dashboard"
        subtitle={`${active.name}: what the cameras see right now.`}
        actions={
          <Chip
            size="small"
            variant="outlined"
            color={connected ? "success" : "default"}
            icon={<NotificationsActiveIcon />}
            label={connected ? "Live alerts on" : "Connecting alerts…"}
          />
        }
      />
      <ErrorState error={stats.error || cams.error} onRetry={() => { stats.reload(); cams.reload(); }} />

      <Box sx={{ display: "grid", gap: 2, gridTemplateColumns: { xs: "repeat(2, minmax(0, 1fr))", lg: "repeat(4, minmax(0, 1fr))" }, mb: 2 }}>
        <StatCard label="Cameras live" value={s ? `${s.cameras_live} / ${s.cameras}` : "…"} hint="running now" icon={<VideocamIcon />} />
        <StatCard label="Open events" value={s ? s.open : "…"} hint="waiting for someone" icon={<NotificationsActiveIcon />} color="warning" />
        <StatCard label="Critical open" value={s ? s.open_critical : "…"} hint="falls, abandoned objects" icon={<ReportIcon />} color="error" />
        <StatCard label="Last 24 hours" value={s ? s.last_24h : "…"} hint={s ? `last ${ago(s.last_event_at)}` : ""} icon={<ScheduleIcon />} color="info" />
      </Box>

      <Card sx={{ mb: 2 }}>
        <CardHeader
          title="Camera health"
          titleTypographyProps={{ variant: "subtitle1", fontWeight: 700 }}
          action={<Button component={RouterLink} to="/live" size="small">Live wall</Button>}
          sx={{ pb: 0 }}
        />
        <CardContent>
          {cams.loading && !cams.data ? (
            <Skeleton variant="rounded" height={64} />
          ) : camRows.length ? (
            <Box sx={{ display: "grid", gap: 1.5, gridTemplateColumns: { xs: "1fr", sm: "repeat(2, minmax(0, 1fr))", lg: "repeat(4, minmax(0, 1fr))" } }}>
              {camRows.map((c) => (
                <Card key={c.id} variant="outlined">
                  <CardActionArea component={RouterLink} to={`/cameras/${c.id}`} sx={{ p: 1.5 }}>
                    <Stack direction="row" justifyContent="space-between" alignItems="center" spacing={1}>
                      <Typography variant="body2" noWrap sx={{ fontWeight: 700, minWidth: 0 }}>{c.name}</Typography>
                      <CameraStateChip state={c.status.state} error={c.status.last_error} />
                    </Stack>
                    <Typography variant="caption" color="text.secondary" noWrap sx={{ display: "block", mt: 0.5 }}>
                      {c.status.running
                        ? [metricSummary(c.status.metrics, 2), c.status.fps ? `${c.status.fps} fps` : ""].filter(Boolean).join(" · ") || "Starting…"
                        : c.status.last_error || "Not running"}
                    </Typography>
                  </CardActionArea>
                </Card>
              ))}
            </Box>
          ) : (
            <Typography variant="body2" color="text.secondary">
              No cameras yet. <Button component={RouterLink} to="/cameras" size="small">Add one</Button>
            </Typography>
          )}
        </CardContent>
      </Card>

      <Box sx={{ display: "grid", gap: 2, gridTemplateColumns: { xs: "1fr", lg: "minmax(0, 3fr) minmax(0, 2fr)" }, alignItems: "start" }}>
        <Card>
          <CardHeader
            title="Latest events"
            titleTypographyProps={{ variant: "subtitle1", fontWeight: 700 }}
            action={<Button component={RouterLink} to="/events" size="small">All events</Button>}
            sx={{ pb: 0 }}
          />
          <CardContent sx={{ pt: 1 }}>
            {latest.loading && !latest.data ? (
              Array.from({ length: 4 }, (_, i) => <Skeleton key={i} height={64} />)
            ) : latest.data?.items.length ? (
              <List disablePadding>
                {latest.data.items.map((e) => (
                  <ListItem
                    key={e.id}
                    disablePadding
                    secondaryAction={
                      e.status === "open" && hasWsRole("operator") ? (
                        <Tooltip title="Acknowledge">
                          <IconButton edge="end" size="small" onClick={() => acknowledge(e)} aria-label={`Acknowledge event ${e.id}`}>
                            <CheckIcon fontSize="small" />
                          </IconButton>
                        </Tooltip>
                      ) : null
                    }
                  >
                    <ListItemButton component={RouterLink} to={`/events/${e.id}`} sx={{ gap: 1.5, borderRadius: 1.5, pr: 7 }}>
                      <Snapshot event={e} />
                      <Box sx={{ minWidth: 0, flexGrow: 1 }}>
                        <Stack direction="row" spacing={1} alignItems="center">
                          <Typography variant="body2" noWrap sx={{ fontWeight: 600 }}>{kindLabel(e.kind)}: {e.label}</Typography>
                          <SeverityChip severity={e.severity} />
                        </Stack>
                        <Typography variant="caption" color="text.secondary" noWrap sx={{ display: "block" }}>
                          {e.camera_name} · {formatDateTime(e.occurred_at)}
                        </Typography>
                      </Box>
                      <Box sx={{ display: { xs: "none", sm: "block" } }}><EventStatusChip status={e.status} /></Box>
                    </ListItemButton>
                  </ListItem>
                ))}
              </List>
            ) : (
              <Typography variant="body2" color="text.secondary" sx={{ py: 2 }}>
                Nothing yet. Cameras running a pipeline that raises events (restricted zone, falls, abandoned objects, PPE) report here.
              </Typography>
            )}
          </CardContent>
        </Card>

        <Card>
          <CardHeader
            title="Live feed"
            subheader="Since you opened the console"
            titleTypographyProps={{ variant: "subtitle1", fontWeight: 700 }}
            sx={{ pb: 0 }}
          />
          <CardContent sx={{ pt: 1 }}>
            {pushed.length ? (
              <List dense disablePadding aria-live="polite">
                {pushed.slice(0, 12).map((e) => (
                  <ListItem key={e.id} disableGutters>
                    <Stack direction="row" spacing={1} alignItems="center" sx={{ width: "100%", minWidth: 0 }}>
                      <SeverityChip severity={e.severity} />
                      <Typography variant="body2" noWrap sx={{ flexGrow: 1, minWidth: 0 }}>
                        {kindLabel(e.kind)}: {e.label} · {e.camera_name}
                      </Typography>
                      <Typography variant="caption" color="text.secondary" noWrap>{ago(e.occurred_at)}</Typography>
                    </Stack>
                  </ListItem>
                ))}
              </List>
            ) : (
              <Typography variant="body2" color="text.secondary" sx={{ py: 2 }}>Waiting for the next event…</Typography>
            )}
          </CardContent>
        </Card>
      </Box>
    </Box>
  );
}
