import { Link as RouterLink, useNavigate } from "react-router-dom";
import Box from "@mui/material/Box";
import Button from "@mui/material/Button";
import Card from "@mui/material/Card";
import CardActionArea from "@mui/material/CardActionArea";
import CardContent from "@mui/material/CardContent";
import CardHeader from "@mui/material/CardHeader";
import Chip from "@mui/material/Chip";
import Grid from "@mui/material/Grid2";
import LinearProgress from "@mui/material/LinearProgress";
import Stack from "@mui/material/Stack";
import Typography from "@mui/material/Typography";
import CheckCircleIcon from "@mui/icons-material/CheckCircle";
import ConstructionIcon from "@mui/icons-material/Construction";
import EventNoteIcon from "@mui/icons-material/EventNote";
import DonutLargeIcon from "@mui/icons-material/DonutLarge";

import { me } from "../api/endpoints";
import { EmptyState, ErrorState, Loading } from "../components/DataStates";
import PageHeader from "../components/PageHeader";
import { ProjectTag } from "../components/ProjectCard";
import StatCard from "../components/StatCard";
import { ProgressBar, StatusChip } from "../components/StatusChips";
import { useAsync } from "../hooks/useAsync";
import { formatDate, pad } from "../utils/format";

const COLUMNS = ["planned", "building", "done"];

export default function Board() {
  const navigate = useNavigate();
  const stats = useAsync((opts) => me.stats(opts), []);
  const mine = useAsync((opts) => me.progress(opts), []);
  const s = stats.data;
  const items = mine.data || [];
  const noteOnly = items.filter((p) => p.progress.status === "idea");

  return (
    <Box>
      <PageHeader
        title="My board"
        subtitle="Everything you are planning, building or have finished, and how far along each domain is."
        actions={<Button component={RouterLink} to="/?view=board">Show in catalog</Button>}
      />
      <ErrorState error={stats.error || mine.error} onRetry={() => { stats.reload(); mine.reload(); }} />
      {!s && !stats.error && <Loading label="Loading your board…" />}

      {s && (
        <>
          <Grid container spacing={2} sx={{ mb: 2 }}>
            <Grid size={{ xs: 6, md: 3 }}><StatCard label="Done" value={s.counts.done} icon={<CheckCircleIcon />} color="success" /></Grid>
            <Grid size={{ xs: 6, md: 3 }}><StatCard label="Building" value={s.counts.building} icon={<ConstructionIcon />} color="warning" /></Grid>
            <Grid size={{ xs: 6, md: 3 }}><StatCard label="Planned" value={s.counts.planned} icon={<EventNoteIcon />} color="primary" /></Grid>
            <Grid size={{ xs: 6, md: 3 }}>
              <StatCard label="Completion" value={`${Math.round((s.counts.done / Math.max(s.total, 1)) * 100)}%`} hint={`of ${s.total} projects`} icon={<DonutLargeIcon />} color="info" />
            </Grid>
          </Grid>

          <Card sx={{ mb: 3 }}>
            <CardHeader title="Progress by domain" titleTypographyProps={{ variant: "subtitle1", fontWeight: 700 }}
              subheader={<Box sx={{ mt: 1 }}><ProgressBar counts={s.counts} total={s.total} label="Overall progress" /></Box>} />
            <CardContent sx={{ pt: 0 }}>
              <Box role="table" aria-label="Progress by domain" sx={{ display: "grid", gap: 0.5 }}>
                {s.by_domain.map((d) => (
                  <Box
                    key={d.code}
                    role="row"
                    component={RouterLink}
                    to={`/?domain=${d.code}&view=board`}
                    sx={{
                      display: "grid", gridTemplateColumns: { xs: "minmax(0, 1fr) 56px", sm: "220px minmax(0, 1fr) 56px" }, alignItems: "center",
                      gap: 2, py: 0.75, px: 1, borderRadius: 2, color: "inherit", textDecoration: "none",
                      "&:hover": { bgcolor: "action.hover" },
                    }}
                  >
                    <Typography role="cell" variant="body2" noWrap sx={{ fontWeight: 600 }}>{d.name}</Typography>
                    <Box role="cell" aria-label={`${d.done} done, ${d.started} started of ${d.total}`} sx={{ display: { xs: "none", sm: "block" } }}>
                      <LinearProgress
                        variant="buffer"
                        color="success"
                        value={(d.done / d.total) * 100}
                        valueBuffer={(d.started / d.total) * 100}
                        sx={{ height: 8, borderRadius: 99, bgcolor: "action.hover", "& .MuiLinearProgress-dashed": { display: "none" } }}
                      />
                    </Box>
                    <Typography role="cell" variant="caption" color="text.secondary" align="right">{d.done}/{d.total}</Typography>
                  </Box>
                ))}
              </Box>
            </CardContent>
          </Card>
        </>
      )}

      {mine.data && items.length === 0 && (
        <EmptyState
          title="Nothing tracked yet"
          description="Open a project in the catalog and set it to Planned, Building or Done."
          action={<Button component={RouterLink} to="/" variant="contained">Open the catalog</Button>}
        />
      )}

      {items.length > 0 && (
        <Box sx={{ display: "grid", gridTemplateColumns: { xs: "minmax(0, 1fr)", md: "repeat(3, minmax(0, 1fr))" }, gap: 2, alignItems: "start" }}>
          {COLUMNS.map((col) => {
            const list = items.filter((p) => p.progress.status === col);
            return (
              <Card key={col} component="section" sx={{ bgcolor: "background.default" }}>
                <Stack direction="row" justifyContent="space-between" alignItems="center" sx={{ px: 2, py: 1.5 }}>
                  <StatusChip status={col} />
                  <Typography variant="caption" color="text.secondary" sx={{ fontWeight: 700 }}>{list.length}</Typography>
                </Stack>
                <Stack spacing={1} sx={{ px: 1.5, pb: 1.5 }}>
                  {list.length === 0 && <Typography variant="body2" color="text.secondary" sx={{ px: 0.5 }}>No projects here yet.</Typography>}
                  {list.map((p) => (
                    <Card key={p.id}>
                      <CardActionArea onClick={() => navigate(`/projects/${p.id}`)} sx={{ p: 1.5, display: "grid", gap: 0.5 }}>
                        <ProjectTag project={p} />
                        <Typography variant="subtitle2">{p.title}</Typography>
                        {p.progress.notes && (
                          <Typography variant="body2" color="text.secondary" sx={{ display: "-webkit-box", WebkitLineClamp: 2, WebkitBoxOrient: "vertical", overflow: "hidden" }}>
                            {p.progress.notes}
                          </Typography>
                        )}
                        <Typography variant="caption" color="text.secondary">{p.domain.name} · updated {formatDate(p.progress.updated_at)}</Typography>
                      </CardActionArea>
                    </Card>
                  ))}
                </Stack>
              </Card>
            );
          })}
        </Box>
      )}

      {noteOnly.length > 0 && (
        <Box component="section" sx={{ mt: 3 }}>
          <Typography variant="overline" color="text.secondary" sx={{ fontWeight: 700 }}>Ideas with notes</Typography>
          <Stack direction="row" spacing={0.75} useFlexGap flexWrap="wrap" sx={{ mt: 0.5 }}>
            {noteOnly.map((p) => (
              <Chip key={p.id} clickable component={RouterLink} to={`/projects/${p.id}`} variant="outlined" label={`#${pad(p.id)} ${p.title}`} />
            ))}
          </Stack>
        </Box>
      )}
    </Box>
  );
}
