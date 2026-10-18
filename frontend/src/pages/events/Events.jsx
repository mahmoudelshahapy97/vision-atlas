import { useEffect, useState } from "react";
import { Link as RouterLink, useSearchParams } from "react-router-dom";
import Box from "@mui/material/Box";
import Card from "@mui/material/Card";
import IconButton from "@mui/material/IconButton";
import Link from "@mui/material/Link";
import MenuItem from "@mui/material/MenuItem";
import Skeleton from "@mui/material/Skeleton";
import Stack from "@mui/material/Stack";
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
import CheckIcon from "@mui/icons-material/Check";
import DoneAllIcon from "@mui/icons-material/DoneAll";
import NotificationsNoneIcon from "@mui/icons-material/NotificationsNone";

import { cameras, events } from "../../api/endpoints";
import { EmptyState, ErrorState } from "../../components/DataStates";
import { EventStatusChip, STATUS_LABEL, SeverityChip, Snapshot, kindLabel } from "../../components/events/EventBits";
import PageHeader from "../../components/PageHeader";
import { useToast } from "../../components/Toast";
import { useAlerts } from "../../hooks/useAlerts";
import { useAsync } from "../../hooks/useAsync";
import { formatDateTime } from "../../utils/format";
import { useWorkspace } from "../../workspace/WorkspaceContext";

const PER_PAGE = 25;
const FILTERS = ["camera_id", "kind", "status", "severity"];

function Filter({ label, value, onChange, children, minWidth = 150 }) {
  return (
    <TextField select size="small" label={label} value={value} onChange={(e) => onChange(e.target.value)}
      SelectProps={{ displayEmpty: true }} InputLabelProps={{ shrink: true }} sx={{ minWidth }}>
      <MenuItem value="">Any</MenuItem>
      {children}
    </TextField>
  );
}

