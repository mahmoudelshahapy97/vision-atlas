import { useState } from "react";
import { Link as RouterLink } from "react-router-dom";
import Alert from "@mui/material/Alert";
import Box from "@mui/material/Box";
import Button from "@mui/material/Button";
import Card from "@mui/material/Card";
import CardContent from "@mui/material/CardContent";
import CardHeader from "@mui/material/CardHeader";
import Checkbox from "@mui/material/Checkbox";
import Chip from "@mui/material/Chip";
import FormControlLabel from "@mui/material/FormControlLabel";
import IconButton from "@mui/material/IconButton";
import Link from "@mui/material/Link";
import Skeleton from "@mui/material/Skeleton";
import Stack from "@mui/material/Stack";
import Table from "@mui/material/Table";
import TableBody from "@mui/material/TableBody";
import TableCell from "@mui/material/TableCell";
import TableContainer from "@mui/material/TableContainer";
import TableHead from "@mui/material/TableHead";
import TableRow from "@mui/material/TableRow";
import TextField from "@mui/material/TextField";
import Tooltip from "@mui/material/Tooltip";
import Typography from "@mui/material/Typography";
import AttachFileIcon from "@mui/icons-material/AttachFile";
import CloudDownloadIcon from "@mui/icons-material/CloudDownload";
import CloudUploadIcon from "@mui/icons-material/CloudUpload";
import DeleteOutlineIcon from "@mui/icons-material/DeleteOutline";
import RefreshIcon from "@mui/icons-material/Refresh";

import { models as modelsApi } from "../api/endpoints";
import { useAuth } from "../auth/AuthContext";
import ConfirmDialog from "../components/ConfirmDialog";
import { ErrorState } from "../components/DataStates";
import PageHeader from "../components/PageHeader";
import { useToast } from "../components/Toast";
import { usePolling } from "../hooks/usePolling";
import { MODEL_DOWNLOAD_POLL_MS } from "../utils/constants";
import { formatMegabytes } from "../utils/format";
import { MONO_FONT } from "../utils/theme";

const isDownloading = (data) => Boolean(data?.builtin.some((b) => b.download_state === "downloading"));
const mono = { fontFamily: MONO_FONT, fontSize: 12.5 };

function DownloadState({ m }) {
  if (m.download_state === "downloading") return <Chip size="small" color="warning" label="Downloading…" />;
  if (m.download_state?.startsWith("error")) {
    return <Tooltip title={m.download_state}><Chip size="small" color="error" label="Failed" /></Tooltip>;
  }
  if (m.loaded) return <Chip size="small" color="success" label="Loaded" />;
  if (m.downloaded) return <Chip size="small" color="primary" variant="outlined" label="On disk" />;
  return <Chip size="small" variant="outlined" label="On first use" />;
}

