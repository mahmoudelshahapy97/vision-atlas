import { useEffect, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { catalog, projects } from "../../api/endpoints";
import { ErrorNote } from "../../components/DataStates";
import { useToast } from "../../components/Toast";
import { useAsync } from "../../hooks/useAsync";
import { LEVELS } from "../../utils/constants";
import { pad } from "../../utils/format";

const EMPTY = {
  title: "", description: "", domain_code: "", task_type_code: "", level: 2,
  technologies: "", is_pick: false, pick_reason: "", caution: "",
};

export default function ProjectForm() {
  const { id } = useParams();
  const editing = Boolean(id);
  const navigate = useNavigate();
  const toast = useToast();
  const domains = useAsync((opts) => catalog.domains(opts), []);
  const tasks = useAsync((opts) => catalog.taskTypes(opts), []);
  const existing = useAsync((opts) => (editing ? projects.get(id, opts) : Promise.resolve(null)), [id]);
  const [form, setForm] = useState(EMPTY);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    const p = existing.data;
    if (!p) return;
    setForm({
      title: p.title, description: p.description, domain_code: p.domain.code, task_type_code: p.task_type.code,
      level: p.level, technologies: p.technologies.join(", "), is_pick: p.is_pick,
      pick_reason: p.pick_reason || "", caution: p.caution || "",
    });
  }, [existing.data]);

  const set = (k) => (e) => setForm({ ...form, [k]: e.target.type === "checkbox" ? e.target.checked : e.target.value });

  async function submit(e) {
    e.preventDefault();
    setError("");
    if (!form.domain_code || !form.task_type_code) return setError("Choose a domain and a task type.");
    setBusy(true);
    const body = {
      ...form,
      level: Number(form.level),
      technologies: form.technologies.split(",").map((t) => t.trim()).filter(Boolean),
      pick_reason: form.is_pick ? form.pick_reason : "",
    };
    try {
      const saved = editing ? await projects.update(id, body) : await projects.create(body);
      toast(editing ? `Saved #${pad(saved.id)}.` : `Created #${pad(saved.id)} ${saved.title}.`);
      navigate("/admin");
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="wrap narrow">
      <p className="small"><Link to="/admin">← Back to admin</Link></p>
      <ErrorNote error={existing.error} />
      <form className="panel form" onSubmit={submit}>
        <h1 className="page-title">{editing ? `Edit project #${pad(id)}` : "New project"}</h1>
        <label className="field" htmlFor="pf-title"><span>Title</span>
          <input id="pf-title" required minLength={3} maxLength={200} value={form.title} onChange={set("title")} />
        </label>
        <label className="field" htmlFor="pf-desc"><span>Description</span>
          <textarea id="pf-desc" required minLength={3} rows={3} value={form.description} onChange={set("description")} />
        </label>
        <div className="grid3">
          <label className="field" htmlFor="pf-domain"><span>Domain</span>
            <select id="pf-domain" required value={form.domain_code} onChange={set("domain_code")}>
              <option value="">Choose…</option>
              {(domains.data || []).map((d) => <option key={d.code} value={d.code}>{d.name}</option>)}
            </select>
          </label>
          <label className="field" htmlFor="pf-task"><span>Task type</span>
            <select id="pf-task" required value={form.task_type_code} onChange={set("task_type_code")}>
              <option value="">Choose…</option>
              {(tasks.data || []).map((t) => <option key={t.code} value={t.code}>{t.name}</option>)}
            </select>
          </label>
          <label className="field" htmlFor="pf-level"><span>Level</span>
            <select id="pf-level" value={form.level} onChange={set("level")}>
              {Object.entries(LEVELS).map(([k, l]) => <option key={k} value={k}>{l}</option>)}
            </select>
          </label>
        </div>
        <label className="field" htmlFor="pf-tech"><span>Technologies</span>
          <input id="pf-tech" value={form.technologies} onChange={set("technologies")} placeholder="YOLO, OpenCV, PyTorch" />
          <small className="muted">Separate with commas.</small>
        </label>
        <label className="check" htmlFor="pf-pick">
          <input id="pf-pick" type="checkbox" checked={form.is_pick} onChange={set("is_pick")} />
          <span>Mark as a top pick</span>
        </label>
        {form.is_pick && (
          <label className="field" htmlFor="pf-why"><span>Why it is a top pick</span>
            <textarea id="pf-why" rows={2} value={form.pick_reason} onChange={set("pick_reason")} />
          </label>
        )}
        <label className="field" htmlFor="pf-caution"><span>Caution note (optional)</span>
          <textarea id="pf-caution" rows={2} value={form.caution} onChange={set("caution")} placeholder="Shown on the project, e.g. for medical or biometric data" />
        </label>
        {error && <div className="errnote" role="alert">{error}</div>}
        <div className="row gap8">
          <button className="btn primary" disabled={busy}>{busy ? "Saving…" : editing ? "Save changes" : "Create project"}</button>
          <Link className="btn ghost" to="/admin">Cancel</Link>
        </div>
      </form>
    </div>
  );
}
