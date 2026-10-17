import { useCallback, useEffect, useRef, useState } from "react";
import { Link as RouterLink, useNavigate, useOutletContext, useParams } from "react-router-dom";
import Alert from "@mui/material/Alert";
import Box from "@mui/material/Box";
import Button from "@mui/material/Button";
import Card from "@mui/material/Card";
import Chip from "@mui/material/Chip";
import Divider from "@mui/material/Divider";
import Drawer from "@mui/material/Drawer";
import IconButton from "@mui/material/IconButton";
import Link from "@mui/material/Link";
import Skeleton from "@mui/material/Skeleton";
import Stack from "@mui/material/Stack";
import TextField from "@mui/material/TextField";
import ToggleButton from "@mui/material/ToggleButton";
import ToggleButtonGroup from "@mui/material/ToggleButtonGroup";
import Tooltip from "@mui/material/Tooltip";
import Typography from "@mui/material/Typography";
import ChevronLeftIcon from "@mui/icons-material/ChevronLeft";
import ChevronRightIcon from "@mui/icons-material/ChevronRight";
import CloseIcon from "@mui/icons-material/Close";
import ScienceIcon from "@mui/icons-material/Science";
import { alpha } from "@mui/material/styles";

import { progress as progressApi, projects as projectsApi } from "../api/endpoints";
import { useAuth } from "../auth/AuthContext";
import { useAsync } from "../hooks/useAsync";
import { LEVELS, STATUS_COLOR, STATUSES } from "../utils/constants";
import { ErrorState } from "./DataStates";
import { ProjectTag } from "./ProjectCard";
import { SupportBadge } from "./StatusChips";
import { useToast } from "./Toast";

const NOTE_STATE = {
  saved: ["Saved", "text.secondary"],
  dirty: ["Unsaved changes", "warning.main"],
  saving: ["Saving…", "text.secondary"],
  error: ["Not saved", "error.main"],
};

function Section({ title, extra, children }) {
  return (
    <Box component="section">
      <Stack direction="row" justifyContent="space-between" alignItems="center" sx={{ mb: 1 }}>
        <Typography variant="overline" color="text.secondary" sx={{ fontWeight: 700, lineHeight: 1.6 }}>{title}</Typography>
        {extra}
      </Stack>
      {children}
    </Box>
  );
}

