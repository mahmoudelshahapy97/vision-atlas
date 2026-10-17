import { useEffect, useMemo, useState } from "react";
import { Link as RouterLink, Outlet, useNavigate, useSearchParams } from "react-router-dom";
import Badge from "@mui/material/Badge";
import Box from "@mui/material/Box";
import Button from "@mui/material/Button";
import Card from "@mui/material/Card";
import CardContent from "@mui/material/CardContent";
import Drawer from "@mui/material/Drawer";
import InputAdornment from "@mui/material/InputAdornment";
import List from "@mui/material/List";
import ListItemButton from "@mui/material/ListItemButton";
import ListItemText from "@mui/material/ListItemText";
import ListSubheader from "@mui/material/ListSubheader";
import Stack from "@mui/material/Stack";
import TextField from "@mui/material/TextField";
import ToggleButton from "@mui/material/ToggleButton";
import ToggleButtonGroup from "@mui/material/ToggleButtonGroup";
import Typography from "@mui/material/Typography";
import useMediaQuery from "@mui/material/useMediaQuery";
import { useTheme } from "@mui/material/styles";
import SearchIcon from "@mui/icons-material/Search";
import FilterListIcon from "@mui/icons-material/FilterList";

import { catalog, me, projects } from "../api/endpoints";
import { useAuth } from "../auth/AuthContext";
import { EmptyState, ErrorState, SkeletonCards } from "../components/DataStates";
import ProjectCard from "../components/ProjectCard";
import { ProgressBar } from "../components/StatusChips";
import { useAsync } from "../hooks/useAsync";
import { useDebounced } from "../hooks/useDebounced";
import { SUPPORT_FILTERS } from "../utils/constants";

const LEVEL_OPTS = [[0, "Any level"], [1, "Beginner"], [2, "Intermediate"], [3, "Advanced"]];

const LEGEND = [
  ["done", "Done", "success.main"],
  ["building", "Building", "warning.main"],
  ["planned", "Planned", "primary.main"],
  ["idea", "Idea", "divider"],
];

const Count = ({ n }) =>
  n === "" || n === undefined ? null : (
    <Typography component="span" variant="caption" color="text.secondary" sx={{ ml: 0.75, fontWeight: 600 }}>
      {n}
    </Typography>
  );

function ProgressPanel({ stats, user }) {
  if (!user) {
    return (
      <Card sx={{ width: { xs: "100%", md: 340 }, flexShrink: 0 }}>
        <CardContent>
          <Typography variant="subtitle2" gutterBottom>Track your progress</Typography>
          <Typography variant="body2" color="text.secondary" sx={{ mb: 2 }}>
            Create a free account to mark projects as planned, building or done, keep notes, and see your board.
          </Typography>
          <Stack direction="row" spacing={1}>
            <Button component={RouterLink} to="/register" variant="contained" size="small">Create account</Button>
            <Button component={RouterLink} to="/login" size="small">Sign in</Button>
          </Stack>
        </CardContent>
      </Card>
    );
  }
  const c = stats?.counts;
  return (
    <Card sx={{ width: { xs: "100%", md: 340 }, flexShrink: 0 }} aria-busy={!stats}>
      <CardContent>
        <Stack direction="row" justifyContent="space-between" sx={{ mb: 1.25 }}>
          <Typography variant="subtitle2">Your progress</Typography>
          {c && <Typography variant="body2" color="text.secondary"><b>{c.done}</b> / {stats.total} done</Typography>}
        </Stack>
        {c ? (
          <>
            <ProgressBar counts={c} total={stats.total} label={`${c.done} done, ${c.building} building, ${c.planned} planned`} />
            <Stack direction="row" spacing={1.5} useFlexGap flexWrap="wrap" sx={{ mt: 1.25 }}>
              {LEGEND.map(([k, l, color]) => (
                <Typography key={k} variant="caption" color="text.secondary" sx={{ display: "inline-flex", alignItems: "center", gap: 0.5 }}>
                  <Box component="span" sx={{ width: 8, height: 8, borderRadius: "50%", bgcolor: color }} />
                  {l} <b>{c[k]}</b>
                </Typography>
              ))}
            </Stack>
          </>
        ) : (
          <Box sx={{ height: 38 }} />
        )}
      </CardContent>
    </Card>
  );
}

function FilterList({ heading, options, selected, onSelect }) {
  return (
    <List
      dense
      disablePadding
      subheader={
        <ListSubheader
          disableSticky
          sx={{ bgcolor: "transparent", lineHeight: 2.4, textTransform: "uppercase", letterSpacing: "0.08em", fontSize: 11, px: 1 }}
        >
          {heading}
        </ListSubheader>
      }
    >
      {options.map(([value, label, count]) => (
        <ListItemButton
          key={value || "all"}
          selected={selected === value}
          onClick={() => onSelect(value)}
          sx={{ borderRadius: 2, py: 0.25, "&.Mui-selected": { color: "primary.main" } }}
        >
          <ListItemText primary={label} primaryTypographyProps={{ variant: "body2", fontWeight: selected === value ? 700 : 500, noWrap: true }} />
          <Typography variant="caption" color="text.secondary">{count}</Typography>
        </ListItemButton>
      ))}
    </List>
  );
}

