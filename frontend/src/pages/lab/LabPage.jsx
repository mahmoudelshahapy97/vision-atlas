import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { mediaUrl } from "../../api/client";
import { lab as labApi, runs as runsApi } from "../../api/endpoints";
import { useAuth } from "../../auth/AuthContext";
import { EmptyState, ErrorNote } from "../../components/DataStates";
import CanvasEditor from "../../components/lab/CanvasEditor";
import ParamForm, { GEOMETRY } from "../../components/lab/ParamForm";
import ResultView from "../../components/lab/ResultView";
import { RunStatusPill, SupportBadge } from "../../components/StatusChips";
import { useToast } from "../../components/Toast";
import { useAsync } from "../../hooks/useAsync";
import { usePolling } from "../../hooks/usePolling";
import { RUN_POLL_MS, isRunActive } from "../../utils/constants";
import { formatDateTime, pad } from "../../utils/format";

const IMG = /\.(jpe?g|png|bmp|webp|tiff?)$/i;
const VID = /\.(mp4|mov|avi|mkv|webm|m4v|mpe?g)$/i;
const kindOf = (name) => (VID.test(name) ? "video" : IMG.test(name) ? "image" : "other");
// shown when the browser can't decode an uploaded video: you can still draw on a 16:9 frame
const BLANK = "data:image/svg+xml," + encodeURIComponent('<svg xmlns="http://www.w3.org/2000/svg" width="1280" height="720"><rect width="100%" height="100%" fill="#2a2f36"/><text x="640" y="360" fill="#9aa4b1" font-family="sans-serif" font-size="34" text-anchor="middle">Video preview unavailable — draw on this 16:9 frame</text></svg>');
const accept = { image: "image/*", images: "image/*", video: "video/*", media: "image/*,video/*" };

function defaultsFor(tab) {
  const v = {};
  for (const p of tab.params) v[p.name] = p.default ?? (p.type === "multiselect" || p.type === "polygons" || p.type === "points" ? [] : null);
  return { ...v, ...(tab.defaults || {}) };
}

async function videoFrame(url) {
  return new Promise((resolve) => {
    const v = document.createElement("video");
    v.muted = true;
    v.preload = "auto";
    v.crossOrigin = "anonymous";
    v.src = url;
    v.addEventListener("loadeddata", () => { v.currentTime = Math.min(0.5, (v.duration || 1) / 4); });
    v.addEventListener("seeked", () => {
      const c = document.createElement("canvas");
      c.width = v.videoWidth;
      c.height = v.videoHeight;
      c.getContext("2d").drawImage(v, 0, 0);
      try { resolve(c.toDataURL("image/jpeg", 0.85)); } catch { resolve(null); }
    });
    v.addEventListener("error", () => resolve(null));
    setTimeout(() => resolve(null), 6000);
  });
}

function SlotInput({ slot, items, setItems, samples }) {
  const ref = useRef(null);
  const [over, setOver] = useState(false);
  const many = slot.max > 1;
  const add = (files) => {
    const list = [...files].map((f) => ({ file: f, name: f.name, kind: kindOf(f.name), url: URL.createObjectURL(f) }));
    setItems(many ? [...items.filter((i) => !i.sample), ...list].slice(0, slot.max) : list.slice(0, 1));
  };
  const useSample = () => setItems(samples.map((s) => ({ sample: s.path, name: s.name, kind: kindOf(s.name), url: mediaUrl(s.url), poster: s.poster && mediaUrl(s.poster) })));
  return (
    <div className="slot">
      <div className="row between">
        <span className="slot-label">{slot.label}{slot.optional ? " (optional)" : ""}</span>
        {samples?.length > 0 && <button type="button" className="linkbtn" onClick={useSample}>Use sample</button>}
      </div>
      <div className={`drop ${over ? "over" : ""}`}
        onDragOver={(e) => { e.preventDefault(); setOver(true); }} onDragLeave={() => setOver(false)}
        onDrop={(e) => { e.preventDefault(); setOver(false); add(e.dataTransfer.files); }}>
        {items.length === 0 ? (
          <button type="button" className="dropbtn" onClick={() => ref.current?.click()}>
            <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" aria-hidden="true"><path d="M12 16V4M6 10l6-6 6 6M4 20h16" /></svg>
            <span>Drop {many ? "files" : slot.kind === "video" ? "a video" : slot.kind === "media" ? "an image or video" : "an image"} here, or browse</span>
          </button>
        ) : (
          <div className="previews">
            {items.map((it, i) => (
              <div key={i} className="prev">
                {it.kind === "video" ? <video src={it.url} poster={it.poster} muted playsInline /> : <img src={it.url} alt={it.name} />}
                <span title={it.name}>{it.sample ? "sample · " : ""}{it.name}</span>
              </div>
            ))}
            <div className="row gap8">
              <button type="button" className="btn ghost sm" onClick={() => ref.current?.click()}>{many ? "Add / replace" : "Replace"}</button>
              <button type="button" className="btn ghost sm" onClick={() => setItems([])}>Clear</button>
            </div>
          </div>
        )}
        <input ref={ref} type="file" hidden multiple={many} accept={accept[slot.kind]} onChange={(e) => { add(e.target.files); e.target.value = ""; }} />
      </div>
    </div>
  );
}

