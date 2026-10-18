import Box from "@mui/material/Box";
import Chip from "@mui/material/Chip";
import ListItemText from "@mui/material/ListItemText";
import MenuItem from "@mui/material/MenuItem";
import TextField from "@mui/material/TextField";
import Typography from "@mui/material/Typography";
import WorkspacesIcon from "@mui/icons-material/Workspaces";

import { useWorkspace } from "../workspace/WorkspaceContext";

/** The active workspace in the app bar: a picker with several, a label with one, nothing with none. */
export function WorkspaceSwitcher() {
  const { workspaces, active, setActive } = useWorkspace();
  if (!active) return null;

  if (workspaces.length === 1) {
    return (
      <Box sx={{ display: "flex", alignItems: "center", gap: 0.75, minWidth: 0, color: "text.secondary" }}>
        <WorkspacesIcon fontSize="small" />
        <Typography variant="body2" noWrap sx={{ fontWeight: 600, maxWidth: { xs: 110, sm: 200 } }}>
          {active.name}
        </Typography>
      </Box>
    );
  }

  return (
    <TextField
      select
      size="small"
      value={active.id}
      onChange={(e) => setActive(Number(e.target.value))}
      SelectProps={{
        // Name it by role, not by its content (MUI points aria-labelledby at itself).
        SelectDisplayProps: { "aria-label": `Workspace: ${active.name}`, "aria-labelledby": undefined },
        renderValue: () => (
          <Box sx={{ display: "flex", alignItems: "center", gap: 0.75, minWidth: 0 }}>
            <WorkspacesIcon fontSize="small" sx={{ color: "text.secondary", display: { xs: "none", sm: "inline-block" } }} />
            <Box component="span" sx={{ overflow: "hidden", textOverflow: "ellipsis", fontWeight: 600 }}>
              {active.name}
            </Box>
          </Box>
        ),
        MenuProps: { PaperProps: { sx: { maxHeight: 420 } } },
      }}
      sx={{ minWidth: { xs: 120, sm: 180 }, maxWidth: { xs: 150, sm: 260 } }}
    >
      {workspaces.map((w) => (
        <MenuItem key={w.id} value={w.id} sx={{ gap: 1.5 }}>
          <ListItemText primary={w.name} secondary={w.is_active ? null : "Deactivated"} />
          <Chip size="small" variant="outlined" label={w.my_role} />
        </MenuItem>
      ))}
    </TextField>
  );
}

export default WorkspaceSwitcher;
