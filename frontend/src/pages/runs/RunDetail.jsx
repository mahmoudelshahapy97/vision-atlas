import { useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { mediaUrl } from "../../api/client";
import { runs as runsApi } from "../../api/endpoints";
import { ErrorNote } from "../../components/DataStates";
import ResultView from "../../components/lab/ResultView";
import { useToast } from "../../components/Toast";
import { usePolling } from "../../hooks/usePolling";
import { RUN_PAGE_POLL_MS, isRunActive } from "../../utils/constants";
import { formatDateTime } from "../../utils/format";

/** One run: its inputs, results and settings. Follows the run live while it is queued or running. */
export default function RunDetail() {
  const { publicId } = useParams();
  const toast = useToast();
  const navigate = useNavigate();
  const [confirm, setConfirm] = useState(false);
  const polled = usePolling((opts) => runsApi.get(publicId, opts), {
    intervalMs: RUN_PAGE_POLL_MS, deps: [publicId], keepPolling: isRunActive,
  });
  const run = polled.data?.public_id === publicId ? polled.data : null;

  async function remove() {
    try {
      await runsApi.remove(publicId);
      toast("Run deleted.");
      navigate("/runs");
    } catch (e) {
      toast(e.message, "err");
    }
  }

  return (
    <div className="wrap">
      <p className="small"><Link to="/runs">← All runs</Link>{run?.project_id && <> · <Link to={`/projects/${run.project_id}/lab`}>Open this lab</Link></>}</p>
      <ErrorNote error={polled.error} />
      {run && (
        <>
          <header className="pagehead row between wrapline">
            <div>
              <p className="eyebrow">{formatDateTime(run.created_at)}</p>
              <h1 className="page-title">Run <code>{run.pipeline}</code></h1>
            </div>
            {!isRunActive(run) && (confirm ? (
              <div className="row gap8"><span className="small">Delete this run and its files?</span>
                <button className="btn danger sm" onClick={remove}>Delete</button>
                <button className="btn ghost sm" onClick={() => setConfirm(false)}>Cancel</button></div>
            ) : <button className="btn ghost sm" onClick={() => setConfirm(true)}>Delete run</button>)}
          </header>
          {run.inputs?.length > 0 && (
            <div className="inputs-strip">
              {run.inputs.map((i) => (
                <a key={i.path} href={mediaUrl(i.url)} target="_blank" rel="noreferrer" title={i.name}>
                  {i.kind === "video" ? <video src={mediaUrl(i.url)} muted /> : <img src={mediaUrl(i.url)} alt={i.name} />}
                </a>
              ))}
            </div>
          )}
          <ResultView run={run} />
          <details className="advanced"><summary>Settings used</summary><pre className="params">{JSON.stringify(run.params, null, 2)}</pre></details>
        </>
      )}
    </div>
  );
}
