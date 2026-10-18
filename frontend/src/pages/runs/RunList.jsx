import { useState } from "react";
import { Link as RouterLink, useNavigate } from "react-router-dom";
import Box from "@mui/material/Box";
import Button from "@mui/material/Button";
import Card from "@mui/material/Card";
import CardActionArea from "@mui/material/CardActionArea";
import CardContent from "@mui/material/CardContent";
import CardMedia from "@mui/material/CardMedia";
import Stack from "@mui/material/Stack";
import Typography from "@mui/material/Typography";
import RefreshIcon from "@mui/icons-material/Refresh";
import ImageNotSupportedIcon from "@mui/icons-material/ImageNotSupported";

import { mediaUrl } from "../../api/client";
import { runs as runsApi } from "../../api/endpoints";
import { EmptyState, ErrorState, SkeletonCards } from "../../components/DataStates";
import PageHeader from "../../components/PageHeader";
import { RunStatusChip } from "../../components/StatusChips";
import { useAsync } from "../../hooks/useAsync";
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

/** The signed-in user's run history across every lab. */
export default function RunList() {
  const runs = useAsync((opts) => runsApi.list({ limit: 100 }, opts), []);
  const navigate = useNavigate();
  return (
    <Box>
      <PageHeader
        title="My runs"
        subtitle="Every lab run you have started, newest first."
        actions={<Button onClick={runs.reload} startIcon={<RefreshIcon />}>Refresh</Button>}
      />
      <ErrorState error={runs.error} onRetry={runs.reload} />
      {runs.data?.length === 0 && (
        <EmptyState
          title="No runs yet"
          description="Open any project and press “Try it in the lab”."
          action={<Button component={RouterLink} to="/" variant="contained">Open the catalog</Button>}
        />
      )}
      <Box sx={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(260px, 1fr))", gap: 2 }}>
        {!runs.data && runs.loading && <SkeletonCards count={8} height={250} />}
        {(runs.data || []).map((r) => (
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