export default function Catalog() {
  const { user } = useAuth();
  const theme = useTheme();
  const isDesktop = useMediaQuery(theme.breakpoints.up("md"));
  const [sp, setSp] = useSearchParams();
  const navigate = useNavigate();
  const [rev, setRev] = useState(0);
  const [filtersOpen, setFiltersOpen] = useState(false);

  const f = {
    q: sp.get("q") || "",
    domain: sp.get("domain") || "",
    task: sp.get("task") || "",
    level: Number(sp.get("level")) || 0,
    view: sp.get("view") || "all",
    support: sp.get("support") || "",
  };
  const view = f.view === "board" && !user ? "all" : f.view;
  const params = {
    q: f.q, domain: f.domain, task: f.task, level: f.level || undefined,
    picks: view === "picks" || undefined,
    status: view === "board" ? "active" : undefined,
  };
  const key = JSON.stringify(params) + (user?.id ?? "");

  const setFilters = (patch) => {
    const next = new URLSearchParams(sp);
    for (const [k, v] of Object.entries(patch)) {
      if (!v || v === "all") next.delete(k);
      else next.set(k, v);
    }
    setSp(next, { replace: true });
  };

  // search box: local state, pushed to the URL after typing pauses
  const [qInput, setQInput] = useState(f.q);
  const q = useDebounced(qInput, 250);
  useEffect(() => {
    if (q !== f.q) setFilters({ q });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [q]);
  // keep the box in sync when the URL changes from elsewhere (e.g. a tech chip link)
  useEffect(() => {
    if (f.q !== q) setQInput(f.q);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [f.q]);

  const domains = useAsync((opts) => catalog.domains(opts), []);
  const tasks = useAsync((opts) => catalog.taskTypes(opts), []);
  const list = useAsync((opts) => projects.list({ ...params, size: 200 }, opts), [key, rev]);
  const facets = useAsync((opts) => projects.facets(params, opts), [key, rev]);
  const stats = useAsync((opts) => (user ? me.stats(opts) : Promise.resolve(null)), [user?.id, rev]);
  const boardCount = useAsync(
    (opts) => (user ? projects.list({ status: "active", size: 1 }, opts) : Promise.resolve(null)),
    [user?.id, rev]
  );

  const counts = useMemo(() => {
    const m = (arr) => Object.fromEntries((arr || []).map((x) => [x.key, x.count]));
    const fd = facets.data;
    return { domains: m(fd?.domains), tasks: m(fd?.task_types), levels: m(fd?.levels) };
  }, [facets.data]);
  const facetTotal = (dim) => Object.values(counts[dim]).reduce((a, b) => a + b, 0);

  const all = list.data?.items || [];
  const items = all.filter((p) => !f.support || p.lab?.support === f.support);
  const active = f.q || f.domain || f.task || f.level || f.support;
  const activeFilters = [f.domain, f.task, f.support].filter(Boolean).length;
  const search = sp.toString();
  const open = (id) => navigate({ pathname: `/projects/${id}`, search: search ? `?${search}` : "" });

  const outletCtx = useMemo(
    () => ({ ids: items.map((p) => p.id), onChanged: () => setRev((r) => r + 1), search }),
    [items, search]
  );

  const pick = (patch) => {
    setFilters(patch);
    setFiltersOpen(false);
  };

  const filters = (
    <Stack spacing={1.5}>
      <FilterList
        heading="Domain"
        selected={f.domain}
        onSelect={(domain) => pick({ domain })}
        options={[
          ["", "All domains", facetTotal("domains")],
          ...(domains.data || []).map((d) => [d.code, d.name, counts.domains[d.code] ?? 0]),
        ]}
      />
      <FilterList
        heading="Lab readiness"
        selected={f.support}
        onSelect={(support) => pick({ support })}
        options={SUPPORT_FILTERS.map(([k, l]) => [k, l, k ? all.filter((p) => p.lab?.support === k).length : list.data ? all.length : ""])}
      />
      <FilterList
        heading="Task type"
        selected={f.task}
        onSelect={(task) => pick({ task })}
        options={[
          ["", "All tasks", facetTotal("tasks")],
          ...(tasks.data || []).map((t) => [t.code, t.name, counts.tasks[t.code] ?? 0]),
        ]}
      />
    </Stack>
  );

  const projectCount = domains.data ? domains.data.reduce((a, d) => a + d.project_count, 0) : 90;

  return (
    <Box>
      <Stack direction={{ xs: "column", md: "row" }} spacing={2} justifyContent="space-between" alignItems={{ md: "center" }} sx={{ mb: 3 }}>
        <Box sx={{ maxWidth: 680 }}>
          <Typography variant="overline" color="primary.main" sx={{ fontWeight: 700 }}>
            Computer vision · {projectCount} projects · {domains.data?.length ?? 15} domains
          </Typography>
          <Typography variant="h4" component="h1">Vision Project Atlas</Typography>
          <Typography variant="body2" color="text.secondary" sx={{ mt: 0.75 }}>
            Browse every project, filter by domain, task type and difficulty, open one for its build path and
            evaluation metric, and track what you are planning, building or have finished.
          </Typography>
        </Box>
        <ProgressPanel stats={stats.data} user={user} />
      </Stack>

      <Stack direction={{ xs: "column", lg: "row" }} spacing={1.5} sx={{ mb: 2.5 }} alignItems={{ lg: "center" }}>
        <TextField
          type="search"
          size="small"
          value={qInput}
          onChange={(e) => setQInput(e.target.value)}
          placeholder="Search projects, models or tools (e.g. YOLO, SAM, Arabic)"
          autoComplete="off"
          inputProps={{ "aria-label": "Search projects" }}
          sx={{ flexGrow: 1, minWidth: 0 }}
          InputProps={{
            startAdornment: (
              <InputAdornment position="start">
                <SearchIcon fontSize="small" />
              </InputAdornment>
            ),
          }}
        />
        <Stack direction="row" spacing={1.5} sx={{ overflowX: "auto", pb: { xs: 0.5, lg: 0 }, "& .MuiToggleButton-root": { whiteSpace: "nowrap" } }}>
          <ToggleButtonGroup
            size="small"
            exclusive
            value={view}
            onChange={(_, v) => v && setFilters({ view: v })}
            aria-label="View"
          >
            <ToggleButton value="all">All</ToggleButton>
            <ToggleButton value="picks">Top picks</ToggleButton>
            {user && (
              <ToggleButton value="board">
                My projects<Count n={boardCount.data?.total ?? ""} />
              </ToggleButton>
            )}
          </ToggleButtonGroup>
          <ToggleButtonGroup
            size="small"
            exclusive
            value={f.level}
            onChange={(_, v) => v !== null && setFilters({ level: v })}
            aria-label="Difficulty"
          >
            {LEVEL_OPTS.map(([k, l]) => (
              <ToggleButton key={k} value={k}>
                {l}{k > 0 && <Count n={counts.levels[String(k)] ?? ""} />}
              </ToggleButton>
            ))}
          </ToggleButtonGroup>
        </Stack>
      </Stack>

      <Box sx={{ display: "grid", gridTemplateColumns: { xs: "minmax(0, 1fr)", md: "250px minmax(0, 1fr)" }, gap: 3, alignItems: "start" }}>
        {isDesktop ? (
          <Card component="nav" aria-label="Filters" sx={{ position: "sticky", top: 88, p: 1, maxHeight: "calc(100vh - 104px)", overflowY: "auto" }}>
            {filters}
          </Card>
        ) : (
          <Drawer anchor="left" open={filtersOpen} onClose={() => setFiltersOpen(false)} PaperProps={{ sx: { width: 300, p: 1.5, backgroundImage: "none" } }}>
            <Box component="nav" aria-label="Filters">{filters}</Box>
          </Drawer>
        )}

        <Box component="section" aria-label="Projects" sx={{ minWidth: 0 }}>
          <Stack direction="row" justifyContent="space-between" alignItems="center" spacing={1} sx={{ mb: 1.5, minHeight: 32 }}>
            <Typography variant="body2" color="text.secondary">
              Showing <b>{list.data ? items.length : "…"}</b> projects{list.loading && list.data ? " · updating" : ""}
            </Typography>
            <Stack direction="row" spacing={1}>
              {active ? (
                <Button size="small" onClick={() => { setQInput(""); setFilters({ q: "", domain: "", task: "", level: 0, support: "" }); }}>
                  Clear filters
                </Button>
              ) : null}
              {!isDesktop && (
                <Button size="small" variant="outlined" onClick={() => setFiltersOpen(true)}
                  startIcon={<Badge color="primary" variant="dot" invisible={!activeFilters}><FilterListIcon /></Badge>}>
                  Filters
                </Button>
              )}
            </Stack>
          </Stack>
          <ErrorState error={list.error} onRetry={list.reload} />
          <Box sx={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(270px, 1fr))", gap: 2 }}>
            {!list.data && list.loading && <SkeletonCards />}
            {items.map((p) => <ProjectCard key={p.id} project={p} onOpen={open} showStatus={!!user} />)}
          </Box>
          {list.data && items.length === 0 && (
            view === "board" && !active ? (
              <EmptyState title="Nothing on your board yet" description="Open any project and set it to Planned, Building or Done." />
            ) : (
              <EmptyState title="No projects match" description="Try another search word or clear the filters." />
            )
          )}
        </Box>
      </Box>

      <Outlet context={outletCtx} />
    </Box>
  );
}
