import Box from "@mui/material/Box";
import Card from "@mui/material/Card";
import CardActionArea from "@mui/material/CardActionArea";
import Chip from "@mui/material/Chip";
import Stack from "@mui/material/Stack";
import Typography from "@mui/material/Typography";
import StarIcon from "@mui/icons-material/Star";

import { pad } from "../utils/format";
import { MONO_FONT } from "../utils/theme";
import { LevelChip, StatusChip, SupportBadge } from "./StatusChips";

const clamp = (lines) => ({
  display: "-webkit-box",
  WebkitLineClamp: lines,
  WebkitBoxOrient: "vertical",
  overflow: "hidden",
});

/** Tag such as "#07 · DET", shared by cards, the drawer and the board. */
export function ProjectTag({ project: p, sx }) {
  return (
    <Typography
      component="span"
      variant="caption"
      color="text.secondary"
      sx={{ fontFamily: MONO_FONT, fontWeight: 600, letterSpacing: "0.02em", ...sx }}
    >
      #{pad(p.id)} · {p.task_type.code.toUpperCase()}
    </Typography>
  );
}

export default function ProjectCard({ project: p, onOpen, showStatus }) {
  return (
    <Card sx={{ height: "100%", "&:hover": { borderColor: "primary.main" }, transition: "border-color .15s" }}>
      <CardActionArea
        onClick={() => onOpen(p.id)}
        aria-label={`Project ${p.id}: ${p.title}`}
        sx={{ height: "100%", p: 2, display: "flex", flexDirection: "column", alignItems: "stretch", gap: 1 }}
      >
        <Stack direction="row" justifyContent="space-between" alignItems="center" spacing={1}>
          <ProjectTag project={p} />
          <LevelChip level={p.level} />
        </Stack>
        <Stack direction="row" justifyContent="space-between" alignItems="center" spacing={1} sx={{ minHeight: 22 }}>
          <Typography variant="caption" color="primary.main" sx={{ fontWeight: 700, textTransform: "uppercase", letterSpacing: "0.06em" }} noWrap>
            {p.domain.name}
          </Typography>
          {p.lab && <SupportBadge level={p.lab.support} compact />}
        </Stack>
        <Typography variant="subtitle1" sx={{ fontWeight: 700, lineHeight: 1.3, ...clamp(2) }}>
          {p.title}
        </Typography>
        <Typography variant="body2" color="text.secondary" sx={clamp(3)}>
          {p.description}
        </Typography>
        <Stack direction="row" spacing={0.5} useFlexGap flexWrap="wrap">
          {p.technologies.slice(0, 3).map((t) => <Chip key={t} label={t} size="small" variant="outlined" />)}
          {p.technologies.length > 3 && <Chip label={`+${p.technologies.length - 3}`} size="small" variant="outlined" />}
        </Stack>
        <Box sx={{ flexGrow: 1 }} />
        <Stack
          direction="row"
          justifyContent="space-between"
          alignItems="center"
          spacing={1}
          sx={{ pt: 1, borderTop: 1, borderColor: "divider" }}
        >
          {showStatus ? (
            <StatusChip status={p.progress?.status} />
          ) : (
            <Typography variant="caption" color="text.secondary" noWrap>{p.task_type.metric}</Typography>
          )}
          {p.is_pick ? (
            <Typography variant="caption" color="warning.main" sx={{ display: "inline-flex", alignItems: "center", gap: 0.5, fontWeight: 700, flexShrink: 0 }}>
              <StarIcon sx={{ fontSize: 14 }} />Top pick
            </Typography>
          ) : showStatus ? (
            <Typography variant="caption" color="text.secondary" noWrap>{p.task_type.metric}</Typography>
          ) : null}
        </Stack>
      </CardActionArea>
    </Card>
  );
}
