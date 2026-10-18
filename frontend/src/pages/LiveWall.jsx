import { useMemo, useState } from "react";
import { Link as RouterLink } from "react-router-dom";
import Box from "@mui/material/Box";
import Button from "@mui/material/Button";
import FormControlLabel from "@mui/material/FormControlLabel";
import Skeleton from "@mui/material/Skeleton";
import Stack from "@mui/material/Stack";
import Switch from "@mui/material/Switch";
import ToggleButton from "@mui/material/ToggleButton";
import ToggleButtonGroup from "@mui/material/ToggleButtonGroup";
import VideocamIcon from "@mui/icons-material/Videocam";

import { cameras } from "../api/endpoints";
import LiveCameraTile from "../components/cameras/LiveCameraTile";
import { EmptyState, ErrorState } from "../components/DataStates";
import PageHeader from "../components/PageHeader";
import { useAsync } from "../hooks/useAsync";
import { usePolling } from "../hooks/usePolling";
import { useWorkspace } from "../workspace/WorkspaceContext";

const LAYOUT_KEY = "atlas:live-layout";
// tiles per row on a wide screen; phones always show one per row
const LAYOUTS = { 1: 1, 4: 2, 9: 3, 16: 4 };

function readLayout() {
  try {
    return Number(localStorage.getItem(LAYOUT_KEY)) in LAYOUTS ? Number(localStorage.getItem(LAYOUT_KEY)) : 4;
  } catch {
    return 4;
  }
}

/** Every camera of the workspace at once, each tile with its own live connection. */
export default function LiveWall() {
  const { active } = useWorkspace();
  const wid = active?.id;
  const list = usePolling((opts) => cameras.list(opts), { intervalMs: 10000, deps: [wid], enabled: Boolean(wid) });
  const catalogue = useAsync((opts) => (wid ? cameras.pipelines(opts) : null), [wid]);
  const titles = useMemo(
    () => Object.fromEntries((catalogue.data?.pipelines || []).map((p) => [p.name, p.title])),
    [catalogue.data]
  );
  const [layout, setLayout] = useState(readLayout);
  const [onlyLive, setOnlyLive] = useState(true);

  if (!active) {
    return <EmptyState title="No workspace yet" description="Cameras belong to a workspace. Ask an admin to add you to one." />;
  }

  const all = list.data || [];
  const shown = (onlyLive ? all.filter((c) => c.status.running) : all).slice(0, layout);
  const cols = LAYOUTS[layout];

  function pick(_, v) {
    if (!v) return;
    setLayout(v);
    try {
      localStorage.setItem(LAYOUT_KEY, String(v));
    } catch {
      /* storage blocked */
    }
  }

  return (
    <Box>
      <PageHeader
        title="Live"
        subtitle={`${all.filter((c) => c.status.running).length} of ${all.length} cameras live in ${active.name}.`}
        actions={
          <Stack direction="row" spacing={1.5} alignItems="center" flexWrap="wrap" useFlexGap>
            <FormControlLabel
              control={<Switch size="small" checked={onlyLive} onChange={(e) => setOnlyLive(e.target.checked)} />}
              label="Only live"
            />
            <ToggleButtonGroup size="small" exclusive value={layout} onChange={pick} aria-label="Tiles on screen">
              {Object.keys(LAYOUTS).map((n) => (
                <ToggleButton key={n} value={Number(n)} aria-label={`${n} tiles`}>{n}</ToggleButton>
              ))}
            </ToggleButtonGroup>
          </Stack>
        }
      />
      <ErrorState error={list.error} onRetry={list.reload} />
      {list.loading && !list.data ? (
        <Box sx={{ display: "grid", gap: 2, gridTemplateColumns: { xs: "1fr", md: "repeat(2, 1fr)" } }}>
          {Array.from({ length: 4 }, (_, i) => <Skeleton key={i} variant="rounded" sx={{ aspectRatio: "16 / 10", height: "auto" }} />)}
        </Box>
      ) : shown.length ? (
        <Box
          sx={{
            display: "grid",
            gap: 2,
            gridTemplateColumns: { xs: "1fr", sm: `repeat(${Math.min(cols, 2)}, minmax(0, 1fr))`, lg: `repeat(${cols}, minmax(0, 1fr))` },
          }}
        >
          {shown.map((c) => (
            <LiveCameraTile key={c.id} camera={c} pipelineTitle={titles[c.pipeline]} />
          ))}
        </Box>
      ) : (
        list.data && (
          <EmptyState
            icon={<VideocamIcon />}
            title={all.length ? "No camera is live" : "No cameras yet"}
            description={all.length ? "Start one from the Cameras page, or switch off “Only live”." : "Add a camera first."}
            action={<Button component={RouterLink} to="/cameras" variant="outlined">Cameras</Button>}
          />
        )
      )}
    </Box>
  );
}
