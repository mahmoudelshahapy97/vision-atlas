// Event markers shared by the dashboard and the events pages.

import Box from "@mui/material/Box";
import Chip from "@mui/material/Chip";
import ImageNotSupportedIcon from "@mui/icons-material/ImageNotSupported";
import { mediaUrl } from "../../api/client";

export const SEVERITY_COLOR = { info: "info", warning: "warning", critical: "error" };
export const STATUS_LABEL = { open: "Open", acknowledged: "Acknowledged", resolved: "Resolved", false_positive: "False alarm" };
const STATUS_COLOR = { open: "error", acknowledged: "warning", resolved: "success", false_positive: "default" };

const KIND_LABEL = {
  zone_entry: "Zone entry",
  fall: "Fall",
  lying: "Person lying down",
  abandoned: "Abandoned object",
  ppe_violation: "Missing PPE",
  lot_full: "Parking full",
};

export const kindLabel = (kind) => KIND_LABEL[kind] || kind.replace(/_/g, " ");

export function SeverityChip({ severity }) {
  return <Chip size="small" color={SEVERITY_COLOR[severity]} label={severity} />;
}

export function EventStatusChip({ status }) {
  return <Chip size="small" variant={status === "open" ? "filled" : "outlined"} color={STATUS_COLOR[status]} label={STATUS_LABEL[status]} />;
}

/** The event's snapshot, letterboxed; a placeholder while it uploads or when there is none. */
export function Snapshot({ event, height = 54, sx }) {
  return (
    <Box
      sx={{
        width: (height * 16) / 9,
        height,
        flexShrink: 0,
        borderRadius: 1,
        overflow: "hidden",
        bgcolor: "#000",
        display: "grid",
        placeItems: "center",
        color: "grey.600",
        ...sx,
      }}
    >
      {event.snapshot_url ? (
        <Box component="img" src={mediaUrl(event.snapshot_url)} alt={`${kindLabel(event.kind)} at ${event.camera_name}`} loading="lazy"
          sx={{ width: "100%", height: "100%", objectFit: "cover", display: "block" }} />
      ) : (
        <ImageNotSupportedIcon fontSize="small" />
      )}
    </Box>
  );
}
