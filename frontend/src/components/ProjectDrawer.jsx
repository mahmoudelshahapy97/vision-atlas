import { useCallback, useEffect, useRef, useState } from "react";
import { Link, useNavigate, useOutletContext, useParams } from "react-router-dom";
import { progress as progressApi, projects as projectsApi } from "../api/endpoints";
import { useAuth } from "../auth/AuthContext";
import { useAsync } from "../hooks/useAsync";
import { LEVELS, STATUSES } from "../utils/constants";
import { pad } from "../utils/format";
import { ErrorNote } from "./DataStates";
import { SupportBadge } from "./StatusChips";
import { useToast } from "./Toast";

const Icon = ({ d }) => (
  <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" aria-hidden="true"><path d={d} /></svg>
);

export default function ProjectDrawer() {
  const { id } = useParams();
  const { ids = [], onChanged = () => {}, search = "" } = useOutletContext() || {};
  const navigate = useNavigate();
  const { user } = useAuth();
  const toast = useToast();
  const closeRef = useRef(null);

  const proj = useAsync((opts) => projectsApi.get(id, opts), [id, user?.id]);
  const p = proj.data && String(proj.data.id) === String(id) ? proj.data : null;

  const [status, setStatus] = useState("idea");
  const [notes, setNotes] = useState("");
  const [noteState, setNoteState] = useState("saved"); // saved | dirty | saving | error
  const savedNotes = useRef("");

  useEffect(() => {
    if (!p) return;
    setStatus(p.progress?.status || "idea");
    setNotes(p.progress?.notes || "");
    savedNotes.current = p.progress?.notes || "";
    setNoteState("saved");
  }, [p]);

  const qs = search ? `?${search}` : "";
  const close = useCallback(() => navigate({ pathname: "/", search: qs }), [navigate, qs]);
  const go = (pid) => pid && navigate({ pathname: `/projects/${pid}`, search: qs });

  useEffect(() => {
    const onKey = (e) => e.key === "Escape" && close();
    document.addEventListener("keydown", onKey);
    document.body.style.overflow = "hidden";
    closeRef.current?.focus();
    return () => {
      document.removeEventListener("keydown", onKey);
      document.body.style.overflow = "";
    };
  }, [close]);

  const idx = ids.indexOf(Number(id));
  const prev = idx > 0 ? ids[idx - 1] : idx === -1 ? p?.prev_id : null;
  const next = idx >= 0 && idx < ids.length - 1 ? ids[idx + 1] : idx === -1 ? p?.next_id : null;

  async function changeStatus(s) {
    const before = status;
    setStatus(s);
    try {
      await progressApi.set(id, { status: s });
      onChanged();
    } catch (e) {
      setStatus(before);
      toast(e.message, "err");
    }
  }

  const saveNotes = useCallback(async (value) => {
    if (value === savedNotes.current) return setNoteState("saved");
    setNoteState("saving");
    try {
      await progressApi.set(id, { notes: value });
      savedNotes.current = value;
      setNoteState("saved");
      onChanged();
    } catch (e) {
      setNoteState("error");
      toast(e.message, "err");
    }
  }, [id, onChanged, toast]);

  // autosave notes shortly after typing stops
  useEffect(() => {
    if (noteState !== "dirty") return;
    const t = setTimeout(() => saveNotes(notes), 900);
    return () => clearTimeout(t);
  }, [notes, noteState, saveNotes]);

  const noteLabel = { saved: "Saved", dirty: "Unsaved changes", saving: "Saving…", error: "Not saved" }[noteState];

  return (
    <>
      <div className="scrim" onClick={close} />
      <aside className="drawer" role="dialog" aria-modal="true" aria-labelledby="dTitle">
        <div className="dtop">
          <span className="tag on">{p ? `#${pad(p.id)} · ${p.task_type.code.toUpperCase()}` : "Loading…"}</span>
          <div className="dnav">
            <button className="iconbtn" disabled={!prev} onClick={() => go(prev)} aria-label="Previous project"><Icon d="m15 18-6-6 6-6" /></button>
            <button className="iconbtn" disabled={!next} onClick={() => go(next)} aria-label="Next project"><Icon d="m9 18 6-6-6-6" /></button>
            <button className="iconbtn" ref={closeRef} onClick={close} aria-label="Close"><Icon d="M18 6 6 18M6 6l12 12" /></button>
          </div>
        </div>

        <ErrorNote error={proj.error} onRetry={proj.reload} />

        {p && (
          <>
            <div className="dhead">
              <span className="dom">{p.domain.name}</span>
              <h2 id="dTitle">{p.title}</h2>
              <p>{p.description}</p>
            </div>
            {p.lab && (
              <div className="labcta">
                <div>
                  <SupportBadge level={p.lab.support} />
                  <p className="small">Run this project on your own images or video{p.lab.samples ? ", or try the built-in sample" : ""}.</p>
                </div>
                <Link className="btn primary" to={`/projects/${p.id}/lab`}>Try it in the lab</Link>
              </div>
            )}
            {p.is_pick && p.pick_reason && <div className="why"><b>Top pick.</b> {p.pick_reason}</div>}
            <dl className="facts">
              <div><dt>Task</dt><dd>{p.task_type.name}</dd></div>
              <div><dt>Level</dt><dd>{LEVELS[p.level]}</dd></div>
              <div><dt>Key metric</dt><dd>{p.task_type.metric}</dd></div>
            </dl>
            <section className="sec">
              <h3>Tech stack</h3>
              <div className="chips">
                {p.technologies.map((t) => (
                  <Link key={t} className="chip link" to={`/?q=${encodeURIComponent(t)}`} title={`Find projects using ${t}`}>{t}</Link>
                ))}
              </div>
            </section>
            <section className="sec">
              <h3>Build path</h3>
              <ol className="steps">{p.steps.map((s) => <li key={s}><span>{s}</span></li>)}</ol>
            </section>
            {p.caution && <div className="note">{p.caution}</div>}

            <section className="sec">
              <h3>Status</h3>
              {user ? (
                <div className="statusseg" role="group" aria-label="Status">
                  {STATUSES.map(([k, l]) => (
                    <button key={k} data-s={k} aria-pressed={status === k} onClick={() => changeStatus(k)}>{l}</button>
                  ))}
                </div>
              ) : (
                <p className="muted small">
                  <Link to={`/login?next=${encodeURIComponent(`/projects/${id}`)}`}>Sign in</Link> to track this project and keep notes.
                </p>
              )}
            </section>
            {user && (
              <section className="sec">
                <div className="row between"><h3>Notes</h3><span className={`savestate ${noteState}`}>{noteLabel}</span></div>
                <textarea id={`notes-${p.id}`} value={notes}
                  onChange={(e) => { setNotes(e.target.value); setNoteState("dirty"); }}
                  onBlur={() => noteState === "dirty" && saveNotes(notes)}
                  placeholder="Datasets you found, repo links, model results, next steps…" />
              </section>
            )}
          </>
        )}
      </aside>
    </>
  );
}
