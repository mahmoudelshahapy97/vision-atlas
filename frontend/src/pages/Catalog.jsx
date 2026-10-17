import { useEffect, useMemo, useState } from "react";
import { Link, Outlet, useNavigate, useSearchParams } from "react-router-dom";
import { catalog, me, projects } from "../api/endpoints";
import { useAuth } from "../auth/AuthContext";
import { EmptyState, ErrorNote, SkeletonCards } from "../components/DataStates";
import ProjectCard from "../components/ProjectCard";
import { ProgressBar } from "../components/StatusChips";
import { useAsync } from "../hooks/useAsync";
import { useDebounced } from "../hooks/useDebounced";
import { SUPPORT_FILTERS } from "../utils/constants";

const LEVEL_OPTS = [[0, "Any level"], [1, "Beginner"], [2, "Intermediate"], [3, "Advanced"]];

function ProgressPanel({ stats, user }) {
  if (!user) {
    return (
      <div className="progress">
        <div className="head"><span>Track your progress</span></div>
        <p className="muted small">Create a free account to mark projects as planned, building or done, keep notes, and see your board.</p>
        <div className="row gap8">
          <Link className="btn primary sm" to="/register">Create account</Link>
          <Link className="btn ghost sm" to="/login">Sign in</Link>
        </div>
      </div>
    );
  }
  if (!stats) return <div className="progress" aria-busy="true" />;
  const c = stats.counts;
  return (
    <div className="progress">
      <div className="head"><span>Your progress</span><span><strong>{c.done}</strong> / {stats.total} done</span></div>
      <ProgressBar counts={c} total={stats.total} label={`${c.done} done, ${c.building} building, ${c.planned} planned`} />
      <div className="legend">
        <span><i className="dot" style={{ background: "var(--done)" }} />Done <b>{c.done}</b></span>
        <span><i className="dot" style={{ background: "var(--build)" }} />Building <b>{c.building}</b></span>
        <span><i className="dot" style={{ background: "var(--accent)" }} />Planned <b>{c.planned}</b></span>
        <span><i className="dot" style={{ background: "var(--line)" }} />Idea <b>{c.idea}</b></span>
      </div>
    </div>
  );
}

export default function Catalog() {
  const { user } = useAuth();
  const [sp, setSp] = useSearchParams();
  const navigate = useNavigate();
  const [rev, setRev] = useState(0);

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

  const items = (list.data?.items || []).filter((p) => !f.support || p.lab?.support === f.support);
  const active = f.q || f.domain || f.task || f.level || f.support;
  const search = sp.toString();
  const open = (id) => navigate({ pathname: `/projects/${id}`, search: search ? `?${search}` : "" });

  const outletCtx = useMemo(
    () => ({ ids: items.map((p) => p.id), onChanged: () => setRev((r) => r + 1), search }),
    [items, search]
  );

  return (
    <div className="wrap">
      <header className="top">
        <div>
          <p className="eyebrow">Computer vision · {domains.data ? domains.data.reduce((a, d) => a + d.project_count, 0) : 90} projects · {domains.data?.length ?? 15} domains</p>
          <h1>Vision <span className="bb">Project</span> Atlas</h1>
          <p className="lede">Browse every project, filter by domain, task type and difficulty, open one for its build path and evaluation metric, and track what you are planning, building or have finished.</p>
        </div>
        <ProgressPanel stats={stats.data} user={user} />
      </header>

      <div className="toolbar">
        <label className="search" htmlFor="q">
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" aria-hidden="true"><circle cx="11" cy="11" r="7" /><path d="m20 20-3.5-3.5" /></svg>
          <input id="q" type="search" value={qInput} onChange={(e) => setQInput(e.target.value)}
            placeholder="Search projects, models or tools (e.g. YOLO, SAM, Arabic)" autoComplete="off" />
        </label>
        <div className="seg" role="group" aria-label="View">
          <button aria-pressed={view === "all"} onClick={() => setFilters({ view: "all" })}>All</button>
          <button aria-pressed={view === "picks"} onClick={() => setFilters({ view: "picks" })}>Top picks</button>
          {user && (
            <button aria-pressed={view === "board"} onClick={() => setFilters({ view: "board" })}>
              My projects<span className="n">{boardCount.data?.total ?? ""}</span>
            </button>
          )}
        </div>
        <div className="seg" role="group" aria-label="Difficulty">
          {LEVEL_OPTS.map(([k, l]) => (
            <button key={k} aria-pressed={f.level === k} onClick={() => setFilters({ level: k })}>
              {l}{k > 0 && <span className="n">{counts.levels[String(k)] ?? ""}</span>}
            </button>
          ))}
        </div>
      </div>

      <div className="layout">
        <nav className="side" aria-label="Filters">
          <div>
            <h2>Domain</h2>
            <div className="flist">
              <button aria-pressed={!f.domain} onClick={() => setFilters({ domain: "" })}>
                <span>All domains</span><span className="n">{facetTotal("domains")}</span>
              </button>
              {(domains.data || []).map((d) => (
                <button key={d.code} aria-pressed={f.domain === d.code} onClick={() => setFilters({ domain: d.code })}>
                  <span>{d.name}</span><span className="n">{counts.domains[d.code] ?? 0}</span>
                </button>
              ))}
            </div>
          </div>
          <div>
            <h2>Lab readiness</h2>
            <div className="flist">
              {SUPPORT_FILTERS.map(([k, l]) => (
                <button key={k} aria-pressed={f.support === k} onClick={() => setFilters({ support: k })}>
                  <span>{l}</span><span className="n">{k ? (list.data?.items || []).filter((p) => p.lab?.support === k).length : list.data?.items?.length ?? ""}</span>
                </button>
              ))}
            </div>
          </div>
          <div>
            <h2>Task type</h2>
            <div className="flist">
              <button aria-pressed={!f.task} onClick={() => setFilters({ task: "" })}>
                <span>All tasks</span><span className="n">{facetTotal("tasks")}</span>
              </button>
              {(tasks.data || []).map((t) => (
                <button key={t.code} aria-pressed={f.task === t.code} onClick={() => setFilters({ task: t.code })}>
                  <span>{t.name}</span><span className="n">{counts.tasks[t.code] ?? 0}</span>
                </button>
              ))}
            </div>
          </div>
        </nav>

        <main>
          <div className="resultbar">
            <span>Showing <b>{list.data ? items.length : "…"}</b> projects{list.loading && list.data ? " · updating" : ""}</span>
            {active ? <button className="linkbtn" onClick={() => { setQInput(""); setFilters({ q: "", domain: "", task: "", level: 0, support: "" }); }}>Clear filters</button> : null}
          </div>
          <ErrorNote error={list.error} onRetry={list.reload} />
          <div className="grid">
            {!list.data && list.loading && <SkeletonCards />}
            {list.data && items.length === 0 && (
              view === "board" && !active ? (
                <EmptyState title="Nothing on your board yet">Open any project and set it to Planned, Building or Done.</EmptyState>
              ) : (
                <EmptyState title="No projects match">Try another search word or clear the filters.</EmptyState>
              )
            )}
            {items.map((p) => <ProjectCard key={p.id} project={p} onOpen={open} showStatus={!!user} />)}
          </div>
        </main>
      </div>

      <Outlet context={outletCtx} />
    </div>
  );
}
