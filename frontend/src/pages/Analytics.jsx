import { useMemo, useState } from "react";
import Box from "@mui/material/Box";
import Button from "@mui/material/Button";
import Card from "@mui/material/Card";
import CardContent from "@mui/material/CardContent";
import LinearProgress from "@mui/material/LinearProgress";
import MenuItem from "@mui/material/MenuItem";
import Stack from "@mui/material/Stack";
import Table from "@mui/material/Table";
import TableBody from "@mui/material/TableBody";
import TableCell from "@mui/material/TableCell";
import TableContainer from "@mui/material/TableContainer";
import TableHead from "@mui/material/TableHead";
import TableRow from "@mui/material/TableRow";
import TextField from "@mui/material/TextField";
import ToggleButton from "@mui/material/ToggleButton";
import ToggleButtonGroup from "@mui/material/ToggleButtonGroup";
import Typography from "@mui/material/Typography";
import { alpha, useTheme } from "@mui/material/styles";
import DownloadIcon from "@mui/icons-material/Download";
import NotificationsActiveIcon from "@mui/icons-material/NotificationsActive";
import ReportIcon from "@mui/icons-material/Report";
import TimerIcon from "@mui/icons-material/Timer";
import DoNotDisturbIcon from "@mui/icons-material/DoNotDisturb";
import InsightsIcon from "@mui/icons-material/Insights";
import {
  BarElement,
  CategoryScale,
  Chart as ChartJS,
  Legend,
  LinearScale,
  LineElement,
  PointElement,
  Tooltip as ChartTooltip,
} from "chart.js";
import { Bar, Line } from "react-chartjs-2";

import { analytics, cameras } from "../api/endpoints";
import { metricLabel } from "../components/cameras/CameraBits";
import { EmptyState, ErrorState, Loading } from "../components/DataStates";
import { STATUS_LABEL, kindLabel } from "../components/events/EventBits";
import HourHeatmap from "../components/HourHeatmap";
import PageHeader from "../components/PageHeader";
import StatCard from "../components/StatCard";
import { useToast } from "../components/Toast";
import { useAsync } from "../hooks/useAsync";
import { CHART_SERIES, SEVERITY_COLORS } from "../utils/theme";
import { useWorkspace } from "../workspace/WorkspaceContext";

ChartJS.register(CategoryScale, LinearScale, BarElement, LineElement, PointElement, ChartTooltip, Legend);

const WINDOWS = [
  { value: 1, label: "24 h" },
  { value: 7, label: "7 days" },
  { value: 30, label: "30 days" },
  { value: 90, label: "90 days" },
];
// Buckets are cut in the viewer's zone, so "busiest hour" means their hour.
const TIMEZONE = Intl.DateTimeFormat().resolvedOptions().timeZone || "UTC";
const AGG_HINT = { avg: "average", max: "highest", sum: "total" };

function duration(s) {
  if (s == null) return "—";
  if (s < 90) return `${Math.round(s)} s`;
  if (s < 5400) return `${Math.round(s / 60)} min`;
  return `${(s / 3600).toFixed(1)} h`;
}

function bucketLabel(iso, hourly) {
  const d = new Date(iso); // naive local wall-clock time from the API
  return hourly
    ? d.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })
    : d.toLocaleDateString([], { month: "short", day: "numeric" });
}

function ChartCard({ title, subtitle, children, action }) {
  return (
    <Card sx={{ height: "100%" }}>
      <CardContent>
        <Stack direction="row" justifyContent="space-between" alignItems="flex-start" spacing={1}>
          <Box>
            <Typography variant="subtitle2">{title}</Typography>
            {subtitle && <Typography variant="caption" color="text.secondary">{subtitle}</Typography>}
          </Box>
          {action}
        </Stack>
        <Box sx={{ mt: 2 }}>{children}</Box>
      </CardContent>
    </Card>
  );
}

