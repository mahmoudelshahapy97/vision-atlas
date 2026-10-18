import { useState } from "react";
import { useNavigate } from "react-router-dom";
import Box from "@mui/material/Box";
import Button from "@mui/material/Button";
import Card from "@mui/material/Card";
import Chip from "@mui/material/Chip";
import IconButton from "@mui/material/IconButton";
import Skeleton from "@mui/material/Skeleton";
import Stack from "@mui/material/Stack";
import Switch from "@mui/material/Switch";
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
import GroupIcon from "@mui/icons-material/Group";

import { workspaces } from "../../api/endpoints";
import ConfirmDialog from "../../components/ConfirmDialog";
import { EmptyState, ErrorState } from "../../components/DataStates";
import PageHeader from "../../components/PageHeader";
import { useToast } from "../../components/Toast";
import { useAsync } from "../../hooks/useAsync";
import { formatDate } from "../../utils/format";
import { useWorkspace } from "../../workspace/WorkspaceContext";
import WorkspaceForm from "./WorkspaceForm";

/** System admin: every workspace, its limits and allowed pipelines. */
export default function Workspaces() {
  const toast = useToast();
  const navigate = useNavigate();
  const { setActive, reload: reloadMine } = useWorkspace();
  const list = useAsync((opts) => workspaces.list(opts), []);
  const [form, setForm] = useState({ open: false, editing: null });
  const [pendingDelete, setPendingDelete] = useState(null);
  const [busyId, setBusyId] = useState(null);

  const refresh = () => {
    list.reload();
    reloadMine();
  };

  async function toggleActive(w) {
    setBusyId(w.id);
    try {
      await workspaces.update(w.id, { is_active: !w.is_active });
      toast(`${w.name} ${w.is_active ? "deactivated: members lose access" : "reactivated"}.`);
      refresh();
    } catch (e) {
      toast(e.message, "err");
    } finally {
      setBusyId(null);
    }
  }

  async function confirmDelete() {
    const w = pendingDelete;
    setBusyId(w.id);
    try {
      await workspaces.remove(w.id);
      toast(`Deleted ${w.name}.`);
      refresh();
    } catch (e) {
      toast(e.message, "err");
    } finally {
      setBusyId(null);
      setPendingDelete(null);
    }
  }

  function openMembers(w) {
    setActive(w.id);
    navigate("/workspace/members");
  }

  const rows = list.data || [];

  return (
    <Box>
      <PageHeader
        title="Workspaces"
        subtitle="Each workspace holds a team's cameras, events and shared models. You act as admin in all of them."
        actions={
          <Button onClick={() => setForm({ open: true, editing: null })} variant="contained" startIcon={<AddIcon />}>
            New workspace
          </Button>
        }
      />
      <ErrorState error={list.error} onRetry={list.reload} />

      {list.loading && !list.data ? (
        <Card aria-busy="true" sx={{ p: 2 }}>
          {Array.from({ length: 5 }, (_, i) => <Skeleton key={i} height={40} />)}
        </Card>
      ) : rows.length ? (
        <Card>
          <TableContainer>
            <Table size="small">
              <TableHead>
                <TableRow>
                  <TableCell>Name</TableCell>
                  <TableCell>Members</TableCell>
                  <TableCell>Camera limit</TableCell>
                  <TableCell>Pipelines</TableCell>
                  <TableCell>Active</TableCell>
                  <TableCell>Created</TableCell>
                  <TableCell align="right">Actions</TableCell>
                </TableRow>
              </TableHead>
              <TableBody>
                {rows.map((w) => (
                  <TableRow key={w.id} hover sx={{ opacity: w.is_active ? 1 : 0.6 }}>
                    <TableCell sx={{ minWidth: 200 }}>
                      <Typography variant="body2" sx={{ fontWeight: 600 }}>{w.name}</Typography>
                      {w.description && (
                        <Typography variant="caption" color="text.secondary" sx={{ display: "block", maxWidth: 360 }} noWrap>
                          {w.description}
                        </Typography>
                      )}
                    </TableCell>
                    <TableCell>{w.member_count}</TableCell>
                    <TableCell>{w.max_cameras}</TableCell>
                    <TableCell>
                      {w.enabled_pipelines == null ? (
                        <Chip size="small" variant="outlined" label="All" />
                      ) : (
                        <Tooltip title={w.enabled_pipelines.join(", ")}>
                          <Chip size="small" variant="outlined" color="info" label={`${w.enabled_pipelines.length} allowed`} />
                        </Tooltip>
                      )}
                    </TableCell>
                    <TableCell>
                      <Switch
                        size="small"
                        checked={w.is_active}
                        disabled={busyId === w.id}
                        onChange={() => toggleActive(w)}
                        inputProps={{ "aria-label": `${w.name} active` }}
                      />
                    </TableCell>
                    <TableCell><Typography variant="body2" noWrap>{formatDate(w.created_at)}</Typography></TableCell>
                    <TableCell align="right">
                      <Stack direction="row" spacing={0.5} justifyContent="flex-end">
                        <Tooltip title="Members">
                          <IconButton size="small" onClick={() => openMembers(w)} aria-label={`Members of ${w.name}`}>
                            <GroupIcon fontSize="small" />
                          </IconButton>
                        </Tooltip>
                        <Tooltip title="Edit">
                          <IconButton size="small" onClick={() => setForm({ open: true, editing: w })} aria-label={`Edit ${w.name}`}>
                            <EditIcon fontSize="small" />
                          </IconButton>
                        </Tooltip>
                        <Tooltip title="Delete">
                          <IconButton size="small" color="error" onClick={() => setPendingDelete(w)} aria-label={`Delete ${w.name}`}>
                            <DeleteOutlineIcon fontSize="small" />
                          </IconButton>
                        </Tooltip>
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
            title="No workspaces yet"
            description="Create one per site or team, then add its members."
            action={
              <Button onClick={() => setForm({ open: true, editing: null })} variant="contained" startIcon={<AddIcon />}>
                New workspace
              </Button>
            }
          />
        )
      )}

      <WorkspaceForm
        open={form.open}
        editing={form.editing}
        onClose={() => setForm({ open: false, editing: null })}
        onSaved={() => {
          setForm({ open: false, editing: null });
          refresh();
        }}
      />
      <ConfirmDialog
        open={Boolean(pendingDelete)}
        title="Delete this workspace?"
        description={
          pendingDelete
            ? `${pendingDelete.name} and its memberships are removed. Models shared with it go back to their owners.`
            : ""
        }
        confirmLabel="Delete"
        confirmColor="error"
        busy={busyId === pendingDelete?.id}
        onConfirm={confirmDelete}
        onClose={() => setPendingDelete(null)}
      />
    </Box>
  );
}
