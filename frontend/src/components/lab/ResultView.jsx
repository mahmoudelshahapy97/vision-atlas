import { useMemo, useState } from "react";
import katex from "katex";
import "katex/dist/katex.min.css";
import Alert from "@mui/material/Alert";
import AlertTitle from "@mui/material/AlertTitle";
import Box from "@mui/material/Box";
import Button from "@mui/material/Button";
import ButtonBase from "@mui/material/ButtonBase";
import Card from "@mui/material/Card";
import CardHeader from "@mui/material/CardHeader";
import CircularProgress from "@mui/material/CircularProgress";
import Dialog from "@mui/material/Dialog";
import LinearProgress from "@mui/material/LinearProgress";
import Link from "@mui/material/Link";
import List from "@mui/material/List";
import ListItem from "@mui/material/ListItem";
import ListItemIcon from "@mui/material/ListItemIcon";
import ListItemText from "@mui/material/ListItemText";
import Stack from "@mui/material/Stack";
import Table from "@mui/material/Table";
import TableBody from "@mui/material/TableBody";
import TableCell from "@mui/material/TableCell";
import TableContainer from "@mui/material/TableContainer";
import TableHead from "@mui/material/TableHead";
import TableRow from "@mui/material/TableRow";
import Typography from "@mui/material/Typography";
import ContentCopyIcon from "@mui/icons-material/ContentCopy";
import DownloadIcon from "@mui/icons-material/Download";
import RecordVoiceOverIcon from "@mui/icons-material/RecordVoiceOver";
import StopIcon from "@mui/icons-material/Stop";

import { mediaUrl } from "../../api/client";
import { MONO_FONT } from "../../utils/theme";
import Chart from "./Chart";
import PointCloud from "./PointCloud";

const TONE_COLOR = { good: "success.main", bad: "error.main", warn: "warning.main" };

