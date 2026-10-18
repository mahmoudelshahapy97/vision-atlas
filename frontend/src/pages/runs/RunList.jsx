import { useMemo, useState } from "react";
import { Link as RouterLink, useNavigate } from "react-router-dom";
import Box from "@mui/material/Box";
import Button from "@mui/material/Button";
import Card from "@mui/material/Card";
import CardActionArea from "@mui/material/CardActionArea";
import CardContent from "@mui/material/CardContent";
import CardMedia from "@mui/material/CardMedia";
import InputAdornment from "@mui/material/InputAdornment";
import Stack from "@mui/material/Stack";
import TextField from "@mui/material/TextField";
import ToggleButton from "@mui/material/ToggleButton";
import ToggleButtonGroup from "@mui/material/ToggleButtonGroup";
import Typography from "@mui/material/Typography";
import RefreshIcon from "@mui/icons-material/Refresh";
import ImageNotSupportedIcon from "@mui/icons-material/ImageNotSupported";
import SearchIcon from "@mui/icons-material/Search";

import { mediaUrl } from "../../api/client";
import { runs as runsApi } from "../../api/endpoints";
import { EmptyState, ErrorState, SkeletonCards } from "../../components/DataStates";
import PageHeader from "../../components/PageHeader";
import { RunStatusChip } from "../../components/StatusChips";
import { usePolling } from "../../hooks/usePolling";
import { RUN_LIST_POLL_MS, isRunActive } from "../../utils/constants";
import { formatDateTime, formatDurationMs } from "../../utils/format";

/** A run's first image or video snapshot; a quiet placeholder when there is none or it won't load. */
export function RunThumb({ src, height = 150 }) {
  const [failed, setFailed] = useState(null);
  return src && failed !== src ? (
    <CardMedia component="img" image={mediaUrl(src)} alt="" loading="lazy" onError={() => setFailed(src)}
      sx={{ height, objectFit: "cover", bgcolor: "action.hover" }} />
  ) : (
    <Stack spacing={0.5} alignItems="center" justifyContent="center" sx={{ height, bgcolor: "action.hover", color: "text.disabled" }}>
      <ImageNotSupportedIcon />
      <Typography variant="caption">No preview</Typography>
    </Stack>
  );
}

const STATUS_FILTERS = [
  ["all", "All", () => true],
  ["done", "Done", (r) => r.status === "done"],
  ["active", "Running", isRunActive],
  ["error", "Failed", (r) => r.status === "error"],
];

/** The signed-in user's run history across every lab. Follows queued and running runs live. */
export default function RunList() {
  const runs = usePolling((opts) => runsApi.list({ limit: 100 }, opts), {
    intervalMs: RUN_LIST_POLL_MS, keepPolling: (list) => list.some(isRunActive),
  });
  const navigate = useNavigate();
  const [status, setStatus] = useState("all");
  const [q, setQ] = useState("");

  const all = runs.data || [];
  const shown = useMemo(() => {
    const test = STATUS_FILTERS.find(([k]) => k === status)[2];
    const s = q.trim().toLowerCase();
    return all.filter((r) => test(r) && (!s || `${r.project_title || ""} ${r.pipeline}`.toLowerCase().includes(s)));
  }, [all, status, q]);

  return (
    <Box>
      <PageHeader
        title="My runs"
        subtitle="Every lab run you have started, newest first."
        actions={<Button onClick={runs.reload} startIcon={<RefreshIcon />}>Refresh</Button>}
      />
      {all.length > 0 && (
        <Stack direction={{ xs: "column", sm: "row" }} spacing={1.5} alignItems={{ sm: "center" }} sx={{ mb: 2 }}>
          <TextField
            type="search"
            size="small"
            value={q}
            onChange={(e) => setQ(e.target.value)}
            placeholder="Filter by project or pipeline"
            inputProps={{ "aria-label": "Filter runs" }}
            sx={{ flexGrow: 1, maxWidth: { sm: 420 } }}
            InputProps={{ startAdornment: <InputAdornment position="start"><SearchIcon fontSize="small" /></InputAdornment> }}
          />
          <ToggleButtonGroup size="small" exclusive value={status} onChange={(_, v) => v && setStatus(v)} aria-label="Run status">
            {STATUS_FILTERS.map(([k, l, test]) => (
              <ToggleButton key={k} value={k}>
                {l}
                <Typography component="span" variant="caption" color="text.secondary" sx={{ ml: 0.75, fontWeight: 600 }}>
                  {all.filter(test).length}
                </Typography>
              </ToggleButton>
            ))}
          </ToggleButtonGroup>
        </Stack>
      )}
      <ErrorState error={runs.error} onRetry={runs.reload} />
      {all.length > 0 && shown.length === 0 && (
        <EmptyState
          title="No runs match"
          description="Try another word or status."
          action={<Button variant="outlined" onClick={() => { setQ(""); setStatus("all"); }}>Show all runs</Button>}
        />
      )}
      {runs.data?.length === 0 && (
        <EmptyState
          title="No runs yet"
          description="Open any project and press “Try it in the lab”."
          action={<Button component={RouterLink} to="/" variant="contained">Open the catalog</Button>}
        />
      )}
      <Box sx={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(260px, 1fr))", gap: 2 }}>
        {!runs.data && runs.loading && <SkeletonCards count={8} height={250} />}
        {shown.map((r) => (
          <Card key={r.public_id}>
            <CardActionArea onClick={() => navigate(`/runs/${r.public_id}`)} sx={{ height: "100%", display: "flex", flexDirection: "column", alignItems: "stretch" }}>
              <RunThumb src={r.thumbnail} />
              <CardContent sx={{ display: "grid", gap: 0.5, flexGrow: 1 }}>
                <Stack direction="row" justifyContent="space-between" alignItems="flex-start" spacing={1}>
                  <Typography variant="subtitle2" sx={{ minWidth: 0 }}>{r.project_title || r.pipeline}</Typography>
                  <RunStatusChip status={r.status} />
                </Stack>
                <Typography variant="caption" color="text.secondary">{formatDateTime(r.created_at)} · {formatDurationMs(r.duration_ms)}</Typography>
                {r.summary?.length > 0 && (
                  <Typography variant="body2">{r.summary.slice(0, 2).map((s) => `${s.label}: ${s.value}`).join(" · ")}</Typography>
                )}
                {r.error && <Typography variant="body2" color="error.main" sx={{ wordBreak: "break-word" }}>{r.error}</Typography>}
              </CardContent>
            </CardActionArea>
          </Card>
        ))}
      </Box>
    </Box>
  );
}