export default function LabPage() {
  const { id } = useParams();
  const { user } = useAuth();
  const toast = useToast();
  const lab = useAsync((opts) => labApi.forProject(id, opts), [id, user?.id]);
  const [tabIdx, setTabIdx] = useState(0);
  const [inputs, setInputs] = useState({});
  const [values, setValues] = useState({});
  const [activeGeo, setActiveGeo] = useState(null);
  // The run shown on the right: just submitted, or picked from history. Polled while active.
  const [runId, setRunId] = useState(null);
  const polled = usePolling((opts) => runsApi.get(runId, opts), {
    intervalMs: RUN_POLL_MS, enabled: Boolean(runId), deps: [runId], keepPolling: isRunActive,
  });
  const run = runId && polled.data?.public_id === runId ? polled.data : null;
  const [busy, setBusy] = useState(false);
  const [bg, setBg] = useState(null);
  const history = useAsync((opts) => (user ? runsApi.list({ project_id: id, limit: 12 }, opts) : Promise.resolve([])), [id, user?.id, run && !isRunActive(run) ? run.public_id : ""]);

  const data = lab.data;
  const tab = data?.tabs?.[tabIdx];

  useEffect(() => {
    if (!tab) return;
    setValues(defaultsFor(tab));
    setActiveGeo(null);
    const init = {};
    for (const s of tab.slots) {
      const smp = data.samples?.[s.name];
      if (smp?.length && tabIdx === 0) init[s.name] = smp.map((x) => ({ sample: x.path, name: x.name, kind: kindOf(x.name), url: mediaUrl(x.url), poster: x.poster && mediaUrl(x.poster) }));
      else init[s.name] = [];
    }
    setInputs(init);
  }, [tab, tabIdx, data]);

  // background for drawing: first image-like input of the first slot
  const firstItem = useMemo(() => tab?.slots.map((s) => inputs[s.name]?.[0]).find(Boolean), [tab, inputs]);
  useEffect(() => {
    let alive = true;
    if (!firstItem) return setBg(null);
    if (firstItem.kind === "video" && firstItem.poster) setBg(firstItem.poster);
    else if (firstItem.kind === "video") videoFrame(firstItem.url).then((u) => alive && setBg(u || BLANK));
    else setBg(firstItem.url);
    return () => { alive = false; };
  }, [firstItem]);

  useEffect(() => {
    if (polled.error) toast(polled.error.message, "err");
  }, [polled.error, toast]);

  const setValue = useCallback((k, v) => setValues((s) => ({ ...s, [k]: v })), []);
  const geoParams = tab ? tab.params.filter((p) => GEOMETRY.has(p.type)) : [];

  async function submit() {
    if (!user) return;
    setBusy(true);
    const fd = new FormData();
    fd.append("project_id", id);
    fd.append("pipeline", tab.name);
    const params = {};
    for (const p of tab.params) params[p.name] = values[p.name];
    if (values.model) params.model = values.model;
    fd.append("params", JSON.stringify(params));
    const samples = {};
    for (const s of tab.slots) {
      for (const it of inputs[s.name] || []) {
        if (it.sample) (samples[s.name] ||= []).push(it.sample);
        else if (it.file) fd.append(s.name, it.file, it.file.name);
      }
    }
    fd.append("samples", JSON.stringify(samples));
    try {
      const r = await runsApi.create(fd);
      polled.setData(r);
      setRunId(r.public_id);
      setActiveGeo(null);
    } catch (e) {
      toast(e.message, "err");
    } finally {
      setBusy(false);
    }
  }

  const openRun = (pid) => setRunId(pid);

  const missing = tab?.slots.filter((s) => !s.optional && (inputs[s.name]?.length || 0) < s.min).map((s) => s.label) || [];

  if (lab.error) return <div className="wrap narrow"><ErrorNote error={lab.error} onRetry={lab.reload} /><Link to="/">Back to the catalog</Link></div>;
  if (!data) return <div className="wrap"><div className="card skeleton" style={{ height: 300 }} /></div>;

  return (
    <div className="wrap lab">
      <header className="labhead">
        <p className="eyebrow"><Link to={`/projects/${data.project.id}`}>#{pad(data.project.id)} · {data.project.domain}</Link></p>
        <h1 className="page-title">{data.project.title}</h1>
        <div className="row gap8 wrapline">
          <SupportBadge level={data.support} />
          <span className="muted small">{data.support.description}</span>
        </div>
        {data.note && <p className="labnote">{data.note}</p>}
        {data.project.caution && <div className="note">{data.project.caution}</div>}
      </header>

      {data.tabs.length > 1 && (
        <div className="seg labtabs" role="tablist" aria-label="Pipelines">
          {data.tabs.map((t, i) => (
            <button key={t.name} role="tab" aria-selected={i === tabIdx} aria-pressed={i === tabIdx} onClick={() => { setTabIdx(i); setRunId(null); }}>
              {i === 0 ? "★ " : ""}{t.label}
            </button>
          ))}
        </div>
      )}

      <div className="labgrid">
        <section className="panel labin" aria-label="Inputs and settings">
          <p className="muted small">{tab.description}</p>
          {tab.slots.map((s) => (
            <SlotInput key={s.name} slot={s} items={inputs[s.name] || []} samples={data.samples?.[s.name]}
              setItems={(items) => setInputs((x) => ({ ...x, [s.name]: items }))} />
          ))}
          {geoParams.length > 0 && bg && (
            <CanvasEditor src={bg} params={geoParams} values={values} active={activeGeo} onChange={setValue} />
          )}
          <ParamForm tab={tab} values={values} setValue={setValue} activeGeo={activeGeo} setActiveGeo={setActiveGeo} hasImage={!!bg} />
          {user ? (
            <button className="btn primary runbtn" onClick={submit} disabled={busy || missing.length > 0 || isRunActive(run)}>
              {busy ? "Uploading…" : isRunActive(run) ? "Running…" : "Run"}
            </button>
          ) : (
            <p className="signin-hint"><Link to={`/login?next=${encodeURIComponent(`/projects/${id}/lab`)}`}>Sign in</Link> to run the lab. Runs are saved to your history.</p>
          )}
          {missing.length > 0 && <p className="muted small">Add: {missing.join(", ")}.</p>}
          {tab.model_specs?.length > 0 && (
            <p className="muted small models-used">Models: {tab.model_specs.map((m) => `${m.name} (${m.license})`).join(" · ")}</p>
          )}
        </section>

        <section className="labout" aria-label="Results" aria-live="polite">
          {run ? <ResultView run={run} /> : (
            <EmptyState title="Results appear here">
              {data.samples && Object.keys(data.samples).length ? "A sample is loaded. Press Run to try it, or add your own files." : "Add your files and press Run."}
            </EmptyState>
          )}
          {user && history.data?.length > 0 && (
            <div className="history">
              <h3>Your recent runs</h3>
              <div className="histlist">
                {history.data.map((h) => (
                  <button key={h.public_id} className={`histitem ${run?.public_id === h.public_id ? "on" : ""}`} onClick={() => openRun(h.public_id)}>
                    {h.thumbnail ? <img src={mediaUrl(h.thumbnail)} alt="" /> : <span className="nothumb" />}
                    <span className="histmeta">
                      <b>{h.summary?.[0] ? `${h.summary[0].label}: ${h.summary[0].value}` : h.status}</b>
                      <small>{formatDateTime(h.created_at)} · {h.pipeline}</small>
                    </span>
                    <RunStatusPill status={h.status} />
                  </button>
                ))}
              </div>
            </div>
          )}
        </section>
      </div>
    </div>
  );
}
