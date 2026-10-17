import { useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { projects } from "../../api/endpoints";
import { ErrorNote } from "../../components/DataStates";
import { Star } from "../../components/StatusChips";
import { useToast } from "../../components/Toast";
import { useAsync } from "../../hooks/useAsync";
import { LEVELS } from "../../utils/constants";
import { pad } from "../../utils/format";

/** Admin: every project, with edit and delete. */
export default function ProjectList() {
  const toast = useToast();
  const list = useAsync((opts) => projects.list({ size: 200 }, opts), []);
  const [q, setQ] = useState("");
  const [confirmId, setConfirmId] = useState(null);

  const rows = useMemo(() => {
    const items = list.data?.items || [];
    const s = q.trim().toLowerCase();
    return s ? items.filter((p) => `${p.id} ${p.title} ${p.domain.name}`.toLowerCase().includes(s)) : items;
  }, [list.data, q]);

  async function remove(p) {
    try {
      await projects.remove(p.id);
      toast(`Deleted #${pad(p.id)} ${p.title}.`);
      setConfirmId(null);
      list.reload();
    } catch (e) {
      toast(e.message, "err");
    }
  }

  return (
    <div className="wrap">
      <header className="pagehead row between wrapline">
        <div>
          <p className="eyebrow">Catalog management</p>
          <h1 className="page-title">Admin</h1>
        </div>
        <Link className="btn primary" to="/admin/new">New project</Link>
      </header>

      <div className="toolbar">
        <label className="search" htmlFor="adminq">
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" aria-hidden="true"><circle cx="11" cy="11" r="7" /><path d="m20 20-3.5-3.5" /></svg>
          <input id="adminq" type="search" value={q} onChange={(e) => setQ(e.target.value)} placeholder="Filter by number, title or domain" />
        </label>
        <span className="muted small">{rows.length} of {list.data?.total ?? "…"} projects</span>
      </div>
      <ErrorNote error={list.error} onRetry={list.reload} />

      <div className="tablewrap">
        <table className="table">
          <thead>
            <tr><th>#</th><th>Title</th><th>Domain</th><th>Task</th><th>Level</th><th>Pick</th><th aria-label="Actions"></th></tr>
          </thead>
          <tbody>
            {rows.map((p) => (
              <tr key={p.id}>
                <td className="mono">{pad(p.id)}</td>
                <td><Link to={`/projects/${p.id}`}>{p.title}</Link></td>
                <td>{p.domain.name}</td>
                <td className="mono">{p.task_type.code}</td>
                <td>{LEVELS[p.level]}</td>
                <td>{p.is_pick ? <span className="pick"><Star /></span> : ""}</td>
                <td className="actions">
                  {confirmId === p.id ? (
                    <>
                      <span className="small">Delete this project?</span>
                      <button className="btn danger sm" onClick={() => remove(p)}>Delete</button>
                      <button className="btn ghost sm" onClick={() => setConfirmId(null)}>Cancel</button>
                    </>
                  ) : (
                    <>
                      <Link className="btn ghost sm" to={`/admin/${p.id}/edit`}>Edit</Link>
                      <button className="btn ghost sm" onClick={() => setConfirmId(p.id)}>Delete</button>
                    </>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
