// Small status markers: project status, level, top pick, progress, lab support, run status.

import Box from "@mui/material/Box";
import Chip from "@mui/material/Chip";
import Tooltip from "@mui/material/Tooltip";
import StarIcon from "@mui/icons-material/Star";
import CheckIcon from "@mui/icons-material/Check";
import AutoAwesomeIcon from "@mui/icons-material/AutoAwesome";
import RuleIcon from "@mui/icons-material/Rule";
import TuneIcon from "@mui/icons-material/Tune";
import ShowChartIcon from "@mui/icons-material/ShowChart";
import UploadFileIcon from "@mui/icons-material/UploadFile";

import {
  LEVELS,
  RUN_STATUS_COLOR,
  STATUS_COLOR,
  STATUS_LABEL,
  SUPPORT_COLOR,
  SUPPORT_LABEL,
} from "../utils/constants";

const STATUS_HINT = {
  idea: "Not started",
  planned: "On your list",
  building: "Work in progress",
  done: "Finished",
};

const RUN_HINT = {
  queued: "Waiting for a lab worker",
  running: "Being analysed now",
  done: "Finished",
  error: "Stopped with an error",
};

/** Three bars, filled up to the level (1 beginner … 3 advanced). */
export function LevelBars({ level }) {
  return (
    <Box component="span" aria-hidden="true" sx={{ display: "inline-flex", alignItems: "flex-end", gap: "2px", height: 12 }}>
      {[1, 2, 3].map((n) => (
        <Box
          key={n}
          component="span"
          sx={{
            width: 3,
            height: 4 + n * 2.5,
            borderRadius: 1,
            bgcolor: n <= level ? "primary.main" : "divider",
          }}
        />
      ))}
    </Box>
  );
}

export function LevelChip({ level, size = "small" }) {
  return (
    <Chip
      size={size}
      variant="outlined"
      label={
        <Box component="span" sx={{ display: "inline-flex", alignItems: "center", gap: 0.75 }}>
          {LEVELS[level]}
          <LevelBars level={level} />
        </Box>
      }
    />
  );
}

export function StatusChip({ status = "idea", size = "small", ...props }) {
  const color = STATUS_COLOR[status] || "default";
  return (
    <Tooltip title={STATUS_HINT[status] || ""}>
      <Chip
        label={STATUS_LABEL[status]}
        color={color}
        size={size}
        variant={color === "default" ? "outlined" : "filled"}
        {...props}
      />
    </Tooltip>
  );
}

export function RunStatusChip({ status, size = "small", ...props }) {
  const color = RUN_STATUS_COLOR[status] || "default";
  return (
    <Tooltip title={RUN_HINT[status] || ""}>
      <Chip
        label={status}
        color={color}
        size={size}
        variant={color === "default" ? "outlined" : "filled"}
        sx={{ textTransform: "capitalize" }}
        {...props}
      />
    </Tooltip>
  );
}

export function PickChip({ size = "small", ...props }) {
  return (
    <Chip
      icon={<StarIcon />}
      label="Top pick"
      size={size}
      color="warning"
      variant="outlined"
      {...props}
    />
  );
}

/** Stacked done / building / planned bar. */
export function ProgressBar({ counts, total, label, height = 10 }) {
  return (
    <Box
      role="img"
      aria-label={label}
      sx={{ display: "flex", height, borderRadius: 99, overflow: "hidden", bgcolor: "action.hover" }}
    >
      {["done", "building", "planned"].map((k) =>
        counts[k] ? (
          <Box key={k} sx={{ width: `${(counts[k] / total) * 100}%`, bgcolor: `${STATUS_COLOR[k]}.main` }} />
        ) : null
      )}
    </Box>
  );
}

const SUPPORT_ICON = {
  ready: <CheckIcon />,
  zero_shot: <AutoAwesomeIcon />,
  rules: <RuleIcon />,
  classical: <TuneIcon />,
  baseline: <ShowChartIcon />,
  custom_model: <UploadFileIcon />,
};

/** Lab readiness. `level` is a support-level object from the API or just its code. */
export function SupportBadge({ level, compact = false }) {
  if (!level) return null;
  const code = level.code || level;
  const label = level.label || SUPPORT_LABEL[code];
  return (
    <Tooltip title={level.description || label}>
      <Chip
        icon={SUPPORT_ICON[code]}
        label={label}
        size="small"
        color={SUPPORT_COLOR[code] || "default"}
        variant={compact ? "outlined" : "filled"}
        sx={compact ? { height: 22, fontSize: 11.5, "& .MuiChip-icon": { fontSize: 14 } } : undefined}
      />
    </Tooltip>
  );
}
