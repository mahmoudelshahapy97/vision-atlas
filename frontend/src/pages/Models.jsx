import { useRef, useState } from "react";
import { Link } from "react-router-dom";
import { models as modelsApi } from "../api/endpoints";
import { useAuth } from "../auth/AuthContext";
import { ErrorNote } from "../components/DataStates";
import { useToast } from "../components/Toast";
import { usePolling } from "../hooks/usePolling";
import { MODEL_DOWNLOAD_POLL_MS } from "../utils/constants";
import { formatMegabytes } from "../utils/format";

const isDownloading = (data) => Boolean(data?.builtin.some((b) => b.download_state === "downloading"));

export default function Models() {
  const { user } = useAuth();
  const toast = useToast();
  // Re-polls while any prefetch is still downloading.
  const models = usePolling((opts) => modelsApi.list(opts), {
    intervalMs: MODEL_DOWNLOAD_POLL_MS, deps: [user?.id], keepPolling: isDownloading,
  });
  const [form, setForm] = useState({ name: "", is_public: false });
  const [file, setFile] = useState(null);
  const [busy, setBusy] = useState(false);
  const [confirm, setConfirm] = useState(null);
  const fileRef = useRef(null);
  const data = models.data;

  async function download(key) {
    try {
      await modelsApi.download(key);
      models.reload();
    } catch (e) {
      toast(e.message, "err");
    }
  }

  async function upload(e) {
    e.preventDefault();
    if (!file) return toast("Choose a .pt file first.", "err");
    setBusy(true);
    const fd = new FormData();
    fd.append("file", file);
    fd.append("name", form.name || file.name.replace(/\.pt$/, ""));
    fd.append("is_public", form.is_public ? "true" : "false");
    try {
      const m = await modelsApi.upload(fd);
      toast(`Uploaded “${m.name}” (${m.task}, ${m.classes.length} classes).`);
      setFile(null);
      setForm({ name: "", is_public: false });
      if (fileRef.current) fileRef.current.value = "";
      models.reload();
    } catch (err) {
      toast(err.message, "err");
    } finally {
      setBusy(false);
    }
  }

  async function remove(m) {
    try {
      await modelsApi.remove(m.id);
      toast(`Deleted “${m.name}”.`);
      setConfirm(null);
      models.reload();
    } catch (e) {
      toast(e.message, "err");
    }
  }

  return (
    <div className="wrap">
      <header className="pagehead">
        <p className="eyebrow">Vision lab</p>
        <h1 className="page-title">Models</h1>
        <p className="lede">Public models download automatically the first time a lab needs them. Upload your own YOLO26 weights to use them in any matching lab.</p>
      </header>
      <ErrorNote error={models.error} onRetry={models.reload} />

      {data && (
        <>
          <section className="sec">
            <div className="row between wrapline">
              <h3>Public models</h3>
              {data.device && (
                <span className="muted small">Model server device: <code>{data.device}</code>{data.gpu && <> ({data.gpu})</>} · YOLO26 size: <code>{data.yolo_size}</code></span>
              )}
            </div>
            {data.model_server_error && <div className="errnote">Model server unavailable: {data.model_server_error}</div>}
            <div className="tablewrap">
              <table className="table">
                <thead><tr><th>Model</th><th>Does</th><th>Source</th><th>License</th><th>Size</th><th>Status</th>{user?.role === "admin" && <th aria-label="Actions" />}</tr></thead>
                <tbody>
                  {data.builtin.map((m) => (
                    <tr key={m.key}>
                      <td><b>{m.name}</b>{m.classes && <div className="muted small">{m.classes}</div>}{m.note && <div className="muted small">{m.note}</div>}</td>
                      <td>{m.task}</td>
                      <td className="small">{m.source}</td>
                      <td className="mono">{m.license}</td>
                      <td className="mono">{m.size_mb ? `${m.size_mb} MB` : "—"}</td>
                      <td>
                        {m.download_state === "downloading" ? <span className="pill building">downloading…</span>
                          : m.download_state?.startsWith("error") ? <span className="pill err" title={m.download_state}>failed</span>
                          : m.loaded ? <span className="pill done">loaded</span>
                          : m.downloaded ? <span className="pill planned">on disk</span>
                          : <span className="pill idea">on first use</span>}
                      </td>
                      {user?.role === "admin" && (
                        <td className="actions">{!m.downloaded && m.download_state !== "downloading" && (
                          <button className="btn ghost sm" onClick={() => download(m.key)}>Download now</button>
                        )}</td>
                      )}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            {data.builtin.filter((m) => m.download_state?.startsWith("error")).map((m) => (
              <div key={m.key} className="errnote">{m.name}: {m.download_state.replace(/^error: /, "")}</div>
            ))}
            <p className="muted small">YOLO26 and YOLOE-26 are AGPL-3.0: fine for research and open-source use; commercial closed-source products need an Ultralytics Enterprise license.</p>
          </section>

          <section className="sec">
            <h3>Your models</h3>
            {user ? (
              <form className="panel form uploadform" onSubmit={upload}>
                <div className="grid3">
                  <label className="field" htmlFor="m-file"><span>Weights file (.pt)</span>
                    <input id="m-file" ref={fileRef} type="file" accept=".pt" onChange={(e) => setFile(e.target.files[0] || null)} />
                  </label>
                  <label className="field" htmlFor="m-name"><span>Name</span>
                    <input id="m-name" value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} placeholder="Saudi plates YOLO26n v3" />
                  </label>
                  <div className="field"><span>&nbsp;</span>
                    <button className="btn primary" disabled={busy}>{busy ? "Checking the file…" : "Upload model"}</button>
                  </div>
                </div>
                {user.role === "admin" && (
                  <label className="check" htmlFor="m-public"><input id="m-public" type="checkbox" checked={form.is_public}
                    onChange={(e) => setForm({ ...form, is_public: e.target.checked })} /><span>Share with all users</span></label>
                )}
                <p className="muted small">Any Ultralytics model works (YOLO26, YOLO11, YOLOv8: detect, segment, classify, pose or OBB). Train with
                  <code> yolo detect train data=data.yaml model=yolo26n.pt</code>, then upload <code>runs/detect/train/weights/best.pt</code>.
                  The lab lets you pick it wherever the task matches.</p>
              </form>
            ) : (
              <p className="muted"><Link to="/login?next=/models">Sign in</Link> to upload your own models.</p>
            )}
            {data.custom.length > 0 && (
              <div className="tablewrap" style={{ marginTop: 14 }}>
                <table className="table">
                  <thead><tr><th>Name</th><th>Task</th><th>Classes</th><th>Size</th><th>Shared</th><th aria-label="Actions" /></tr></thead>
                  <tbody>
                    {data.custom.map((m) => (
                      <tr key={m.id}>
                        <td><b>{m.name}</b></td>
                        <td className="mono">{m.task}</td>
                        <td className="small">{(m.classes || []).slice(0, 8).join(", ")}{m.classes?.length > 8 ? ` +${m.classes.length - 8}` : ""}</td>
                        <td className="mono">{formatMegabytes(m.size_bytes)}</td>
                        <td>{m.is_public ? "yes" : "no"}</td>
                        <td className="actions">
                          {(m.owner_id === user?.id || user?.role === "admin") && (confirm === m.id ? (
                            <><span className="small">Delete?</span><button className="btn danger sm" onClick={() => remove(m)}>Delete</button>
                              <button className="btn ghost sm" onClick={() => setConfirm(null)}>Cancel</button></>
                          ) : <button className="btn ghost sm" onClick={() => setConfirm(m.id)}>Delete</button>)}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </section>
        </>
      )}
    </div>
  );
}
