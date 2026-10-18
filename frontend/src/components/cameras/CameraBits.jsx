// Small camera markers shared by the camera pages, the live wall and the dashboard.

import Box from "@mui/material/Box";
import Chip from "@mui/material/Chip";
import Tooltip from "@mui/material/Tooltip";

const STATE = {
  running: { label: "Live", color: "success" },
  starting: { label: "Starting", color: "info" },
  reconnecting: { label: "Reconnecting", color: "warning" },
  error: { label: "Error", color: "error" },
  stopped: { label: "Stopped", color: "default" },
};

/** The worker's state (status.state) as a chip; a pulsing dot when live. */
export function CameraStateChip({ state, error, size = "small" }) {
  const s = STATE[state] || STATE.stopped;
  const chip = (
    <Chip
      size={size}
      color={s.color}
      variant={state === "running" ? "outlined" : "filled"}
      label={s.label}
      icon={
        state === "running" ? (
          <Box
            component="span"
            className="pulse-indicator"
            sx={{ width: 7, height: 7, borderRadius: "50%", bgcolor: "success.main", ml: "8px !important" }}
          />
        ) : undefined
      }
    />
  );
  return error && state !== "running" ? <Tooltip title={error}>{chip}</Tooltip> : chip;
}

const METRIC_LABEL = { objects: "Objects", in: "In", out: "Out", tracked: "Tracked", in_zone: "In zone" };

/** "count:person" -> "person", "in_zone" -> "In zone". */
export function metricLabel(name) {
  if (name.startsWith("count:")) return name.slice(6);
  return METRIC_LABEL[name] || name.replace(/_/g, " ");
}

/** The few most telling metrics of a frame, as "In zone 2 · person 3". */
export function metricSummary(metrics, max = 3) {
  return Object.entries(metrics || {})
    .slice(0, max)
    .map(([k, v]) => `${metricLabel(k)} ${Math.round(v * 10) / 10}`)
    .join(" · ");
}

/** A 16:9 black stage for a camera picture (live, snapshot or placeholder). */
export function Stage({ children, sx }) {
  return (
    <Box
      sx={{
        position: "relative",
        aspectRatio: "16 / 9",
        bgcolor: "#000",
        borderRadius: 1.5,
        overflow: "hidden",
        display: "grid",
        placeItems: "center",
        "& > img": { width: "100%", height: "100%", objectFit: "contain", display: "block" },
        ...sx,
      }}
    >
      {children}
    </Box>
  );
}
