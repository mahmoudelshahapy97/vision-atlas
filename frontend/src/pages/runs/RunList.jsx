import { useNavigate } from "react-router-dom";
import { mediaUrl } from "../../api/client";
import { runs as runsApi } from "../../api/endpoints";
import { EmptyState, ErrorNote } from "../../components/DataStates";
import { RunStatusPill } from "../../components/StatusChips";
import { useAsync } from "../../hooks/useAsync";
import { formatDateTime, formatDurationMs } from "../../utils/format";

/** The signed-in user's run history across every lab. */
export default function RunList() {
  const runs = useAsync((opts) => runsApi.list({ limit: 100 }, opts), []);
  const navigate = useNavigate();
  return (
    <div className="wrap">
      <header className="pagehead">
        <p className="eyebrow">Vision lab</p>
        <h1 className="page-title">My runs</h1>
      </header>
      <ErrorNote error={runs.error} onRetry={runs.reload} />
      {runs.data?.length === 0 && (
        <EmptyState title="No runs yet">Open any project and press “Try it in the lab”.</EmptyState>
      )}
      <div className="runsgrid">
        {(runs.data || []).map((r) => (
          <button key={r.public_id} className="runcard" onClick={() => navigate(`/runs/${r.public_id}`)}>
            {r.thumbnail ? <img src={mediaUrl(r.thumbnail)} alt="" loading="lazy" /> : <span className="nothumb big" />}
            <span className="runcard-body">
              <span className="row between">
                <b>{r.project_title || r.pipeline}</b>
                <RunStatusPill status={r.status} />
              </span>
              <small className="muted">{formatDateTime(r.created_at)} · {formatDurationMs(r.duration_ms)}</small>
              {r.summary?.length > 0 && <small>{r.summary.slice(0, 2).map((s) => `${s.label}: ${s.value}`).join(" · ")}</small>}
              {r.error && <small className="errtext">{r.error}</small>}
            </span>
          </button>
        ))}
      </div>
    </div>
  );
}
