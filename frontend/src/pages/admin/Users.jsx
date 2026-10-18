import { useState } from "react";
import Box from "@mui/material/Box";
import Button from "@mui/material/Button";
import Card from "@mui/material/Card";
import Chip from "@mui/material/Chip";
import IconButton from "@mui/material/IconButton";
import InputAdornment from "@mui/material/InputAdornment";
import MenuItem from "@mui/material/MenuItem";
import Skeleton from "@mui/material/Skeleton";
import Stack from "@mui/material/Stack";
import Switch from "@mui/material/Switch";
import Table from "@mui/material/Table";
import TableBody from "@mui/material/TableBody";
import TableCell from "@mui/material/TableCell";
import TableContainer from "@mui/material/TableContainer";
import TableHead from "@mui/material/TableHead";
import TablePagination from "@mui/material/TablePagination";
import TableRow from "@mui/material/TableRow";
import TextField from "@mui/material/TextField";
import Tooltip from "@mui/material/Tooltip";
import Typography from "@mui/material/Typography";
import AddIcon from "@mui/icons-material/Add";
import DeleteOutlineIcon from "@mui/icons-material/DeleteOutline";
import EditIcon from "@mui/icons-material/Edit";
import LockResetIcon from "@mui/icons-material/LockReset";
import SearchIcon from "@mui/icons-material/Search";

import { users } from "../../api/endpoints";
import { useAuth } from "../../auth/AuthContext";
import { ROLES } from "../../auth/roles";
import ConfirmDialog from "../../components/ConfirmDialog";
import { EmptyState, ErrorState } from "../../components/DataStates";
import PageHeader from "../../components/PageHeader";
import PasswordDialog from "../../components/PasswordDialog";
import { useToast } from "../../components/Toast";
import { useAsync } from "../../hooks/useAsync";
import { useDebounced } from "../../hooks/useDebounced";
import { formatDateTime } from "../../utils/format";
import UserForm from "./UserForm";

const ROLE_COLOR = { admin: "error", user: "primary" };
const PER_PAGE = 25;

