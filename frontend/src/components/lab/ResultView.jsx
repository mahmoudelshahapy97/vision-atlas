import { useEffect, useMemo, useState } from "react";
import katex from "katex";
import "katex/dist/katex.min.css";
import { mediaUrl } from "../../api/client";
import Chart from "./Chart";
import PointCloud from "./PointCloud";

const toneClass = { good: "tone-good", bad: "tone-bad", warn: "tone-warn" };

function fmtBytes(n) {
  if (!n && n !== 0) return "";
  if (n < 1024) return `${n} B`;
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(0)} KB`;
  return `${(n / 1024 / 1024).toFixed(1)} MB`;
}

function Lightbox({ image, onClose }) {
  useEffect(() => {
    const k = (e) => e.key === "Escape" && onClose();
    document.addEventListener("keydown", k);
    return () => document.removeEventListener("keydown", k);
  }, [onClose]);
  return (
    <div className="lightbox" onClick={onClose} role="dialog" aria-label={image.caption}>
      <img src={mediaUrl(image.url)} alt={image.caption} />
      <p>{image.caption} · click anywhere to close</p>
    </div>
  );
}

function DataTable({ table }) {
  return (
    <section className="rtable">
      <h4>{table.title}{table.total_rows > table.rows.length ? ` (first ${table.rows.length} of ${table.total_rows})` : ""}</h4>
      <div className="tablewrap">
        <table className="table compact">
          <thead><tr>{table.columns.map((c) => <th key={c}>{c}</th>)}</tr></thead>
          <tbody>
            {table.rows.length === 0 && <tr><td colSpan={table.columns.length} className="muted">No rows.</td></tr>}
            {table.rows.map((r, i) => (
              <tr key={i}>{r.map((v, j) => <td key={j} dir="auto">{v === null || v === undefined ? "—" : String(v)}</td>)}</tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
}

function Speak({ text, lang }) {
  const [on, setOn] = useState(false);
  if (typeof window === "undefined" || !window.speechSynthesis) return null;
  const speak = () => {
    window.speechSynthesis.cancel();
    if (on) return setOn(false);
    const u = new SpeechSynthesisUtterance(text);
    u.lang = lang === "ar" ? "ar-SA" : "en-US";
    u.onend = () => setOn(false);
    setOn(true);
    window.speechSynthesis.speak(u);
  };
  return <button className="btn ghost sm" onClick={speak}>{on ? "Stop" : "Speak"}</button>;
}

export default function ResultView({ run }) {
  const [zoom, setZoom] = useState(null);
  const [copied, setCopied] = useState(false);
  const res = run?.result;
  const latex = useMemo(() => (res?.latex || []).map((l) => {
    try { return katex.renderToString(l, { throwOnError: false, displayMode: true }); } catch { return null; }
  }), [res]);

  if (!run) return null;
  if (run.status === "queued" || run.status === "running") {
    return (
      <div className="runstate">
        <div className="spinner" aria-hidden="true" />
        <div>
          <strong>{run.status === "queued" ? "Waiting in the queue…" : "Analyzing…"}</strong>
          <p className="muted small">First runs download the model weights, so they take longer.</p>
          <div className="pbar"><i style={{ width: `${Math.round((run.progress || 0) * 100)}%` }} /></div>
        </div>
      </div>
    );
  }
  if (run.status === "error") {
    return <div className="errnote big" role="alert"><strong>This run didn't finish.</strong><span>{run.error}</span></div>;
  }
  if (!res) return null;

  const copy = async (t) => {
    try { await navigator.clipboard.writeText(t); setCopied(true); setTimeout(() => setCopied(false), 1500); } catch { /* ignore */ }
  };
  const [first, ...rest] = res.images || [];

  return (
    <div className="results">
      {res.summary?.length > 0 && (
        <div className="tiles">
          {res.summary.map((s, i) => (
            <div key={i} className={`tile ${toneClass[s.tone] || ""}`}>
              <span className="tile-label">{s.label}</span>
              <span className="tile-value" dir="auto">{String(s.value)}{s.unit ? <small> {s.unit}</small> : null}</span>
            </div>
          ))}
        </div>
      )}

      {res.video && (
        <figure className="media-main">
          <video src={mediaUrl(res.video.url)} poster={mediaUrl(res.video.poster)} controls playsInline preload="metadata" />
          <figcaption>{res.video.caption}</figcaption>
        </figure>
      )}
      {first && !res.video && (
        <figure className="media-main">
          <button className="imgbtn" onClick={() => setZoom(first)} aria-label={`Enlarge: ${first.caption}`}>
            <img src={mediaUrl(first.url)} alt={first.caption} />
          </button>
          <figcaption>{first.caption}</figcaption>
        </figure>
      )}
      {(res.video ? res.images : rest)?.length > 0 && (
        <div className="thumbs">
          {(res.video ? res.images : rest).map((im) => (
            <figure key={im.url}>
              <button className="imgbtn" onClick={() => setZoom(im)} aria-label={`Enlarge: ${im.caption}`}>
                <img src={mediaUrl(im.url)} alt={im.caption} loading="lazy" />
              </button>
              <figcaption>{im.caption}</figcaption>
            </figure>
          ))}
        </div>
      )}

      {res.text?.content && (
        <section className="textout">
          <div className="row between"><h4>Text</h4>
            <div className="row gap8">
              {res.speak && <Speak text={res.speak} lang={res.speak_lang} />}
              <button className="btn ghost sm" onClick={() => copy(res.text.content)}>{copied ? "Copied" : "Copy"}</button>
            </div>
          </div>
          <pre dir={res.text.dir === "rtl" ? "rtl" : "auto"}>{res.text.content}</pre>
        </section>
      )}
      {latex.some(Boolean) && (
        <section className="textout">
          <h4>Rendered formulas</h4>
          {latex.map((h, i) => h && <div key={i} className="katex-block" dangerouslySetInnerHTML={{ __html: h }} />)}
        </section>
      )}

      {res.points3d && <PointCloud points={res.points3d} />}
      {res.chart && <Chart chart={res.chart} />}
      {(res.tables || []).map((t, i) => <DataTable key={i} table={t} />)}

      {res.files?.length > 0 && (
        <section className="files">
          <h4>Downloads</h4>
          <ul>{res.files.map((f) => (
            <li key={f.url}><a href={mediaUrl(f.url)} download={f.name}>{f.name}</a> <span className="muted small">{fmtBytes(f.size)}</span></li>
          ))}</ul>
        </section>
      )}
      {res.notes?.length > 0 && <ul className="notes">{res.notes.map((n, i) => <li key={i}>{n}</li>)}</ul>}
      <p className="muted small">Finished in {(run.duration_ms / 1000).toFixed(1)} s · pipeline <code>{run.pipeline}</code></p>
      {zoom && <Lightbox image={zoom} onClose={() => setZoom(null)} />}
    </div>
  );
}
