import { Link as RouterLink } from "react-router-dom";
import Card from "@mui/material/Card";
import CardActionArea from "@mui/material/CardActionArea";
import Stack from "@mui/material/Stack";
import Typography from "@mui/material/Typography";
import VideocamOffIcon from "@mui/icons-material/VideocamOff";

import { useCameraStream } from "../../hooks/useCameraStream";
import { CameraStateChip, Stage, metricSummary } from "./CameraBits";

const PLACEHOLDER = {
  stopped: "Stopped",
  starting: "Starting…",
  reconnecting: "Reconnecting to the camera…",
  error: "The camera stopped with an error",
};

/** One camera on the live wall: its own WebSocket, name, state and the latest metrics. */
export default function LiveCameraTile({ camera, pipelineTitle }) {
  const running = camera.status?.running;
  const { imageSrc, state, error, frame } = useCameraStream(camera.id, { enabled: Boolean(running) });
  const shownState = running ? state || camera.status.state : "stopped";

  return (
    <Card>
      <CardActionArea component={RouterLink} to={`/cameras/${camera.id}`} sx={{ p: 1.25 }}>
        <Stack direction="row" justifyContent="space-between" alignItems="center" spacing={1} sx={{ mb: 1 }}>
          <Typography variant="subtitle2" noWrap sx={{ fontWeight: 700, minWidth: 0 }}>
            {camera.name}
          </Typography>
          <CameraStateChip state={shownState} error={error || camera.status?.last_error} />
        </Stack>
        <Stage>
          {imageSrc && running ? (
            <img src={imageSrc} alt={`Live view of ${camera.name}`} />
          ) : (
            <Stack alignItems="center" spacing={1} sx={{ color: "grey.500", px: 2, textAlign: "center" }}>
              <VideocamOffIcon />
              <Typography variant="caption">{(running && error) || PLACEHOLDER[shownState] || "Waiting for frames…"}</Typography>
            </Stack>
          )}
        </Stage>
        <Stack direction="row" justifyContent="space-between" spacing={1} sx={{ mt: 1, minHeight: 20 }}>
          <Typography variant="caption" color="text.secondary" noWrap sx={{ minWidth: 0 }}>
            {pipelineTitle || "Live view"}
            {camera.location ? ` · ${camera.location}` : ""}
          </Typography>
          <Typography variant="caption" color="text.secondary" noWrap>
            {running && frame ? [metricSummary(frame.metrics, 2), `${frame.fps} fps`].filter(Boolean).join(" · ") : ""}
          </Typography>
        </Stack>
      </CardActionArea>
    </Card>
  );
}