export default function ProjectDrawer() {
  const { id } = useParams();
  const { ids = [], onChanged = () => {}, search = "" } = useOutletContext() || {};
  const navigate = useNavigate();
  const { user } = useAuth();
  const toast = useToast();

  const proj = useAsync((opts) => projectsApi.get(id, opts), [id, user?.id]);
  const p = proj.data && String(proj.data.id) === String(id) ? proj.data : null;

  const [status, setStatus] = useState("idea");
  const [notes, setNotes] = useState("");
  const [noteState, setNoteState] = useState("saved"); // saved | dirty | saving | error
  const savedNotes = useRef("");

  useEffect(() => {
    if (!p) return;
    setStatus(p.progress?.status || "idea");
    setNotes(p.progress?.notes || "");
    savedNotes.current = p.progress?.notes || "";
    setNoteState("saved");
  }, [p]);

  const qs = search ? `?${search}` : "";
  const close = useCallback(() => navigate({ pathname: "/", search: qs }), [navigate, qs]);
  const go = (pid) => pid && navigate({ pathname: `/projects/${pid}`, search: qs });

  const idx = ids.indexOf(Number(id));
  const prev = idx > 0 ? ids[idx - 1] : idx === -1 ? p?.prev_id : null;
  const next = idx >= 0 && idx < ids.length - 1 ? ids[idx + 1] : idx === -1 ? p?.next_id : null;

  async function changeStatus(s) {
    const before = status;
    setStatus(s);
    try {
      await progressApi.set(id, { status: s });
      onChanged();
    } catch (e) {
      setStatus(before);
      toast(e.message, "err");
    }
  }

  const saveNotes = useCallback(async (value) => {
    if (value === savedNotes.current) return setNoteState("saved");
    setNoteState("saving");
    try {
      await progressApi.set(id, { notes: value });
      savedNotes.current = value;
      setNoteState("saved");
      onChanged();
    } catch (e) {
      setNoteState("error");
      toast(e.message, "err");
    }
  }, [id, onChanged, toast]);

  // autosave notes shortly after typing stops
  useEffect(() => {
    if (noteState !== "dirty") return;
    const t = setTimeout(() => saveNotes(notes), 900);
    return () => clearTimeout(t);
  }, [notes, noteState, saveNotes]);

  const [noteLabel, noteColor] = NOTE_STATE[noteState];

  return (
    <Drawer
      anchor="right"
      open
      onClose={close}
      PaperProps={{
        sx: { width: { xs: "100%", sm: 560 }, backgroundImage: "none" },
        role: "dialog",
        "aria-labelledby": "dTitle",
      }}
    >
      <Stack
        direction="row"
        alignItems="center"
        justifyContent="space-between"
        sx={{ px: 2.5, py: 1.25, borderBottom: 1, borderColor: "divider", position: "sticky", top: 0, bgcolor: "background.paper", backdropFilter: "blur(18px)", zIndex: 1 }}
      >
        {p ? <ProjectTag project={p} /> : <Typography variant="caption" color="text.secondary">Loading…</Typography>}
        <Stack direction="row" spacing={0.5}>
          <Tooltip title="Previous project">
            <span><IconButton size="small" disabled={!prev} onClick={() => go(prev)} aria-label="Previous project"><ChevronLeftIcon /></IconButton></span>
          </Tooltip>
          <Tooltip title="Next project">
            <span><IconButton size="small" disabled={!next} onClick={() => go(next)} aria-label="Next project"><ChevronRightIcon /></IconButton></span>
          </Tooltip>
          <IconButton size="small" onClick={close} aria-label="Close" autoFocus><CloseIcon /></IconButton>
        </Stack>
      </Stack>

      <Stack spacing={3} sx={{ p: 2.5 }}>
        <ErrorState error={proj.error} onRetry={proj.reload} />

        {!p && !proj.error && (
          <Box>
            <Skeleton width="30%" />
            <Skeleton variant="rounded" height={36} sx={{ my: 1 }} />
            <Skeleton />
            <Skeleton width="85%" />
          </Box>
        )}

        {p && (
          <>
            <Box>
              <Typography variant="caption" color="primary.main" sx={{ fontWeight: 700, textTransform: "uppercase", letterSpacing: "0.06em" }}>
                {p.domain.name}
              </Typography>
              <Typography id="dTitle" variant="h5" component="h2" sx={{ mt: 0.5, mb: 1 }}>{p.title}</Typography>
              <Typography variant="body2" color="text.secondary">{p.description}</Typography>
            </Box>

            {p.lab && (
              <Card sx={{ p: 2, bgcolor: (t) => alpha(t.palette.primary.main, t.palette.mode === "dark" ? 0.08 : 0.05), borderColor: "primary.main" }}>
                <Stack direction={{ xs: "column", sm: "row" }} spacing={2} alignItems={{ sm: "center" }} justifyContent="space-between">
                  <Box>
                    <SupportBadge level={p.lab.support} />
                    <Typography variant="body2" color="text.secondary" sx={{ mt: 1 }}>
                      Run this project on your own images or video{p.lab.samples ? ", or try the built-in sample" : ""}.
                    </Typography>
                  </Box>
                  <Button component={RouterLink} to={`/projects/${p.id}/lab`} variant="contained" startIcon={<ScienceIcon />} sx={{ flexShrink: 0 }}>
                    Try it in the lab
                  </Button>
                </Stack>
              </Card>
            )}

            {p.is_pick && p.pick_reason && <Alert severity="info" icon={false}><b>Top pick.</b> {p.pick_reason}</Alert>}

            <Card component="dl" sx={{ m: 0, display: "grid", gridTemplateColumns: "repeat(3, minmax(0, 1fr))" }}>
              {[["Task", p.task_type.name], ["Level", LEVELS[p.level]], ["Key metric", p.task_type.metric]].map(([k, v], i) => (
                <Box key={k} sx={{ p: 1.5, borderLeft: i ? 1 : 0, borderColor: "divider" }}>
                  <Typography component="dt" variant="caption" color="text.secondary">{k}</Typography>
                  <Typography component="dd" variant="body2" sx={{ m: 0, fontWeight: 600 }}>{v}</Typography>
                </Box>
              ))}
            </Card>

            <Section title="Tech stack">
              <Stack direction="row" spacing={0.75} useFlexGap flexWrap="wrap">
                {p.technologies.map((t) => (
                  <Tooltip key={t} title={`Find projects using ${t}`}>
                    <Chip label={t} size="small" clickable component={RouterLink} to={`/?q=${encodeURIComponent(t)}`} variant="outlined" />
                  </Tooltip>
                ))}
              </Stack>
            </Section>

            <Section title="Build path">
              <Box component="ol" sx={{ m: 0, p: 0, listStyle: "none", display: "grid", gap: 1 }}>
                {p.steps.map((s, i) => (
                  <Box component="li" key={s} sx={{ display: "flex", gap: 1.5, alignItems: "flex-start" }}>
                    <Box
                      sx={{
                        flexShrink: 0, width: 24, height: 24, borderRadius: "50%", display: "grid", placeItems: "center",
                        fontSize: 12, fontWeight: 700, bgcolor: "action.selected", color: "primary.main",
                      }}
                    >
                      {i + 1}
                    </Box>
                    <Typography variant="body2" sx={{ pt: 0.25 }}>{s}</Typography>
                  </Box>
                ))}
              </Box>
            </Section>

            {p.caution && <Alert severity="warning">{p.caution}</Alert>}

            <Divider />

            <Section title="Status">
              {user ? (
                <ToggleButtonGroup
                  exclusive
                  size="small"
                  fullWidth
                  value={status}
                  onChange={(_, s) => s && s !== status && changeStatus(s)}
                  aria-label="Status"
                >
                  {STATUSES.map(([k, l]) => (
                    <ToggleButton
                      key={k}
                      value={k}
                      sx={STATUS_COLOR[k] !== "default" ? {
                        "&.Mui-selected, &.Mui-selected:hover": { bgcolor: `${STATUS_COLOR[k]}.main`, color: `${STATUS_COLOR[k]}.contrastText` },
                      } : undefined}
                    >
                      {l}
                    </ToggleButton>
                  ))}
                </ToggleButtonGroup>
              ) : (
                <Typography variant="body2" color="text.secondary">
                  <Link component={RouterLink} to={`/login?next=${encodeURIComponent(`/projects/${id}`)}`}>Sign in</Link> to track this project and keep notes.
                </Typography>
              )}
            </Section>

            {user && (
              <Section title="Notes" extra={<Typography variant="caption" color={noteColor}>{noteLabel}</Typography>}>
                <TextField
                  id={`notes-${p.id}`}
                  multiline
                  minRows={4}
                  fullWidth
                  value={notes}
                  onChange={(e) => { setNotes(e.target.value); setNoteState("dirty"); }}
                  onBlur={() => noteState === "dirty" && saveNotes(notes)}
                  placeholder="Datasets you found, repo links, model results, next steps…"
                  inputProps={{ "aria-label": "Notes" }}
                />
              </Section>
            )}
          </>
        )}
      </Stack>
    </Drawer>
  );
}