/** Shared chart.js styling: recessive grid and axes in text tokens, thin marks, hover tooltips. */
function useChartBase() {
  const theme = useTheme();
  return useMemo(() => {
    const ink = theme.palette.text.secondary;
    const grid = alpha(theme.palette.text.primary, 0.08);
    const surface = theme.palette.mode === "dark" ? "#0E131F" : "#ffffff";
    return {
      surface,
      series: CHART_SERIES[theme.palette.mode === "dark" ? "dark" : "light"],
      options: {
        responsive: true,
        maintainAspectRatio: false,
        animation: false,
        plugins: {
          legend: { labels: { color: ink, boxWidth: 12, boxHeight: 12, usePointStyle: true, pointStyle: "rectRounded" } },
          tooltip: { backgroundColor: theme.palette.mode === "dark" ? "#1e2433" : "#0b0b0b", padding: 10, cornerRadius: 6 },
        },
        scales: {
          x: { ticks: { color: ink, maxRotation: 0, autoSkipPadding: 12 }, grid: { display: false }, border: { color: grid } },
          y: { beginAtZero: true, ticks: { color: ink, precision: 0 }, grid: { color: grid }, border: { display: false } },
        },
      },
    };
  }, [theme]);
}

/** One horizontal bar per row, one hue: a ranking, so no legend. */
function RankBars({ rows, label, value, color, base }) {
  const data = {
    labels: rows.map(label),
    datasets: [{ data: rows.map(value), backgroundColor: color, borderRadius: 4, borderSkipped: "start", barThickness: 14 }],
  };
  const options = {
    ...base.options,
    indexAxis: "y",
    plugins: { ...base.options.plugins, legend: { display: false } },
    scales: {
      x: { ...base.options.scales.y, grid: { color: base.options.scales.y.grid.color } },
      y: { ...base.options.scales.x, ticks: { ...base.options.scales.x.ticks, autoSkip: false } },
    },
  };
  return <Box sx={{ height: Math.max(120, rows.length * 30 + 30) }}><Bar data={data} options={options} /></Box>;
}

