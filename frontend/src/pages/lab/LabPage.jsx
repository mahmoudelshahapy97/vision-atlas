import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Link as RouterLink, useParams } from "react-router-dom";
import Alert from "@mui/material/Alert";
import Box from "@mui/material/Box";
import Breadcrumbs from "@mui/material/Breadcrumbs";
import Button from "@mui/material/Button";
import ButtonBase from "@mui/material/ButtonBase";
import Card from "@mui/material/Card";
import CardHeader from "@mui/material/CardHeader";
import Grid from "@mui/material/Grid2";
import IconButton from "@mui/material/IconButton";
import Link from "@mui/material/Link";
import List from "@mui/material/List";
import ListItemButton from "@mui/material/ListItemButton";
import ListItemText from "@mui/material/ListItemText";
import Skeleton from "@mui/material/Skeleton";
import Stack from "@mui/material/Stack";
import Tab from "@mui/material/Tab";
import Tabs from "@mui/material/Tabs";
import Typography from "@mui/material/Typography";
import { alpha } from "@mui/material/styles";
import CloseIcon from "@mui/icons-material/Close";
import CloudUploadIcon from "@mui/icons-material/CloudUpload";
import PlayArrowIcon from "@mui/icons-material/PlayArrow";
import ScienceIcon from "@mui/icons-material/Science";
import StarIcon from "@mui/icons-material/Star";
import { mediaUrl } from "../../api/client";
import { lab as labApi, runs as runsApi } from "../../api/endpoints";
import { useAuth } from "../../auth/AuthContext";
import { EmptyState, ErrorState } from "../../components/DataStates";
import CanvasEditor from "../../components/lab/CanvasEditor";
import ParamForm, { GEOMETRY } from "../../components/lab/ParamForm";
import ResultView from "../../components/lab/ResultView";
import { RunStatusChip, SupportBadge } from "../../components/StatusChips";
import { useToast } from "../../components/Toast";
import { useAsync } from "../../hooks/useAsync";
import { usePolling } from "../../hooks/usePolling";
import { RUN_POLL_MS, isRunActive } from "../../utils/constants";
import { formatDateTime, pad } from "../../utils/format";
import { MONO_FONT } from "../../utils/theme";

const IMG = /\.(jpe?g|png|bmp|webp|tiff?)$/i;
const VID = /\.(mp4|mov|avi|mkv|webm|m4v|mpe?g)$/i;
const kindOf = (name) => (VID.test(name) ? "video" : IMG.test(name) ? "image" : "other");
// shown when the browser can't decode an uploaded video: you can still draw on a 16:9 frame
const BLANK = "data:image/svg+xml," + encodeURIComponent('<svg xmlns="http://www.w3.org/2000/svg" width="1280" height="720"><rect width="100%" height="100%" fill="#2a2f36"/><text x="640" y="360" fill="#9aa4b1" font-family="sans-serif" font-size="34" text-anchor="middle">Video preview unavailable — draw on this 16:9 frame</text></svg>');
const accept = { image: "image/*", images: "image/*", video: "video/*", media: "image/*,video/*" };

function defaultsFor(tab) {
  const v = {};
  for (const p of tab.params) v[p.name] = p.default ?? (p.type === "multiselect" || p.type === "polygons" || p.type === "points" ? [] : null);
  return { ...v, ...(tab.defaults || {}) };
}

async function videoFrame(url) {
  return new Promise((resolve) => {
    const v = document.createElement("video");
    v.muted = true;
    v.preload = "auto";
    v.crossOrigin = "anonymous";
    v.src = url;
    v.addEventListener("loadeddata", () => { v.currentTime = Math.min(0.5, (v.duration || 1) / 4); });
    v.addEventListener("seeked", () => {
      const c = document.createElement("canvas");
      c.width = v.videoWidth;
      c.height = v.videoHeight;
      c.getContext("2d").drawImage(v, 0, 0);
      try { resolve(c.toDataURL("image/jpeg", 0.85)); } catch { resolve(null); }
    });
    v.addEventListener("error", () => resolve(null));
    setTimeout(() => resolve(null), 6000);
  });
}

