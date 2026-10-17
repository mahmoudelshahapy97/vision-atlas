import { useState } from "react";
import { Link as RouterLink, useNavigate, useParams } from "react-router-dom";
import Accordion from "@mui/material/Accordion";
import AccordionDetails from "@mui/material/AccordionDetails";
import AccordionSummary from "@mui/material/AccordionSummary";
import Box from "@mui/material/Box";
import Button from "@mui/material/Button";
import Stack from "@mui/material/Stack";
import Typography from "@mui/material/Typography";
import ArrowBackIcon from "@mui/icons-material/ArrowBack";
import DeleteOutlineIcon from "@mui/icons-material/DeleteOutline";
import ExpandMoreIcon from "@mui/icons-material/ExpandMore";
import ScienceIcon from "@mui/icons-material/Science";

import { mediaUrl } from "../../api/client";
import { runs as runsApi } from "../../api/endpoints";
import ConfirmDialog from "../../components/ConfirmDialog";
import { ErrorState, Loading } from "../../components/DataStates";
import ResultView from "../../components/lab/ResultView";
import PageHeader from "../../components/PageHeader";
import { RunStatusChip } from "../../components/StatusChips";
import { useToast } from "../../components/Toast";
import { usePolling } from "../../hooks/usePolling";
import { RUN_PAGE_POLL_MS, isRunActive } from "../../utils/constants";
import { formatDateTime } from "../../utils/format";
import { MONO_FONT } from "../../utils/theme";

/** One run: its inputs, results and settings. Follows the run live while it is queued or running. */
export default function RunDetail() {
  const { publicId } = useParams();
  const toast = useToast();
  const navigate = useNavigate();
  const [confirm, setConfirm] = useState(false);
  const [busy, setBusy] = useState(false);
  const polled = usePolling((opts) => runsApi.get(publicId, opts), {
    intervalMs: RUN_PAGE_POLL_MS, deps: [publicId], keepPolling: isRunActive,
  });
  const run = polled.data?.public_id === publicId ? polled.data : null;

  async function remove() {
    setBusy(true);
    try {
      await runsApi.remove(publicId);
      toast("Run deleted.");
      navigate("/runs");
    } catch (e) {
      toast(e.message, "err");
      setBusy(false);
      setConfirm(false);
    }
  }

  return (
    <Box>
      <Stack direction="row" spacing={1} sx={{ mb: 2 }}>
        <Button component={RouterLink} to="/runs" startIcon={<ArrowBackIcon />} size="small">All runs</Button>
        {run?.project_id && (
          <Button component={RouterLink} to={`/projects/${run.project_id}/lab`} startIcon={<ScienceIcon />} size="small">Open this lab</Button>
        )}
      </Stack>
      <ErrorState error={polled.error} onRetry={polled.reload} />
      {!run && !polled.error && <Loading label="Loading the run…" />}
      {run && (
        <>
          <PageHeader
            title={<>Run <Box component="code" sx={{ fontFamily: MONO_FONT, fontSize: "0.85em" }}>{run.pipeline}</Box></>}
            subtitle={`${run.project_title ? `${run.project_title} · ` : ""}${formatDateTime(run.created_at)}`}
            actions={[
              <Stack key="status" justifyContent="center"><RunStatusChip status={run.status} /></Stack>,
              !isRunActive(run) && (
                <Button key="delete" color="error" variant="outlined" startIcon={<DeleteOutlineIcon />} onClick={() => setConfirm(true)}>Delete run</Button>
              ),
            ]}
          />
          {run.inputs?.length > 0 && (
            <Stack direction="row" spacing={1} sx={{ mb: 2, overflowX: "auto", pb: 0.5 }}>
              {run.inputs.map((i) => (
                <Box
                  key={i.path}
                  component="a"
                  href={mediaUrl(i.url)}
                  target="_blank"
                  rel="noreferrer"
                  title={i.name}
                  sx={{
                    flexShrink: 0, width: 96, height: 72, borderRadius: 2, overflow: "hidden", border: 1, borderColor: "divider",
                    "& img, & video": { width: "100%", height: "100%", objectFit: "cover", display: "block" },
                  }}
                >
                  {i.kind === "video" ? <video src={mediaUrl(i.url)} muted /> : <img src={mediaUrl(i.url)} alt={i.name} />}
                </Box>
              ))}
            </Stack>
          )}
          <ResultView run={run} />
          <Accordion variant="outlined" disableGutters sx={{ mt: 2, borderRadius: 3, "&:before": { display: "none" } }}>
            <AccordionSummary expandIcon={<ExpandMoreIcon />}>
              <Typography variant="subtitle2">Settings used</Typography>
            </AccordionSummary>
            <AccordionDetails>
              <Box component="pre" sx={{ m: 0, fontFamily: MONO_FONT, fontSize: 12.5, overflowX: "auto" }}>
                {JSON.stringify(run.params, null, 2)}
              </Box>
            </AccordionDetails>
          </Accordion>
        </>
      )}
      <ConfirmDialog
        open={confirm}
        title="Delete this run?"
        description="The run, its uploaded inputs and its output files are removed. This cannot be undone."
        confirmLabel="Delete"
        confirmColor="error"
        busy={busy}
        onConfirm={remove}
        onClose={() => setConfirm(false)}
      />
    </Box>
  );
}