export default function Models() {
  const { user } = useAuth();
  const toast = useToast();
  // Re-polls while any prefetch is still downloading.
  const models = usePolling((opts) => modelsApi.list(opts), {
    intervalMs: MODEL_DOWNLOAD_POLL_MS, deps: [user?.id], keepPolling: isDownloading,
  });
  const [form, setForm] = useState({ name: "", is_public: false });
  const [file, setFile] = useState(null);
  const [dragOver, setDragOver] = useState(false);
  const [busy, setBusy] = useState(false);
  const [pendingDelete, setPendingDelete] = useState(null);
  const data = models.data;
  const isAdmin = user?.role === "admin";

  async function download(key) {
    try {
      await modelsApi.download(key);
      models.reload();
    } catch (e) {
      toast(e.message, "err");
    }
  }

  async function upload(e) {
    e.preventDefault();
    if (!file) return toast("Choose a .pt file first.", "err");
    setBusy(true);
    const fd = new FormData();
    fd.append("file", file);
    fd.append("name", form.name || file.name.replace(/\.pt$/, ""));
    fd.append("is_public", form.is_public ? "true" : "false");
    try {
      const m = await modelsApi.upload(fd);
      toast(`Uploaded “${m.name}” (${m.task}, ${m.classes.length} classes).`);
      setFile(null);
      setForm({ name: "", is_public: false });
      models.reload();
    } catch (err) {
      toast(err.message, "err");
    } finally {
      setBusy(false);
    }
  }

  async function confirmDelete() {
    const m = pendingDelete;
    setPendingDelete(null);
    try {
      await modelsApi.remove(m.id);
      toast(`Deleted “${m.name}”.`);
      models.reload();
    } catch (e) {
      toast(e.message, "err");
    }
  }

  return (
    <Box>
      <PageHeader
        title="Models"
        subtitle="Public models download automatically the first time a lab needs them. Upload your own YOLO26 weights to use them in any matching lab."
        actions={<Button onClick={models.reload} startIcon={<RefreshIcon />}>Refresh</Button>}
      />
      <ErrorState error={models.error} onRetry={models.reload} />
      {!data && !models.error && (
        <Card aria-busy="true" sx={{ p: 2 }}>
          <Skeleton width={180} height={28} />
          <Skeleton width={320} sx={{ mb: 2 }} />
          {[0, 1, 2, 3, 4, 5].map((i) => <Skeleton key={i} height={44} />)}
        </Card>
      )}

      {data && (
        <Stack spacing={3}>
          <Card>
            <CardHeader
              title="Public models"
              titleTypographyProps={{ variant: "subtitle1", fontWeight: 700 }}
              subheaderTypographyProps={{ variant: "body2" }}
              subheader={data.device && (
                <>Model server device: <Box component="code" sx={mono}>{data.device}</Box>{data.gpu && <> ({data.gpu})</>} · YOLO26 size: <Box component="code" sx={mono}>{data.yolo_size}</Box></>
              )}
            />
            {data.model_server_error && (
              <Alert severity="warning" sx={{ mx: 2, mb: 2 }}>Model server unavailable: {data.model_server_error}</Alert>
            )}
            <TableContainer>
              <Table size="small">
                <TableHead>
                  <TableRow>
                    <TableCell>Model</TableCell>
                    <TableCell>Task</TableCell>
                    <TableCell>Source</TableCell>
                    <TableCell>License</TableCell>
                    <TableCell>Size</TableCell>
                    <TableCell>Status</TableCell>
                    {isAdmin && <TableCell align="right">Actions</TableCell>}
                  </TableRow>
                </TableHead>
                <TableBody>
                  {data.builtin.map((m) => (
                    <TableRow key={m.key} hover>
                      <TableCell sx={{ minWidth: 200 }}>
                        <Typography variant="body2" sx={{ fontWeight: 600 }}>{m.name}</Typography>
                        {m.classes && <Typography variant="caption" color="text.secondary" component="div">{m.classes}</Typography>}
                        {m.note && <Typography variant="caption" color="text.secondary" component="div">{m.note}</Typography>}
                      </TableCell>
                      <TableCell>{m.task}</TableCell>
                      <TableCell><Typography variant="caption" color="text.secondary">{m.source}</Typography></TableCell>
                      <TableCell sx={mono}>{m.license}</TableCell>
                      <TableCell sx={{ ...mono, whiteSpace: "nowrap" }}>{m.size_mb ? `${m.size_mb} MB` : "—"}</TableCell>
                      <TableCell><DownloadState m={m} /></TableCell>
                      {isAdmin && (
                        <TableCell align="right">
                          {!m.downloaded && m.download_state !== "downloading" && (
                            <Tooltip title="Download now">
                              <IconButton size="small" onClick={() => download(m.key)} aria-label={`Download ${m.name}`}>
                                <CloudDownloadIcon fontSize="small" />
                              </IconButton>
                            </Tooltip>
                          )}
                        </TableCell>
                      )}
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </TableContainer>
            <CardContent sx={{ pt: 1.5 }}>
              {data.builtin.filter((m) => m.download_state?.startsWith("error")).map((m) => (
                <Alert key={m.key} severity="error" sx={{ mb: 1 }}>{m.name}: {m.download_state.replace(/^error: /, "")}</Alert>
              ))}
              <Typography variant="caption" color="text.secondary">
                YOLO26 and YOLOE-26 are AGPL-3.0: fine for research and open-source use; commercial closed-source products need an Ultralytics Enterprise license.
              </Typography>
            </CardContent>
          </Card>

          <Card>
            <CardHeader title="Your models" titleTypographyProps={{ variant: "subtitle1", fontWeight: 700 }} />
            <CardContent sx={{ pt: 0 }}>
              {user ? (
                <Box component="form" onSubmit={upload}>
                  <Stack direction={{ xs: "column", md: "row" }} spacing={1.5} alignItems={{ md: "center" }}>
                    <Button
                      component="label"
                      variant="outlined"
                      startIcon={<AttachFileIcon />}
                      // Dropping a .pt on the button works as well as browsing.
                      onDragOver={(e) => { e.preventDefault(); setDragOver(true); }}
                      onDragLeave={() => setDragOver(false)}
                      onDrop={(e) => { e.preventDefault(); setDragOver(false); setFile(e.dataTransfer.files[0] || null); }}
                      sx={{ flexShrink: 0, maxWidth: { md: 280 }, ...(dragOver && { borderStyle: "dashed", bgcolor: "action.selected" }) }}
                    >
                      <Box component="span" sx={{ overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                        {file ? file.name : "Choose or drop weights (.pt)"}
                      </Box>
                      <input hidden type="file" accept=".pt" onChange={(e) => { setFile(e.target.files[0] || null); e.target.value = ""; }} />
                    </Button>
                    <TextField
                      size="small"
                      label="Name"
                      value={form.name}
                      onChange={(e) => setForm({ ...form, name: e.target.value })}
                      placeholder="Saudi plates YOLO26n v3"
                      sx={{ flexGrow: 1 }}
                    />
                    {isAdmin && (
                      <FormControlLabel
                        control={<Checkbox checked={form.is_public} onChange={(e) => setForm({ ...form, is_public: e.target.checked })} />}
                        label="Share with all users"
                        sx={{ flexShrink: 0 }}
                      />
                    )}
                    <Button type="submit" variant="contained" startIcon={<CloudUploadIcon />} disabled={busy} sx={{ flexShrink: 0 }}>
                      {busy ? "Checking the file…" : "Upload model"}
                    </Button>
                  </Stack>
                  <Typography variant="body2" color="text.secondary" sx={{ mt: 1.5 }}>
                    Any Ultralytics model works (YOLO26, YOLO11, YOLOv8: detect, segment, classify, pose or OBB). Train with{" "}
                    <Box component="code" sx={mono}>yolo detect train data=data.yaml model=yolo26n.pt</Box>, then upload{" "}
                    <Box component="code" sx={mono}>runs/detect/train/weights/best.pt</Box>. The lab lets you pick it wherever the task matches.
                  </Typography>
                </Box>
              ) : (
                <Typography variant="body2" color="text.secondary">
                  <Link component={RouterLink} to="/login?next=/models">Sign in</Link> to upload your own models.
                </Typography>
              )}
            </CardContent>
            {data.custom.length > 0 && (
              <TableContainer sx={{ borderTop: 1, borderColor: "divider" }}>
                <Table size="small">
                  <TableHead>
                    <TableRow>
                      <TableCell>Name</TableCell>
                      <TableCell>Task</TableCell>
                      <TableCell>Classes</TableCell>
                      <TableCell>Size</TableCell>
                      <TableCell>Shared</TableCell>
                      <TableCell align="right">Actions</TableCell>
                    </TableRow>
                  </TableHead>
                  <TableBody>
                    {data.custom.map((m) => (
                      <TableRow key={m.id} hover>
                        <TableCell sx={{ fontWeight: 600 }}>{m.name}</TableCell>
                        <TableCell sx={mono}>{m.task}</TableCell>
                        <TableCell>
                          <Typography variant="caption" color="text.secondary">
                            {(m.classes || []).slice(0, 8).join(", ")}{m.classes?.length > 8 ? ` +${m.classes.length - 8}` : ""}
                          </Typography>
                        </TableCell>
                        <TableCell sx={{ ...mono, whiteSpace: "nowrap" }}>{formatMegabytes(m.size_bytes)}</TableCell>
                        <TableCell>
                          <Chip size="small" label={m.is_public ? "Shared" : "Private"} color={m.is_public ? "info" : "default"} variant="outlined" />
                        </TableCell>
                        <TableCell align="right">
                          {(m.owner_id === user?.id || isAdmin) && (
                            <Tooltip title="Delete model">
                              <IconButton size="small" color="error" onClick={() => setPendingDelete(m)} aria-label={`Delete ${m.name}`}>
                                <DeleteOutlineIcon fontSize="small" />
                              </IconButton>
                            </Tooltip>
                          )}
                        </TableCell>
                      </TableRow>
                    ))}
                  </TableBody>
                </Table>
              </TableContainer>
            )}
          </Card>
        </Stack>
      )}

      <ConfirmDialog
        open={Boolean(pendingDelete)}
        title="Delete this model?"
        description={pendingDelete ? `“${pendingDelete.name}” is removed, and labs fall back to the built-in model.` : ""}
        confirmLabel="Delete"
        confirmColor="error"
        onConfirm={confirmDelete}
        onClose={() => setPendingDelete(null)}
      />
    </Box>
  );
}