/** Every event of the workspace, filtered (kept in the URL) and handled from here. */
export default function Events() {
  const toast = useToast();
  const { active, hasWsRole } = useWorkspace();
  const { version } = useAlerts();
  const [params, setParams] = useSearchParams();
  const [page, setPage] = useState(0);
  const wid = active?.id;
  const filters = Object.fromEntries(FILTERS.map((k) => [k, params.get(k) || ""]));
  const key = FILTERS.map((k) => filters[k]).join("|");
  const list = useAsync(
    (o) => (wid ? events.list({ ...filters, page: page + 1, per_page: PER_PAGE }, o) : null),
    [wid, key, page, page === 0 ? version : 0] // new alerts refresh the first page only
  );
  const cams = useAsync((o) => (wid ? cameras.list(o) : null), [wid]);
  const stats = useAsync((o) => (wid ? events.stats(o) : null), [wid]);

  useEffect(() => setPage(0), [key]);

  if (!active) return <EmptyState title="No workspace yet" description="Events belong to a workspace's cameras." />;

  function setFilter(k, v) {
    const next = new URLSearchParams(params);
    if (v) next.set(k, v);
    else next.delete(k);
    setParams(next, { replace: true });
  }

  async function handle(e, status) {
    try {
      await events.setStatus(e.id, status);
      list.reload();
    } catch (err) {
      toast(err.message, "err");
    }
  }

  const rows = list.data?.items || [];
  const canHandle = hasWsRole("operator");

  return (
    <Box>
      <PageHeader title="Events" subtitle={`What the cameras of ${active.name} raised. Operators acknowledge, resolve or dismiss them.`} />
      <Stack direction="row" spacing={1.5} useFlexGap flexWrap="wrap" sx={{ mb: 2 }}>
        <Filter label="Camera" value={filters.camera_id} onChange={(v) => setFilter("camera_id", v)} minWidth={170}>
          {(cams.data || []).map((c) => <MenuItem key={c.id} value={String(c.id)}>{c.name}</MenuItem>)}
        </Filter>
        <Filter label="Kind" value={filters.kind} onChange={(v) => setFilter("kind", v)}>
          {(stats.data?.kinds || []).map((k) => <MenuItem key={k} value={k}>{kindLabel(k)}</MenuItem>)}
        </Filter>
        <Filter label="Status" value={filters.status} onChange={(v) => setFilter("status", v)}>
          {Object.entries(STATUS_LABEL).map(([k, l]) => <MenuItem key={k} value={k}>{l}</MenuItem>)}
        </Filter>
        <Filter label="Severity" value={filters.severity} onChange={(v) => setFilter("severity", v)} minWidth={130}>
          {["critical", "warning", "info"].map((k) => <MenuItem key={k} value={k}>{k}</MenuItem>)}
        </Filter>
        <Typography variant="body2" color="text.secondary" sx={{ alignSelf: "center" }}>
          {list.data ? `${list.data.total} event${list.data.total === 1 ? "" : "s"}` : "…"}
        </Typography>
      </Stack>
      <ErrorState error={list.error} onRetry={list.reload} />

      {list.loading && !list.data ? (
        <Card aria-busy="true" sx={{ p: 2 }}>{Array.from({ length: 6 }, (_, i) => <Skeleton key={i} height={64} />)}</Card>
      ) : rows.length ? (
        <Card>
          <TableContainer>
            <Table size="small">
              <TableHead>
                <TableRow>
                  <TableCell>Snapshot</TableCell>
                  <TableCell>Event</TableCell>
                  <TableCell>Camera</TableCell>
                  <TableCell>When</TableCell>
                  <TableCell>Severity</TableCell>
                  <TableCell>Status</TableCell>
                  {canHandle && <TableCell align="right">Handle</TableCell>}
                </TableRow>
              </TableHead>
              <TableBody>
                {rows.map((e) => (
                  <TableRow key={e.id} hover>
                    <TableCell sx={{ py: 0.75 }}>
                      <Link component={RouterLink} to={`/events/${e.id}`} aria-label={`Open event ${e.id}`}><Snapshot event={e} height={48} /></Link>
                    </TableCell>
                    <TableCell sx={{ minWidth: 160 }}>
                      <Link component={RouterLink} to={`/events/${e.id}`} underline="hover" sx={{ fontWeight: 600 }}>{kindLabel(e.kind)}</Link>
                      <Typography variant="caption" color="text.secondary" sx={{ display: "block" }}>
                        {e.label}{e.track_id != null ? ` #${e.track_id}` : ""}
                      </Typography>
                    </TableCell>
                    <TableCell><Typography variant="body2" noWrap>{e.camera_name}</Typography></TableCell>
                    <TableCell><Typography variant="body2" noWrap>{formatDateTime(e.occurred_at)}</Typography></TableCell>
                    <TableCell><SeverityChip severity={e.severity} /></TableCell>
                    <TableCell><EventStatusChip status={e.status} /></TableCell>
                    {canHandle && (
                      <TableCell align="right">
                        <Stack direction="row" spacing={0.5} justifyContent="flex-end">
                          {e.status === "open" && (
                            <Tooltip title="Acknowledge">
                              <IconButton size="small" onClick={() => handle(e, "acknowledged")} aria-label={`Acknowledge event ${e.id}`}><CheckIcon fontSize="small" /></IconButton>
                            </Tooltip>
                          )}
                          {e.status !== "resolved" && (
                            <Tooltip title="Resolve">
                              <IconButton size="small" color="success" onClick={() => handle(e, "resolved")} aria-label={`Resolve event ${e.id}`}><DoneAllIcon fontSize="small" /></IconButton>
                            </Tooltip>
                          )}
                        </Stack>
                      </TableCell>
                    )}
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </TableContainer>
          <TablePagination component="div" count={list.data?.total || 0} page={page} onPageChange={(_, p) => setPage(p)}
            rowsPerPage={PER_PAGE} rowsPerPageOptions={[PER_PAGE]} />
        </Card>
      ) : (
        list.data && (
          <EmptyState
            icon={<NotificationsNoneIcon />}
            title={FILTERS.some((k) => filters[k]) ? "No events match" : "No events yet"}
            description={FILTERS.some((k) => filters[k]) ? "Try other filters." : "Cameras running restricted zone, fall, abandoned-object or PPE pipelines report here."}
          />
        )
      )}
    </Box>
  );
}
