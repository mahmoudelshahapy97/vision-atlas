import { Link, useNavigate } from "react-router-dom";
import { me } from "../api/endpoints";
import { EmptyState, ErrorNote } from "../components/DataStates";
import { ProgressBar } from "../components/StatusChips";
import { useAsync } from "../hooks/useAsync";
import { STATUS_LABEL } from "../utils/constants";
import { formatDate, pad } from "../utils/format";

const COLUMNS = ["planned", "building", "done"];

export default function Board() {
  const navigate = useNavigate();
  const stats = useAsync((opts) => me.stats(opts), []);
  const mine = useAsync((opts) => me.progress(opts), []);
  const s = stats.data;
  const items = mine.data || [];
  const noteOnly = items.filter((p) => p.progress.status === "idea");

  return (
    <div className="wrap">
      <header className="pagehead">
        <p className="eyebrow">Your workspace</p>
        <h1 className="page-title">My board</h1>
      </header>
      <ErrorNote error={stats.error || mine.error} onRetry={() => { stats.reload(); mine.reload(); }} />

      {s && (
        <section className="overview">
          <div className="kpis">
            {[["done", "Done"], ["building", "Building"], ["planned", "Planned"]].map(([k, l]) => (
              <div key={k} className="kpi">
                <span className="kpi-label"><i className="dot" style={{ background: `var(--${k === "planned" ? "accent" : k === "building" ? "build" : "done"})` }} />{l}</span>
                <span className="kpi-num">{s.counts[k]}</span>
              </div>
            ))}
            <div className="kpi">
              <span className="kpi-label">Completion</span>
              <span className="kpi-num">{Math.round((s.counts.done / Math.max(s.total, 1)) * 100)}<small>%</small></span>
            </div>
          </div>
          <ProgressBar counts={s.counts} total={s.total} label="Overall progress" />

          <div className="domtable" role="table" aria-label="Progress by domain">
            {s.by_domain.map((d) => (
              <Link key={d.code} role="row" className="domrow" to={`/?domain=${d.code}&view=board`}>
                <span role="cell" className="domname">{d.name}</span>
                <span role="cell" className="dombar" aria-label={`${d.done} done, ${d.started} started of ${d.total}`}>
                  <i style={{ width: `${(d.started / d.total) * 100}%`, background: "var(--accent-soft)" }} />
                  <i className="over" style={{ width: `${(d.done / d.total) * 100}%`, background: "var(--done)" }} />
                </span>
                <span role="cell" className="domnum">{d.done}/{d.total}</span>
              </Link>
            ))}
          </div>
        </section>
      )}

      {mine.data && items.length === 0 && (
        <EmptyState title="Nothing tracked yet">
          Open a project in the <Link to="/">catalog</Link> and set it to Planned, Building or Done.
        </EmptyState>
      )}

      {items.length > 0 && (
        <div className="kanban">
          {COLUMNS.map((col) => {
            const list = items.filter((p) => p.progress.status === col);
            return (
              <section key={col} className="kcol">
                <h2><span className={`pill ${col}`}>{STATUS_LABEL[col]}</span><span className="n">{list.length}</span></h2>
                {list.length === 0 && <p className="muted small">No projects here yet.</p>}
                {list.map((p) => (
                  <button key={p.id} className="kcard" onClick={() => navigate(`/projects/${p.id}`)}>
                    <span className="tag">#{pad(p.id)} · {p.task_type.code.toUpperCase()}</span>
                    <span className="kt">{p.title}</span>
                    {p.progress.notes && <span className="kn">{p.progress.notes}</span>}
                    <span className="kd">{p.domain.name} · updated {formatDate(p.progress.updated_at)}</span>
                  </button>
                ))}
              </section>
            );
          })}
        </div>
      )}

      {noteOnly.length > 0 && (
        <section className="sec" style={{ marginTop: 28 }}>
          <h3>Ideas with notes</h3>
          <div className="chips">
            {noteOnly.map((p) => <Link key={p.id} className="chip link" to={`/projects/${p.id}`}>#{pad(p.id)} {p.title}</Link>)}
          </div>
        </section>
      )}
    </div>
  );
}