export default function Analytics() {
  const theme = useTheme();
  const toast = useToast();
  const base = useChartBase();
  const { active } = useWorkspace();
  const wid = active?.id;
  const [days, setDays] = useState(7);
  const [cameraId, setCameraId] = useState("");
  const [metric, setMetric] = useState("");
  const params = { days, tz: TIMEZONE, ...(cameraId ? { camera_id: cameraId } : {}) };

  const cams = useAsync((o) => (wid ? cameras.list(o) : null), [wid]);
  const sum = useAsync((o) => (wid ? analytics.summary(params, o) : null), [wid, days, cameraId]);
  const met = useAsync((o) => (wid ? analytics.metrics({ ...params, ...(metric ? { name: metric } : {}) }, o) : null), [wid, days, cameraId, metric]);

  // A camera keeps its colour slot whatever the filter: slot = its position among the workspace's cameras.
  const slotOf = useMemo(() => {
    const ids = (cams.data || []).map((c) => c.id).sort((a, b) => a - b);
    return (id) => base.series[Math.max(0, ids.indexOf(id)) % base.series.length];
  }, [cams.data, base.series]);

  if (!active) return <EmptyState title="No workspace yet" description="Analytics cover a workspace's cameras." />;
  if (sum.error) return <ErrorState error={sum.error} onRetry={sum.reload} />;
  const s = sum.data;
  const hourly = s?.window.bucket === "hour";

  async function exportCsv() {
    try {
      const blob = await analytics.eventsCsv(params);
      const a = document.createElement("a");
      a.href = URL.createObjectURL(blob);
      a.download = `events-${active.slug}-${days}d.csv`;
      a.click();
      setTimeout(() => URL.revokeObjectURL(a.href), 1000);
    } catch (e) {
      toast(e.message, "err");
    }
  }

  const severities = ["critical", "warning", "info"];
  const trend = s && {
    labels: s.series.map((b) => bucketLabel(b.bucket_start, hourly)),
    // only the severities that occur: an empty legend entry is noise
    datasets: severities.filter((sev) => s.series.some((b) => b[sev])).map((sev) => ({
      label: sev[0].toUpperCase() + sev.slice(1),
      data: s.series.map((b) => b[sev]),
      backgroundColor: SEVERITY_COLORS[sev],
      borderColor: base.surface, // the 2px gap between stacked segments
      borderWidth: { top: 2 },
      borderRadius: 4,
      borderSkipped: "bottom",
      maxBarThickness: 28,
    })),
  };
  const trendOptions = {
    ...base.options,
    interaction: { mode: "index", intersect: false },
    scales: { x: { ...base.options.scales.x, stacked: true }, y: { ...base.options.scales.y, stacked: true } },
  };

  const m = met.data;
  const metricData = m?.name && {
    labels: m.buckets.map((b) => bucketLabel(b, hourly)),
    datasets: m.series.map((line) => ({
      label: line.camera_name,
      data: line.values,
      borderColor: slotOf(line.camera_id),
      backgroundColor: slotOf(line.camera_id),
      borderWidth: 2,
      pointRadius: 2.5, // a lone bucket between gaps must still show
      pointHoverRadius: 5,
      pointHoverBorderColor: base.surface,
      pointHoverBorderWidth: 2,
      spanGaps: false,
      tension: 0.25,
    })),
  };
  const metricOptions = {
    ...base.options,
    interaction: { mode: "index", intersect: false }, // crosshair-like: every camera at the hovered time
    plugins: { ...base.options.plugins, legend: { ...base.options.plugins.legend, display: (m?.series.length || 0) > 1 } },
    scales: { ...base.options.scales, y: { ...base.options.scales.y, ticks: { color: theme.palette.text.secondary } } },
  };

  const statusTotal = s ? Object.values(s.by_status).reduce((a, b) => a + b, 0) : 0;

  return (
    <Box>
      <PageHeader
        title="Analytics"
        subtitle={`${active.name}: events and what the cameras measured, in ${TIMEZONE} time.`}
        actions={
          <Stack direction="row" spacing={1.5} useFlexGap flexWrap="wrap" alignItems="center">
            <ToggleButtonGroup size="small" exclusive value={days} onChange={(_, v) => v && setDays(v)} aria-label="Time window">
              {WINDOWS.map((w) => <ToggleButton key={w.value} value={w.value}>{w.label}</ToggleButton>)}
            </ToggleButtonGroup>
            <TextField select size="small" label="Camera" value={cameraId} onChange={(e) => setCameraId(e.target.value)}
              SelectProps={{ displayEmpty: true }} InputLabelProps={{ shrink: true }} sx={{ minWidth: 160 }}>
              <MenuItem value="">All cameras</MenuItem>
              {(cams.data || []).map((c) => <MenuItem key={c.id} value={c.id}>{c.name}</MenuItem>)}
            </TextField>
            <Button startIcon={<DownloadIcon />} onClick={exportCsv} disabled={!s?.kpis.events}>CSV</Button>
          </Stack>
        }
      />
      {!s ? (
        <Loading />
      ) : (
        <Stack spacing={2}>
          <Box sx={{ display: "grid", gap: 2, gridTemplateColumns: { xs: "repeat(2, minmax(0, 1fr))", md: "repeat(3, minmax(0, 1fr))", lg: "repeat(5, minmax(0, 1fr))" } }}>
            <StatCard dense label="Events" value={s.kpis.events} icon={<NotificationsActiveIcon />} />
            <StatCard dense label="Still open" value={s.kpis.open} icon={<InsightsIcon />} color="warning" />
            <StatCard dense label="Critical" value={s.kpis.critical} icon={<ReportIcon />} color="error" />
            <StatCard dense label="False alarms" value={s.kpis.false_positive_pct == null ? "—" : `${s.kpis.false_positive_pct}%`}
              hint={`${s.kpis.false_positives} dismissed`} icon={<DoNotDisturbIcon />} color="info" />
            <StatCard dense label="Median time to handle" value={duration(s.kpis.median_handle_s)} icon={<TimerIcon />} color="success" />
          </Box>

          <ChartCard title="Events over time" subtitle={`Per ${hourly ? "hour" : "day"}, by severity`}>
            {s.kpis.events ? (
              <Box sx={{ height: 260 }}><Bar data={trend} options={trendOptions} aria-label="Events over time by severity" /></Box>
            ) : (
              <Typography variant="body2" color="text.secondary" sx={{ py: 6, textAlign: "center" }}>No events in this window.</Typography>
            )}
          </ChartCard>

          <Box sx={{ display: "grid", gap: 2, gridTemplateColumns: { xs: "1fr", lg: "repeat(3, minmax(0, 1fr))" } }}>
            <ChartCard title="By kind" subtitle="What was raised most">
              {s.by_kind.length ? (
                <RankBars rows={s.by_kind} label={(r) => kindLabel(r.kind)} value={(r) => r.events} color={base.series[0]} base={base} />
              ) : <Typography variant="body2" color="text.secondary">—</Typography>}
            </ChartCard>
            <ChartCard title="By camera" subtitle="Where it happened">
              {s.by_camera.length ? (
                <RankBars rows={s.by_camera.slice(0, 10)} label={(r) => r.camera_name} value={(r) => r.events} color={base.series[0]} base={base} />
              ) : <Typography variant="body2" color="text.secondary">—</Typography>}
            </ChartCard>
            <ChartCard title="How events were handled" subtitle="Share of the window's events">
              <Stack spacing={1.75}>
                {Object.entries(STATUS_LABEL).map(([k, label]) => {
                  const v = s.by_status[k] || 0;
                  return (
                    <Box key={k}>
                      <Stack direction="row" justifyContent="space-between">
                        <Typography variant="body2">{label}</Typography>
                        <Typography variant="body2" sx={{ fontWeight: 600 }}>{v}</Typography>
                      </Stack>
                      <LinearProgress variant="determinate" value={statusTotal ? (100 * v) / statusTotal : 0}
                        aria-label={`${label}: ${v}`} sx={{ height: 8, borderRadius: 4, my: 0.5 }} />
                    </Box>
                  );
                })}
              </Stack>
            </ChartCard>
          </Box>

          <ChartCard title="When events happen" subtitle={`Weekday × hour, ${TIMEZONE}`}>
            <HourHeatmap cells={s.heatmap} />
          </ChartCard>

          <ChartCard
            title={m?.name ? `${metricLabel(m.name)} (${AGG_HINT[m.agg]} per ${hourly ? "hour" : "day"})` : "Measured by the cameras"}
            subtitle="What the live pipelines counted, per camera"
            action={
              m?.names?.length > 0 && (
                <TextField select size="small" label="Metric" value={m.name || ""} onChange={(e) => setMetric(e.target.value)} sx={{ minWidth: 170 }}>
                  {[...m.names].sort((a, b) => metricLabel(a.name).localeCompare(metricLabel(b.name))).map((n) => (
                    <MenuItem key={n.name} value={n.name}>{metricLabel(n.name)}</MenuItem>
                  ))}
                </TextField>
              )
            }
          >
            {met.error ? (
              <ErrorState error={met.error} onRetry={met.reload} />
            ) : !m ? (
              <Loading height={120} />
            ) : m.name ? (
              <>
                <Box sx={{ height: 260 }}><Line data={metricData} options={metricOptions} aria-label={`${metricLabel(m.name)} per camera`} /></Box>
                {/* The table view: the same numbers without needing the colours. */}
                <TableContainer sx={{ mt: 2 }}>
                <Table size="small">
                  <TableHead>
                    <TableRow>
                      <TableCell>Camera</TableCell>
                      <TableCell align="right">Highest</TableCell>
                      <TableCell align="right">Average</TableCell>
                      {m.agg === "sum" && <TableCell align="right">Total</TableCell>}
                    </TableRow>
                  </TableHead>
                  <TableBody>
                    {m.series.map((line) => {
                      const vals = line.values.filter((v) => v != null);
                      const total = vals.reduce((a, b) => a + b, 0);
                      return (
                        <TableRow key={line.camera_id}>
                          <TableCell>
                            <Stack direction="row" spacing={1} alignItems="center">
                              <Box sx={{ width: 10, height: 10, borderRadius: "3px", bgcolor: slotOf(line.camera_id), flexShrink: 0 }} />
                              <span>{line.camera_name}</span>
                            </Stack>
                          </TableCell>
                          <TableCell align="right">{vals.length ? Math.max(...vals).toFixed(1) : "—"}</TableCell>
                          <TableCell align="right">{vals.length ? (total / vals.length).toFixed(1) : "—"}</TableCell>
                          {m.agg === "sum" && <TableCell align="right">{total.toFixed(0)}</TableCell>}
                        </TableRow>
                      );
                    })}
                  </TableBody>
                </Table>
                </TableContainer>
              </>
            ) : (
              <Typography variant="body2" color="text.secondary" sx={{ py: 4, textAlign: "center" }}>
                Nothing measured in this window. Cameras running a pipeline record counts every minute.
              </Typography>
            )}
          </ChartCard>
        </Stack>
      )}
    </Box>
  );
}