/** Admin: every account, with role, active switch, password reset and delete. */
export default function Users() {
  const toast = useToast();
  const { user: me } = useAuth();
  const [q, setQ] = useState("");
  const [role, setRole] = useState("");
  const [page, setPage] = useState(0);
  const query = useDebounced(q.trim(), 300);
  const list = useAsync(
    (opts) => users.list({ q: query, role, page: page + 1, per_page: PER_PAGE }, opts),
    [query, role, page]
  );

  const [form, setForm] = useState({ open: false, editing: null });
  const [pendingDelete, setPendingDelete] = useState(null);
  const [pendingReset, setPendingReset] = useState(null);
  const [busyId, setBusyId] = useState(null);

  const rows = list.data?.items || [];

  async function toggleActive(u) {
    setBusyId(u.id);
    try {
      await users.update(u.id, { is_active: !u.is_active });
      toast(`${u.name} ${u.is_active ? "deactivated: signed out everywhere" : "reactivated"}.`);
      list.reload();
    } catch (e) {
      toast(e.message, "err");
    } finally {
      setBusyId(null);
    }
  }

  async function confirmDelete() {
    const u = pendingDelete;
    setBusyId(u.id);
    try {
      await users.remove(u.id);
      toast(`Deleted ${u.email}.`);
      list.reload();
    } catch (e) {
      toast(e.message, "err");
    } finally {
      setBusyId(null);
      setPendingDelete(null);
    }
  }

  async function resetPassword(newPassword) {
    await users.resetPassword(pendingReset.id, newPassword);
    toast(`Password for ${pendingReset.email} changed. Their sessions were signed out.`);
    setPendingReset(null);
  }

  return (
    <Box>
      <PageHeader
        title="Users"
        subtitle="Every account. Anyone can register; admins create accounts here, set roles and deactivate them."
        actions={
          <Button onClick={() => setForm({ open: true, editing: null })} variant="contained" startIcon={<AddIcon />}>
            New account
          </Button>
        }
      />

      <Stack direction={{ xs: "column", sm: "row" }} spacing={2} alignItems={{ sm: "center" }} sx={{ mb: 2 }}>
        <TextField
          type="search"
          size="small"
          value={q}
          onChange={(e) => {
            setQ(e.target.value);
            setPage(0);
          }}
          placeholder="Search by name or email"
          inputProps={{ "aria-label": "Search users" }}
          sx={{ flexGrow: 1, maxWidth: { sm: 420 } }}
          InputProps={{ startAdornment: <InputAdornment position="start"><SearchIcon fontSize="small" /></InputAdornment> }}
        />
        <TextField
          select
          size="small"
          label="Role"
          value={role}
          onChange={(e) => {
            setRole(e.target.value);
            setPage(0);
          }}
          SelectProps={{ displayEmpty: true }}
          InputLabelProps={{ shrink: true }}
          sx={{ minWidth: 140 }}
        >
          <MenuItem value="">Any role</MenuItem>
          {ROLES.map((r) => (
            <MenuItem key={r} value={r}>{r}</MenuItem>
          ))}
        </TextField>
        <Typography variant="body2" color="text.secondary">{list.data ? `${list.data.total} account${list.data.total === 1 ? "" : "s"}` : "…"}</Typography>
      </Stack>
      <ErrorState error={list.error} onRetry={list.reload} />

      {list.loading && !list.data ? (
        <Card aria-busy="true" sx={{ p: 2 }}>
          {Array.from({ length: 8 }, (_, i) => <Skeleton key={i} height={40} />)}
        </Card>
      ) : rows.length ? (
        <Card>
          <TableContainer>
            <Table size="small">
              <TableHead>
                <TableRow>
                  <TableCell>Name</TableCell>
                  <TableCell>Email</TableCell>
                  <TableCell>Role</TableCell>
                  <TableCell>Active</TableCell>
                  <TableCell>Last sign-in</TableCell>
                  <TableCell>Created</TableCell>
                  <TableCell align="right">Actions</TableCell>
                </TableRow>
              </TableHead>
              <TableBody>
                {rows.map((u) => {
                  const busy = busyId === u.id;
                  const self = u.id === me?.id;
                  return (
                    <TableRow key={u.id} hover sx={{ opacity: u.is_active ? 1 : 0.6 }}>
                      <TableCell sx={{ fontWeight: 600, minWidth: 160 }}>
                        {u.name}
                        {self && (
                          <Typography component="span" variant="caption" color="text.secondary"> (you)</Typography>
                        )}
                      </TableCell>
                      <TableCell>{u.email}</TableCell>
                      <TableCell>
                        <Chip size="small" label={u.role} color={ROLE_COLOR[u.role] || "default"} />
                      </TableCell>
                      <TableCell>
                        <Tooltip title={self ? "You can't deactivate yourself" : u.is_active ? "Deactivate" : "Reactivate"}>
                          <span>
                            <Switch
                              size="small"
                              checked={u.is_active}
                              disabled={busy || self}
                              onChange={() => toggleActive(u)}
                              inputProps={{ "aria-label": `${u.name} active` }}
                            />
                          </span>
                        </Tooltip>
                      </TableCell>
                      <TableCell><Typography variant="body2" noWrap>{formatDateTime(u.last_login)}</Typography></TableCell>
                      <TableCell><Typography variant="body2" noWrap>{formatDateTime(u.created_at)}</Typography></TableCell>
                      <TableCell align="right">
                        <Stack direction="row" spacing={0.5} justifyContent="flex-end">
                          <Tooltip title="Edit">
                            <IconButton size="small" disabled={busy} onClick={() => setForm({ open: true, editing: u })} aria-label={`Edit ${u.name}`}>
                              <EditIcon fontSize="small" />
                            </IconButton>
                          </Tooltip>
                          <Tooltip title="Set a new password">
                            <IconButton size="small" disabled={busy} onClick={() => setPendingReset(u)} aria-label={`Reset password for ${u.name}`}>
                              <LockResetIcon fontSize="small" />
                            </IconButton>
                          </Tooltip>
                          <Tooltip title={self ? "You can't delete your own account" : "Delete"}>
                            <span>
                              <IconButton size="small" color="error" disabled={busy || self} onClick={() => setPendingDelete(u)} aria-label={`Delete ${u.name}`}>
                                <DeleteOutlineIcon fontSize="small" />
                              </IconButton>
                            </span>
                          </Tooltip>
                        </Stack>
                      </TableCell>
                    </TableRow>
                  );
                })}
              </TableBody>
            </Table>
          </TableContainer>
          <TablePagination
            component="div"
            count={list.data?.total || 0}
            page={page}
            onPageChange={(_, p) => setPage(p)}
            rowsPerPage={PER_PAGE}
            rowsPerPageOptions={[PER_PAGE]}
          />
        </Card>
      ) : (
        list.data && <EmptyState title="No accounts match" description="Try another search or role." />
      )}

      <UserForm
        open={form.open}
        editing={form.editing}
        onClose={() => setForm({ open: false, editing: null })}
        onSaved={() => {
          setForm({ open: false, editing: null });
          list.reload();
        }}
      />

      <PasswordDialog
        open={Boolean(pendingReset)}
        title="Set a new password"
        description={pendingReset ? `For ${pendingReset.email}. Every session of the account is signed out.` : ""}
        submitLabel="Set password"
        onSubmit={resetPassword}
        onClose={() => setPendingReset(null)}
      />

      <ConfirmDialog
        open={Boolean(pendingDelete)}
        title="Delete this account?"
        description={pendingDelete ? `${pendingDelete.email} is removed with their lab runs, run files, board and uploaded models.` : ""}
        confirmLabel="Delete"
        confirmColor="error"
        busy={busyId === pendingDelete?.id}
        onConfirm={confirmDelete}
        onClose={() => setPendingDelete(null)}
      />
    </Box>
  );
}
