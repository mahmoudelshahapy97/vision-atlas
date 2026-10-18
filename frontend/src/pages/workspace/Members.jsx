import { useState } from "react";
import { useNavigate } from "react-router-dom";
import Alert from "@mui/material/Alert";
import Box from "@mui/material/Box";
import Button from "@mui/material/Button";
import Card from "@mui/material/Card";
import CardContent from "@mui/material/CardContent";
import Chip from "@mui/material/Chip";
import IconButton from "@mui/material/IconButton";
import MenuItem from "@mui/material/MenuItem";
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
import PersonAddIcon from "@mui/icons-material/PersonAdd";
import PersonRemoveIcon from "@mui/icons-material/PersonRemove";

import { workspaces as workspacesApi } from "../../api/endpoints";
import { useAuth } from "../../auth/AuthContext";
import { WS_ROLES } from "../../auth/roles";
import ConfirmDialog from "../../components/ConfirmDialog";
import { EmptyState, ErrorState } from "../../components/DataStates";
import PageHeader from "../../components/PageHeader";
import { useToast } from "../../components/Toast";
import { useAsync } from "../../hooks/useAsync";
import { formatDate } from "../../utils/format";
import { useWorkspace } from "../../workspace/WorkspaceContext";

const ROLE_HELP = {
  viewer: "Watches live cameras, events and analytics.",
  operator: "Also starts and stops cameras, handles events and shares models.",
  admin: "Also adds cameras and manages members.",
};
const ROLE_COLOR = { admin: "error", operator: "primary", viewer: "default" };

