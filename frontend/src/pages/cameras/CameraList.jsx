import { useMemo, useState } from "react";
import { Link as RouterLink } from "react-router-dom";
import Box from "@mui/material/Box";
import Button from "@mui/material/Button";
import Card from "@mui/material/Card";
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
import Tooltip from "@mui/material/Tooltip";
import Typography from "@mui/material/Typography";
import AddIcon from "@mui/icons-material/Add";
import DeleteOutlineIcon from "@mui/icons-material/DeleteOutline";
import EditIcon from "@mui/icons-material/Edit";
import PlayArrowIcon from "@mui/icons-material/PlayArrow";
import StopIcon from "@mui/icons-material/Stop";
import VideocamIcon from "@mui/icons-material/Videocam";

import { cameras } from "../../api/endpoints";
import { CameraStateChip, metricSummary } from "../../components/cameras/CameraBits";
import ConfirmDialog from "../../components/ConfirmDialog";
import { EmptyState, ErrorState } from "../../components/DataStates";
import PageHeader from "../../components/PageHeader";
import { useToast } from "../../components/Toast";
import { useAsync } from "../../hooks/useAsync";
import { usePolling } from "../../hooks/usePolling";
import { MONO_FONT } from "../../utils/theme";
import { useWorkspace } from "../../workspace/WorkspaceContext";

const mono = { fontFamily: MONO_FONT, fontSize: 12.5 };

/** The active workspace's cameras with their live state. */
export default function CameraList() {
  const toast = useToast();
  const { active, hasWsRole } = useWorkspace();
  const wid = active?.id;
  const list = usePolling((opts) => cameras.list(opts), { intervalMs: 5000, deps: [wid], enabled: Boolean(wid) });
  const catalogue = useAsync((opts) => (wid ? cameras.pipelines(opts) : null), [wid]);
  const titles = useMemo(
    () => Object.fromEntries((catalogue.data?.pipelines || []).map((p) => [p.name, p.title])),
    [catalogue.data]
  );
  const [busyId, setBusyId] = useState(null);
  const [pendingDelete, setPendingDelete] = useState(null);
  const canRun = hasWsRole("operator");
  const canEdit = hasWsRole("admin");

  if (!active) {
    return <EmptyState title="No workspace yet" description="Cameras belong to a workspace. Ask an admin to add you to one." />;
  }

  async function toggle(c) {
    setBusyId(c.id);
    try {
      if (c.enabled) {
        await cameras.stop(c.id);
        toast(`Stopped ${c.name}.`);
      } else {
        await cameras.start(c.id);
        toast(`Starting ${c.name}…`);
      }
      list.reload();
    } catch (e) {
      toast(e.message, "err");
    } finally {
      setBusyId(null);
    }
  }

  async function confirmDelete() {
    const c = pendingDelete;
    setBusyId(c.id);
    try {
      await cameras.remove(c.id);
      toast(`Deleted ${c.name}.`);
      list.reload();
    } catch (e) {
      toast(e.message, "err");
    } finally {
      setBusyId(null);
      setPendingDelete(null);
    }
  }

  const rows = list.data || [];
  const live = rows.filter((c) => c.status.running).length;

  return (
    <Box>
      <PageHeader
        title="Cameras"
        subtitle={`${rows.length} of ${active.max_cameras} cameras in ${active.name} · ${live} live. Each can run a lab pipeline continuously.`}
        actions={
          canEdit && (
            <Button component={RouterLink} to="/cameras/new" variant="contained" startIcon={<AddIcon />}>
              Add camera
            </Button>
          )
        }
      />
      <ErrorState error={list.error} onRetry={list.reload} />

      {list.loading && !list.data ? (
        <Card aria-busy="true" sx={{ p: 2 }}>
          {Array.from({ length: 5 }, (_, i) => <Skeleton key={i} height={44} />)}
        </Card>
      ) : rows.length ? (
        <Card>
          <TableContainer>
            <Table size="small">
              <TableHead>
                <TableRow>
                  <TableCell>Camera</TableCell>
                  <TableCell>Pipeline</TableCell>
                  <TableCell>State</TableCell>
                  <TableCell>Now</TableCell>
                  <TableCell>Source</TableCell>
                  <TableCell align="right">Actions</TableCell>
                </TableRow>
              </TableHead>
              <TableBody>
                {rows.map((c) => (
                  <TableRow key={c.id} hover>
                    <TableCell sx={{ minWidth: 180 }}>
                      <Link component={RouterLink} to={`/cameras/${c.id}`} underline="hover" sx={{ fontWeight: 600 }}>
                        {c.name}
                      </Link>
                      {c.location && (
                        <Typography variant="caption" color="text.secondary" sx={{ display: "block" }}>{c.location}</Typography>
                      )}
                    </TableCell>
                    <TableCell><Typography variant="body2" noWrap>{c.pipeline ? titles[c.pipeline] || c.pipeline : "Live view only"}</Typography></TableCell>
                    <TableCell><CameraStateChip state={c.status.state} error={c.status.last_error} /></TableCell>
                    <TableCell>
                      <Typography variant="body2" color="text.secondary" noWrap>
                        {c.status.running ? [metricSummary(c.status.metrics, 2), c.status.fps ? `${c.status.fps} fps` : ""].filter(Boolean).join(" · ") || "…" : "—"}
                      </Typography>
                    </TableCell>
                    <TableCell sx={{ ...mono, maxWidth: 260 }}><Box component="span" sx={{ display: "block", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{c.source_url}</Box></TableCell>
                    <TableCell align="right">
                      <Stack direction="row" spacing={0.5} justifyContent="flex-end">
                        {canRun && (
                          <Tooltip title={c.enabled ? "Stop" : "Start"}>
                            <span>
                              <IconButton size="small" color={c.enabled ? "default" : "success"} disabled={busyId === c.id}
                                onClick={() => toggle(c)} aria-label={`${c.enabled ? "Stop" : "Start"} ${c.name}`}>
                                {c.enabled ? <StopIcon fontSize="small" /> : <PlayArrowIcon fontSize="small" />}
                              </IconButton>
                            </span>
                          </Tooltip>
                        )}
                        {canEdit && (
                          <>
                            <Tooltip title="Edit">
                              <IconButton size="small" component={RouterLink} to={`/cameras/${c.id}/edit`} aria-label={`Edit ${c.name}`}>
                                <EditIcon fontSize="small" />
                              </IconButton>
                            </Tooltip>
                            <Tooltip title="Delete">
                              <IconButton size="small" color="error" onClick={() => setPendingDelete(c)} aria-label={`Delete ${c.name}`}>
                                <DeleteOutlineIcon fontSize="small" />
                              </IconButton>
                            </Tooltip>
                          </>
                        )}
                      </Stack>
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </TableContainer>
        </Card>
      ) : (
        list.data && (
          <EmptyState
            icon={<VideocamIcon />}
            title="No cameras yet"
            description={canEdit ? "Add an RTSP camera, or try one of the sample videos." : "A workspace admin adds cameras."}
            action={canEdit && <Button component={RouterLink} to="/cameras/new" variant="contained" startIcon={<AddIcon />}>Add camera</Button>}
          />
        )
      )}

      <ConfirmDialog
        open={Boolean(pendingDelete)}
        title="Delete this camera?"
        description={pendingDelete ? `${pendingDelete.name} stops and is removed.` : ""}
        confirmLabel="Delete"
        confirmColor="error"
        busy={busyId === pendingDelete?.id}
        onConfirm={confirmDelete}
        onClose={() => setPendingDelete(null)}
      />
    </Box>
  );
}