function fmtBytes(n) {
  if (!n && n !== 0) return "";
  if (n < 1024) return `${n} B`;
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(0)} KB`;
  return `${(n / 1024 / 1024).toFixed(1)} MB`;
}

const media = { display: "block", width: "100%", maxHeight: "70vh", objectFit: "contain", bgcolor: "#000" };

function Lightbox({ image, onClose }) {
  return (
    <Dialog open onClose={onClose} maxWidth="xl" aria-label={image.caption} onClick={onClose}
      PaperProps={{ sx: { bgcolor: "transparent", boxShadow: "none", backgroundImage: "none", border: 0 } }}>
      <Box component="img" src={mediaUrl(image.url)} alt={image.caption} sx={{ display: "block", maxWidth: "100%", maxHeight: "85vh", mx: "auto", borderRadius: 2 }} />
      <Typography variant="body2" align="center" sx={{ color: "#fff", mt: 1 }}>{image.caption} · click anywhere to close</Typography>
    </Dialog>
  );
}

function DataTable({ table }) {
  return (
    <Card>
      <CardHeader
        title={`${table.title}${table.total_rows > table.rows.length ? ` (first ${table.rows.length} of ${table.total_rows})` : ""}`}
        titleTypographyProps={{ variant: "subtitle2" }}
        sx={{ py: 1.5 }}
      />
      <TableContainer sx={{ maxHeight: 420 }}>
        <Table size="small" stickyHeader>
          <TableHead><TableRow>{table.columns.map((c) => <TableCell key={c}>{c}</TableCell>)}</TableRow></TableHead>
          <TableBody>
            {table.rows.length === 0 && (
              <TableRow><TableCell colSpan={table.columns.length}><Typography variant="body2" color="text.secondary">No rows.</Typography></TableCell></TableRow>
            )}
            {table.rows.map((r, i) => (
              <TableRow key={i} hover>
                {r.map((v, j) => <TableCell key={j} dir="auto">{v === null || v === undefined ? "—" : String(v)}</TableCell>)}
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </TableContainer>
    </Card>
  );
}

function Speak({ text, lang }) {
  const [on, setOn] = useState(false);
  if (typeof window === "undefined" || !window.speechSynthesis) return null;
  const speak = () => {
    window.speechSynthesis.cancel();
    if (on) return setOn(false);
    const u = new SpeechSynthesisUtterance(text);
    u.lang = lang === "ar" ? "ar-SA" : "en-US";
    u.onend = () => setOn(false);
    setOn(true);
    window.speechSynthesis.speak(u);
  };
  return (
    <Button size="small" onClick={speak} startIcon={on ? <StopIcon /> : <RecordVoiceOverIcon />}>{on ? "Stop" : "Speak"}</Button>
  );
}

function Figure({ caption, children }) {
  return (
    <Card component="figure" sx={{ m: 0, overflow: "hidden" }}>
      {children}
      <Typography component="figcaption" variant="caption" color="text.secondary" sx={{ display: "block", px: 1.5, py: 1 }}>
        {caption}
      </Typography>
    </Card>
  );
}

export default function ResultView({ run }) {
  const [zoom, setZoom] = useState(null);
  const [copied, setCopied] = useState(false);
  const res = run?.result;
  const latex = useMemo(() => (res?.latex || []).map((l) => {
    try { return katex.renderToString(l, { throwOnError: false, displayMode: true }); } catch { return null; }
  }), [res]);

  if (!run) return null;
  if (run.status === "queued" || run.status === "running") {
    const pct = Math.round((run.progress || 0) * 100);
    return (
      <Card sx={{ p: 3 }}>
        <Stack direction="row" spacing={2.5} alignItems="center">
          <CircularProgress size={36} />
          <Box sx={{ flexGrow: 1, minWidth: 0 }}>
            <Typography variant="subtitle1" sx={{ fontWeight: 700 }}>
              {run.status === "queued" ? "Waiting in the queue…" : "Analyzing…"}
            </Typography>
            <Typography variant="body2" color="text.secondary" sx={{ mb: 1.5 }}>
              First runs download the model weights, so they take longer.
            </Typography>
            <LinearProgress variant="determinate" value={pct} sx={{ height: 6, borderRadius: 99 }} aria-label={`${pct}% done`} />
          </Box>
        </Stack>
      </Card>
    );
  }
  if (run.status === "error") {
    return (
      <Alert severity="error">
        <AlertTitle>This run didn't finish.</AlertTitle>
        {run.error}
      </Alert>
    );
  }
  if (!res) return null;

  const copy = async (t) => {
    try { await navigator.clipboard.writeText(t); setCopied(true); setTimeout(() => setCopied(false), 1500); } catch { /* ignore */ }
  };
  const [first, ...rest] = res.images || [];
  const thumbs = res.video ? res.images : rest;

  return (
    <Stack spacing={2}>
      {res.summary?.length > 0 && (
        <Box sx={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(150px, 1fr))", gap: 1.5 }}>
          {res.summary.map((s, i) => (
            <Card key={i} sx={{ px: 2, py: 1.5, borderLeft: TONE_COLOR[s.tone] ? 3 : 1, borderLeftColor: TONE_COLOR[s.tone] || "divider" }}>
              <Typography variant="overline" color="text.secondary" sx={{ lineHeight: 1.4, display: "block" }}>{s.label}</Typography>
              <Typography variant="h6" dir="auto" sx={{ color: TONE_COLOR[s.tone], wordBreak: "break-word" }}>
                {String(s.value)}
                {s.unit ? <Typography component="small" variant="body2" color="text.secondary"> {s.unit}</Typography> : null}
              </Typography>
            </Card>
          ))}
        </Box>
      )}

      {res.video && (
        <Figure caption={res.video.caption}>
          <Box component="video" src={mediaUrl(res.video.url)} poster={mediaUrl(res.video.poster)} controls playsInline preload="metadata" sx={media} />
        </Figure>
      )}
      {first && !res.video && (
        <Figure caption={first.caption}>
          <ButtonBase onClick={() => setZoom(first)} aria-label={`Enlarge: ${first.caption}`} sx={{ display: "block", width: "100%" }}>
            <Box component="img" src={mediaUrl(first.url)} alt={first.caption} sx={media} />
          </ButtonBase>
        </Figure>
      )}
      {thumbs?.length > 0 && (
        <Box sx={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(160px, 1fr))", gap: 1.5 }}>
          {thumbs.map((im) => (
            <Figure key={im.url} caption={im.caption}>
              <ButtonBase onClick={() => setZoom(im)} aria-label={`Enlarge: ${im.caption}`} sx={{ display: "block", width: "100%" }}>
                <Box component="img" src={mediaUrl(im.url)} alt={im.caption} loading="lazy" sx={{ display: "block", width: "100%", height: 120, objectFit: "cover" }} />
              </ButtonBase>
            </Figure>
          ))}
        </Box>
      )}

      {res.text?.content && (
        <Card>
          <CardHeader
            title="Text"
            titleTypographyProps={{ variant: "subtitle2" }}
            sx={{ py: 1.25 }}
            action={
              <Stack direction="row" spacing={0.5}>
                {res.speak && <Speak text={res.speak} lang={res.speak_lang} />}
                <Button size="small" startIcon={<ContentCopyIcon />} onClick={() => copy(res.text.content)}>{copied ? "Copied" : "Copy"}</Button>
              </Stack>
            }
          />
          <Box
            component="pre"
            dir={res.text.dir === "rtl" ? "rtl" : "auto"}
            sx={{ m: 0, px: 2, pb: 2, whiteSpace: "pre-wrap", wordBreak: "break-word", fontFamily: MONO_FONT, fontSize: 13, maxHeight: 420, overflowY: "auto" }}
          >
            {res.text.content}
          </Box>
        </Card>
      )}
      {latex.some(Boolean) && (
        <Card sx={{ px: 2, pb: 1 }}>
          <Typography variant="subtitle2" sx={{ pt: 1.5 }}>Rendered formulas</Typography>
          {latex.map((h, i) => h && <div key={i} className="katex-block" dangerouslySetInnerHTML={{ __html: h }} />)}
        </Card>
      )}

      {res.points3d && <PointCloud points={res.points3d} />}
      {res.chart && <Chart chart={res.chart} />}
      {(res.tables || []).map((t, i) => <DataTable key={i} table={t} />)}

      {res.files?.length > 0 && (
        <Card>
          <CardHeader title="Downloads" titleTypographyProps={{ variant: "subtitle2" }} sx={{ pb: 0 }} />
          <List dense>
            {res.files.map((f) => (
              <ListItem key={f.url}>
                <ListItemIcon sx={{ minWidth: 36 }}><DownloadIcon fontSize="small" /></ListItemIcon>
                <ListItemText
                  primary={<Link href={mediaUrl(f.url)} download={f.name} underline="hover">{f.name}</Link>}
                  secondary={fmtBytes(f.size)}
                />
              </ListItem>
            ))}
          </List>
        </Card>
      )}
      {res.notes?.length > 0 && (
        <Alert severity="info" icon={false}>
          <Box component="ul" sx={{ m: 0, pl: 2.5 }}>{res.notes.map((n, i) => <li key={i}>{n}</li>)}</Box>
        </Alert>
      )}
      <Typography variant="caption" color="text.secondary">
        Finished in {(run.duration_ms / 1000).toFixed(1)} s · pipeline <Box component="code" sx={{ fontFamily: MONO_FONT }}>{run.pipeline}</Box>
      </Typography>
      {zoom && <Lightbox image={zoom} onClose={() => setZoom(null)} />}
    </Stack>
  );
}