/** The active workspace's members. Workspace admins add, re-role and remove; anyone can leave. */
export default function Members() {
  const toast = useToast();
  const navigate = useNavigate();
  const { user } = useAuth();
  const { active, hasWsRole, reload: reloadWorkspaces } = useWorkspace();
  const wid = active?.id;
  const list = useAsync((opts) => (wid ? workspacesApi.members(wid, opts) : null), [wid]);
  const canManage = hasWsRole("admin");

  const [email, setEmail] = useState("");
  const [role, setRole] = useState("viewer");
  const [busy, setBusy] = useState(false);
  const [pendingRemove, setPendingRemove] = useState(null);

  if (!active) {
    return (
      <EmptyState
        title="No workspace yet"
        description="Workspaces hold cameras, their events and shared models. Ask an admin to add you to one."
      />
    );
  }

  async function add(e) {
    e.preventDefault();
    setBusy(true);
    try {
      const m = await workspacesApi.addMember(wid, email.trim(), role);
      toast(`Added ${m.name} as ${m.role}.`);
      setEmail("");
      list.reload();
      reloadWorkspaces();
    } catch (err) {
      toast(err.message, "err");
    } finally {
      setBusy(false);
    }
  }

  async function changeRole(m, next) {
    try {
      await workspacesApi.setMemberRole(wid, m.user_id, next);
      toast(`${m.name} is now ${next}.`);
      list.reload();
      if (m.user_id === user.id) reloadWorkspaces();
    } catch (err) {
      toast(err.message, "err");
    }
  }

  async function confirmRemove() {
    const m = pendingRemove;
    setBusy(true);
    try {
      await workspacesApi.removeMember(wid, m.user_id);
      if (m.user_id === user.id) {
        toast(`You left ${active.name}.`);
        await reloadWorkspaces();
        navigate("/", { replace: true });
        return;
      }
      toast(`Removed ${m.name}.`);
      list.reload();
      reloadWorkspaces();
    } catch (err) {
      toast(err.message, "err");
    } finally {
      setBusy(false);
      setPendingRemove(null);
    }
  }

  const rows = list.data || [];
  const self = rows.find((m) => m.user_id === user?.id);

  return (
    <Box>
      <PageHeader
        title="Members"
        subtitle={`Who can see and run ${active.name}. Roles apply only inside this workspace.`}
        actions={
          self && (
            <Button color="inherit" startIcon={<PersonRemoveIcon />} onClick={() => setPendingRemove(self)}>
              Leave workspace
            </Button>
          )
        }
      />

      {canManage && (
        <Card sx={{ mb: 2 }}>
          <CardContent>
            <Box component="form" onSubmit={add}>
              <Stack direction={{ xs: "column", md: "row" }} spacing={1.5} alignItems={{ md: "flex-start" }}>
                <TextField
                  size="small"
                  type="email"
                  label="Email of an existing account"
                  value={email}
                  onChange={(e) => setEmail(e.target.value)}
                  sx={{ flexGrow: 1 }}
                />
                <TextField
                  select
                  size="small"
                  label="Role"
                  value={role}
                  onChange={(e) => setRole(e.target.value)}
                  helperText={ROLE_HELP[role]}
                  sx={{ minWidth: { md: 260 } }}
                >
                  {WS_ROLES.map((r) => (
                    <MenuItem key={r} value={r}>{r}</MenuItem>
                  ))}
                </TextField>
                <Button type="submit" variant="contained" startIcon={<PersonAddIcon />} disabled={busy || !email.trim()} sx={{ flexShrink: 0 }}>
                  Add member
                </Button>
              </Stack>
            </Box>
          </CardContent>
        </Card>
      )}
      {!canManage && (
        <Alert severity="info" sx={{ mb: 2 }}>
          You are {active.my_role === "operator" ? "an" : "a"} {active.my_role} here. Workspace admins manage members.
        </Alert>
      )}

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
                  <TableCell>Email</TableCell>
                  <TableCell>Role</TableCell>
                  <TableCell>Member since</TableCell>
                  {canManage && <TableCell align="right">Remove</TableCell>}
                </TableRow>
              </TableHead>
              <TableBody>
                {rows.map((m) => (
                  <TableRow key={m.user_id} hover sx={{ opacity: m.is_active ? 1 : 0.6 }}>
                    <TableCell sx={{ fontWeight: 600, minWidth: 140 }}>
                      {m.name}
                      {m.user_id === user?.id && (
                        <Typography component="span" variant="caption" color="text.secondary"> (you)</Typography>
                      )}
                      {!m.is_active && <Chip size="small" label="deactivated" sx={{ ml: 1 }} />}
                    </TableCell>
                    <TableCell>{m.email}</TableCell>
                    <TableCell>
                      {canManage ? (
                        <TextField
                          select
                          size="small"
                          value={m.role}
                          onChange={(e) => changeRole(m, e.target.value)}
                          SelectProps={{ SelectDisplayProps: { "aria-label": `Role of ${m.name}`, "aria-labelledby": undefined } }}
                          sx={{ minWidth: 120 }}
                        >
                          {WS_ROLES.map((r) => (
                            <MenuItem key={r} value={r}>{r}</MenuItem>
                          ))}
                        </TextField>
                      ) : (
                        <Chip size="small" label={m.role} color={ROLE_COLOR[m.role]} />
                      )}
                    </TableCell>
                    <TableCell>{formatDate(m.created_at)}</TableCell>
                    {canManage && (
                      <TableCell align="right">
                        <Tooltip title="Remove from workspace">
                          <IconButton size="small" color="error" onClick={() => setPendingRemove(m)} aria-label={`Remove ${m.name}`}>
                            <PersonRemoveIcon fontSize="small" />
                          </IconButton>
                        </Tooltip>
                      </TableCell>
                    )}
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </TableContainer>
        </Card>
      ) : (
        list.data && (
          <EmptyState
            title="No members yet"
            description={canManage ? "Add people by the email they signed up with." : "A workspace admin adds members."}
          />
        )
      )}

      <ConfirmDialog
        open={Boolean(pendingRemove)}
        title={pendingRemove?.user_id === user?.id ? "Leave this workspace?" : "Remove this member?"}
        description={
          pendingRemove
            ? pendingRemove.user_id === user?.id
              ? `You lose access to ${active.name}'s cameras, events and shared models.`
              : `${pendingRemove.name} loses access to ${active.name}.`
            : ""
        }
        confirmLabel={pendingRemove?.user_id === user?.id ? "Leave" : "Remove"}
        confirmColor="error"
        busy={busy}
        onConfirm={confirmRemove}
        onClose={() => setPendingRemove(null)}
      />
    </Box>
  );
}
