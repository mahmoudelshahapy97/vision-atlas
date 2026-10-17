import { useMemo, useState } from "react";
import { Link as RouterLink } from "react-router-dom";
import Box from "@mui/material/Box";
import Button from "@mui/material/Button";
import Card from "@mui/material/Card";
import IconButton from "@mui/material/IconButton";
import InputAdornment from "@mui/material/InputAdornment";
import Link from "@mui/material/Link";
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
import AddIcon from "@mui/icons-material/Add";
import DeleteOutlineIcon from "@mui/icons-material/DeleteOutline";
import EditIcon from "@mui/icons-material/Edit";
import SearchIcon from "@mui/icons-material/Search";
import StarIcon from "@mui/icons-material/Star";

import { projects } from "../../api/endpoints";
import ConfirmDialog from "../../components/ConfirmDialog";
import { EmptyState, ErrorState, Loading } from "../../components/DataStates";
import PageHeader from "../../components/PageHeader";
import { useToast } from "../../components/Toast";
import { useAsync } from "../../hooks/useAsync";
import { LEVELS } from "../../utils/constants";
import { pad } from "../../utils/format";
import { MONO_FONT } from "../../utils/theme";

const mono = { fontFamily: MONO_FONT, fontSize: 12.5 };

/** Admin: every project, with edit and delete. */
export default function ProjectList() {
  const toast = useToast();
  const list = useAsync((opts) => projects.list({ size: 200 }, opts), []);
  const [q, setQ] = useState("");
  const [pendingDelete, setPendingDelete] = useState(null);
  const [busy, setBusy] = useState(false);

  const rows = useMemo(() => {
    const items = list.data?.items || [];
    const s = q.trim().toLowerCase();
    return s ? items.filter((p) => `${p.id} ${p.title} ${p.domain.name}`.toLowerCase().includes(s)) : items;
  }, [list.data, q]);

  async function confirmDelete() {
    const p = pendingDelete;
    setBusy(true);
    try {
      await projects.remove(p.id);
      toast(`Deleted #${pad(p.id)} ${p.title}.`);
      list.reload();
    } catch (e) {
      toast(e.message, "err");
    } finally {
      setBusy(false);
      setPendingDelete(null);
    }
  }

  return (
    <Box>
      <PageHeader
        title="Projects"
        subtitle="Catalog management: add, edit or remove projects."
        actions={
          <Button component={RouterLink} to="/admin/new" variant="contained" startIcon={<AddIcon />}>
            New project
          </Button>
        }
      />

      <Stack direction="row" spacing={2} alignItems="center" sx={{ mb: 2 }}>
        <TextField
          type="search"
          size="small"
          value={q}
          onChange={(e) => setQ(e.target.value)}
          placeholder="Filter by number, title or domain"
          inputProps={{ "aria-label": "Filter projects" }}
          sx={{ flexGrow: 1, maxWidth: 420 }}
          InputProps={{ startAdornment: <InputAdornment position="start"><SearchIcon fontSize="small" /></InputAdornment> }}
        />
        <Typography variant="body2" color="text.secondary">{rows.length} of {list.data?.total ?? "…"} projects</Typography>
      </Stack>
      <ErrorState error={list.error} onRetry={list.reload} />

      {list.loading && !list.data ? (
        <Loading label="Loading projects…" />
      ) : rows.length ? (
        <Card>
          <TableContainer>
            <Table size="small">
              <TableHead>
                <TableRow>
                  <TableCell>#</TableCell>
                  <TableCell>Title</TableCell>
                  <TableCell>Domain</TableCell>
                  <TableCell>Task</TableCell>
                  <TableCell>Level</TableCell>
                  <TableCell>Pick</TableCell>
                  <TableCell align="right">Actions</TableCell>
                </TableRow>
              </TableHead>
              <TableBody>
                {rows.map((p) => (
                  <TableRow key={p.id} hover>
                    <TableCell sx={mono}>{pad(p.id)}</TableCell>
                    <TableCell sx={{ minWidth: 220 }}>
                      <Link component={RouterLink} to={`/projects/${p.id}`} underline="hover" sx={{ fontWeight: 600 }}>{p.title}</Link>
                    </TableCell>
                    <TableCell><Typography variant="body2" color="text.secondary" noWrap>{p.domain.name}</Typography></TableCell>
                    <TableCell sx={mono}>{p.task_type.code}</TableCell>
                    <TableCell>{LEVELS[p.level]}</TableCell>
                    <TableCell>{p.is_pick ? <StarIcon fontSize="small" color="warning" titleAccess="Top pick" /> : null}</TableCell>
                    <TableCell align="right">
                      <Stack direction="row" spacing={0.5} justifyContent="flex-end">
                        <Tooltip title="Edit">
                          <IconButton size="small" component={RouterLink} to={`/admin/${p.id}/edit`} aria-label={`Edit ${p.title}`}>
                            <EditIcon fontSize="small" />
                          </IconButton>
                        </Tooltip>
                        <Tooltip title="Delete">
                          <IconButton size="small" color="error" onClick={() => setPendingDelete(p)} aria-label={`Delete ${p.title}`}>
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
        list.data && <EmptyState title="No projects match" description="Try another filter." />
      )}

      <ConfirmDialog
        open={Boolean(pendingDelete)}
        title="Delete this project?"
        description={pendingDelete ? `#${pad(pendingDelete.id)} ${pendingDelete.title} and everyone's progress on it are removed.` : ""}
        confirmLabel="Delete"
        confirmColor="error"
        busy={busy}
        onConfirm={confirmDelete}
        onClose={() => setPendingDelete(null)}
      />
    </Box>
  );
}
