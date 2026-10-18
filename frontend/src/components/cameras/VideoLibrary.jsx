import { useRef, useState } from "react";
import Box from "@mui/material/Box";
import Button from "@mui/material/Button";
import Card from "@mui/material/Card";
import CardContent from "@mui/material/CardContent";
import CardHeader from "@mui/material/CardHeader";
import Chip from "@mui/material/Chip";
import IconButton from "@mui/material/IconButton";
import LinearProgress from "@mui/material/LinearProgress";
import Table from "@mui/material/Table";
import TableBody from "@mui/material/TableBody";
import TableCell from "@mui/material/TableCell";
import TableContainer from "@mui/material/TableContainer";
import TableHead from "@mui/material/TableHead";
import TableRow from "@mui/material/TableRow";
import Tooltip from "@mui/material/Tooltip";
import Typography from "@mui/material/Typography";
import ContentCopyIcon from "@mui/icons-material/ContentCopy";
import DeleteOutlineIcon from "@mui/icons-material/DeleteOutline";
import UploadFileIcon from "@mui/icons-material/UploadFile";

import { cameras } from "../../api/endpoints";
import { formatDateTime, formatMegabytes } from "../../utils/format";
import { MONO_FONT } from "../../utils/theme";
import ConfirmDialog from "../ConfirmDialog";
import { useToast } from "../Toast";

export const VIDEO_ACCEPT = ".mp4,.mkv,.mov,.avi,.webm,.m4v,.ts,.mpg,.mpeg,video/*";

/** Upload a recording to the workspace's library; resolves with the stored video. */
export async function uploadVideo(file) {
  const fd = new FormData();
  fd.append("file", file);
  return cameras.uploadVideo(fd);
}

/** The source a camera should use for a library video: its RTSP stream when mediamtx is on. */
export const sourceOf = (video) => video.rtsp_url || video.file_source;

/**
 * The workspace's recordings: each plays as a looping RTSP stream
 * (mediamtx) a camera can use like a real one. Workspace admins upload and
 * delete; a video a camera uses can't be deleted.
 */
export default function VideoLibrary({ library, onChange, canEdit }) {
  const toast = useToast();
  const input = useRef(null);
  const [busy, setBusy] = useState(false);
  const [pendingDelete, setPendingDelete] = useState(null);
  const videos = library?.videos || [];

  async function onPick(e) {
    const file = e.target.files[0];
    e.target.value = "";
    if (!file) return;
    setBusy(true);
    try {
      const v = await uploadVideo(file);
      toast(`Added ${v.name}.${v.rtsp_url ? " It streams at " + v.rtsp_url : ""}`);
      onChange();
    } catch (err) {
      toast(err.message, "err");
    } finally {
      setBusy(false);
    }
  }

  async function copy(text) {
    try {
      await navigator.clipboard.writeText(text);
      toast("Copied.");
    } catch {
      toast(text);
    }
  }

  async function confirmDelete() {
    const v = pendingDelete;
    setBusy(true);
    try {
      await cameras.removeVideo(v.name);
      toast(`Deleted ${v.name}.`);
      onChange();
    } catch (err) {
      toast(err.message, "err");
    } finally {
      setBusy(false);
      setPendingDelete(null);
    }
  }

  return (
    <Card>
      <CardHeader
        title="Video library"
        subheader={
          library?.rtsp_enabled
            ? "Recordings played as looping RTSP streams, for cameras to run on as if live."
            : "Recordings cameras can loop as if live (file: sources)."
        }
        titleTypographyProps={{ variant: "subtitle1", fontWeight: 700 }}
        action={
          canEdit && (
            <>
              <input ref={input} hidden type="file" accept={VIDEO_ACCEPT} onChange={onPick} />
              <Button startIcon={<UploadFileIcon />} onClick={() => input.current.click()} disabled={busy}>
                {busy ? "Uploading…" : "Upload video"}
              </Button>
            </>
          )
        }
        sx={{ pb: 0, "& .MuiCardHeader-action": { alignSelf: "center" } }}
      />
      {busy && <LinearProgress sx={{ mx: 2, mt: 1 }} />}
      <CardContent>
        {videos.length ? (
          <TableContainer>
            <Table size="small">
              <TableHead>
                <TableRow>
                  <TableCell>Video</TableCell>
                  <TableCell>{library.rtsp_enabled ? "RTSP stream" : "Source"}</TableCell>
                  <TableCell>Used by</TableCell>
                  <TableCell>Size</TableCell>
                  <TableCell>Added</TableCell>
                  {canEdit && <TableCell align="right">Delete</TableCell>}
                </TableRow>
              </TableHead>
              <TableBody>
                {videos.map((v) => (
                  <TableRow key={v.name} hover>
                    <TableCell sx={{ fontWeight: 600 }}>{v.name}</TableCell>
                    <TableCell sx={{ fontFamily: MONO_FONT, fontSize: 12.5, maxWidth: 380 }}>
                      <Box sx={{ display: "flex", alignItems: "center", gap: 0.5, minWidth: 0 }}>
                        <Box component="span" sx={{ overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{sourceOf(v)}</Box>
                        <Tooltip title="Copy">
                          <IconButton size="small" onClick={() => copy(sourceOf(v))} aria-label={`Copy the source of ${v.name}`}>
                            <ContentCopyIcon fontSize="inherit" />
                          </IconButton>
                        </Tooltip>
                      </Box>
                    </TableCell>
                    <TableCell>
                      {v.used_by.length ? v.used_by.map((c) => <Chip key={c} size="small" label={c} sx={{ mr: 0.5 }} />) : "—"}
                    </TableCell>
                    <TableCell sx={{ whiteSpace: "nowrap" }}>{formatMegabytes(v.size_bytes)}</TableCell>
                    <TableCell><Typography variant="body2" noWrap>{formatDateTime(v.uploaded_at)}</Typography></TableCell>
                    {canEdit && (
                      <TableCell align="right">
                        <Tooltip title={v.used_by.length ? "A camera uses it" : "Delete"}>
                          <span>
                            <IconButton size="small" color="error" disabled={busy || v.used_by.length > 0}
                              onClick={() => setPendingDelete(v)} aria-label={`Delete ${v.name}`}>
                              <DeleteOutlineIcon fontSize="small" />
                            </IconButton>
                          </span>
                        </Tooltip>
                      </TableCell>
                    )}
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </TableContainer>
        ) : (
          <Typography variant="body2" color="text.secondary">
            No recordings yet.{canEdit ? ` Upload a video (up to ${library?.max_mb ?? 250} MB) to run a camera on it.` : ""}
            {library?.rtsp_enabled && library.samples.length > 0 && (
              <> The lab samples always stream at {library.samples.map((s) => s.rtsp_url).join(" and ")}.</>
            )}
          </Typography>
        )}
      </CardContent>
      <ConfirmDialog
        open={Boolean(pendingDelete)}
        title="Delete this video?"
        description={pendingDelete ? `${pendingDelete.name} is removed from the library.` : ""}
        confirmLabel="Delete"
        confirmColor="error"
        busy={busy}
        onConfirm={confirmDelete}
        onClose={() => setPendingDelete(null)}
      />
    </Card>
  );
}