function SlotInput({ slot, items, setItems, samples }) {
  const ref = useRef(null);
  const [over, setOver] = useState(false);
  const many = slot.max > 1;
  const add = (files) => {
    const list = [...files].map((f) => ({ file: f, name: f.name, kind: kindOf(f.name), url: URL.createObjectURL(f) }));
    setItems(many ? [...items.filter((i) => !i.sample), ...list].slice(0, slot.max) : list.slice(0, 1));
  };
  const useSample = () => setItems(samples.map((s) => ({ sample: s.path, name: s.name, kind: kindOf(s.name), url: mediaUrl(s.url), poster: s.poster && mediaUrl(s.poster) })));
  return (
    <Box>
      <Stack direction="row" justifyContent="space-between" alignItems="center" sx={{ mb: 0.75 }}>
        <Typography variant="body2" sx={{ fontWeight: 600 }}>{slot.label}{slot.optional ? " (optional)" : ""}</Typography>
        {samples?.length > 0 && <Button size="small" onClick={useSample}>Use sample</Button>}
      </Stack>
      <Box
        onDragOver={(e) => { e.preventDefault(); setOver(true); }} onDragLeave={() => setOver(false)}
        onDrop={(e) => { e.preventDefault(); setOver(false); add(e.dataTransfer.files); }}
        sx={{
          border: "1.5px dashed",
          borderColor: (t) =>
            over ? t.palette.primary.main : t.palette.mode === "dark" ? "rgba(255, 255, 255, 0.16)" : t.palette.divider,
          borderRadius: 2,
          bgcolor: (t) => (over ? alpha(t.palette.primary.main, 0.08) : t.palette.surface.sunken),
          transition: "border-color .15s, background-color .15s",
        }}
      >
        {items.length === 0 ? (
          <ButtonBase
            onClick={() => ref.current?.click()}
            sx={{ width: "100%", py: 3, px: 1.5, borderRadius: 2, display: "flex", flexDirection: "column", gap: 0.75, color: "text.secondary" }}
          >
            <CloudUploadIcon />
            <Typography variant="body2">
              Drop {many ? "files" : slot.kind === "video" ? "a video" : slot.kind === "media" ? "an image or video" : "an image"} here, or browse
            </Typography>
          </ButtonBase>
        ) : (
          <Box sx={{ p: 1 }}>
            <Stack direction="row" spacing={1} useFlexGap flexWrap="wrap">
              {items.map((it, i) => (
                <Box key={i} sx={{ position: "relative", width: 104, "& img, & video": { width: 104, height: 78, objectFit: "cover", borderRadius: 1.5, display: "block", bgcolor: "action.hover" } }}>
                  {it.kind === "video" ? <video src={it.url} poster={it.poster} muted playsInline /> : <img src={it.url} alt={it.name} />}
                  <IconButton
                    size="small"
                    aria-label={`Remove ${it.name}`}
                    onClick={() => setItems(items.filter((_, j) => j !== i))}
                    sx={{ position: "absolute", top: 4, right: 4, p: 0.25, color: "#fff", bgcolor: "rgba(0, 0, 0, 0.55)", "&:hover": { bgcolor: "rgba(0, 0, 0, 0.75)" } }}
                  >
                    <CloseIcon sx={{ fontSize: 16 }} />
                  </IconButton>
                  <Typography variant="caption" color="text.secondary" noWrap title={it.name} component="div" sx={{ mt: 0.25 }}>
                    {it.sample ? "sample · " : ""}{it.name}
                  </Typography>
                </Box>
              ))}
            </Stack>
            <Stack direction="row" spacing={1} sx={{ mt: 1 }}>
              <Button size="small" variant="outlined" onClick={() => ref.current?.click()}>{many ? "Add / replace" : "Replace"}</Button>
              <Button size="small" color="inherit" onClick={() => setItems([])}>Clear</Button>
            </Stack>
          </Box>
        )}
        <input ref={ref} type="file" hidden multiple={many} accept={accept[slot.kind]} onChange={(e) => { add(e.target.files); e.target.value = ""; }} />
      </Box>
    </Box>
  );
}

export default function LabPage() {
  const { id } = useParams();
  const { user } = useAuth();
  const toast = useToast();
  const resultsRef = useRef(null);
  const lab = useAsync((opts) => labApi.forProject(id, opts), [id, user?.id]);
  const [tabIdx, setTabIdx] = useState(0);
  const [inputs, setInputs] = useState({});
  const [values, setValues] = useState({});
  const [activeGeo, setActiveGeo] = useState(null);
  // The run shown on the right: just submitted, or picked from history. Polled while active.
  const [runId, setRunId] = useState(null);
  const polled = usePolling((opts) => runsApi.get(runId, opts), {
    intervalMs: RUN_POLL_MS, enabled: Boolean(runId), deps: [runId], keepPolling: isRunActive,
  });
  const run = runId && polled.data?.public_id === runId ? polled.data : null;
  const [busy, setBusy] = useState(false);
  const [bg, setBg] = useState(null);
  const history = useAsync((opts) => (user ? runsApi.list({ project_id: id, limit: 12 }, opts) : Promise.resolve([])), [id, user?.id, run && !isRunActive(run) ? run.public_id : ""]);

  const data = lab.data;
  const tab = data?.tabs?.[tabIdx];

  useEffect(() => {
    if (!tab) return;
    setValues(defaultsFor(tab));
    setActiveGeo(null);
    const init = {};
    for (const s of tab.slots) {
      const smp = data.samples?.[s.name];
      if (smp?.length && tabIdx === 0) init[s.name] = smp.map((x) => ({ sample: x.path, name: x.name, kind: kindOf(x.name), url: mediaUrl(x.url), poster: x.poster && mediaUrl(x.poster) }));
      else init[s.name] = [];
    }
    setInputs(init);
  }, [tab, tabIdx, data]);

  // background for drawing: first image-like input of the first slot
  const firstItem = useMemo(() => tab?.slots.map((s) => inputs[s.name]?.[0]).find(Boolean), [tab, inputs]);
  useEffect(() => {
    let alive = true;
    if (!firstItem) return setBg(null);
    if (firstItem.kind === "video" && firstItem.poster) setBg(firstItem.poster);
    else if (firstItem.kind === "video") videoFrame(firstItem.url).then((u) => alive && setBg(u || BLANK));
    else setBg(firstItem.url);
    return () => { alive = false; };
  }, [firstItem]);

  useEffect(() => {
    if (polled.error) toast(polled.error.message, "err");
  }, [polled.error, toast]);

  const setValue = useCallback((k, v) => setValues((s) => ({ ...s, [k]: v })), []);
  const geoParams = tab ? tab.params.filter((p) => GEOMETRY.has(p.type)) : [];

  async function submit() {
    if (!user) return;
    setBusy(true);
    const fd = new FormData();
    fd.append("project_id", id);
    fd.append("pipeline", tab.name);
    const params = {};
    for (const p of tab.params) params[p.name] = values[p.name];
    if (values.model) params.model = values.model;
    fd.append("params", JSON.stringify(params));
    const samples = {};
    for (const s of tab.slots) {
      for (const it of inputs[s.name] || []) {
        if (it.sample) (samples[s.name] ||= []).push(it.sample);
        else if (it.file) fd.append(s.name, it.file, it.file.name);
      }
    }
    fd.append("samples", JSON.stringify(samples));
    try {
      const r = await runsApi.create(fd);
      polled.setData(r);
      setRunId(r.public_id);
      setActiveGeo(null);
      // After scrolling down a long form (or on a phone, where results sit
      // below it) the results start off screen; bring them up.
      const top = resultsRef.current?.getBoundingClientRect().top;
      if (top !== undefined && (top < 64 || top > window.innerHeight - 120)) {
        resultsRef.current.scrollIntoView({ behavior: "smooth", block: "start" });
      }
    } catch (e) {
      toast(e.message, "err");
    } finally {
      setBusy(false);
    }
  }

  const openRun = (pid) => setRunId(pid);

  const missing = tab?.slots.filter((s) => !s.optional && (inputs[s.name]?.length || 0) < s.min).map((s) => s.label) || [];

  if (lab.error) {
    return (
      <Box>
        <ErrorState error={lab.error} onRetry={lab.reload} />
        <Button component={RouterLink} to="/">Back to the catalog</Button>
      </Box>
    );
  }
  if (!data) {
    return (
      <Box>
        <Skeleton width={220} />
        <Skeleton variant="rounded" height={40} sx={{ my: 1, maxWidth: 520 }} />
        <Grid container spacing={3} sx={{ mt: 2 }}>
          <Grid size={{ xs: 12, md: 5, lg: 4 }}><Skeleton variant="rounded" height={420} /></Grid>
          <Grid size={{ xs: 12, md: 7, lg: 8 }}><Skeleton variant="rounded" height={300} /></Grid>
        </Grid>
      </Box>
    );
  }

  return (
    <Box>
      <Box component="header" sx={{ mb: 2.5 }}>
        <Breadcrumbs sx={{ mb: 0.75, "& .MuiBreadcrumbs-li": { fontSize: 13 } }}>
          <Link component={RouterLink} to="/" underline="hover" color="inherit">Catalog</Link>
          <Link component={RouterLink} to={`/projects/${data.project.id}`} underline="hover" color="inherit">
            <Box component="span" sx={{ fontFamily: MONO_FONT }}>#{pad(data.project.id)}</Box> · {data.project.domain}
          </Link>
          <Typography color="text.primary" sx={{ fontSize: 13 }}>Lab</Typography>
        </Breadcrumbs>
        <Typography variant="h5" component="h1">{data.project.title}</Typography>
        <Stack direction="row" spacing={1} alignItems="center" useFlexGap flexWrap="wrap" sx={{ mt: 1 }}>
          <SupportBadge level={data.support} />
          <Typography variant="body2" color="text.secondary">{data.support.description}</Typography>
        </Stack>
        {data.note && <Typography variant="body2" color="text.secondary" sx={{ mt: 1, maxWidth: "75ch" }}>{data.note}</Typography>}
        {data.project.caution && <Alert severity="warning" sx={{ mt: 1.5 }}>{data.project.caution}</Alert>}
      </Box>

      {data.tabs.length > 1 && (
        <Tabs
          value={tabIdx}
          onChange={(_, i) => { setTabIdx(i); setRunId(null); }}
          variant="scrollable"
          scrollButtons="auto"
          aria-label="Pipelines"
          sx={{ mb: 2.5, borderBottom: 1, borderColor: "divider" }}
        >
          {data.tabs.map((t, i) => (
            <Tab
              key={t.name}
              value={i}
              label={t.label}
              {...(i === 0 && { icon: <StarIcon sx={{ fontSize: 16 }} />, iconPosition: "start", title: "Recommended pipeline" })}
              sx={{ minHeight: 48 }}
            />
          ))}
        </Tabs>
      )}

      <Grid container spacing={3} alignItems="flex-start">
        <Grid size={{ xs: 12, md: 5, lg: 4 }}>
          <Card
            component="section"
            aria-label="Inputs and settings"
            // overflow visible: a clipping card would trap the sticky Run bar inside it
            sx={{ p: 2, overflow: "visible" }}
          >
            <Stack spacing={2.25}>
              <Typography variant="body2" color="text.secondary">{tab.description}</Typography>
              {tab.slots.map((s) => (
                <SlotInput key={s.name} slot={s} items={inputs[s.name] || []} samples={data.samples?.[s.name]}
                  setItems={(items) => setInputs((x) => ({ ...x, [s.name]: items }))} />
              ))}
              {geoParams.length > 0 && bg && (
                <CanvasEditor src={bg} params={geoParams} values={values} active={activeGeo} onChange={setValue} />
              )}
              <ParamForm tab={tab} values={values} setValue={setValue} activeGeo={activeGeo} setActiveGeo={setActiveGeo} hasImage={!!bg} />
              {tab.model_specs?.length > 0 && (
                <Typography variant="caption" color="text.secondary">
                  Models: {tab.model_specs.map((m) => `${m.name} (${m.license})`).join(" · ")}
                </Typography>
              )}
              {/* Pinned to the bottom of the window while the card is on screen, so Run stays in reach on long forms. */}
              <Stack
                spacing={1}
                sx={{
                  position: "sticky", bottom: 0, zIndex: 1, mx: -2, mb: -2, px: 2, py: 1.5,
                  borderTop: 1, borderColor: "divider", bgcolor: "surface.solid", borderRadius: "0 0 16px 16px",
                  boxShadow: "0 -10px 20px -12px rgba(0, 0, 0, 0.45)",
                }}
              >
                {missing.length > 0 && <Typography variant="caption" color="warning.main">Add: {missing.join(", ")}.</Typography>}
                {user ? (
                  <Button variant="contained" size="large" startIcon={<PlayArrowIcon />} onClick={submit}
                    disabled={busy || missing.length > 0 || isRunActive(run)}>
                    {busy ? "Uploading…" : isRunActive(run) ? "Running…" : "Run"}
                  </Button>
                ) : (
                  <Alert severity="info" icon={<ScienceIcon />}>
                    <Link component={RouterLink} to={`/login?next=${encodeURIComponent(`/projects/${id}/lab`)}`}>Sign in</Link> to run the lab. Runs are saved to your history.
                  </Alert>
                )}
              </Stack>
            </Stack>
          </Card>
        </Grid>

        <Grid size={{ xs: 12, md: 7, lg: 8 }} component="section" aria-label="Results" aria-live="polite" ref={resultsRef} sx={{ scrollMarginTop: 80 }}>
          <Stack spacing={3}>
            {run ? <ResultView run={run} /> : (
              <Card sx={{ borderStyle: "dashed" }}>
                <EmptyState
                  icon={<ScienceIcon fontSize="inherit" />}
                  title="Results appear here"
                  description={data.samples && Object.keys(data.samples).length ? "A sample is loaded. Press Run to try it, or add your own files." : "Add your files and press Run."}
                />
              </Card>
            )}
            {user && history.data?.length > 0 && (
              <Card>
                <CardHeader
                  title="Your recent runs"
                  titleTypographyProps={{ variant: "subtitle2" }}
                  action={<Button size="small" component={RouterLink} to="/runs">View all runs</Button>}
                  sx={{ pb: 0, "& .MuiCardHeader-action": { alignSelf: "center", m: 0 } }}
                />
                <List dense>
                  {history.data.map((h) => (
                    <ListItemButton key={h.public_id} selected={run?.public_id === h.public_id} onClick={() => openRun(h.public_id)} sx={{ gap: 1.5 }}>
                      <Box
                        sx={{ width: 56, height: 42, flexShrink: 0, borderRadius: 1.5, overflow: "hidden", bgcolor: "action.hover",
                          "& img": { width: "100%", height: "100%", objectFit: "cover", display: "block" } }}
                      >
                        {h.thumbnail && <img src={mediaUrl(h.thumbnail)} alt="" onError={(e) => { e.currentTarget.style.display = "none"; }} />}
                      </Box>
                      <ListItemText
                        primary={h.summary?.[0] ? `${h.summary[0].label}: ${h.summary[0].value}` : h.status}
                        secondary={`${formatDateTime(h.created_at)} · ${h.pipeline}`}
                        primaryTypographyProps={{ fontWeight: 600, noWrap: true }}
                        secondaryTypographyProps={{ noWrap: true }}
                        sx={{ minWidth: 0 }}
                      />
                      <RunStatusChip status={h.status} />
                    </ListItemButton>
                  ))}
                </List>
              </Card>
            )}
          </Stack>
        </Grid>
      </Grid>
    </Box>
  );
}
