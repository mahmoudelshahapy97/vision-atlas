import { Suspense, useState } from "react";
import { Link as RouterLink, NavLink, Outlet, useLocation } from "react-router-dom";
import AppBar from "@mui/material/AppBar";
import Box from "@mui/material/Box";
import Chip from "@mui/material/Chip";
import Divider from "@mui/material/Divider";
import Drawer from "@mui/material/Drawer";
import IconButton from "@mui/material/IconButton";
import List from "@mui/material/List";
import ListItemButton from "@mui/material/ListItemButton";
import ListItemIcon from "@mui/material/ListItemIcon";
import ListItemText from "@mui/material/ListItemText";
import ListSubheader from "@mui/material/ListSubheader";
import Stack from "@mui/material/Stack";
import Toolbar from "@mui/material/Toolbar";
import Tooltip from "@mui/material/Tooltip";
import Typography from "@mui/material/Typography";
import useMediaQuery from "@mui/material/useMediaQuery";
import { useTheme } from "@mui/material/styles";

import ViewModuleIcon from "@mui/icons-material/ViewModule";
import MemoryIcon from "@mui/icons-material/Memory";
import ViewKanbanIcon from "@mui/icons-material/ViewKanban";
import HistoryIcon from "@mui/icons-material/History";
import AdminPanelSettingsIcon from "@mui/icons-material/AdminPanelSettings";
import PeopleIcon from "@mui/icons-material/People";
import GroupIcon from "@mui/icons-material/Group";
import WorkspacesIcon from "@mui/icons-material/Workspaces";
import VideocamIcon from "@mui/icons-material/Videocam";
import GridViewIcon from "@mui/icons-material/GridView";
import DashboardIcon from "@mui/icons-material/Dashboard";
import NotificationsIcon from "@mui/icons-material/Notifications";
import InsightsIcon from "@mui/icons-material/Insights";
import MenuIcon from "@mui/icons-material/Menu";
import DarkModeIcon from "@mui/icons-material/DarkMode";
import LightModeIcon from "@mui/icons-material/LightMode";
import MenuBookIcon from "@mui/icons-material/MenuBook";

import { health } from "../api/endpoints";
import { usePolling } from "../hooks/usePolling";
import { useAuth } from "../auth/AuthContext";
import BrandMark from "../components/BrandMark";
import { Loading } from "../components/DataStates";
import UserMenu from "../components/UserMenu";
import WorkspaceSwitcher from "../components/WorkspaceSwitcher";
import { useWorkspace } from "../workspace/WorkspaceContext";

const DRAWER_WIDTH = 248;

/**
 * `minimum` is a role from auth/roles.js. Items without one are public: the
 * catalog, labs and model list can be browsed signed out. `ws` is a workspace
 * role: the item needs an active workspace where the user has at least that.
 * The API check on each route is the real one; this only decides what the nav
 * shows.
 */
const NAV_SECTIONS = [
  {
    heading: "Explore",
    items: [
      { to: "/", label: "Catalog", icon: <ViewModuleIcon />, end: true },
      { to: "/models", label: "Models", icon: <MemoryIcon /> },
    ],
  },
  {
    heading: "My work",
    items: [
      { to: "/board", label: "My board", icon: <ViewKanbanIcon />, minimum: "user" },
      { to: "/runs", label: "My runs", icon: <HistoryIcon />, minimum: "user" },
    ],
  },
  {
    heading: "Operations",
    items: [
      { to: "/dashboard", label: "Dashboard", icon: <DashboardIcon />, ws: "viewer" },
      { to: "/live", label: "Live", icon: <GridViewIcon />, ws: "viewer" },
      { to: "/events", label: "Events", icon: <NotificationsIcon />, ws: "viewer" },
      { to: "/analytics", label: "Analytics", icon: <InsightsIcon />, ws: "viewer" },
      { to: "/cameras", label: "Cameras", icon: <VideocamIcon />, ws: "viewer" },
      { to: "/workspace/members", label: "Members", icon: <GroupIcon />, ws: "viewer" },
    ],
  },
  {
    heading: "Admin",
    items: [
      { to: "/admin", label: "Projects", icon: <AdminPanelSettingsIcon />, minimum: "admin" },
      { to: "/users", label: "Users", icon: <PeopleIcon />, minimum: "admin" },
      { to: "/workspaces", label: "Workspaces", icon: <WorkspacesIcon />, minimum: "admin" },
    ],
  },
];

const NAV_ITEMS = NAV_SECTIONS.flatMap((section) => section.items);

// Pages that aren't in the nav but still want a bar title.
const EXTRA_TITLES = [{ to: "/projects/", label: "Lab" }];

/**
 * Backend reachability, shown in the bar so a dead API is never a mystery.
 * The model server being down leaves the catalog and run history working, so
 * it is a warning rather than an error.
 */
function BackendStatus() {
  const { data, error } = usePolling((opts) => health.live(opts), { intervalMs: 15000 });

  if (error) {
    return <Chip size="small" color="error" label="API unreachable" variant="filled" />;
  }
  if (!data) return <Chip size="small" label="Checking…" variant="outlined" />;

  const dbDown = data.status !== "healthy";
  const modelsDown = data.models && !data.models.ok;
  const label = dbDown ? `API ${data.status}` : modelsDown ? "Models offline" : "API ok";
  return (
    <Tooltip
      title={
        `Database: ${data.db_connection_ok ? "connected" : "unreachable"} · ` +
        `model server: ${data.models?.ok ? data.models.device || "up" : "unreachable"}` +
        (data.version ? ` · API v${data.version}` : "")
      }
    >
      <Chip
        size="small"
        color={dbDown || modelsDown ? "warning" : "success"}
        variant={dbDown || modelsDown ? "filled" : "outlined"}
        label={label}
        icon={
          dbDown || modelsDown ? undefined : (
            <Box
              component="span"
              className="pulse-indicator"
              sx={{ width: 7, height: 7, borderRadius: "50%", bgcolor: "success.main", ml: "8px !important" }}
            />
          )
        }
      />
    </Tooltip>
  );
}

function Brand() {
  return (
    <Box
      component={RouterLink}
      to="/"
      sx={{ display: "flex", alignItems: "center", gap: 1.25, color: "inherit", textDecoration: "none" }}
    >
      <BrandMark />
      <Box>
        <Typography variant="subtitle1" sx={{ fontWeight: 800, lineHeight: 1.2 }}>
          Vision Atlas
        </Typography>
        <Typography variant="caption" color="text.secondary">
          Computer-vision project lab
        </Typography>
      </Box>
    </Box>
  );
}

export function AppLayout({ mode, onToggleMode }) {
  const theme = useTheme();
  const isDesktop = useMediaQuery(theme.breakpoints.up("md"));
  const [mobileOpen, setMobileOpen] = useState(false);
  const location = useLocation();
  const { hasRole } = useAuth();
  const { active, hasWsRole } = useWorkspace();

  const visibleSections = NAV_SECTIONS.map((section) => ({
    ...section,
    heading: section.heading === "Operations" && active ? active.name : section.heading,
    items: section.items.filter(
      (item) => (!item.minimum || hasRole(item.minimum)) && (!item.ws || hasWsRole(item.ws))
    ),
  })).filter((section) => section.items.length > 0);

  const drawer = (
    <Box sx={{ display: "flex", flexDirection: "column", height: "100%" }}>
      <Toolbar sx={{ px: 2.5 }}>
        <Brand />
      </Toolbar>
      <Divider />
      <Box sx={{ flexGrow: 1, overflowY: "auto", py: 1 }}>
        {visibleSections.map((section) => (
          <List
            key={section.heading}
            dense
            sx={{ px: 1.5 }}
            subheader={
              <ListSubheader
                disableSticky
                sx={{ bgcolor: "transparent", lineHeight: 2.4 }}
              >
                {section.heading}
              </ListSubheader>
            }
          >
            {section.items.map((item) => (
              <ListItemButton
                key={item.to}
                component={NavLink}
                to={item.to}
                end={item.end}
                onClick={() => setMobileOpen(false)}
                sx={{
                  borderRadius: 2,
                  mb: 0.5,
                  // NavLink stamps .active on the matching route, so the
                  // highlight is the router's business rather than state we keep.
                  "&.active": {
                    bgcolor: "action.selected",
                    color: "nav.active",
                    "& .MuiListItemIcon-root": { color: "inherit" },
                  },
                }}
              >
                <ListItemIcon sx={{ minWidth: 40 }}>{item.icon}</ListItemIcon>
                <ListItemText primaryTypographyProps={{ fontWeight: 600 }} primary={item.label} />
              </ListItemButton>
            ))}
          </List>
        ))}
      </Box>
      <Divider />
      <Box sx={{ p: 1.5 }}>
        <ListItemButton
          component="a"
          href="/docs"
          target="_blank"
          rel="noreferrer"
          sx={{ borderRadius: 2 }}
        >
          <ListItemIcon sx={{ minWidth: 40 }}>
            <MenuBookIcon />
          </ListItemIcon>
          <ListItemText
            primary="API docs"
            secondary="FastAPI /docs"
            primaryTypographyProps={{ fontWeight: 600 }}
          />
        </ListItemButton>
      </Box>
    </Box>
  );

  // Longest matching prefix, so /runs/<id> still titles as "My runs" and
  // "/" does not match everything. /projects/<id> is the catalog drawer.
  const path = location.pathname;
  const currentTitle =
    (/^\/projects\/\d+\/?$/.test(path) && "Catalog") ||
    [...NAV_ITEMS, ...EXTRA_TITLES]
      .sort((a, b) => b.to.length - a.to.length)
      .find((item) => (item.end ? path === item.to : path.startsWith(item.to)))?.label ||
    "Vision Atlas";

  return (
    <Box sx={{ display: "flex", minHeight: "100vh" }}>
      <AppBar
        position="fixed"
        color="default"
        elevation={0}
        sx={{
          width: { md: `calc(100% - ${DRAWER_WIDTH}px)` },
          ml: { md: `${DRAWER_WIDTH}px` },
          borderBottom: 1,
          borderColor: "divider",
        }}
      >
        <Toolbar>
          <IconButton
            edge="start"
            onClick={() => setMobileOpen(true)}
            aria-label="Open navigation"
            sx={{ mr: 2, display: { md: "none" } }}
          >
            <MenuIcon />
          </IconButton>
          {/* On desktop the highlighted nav item and the page's own heading
              already say where you are; the bar title is for phones. */}
          <Typography variant="h6" noWrap sx={{ flexGrow: 1, minWidth: 0, visibility: { md: "hidden" } }}>
            {currentTitle}
          </Typography>
          <Stack direction="row" spacing={1.5} alignItems="center" sx={{ minWidth: 0 }}>
            <WorkspaceSwitcher />
            <Box sx={{ display: { xs: "none", lg: "block" } }}>
              <BackendStatus />
            </Box>
            <Tooltip title={mode === "dark" ? "Switch to light" : "Switch to dark"}>
              <IconButton onClick={onToggleMode} aria-label="Toggle colour mode">
                {mode === "dark" ? <LightModeIcon /> : <DarkModeIcon />}
              </IconButton>
            </Tooltip>
            <UserMenu />
          </Stack>
        </Toolbar>
      </AppBar>

      <Box component="nav" sx={{ width: { md: DRAWER_WIDTH }, flexShrink: { md: 0 } }}>
        <Drawer
          variant={isDesktop ? "permanent" : "temporary"}
          open={isDesktop || mobileOpen}
          onClose={() => setMobileOpen(false)}
          ModalProps={{ keepMounted: true }}
          sx={{
            "& .MuiDrawer-paper": {
              width: DRAWER_WIDTH,
              boxSizing: "border-box",
              borderRight: 1,
              borderColor: "divider",
            },
          }}
        >
          {drawer}
        </Drawer>
      </Box>

      <Box
        component="main"
        sx={{
          flexGrow: 1,
          // A flex child otherwise grows to its widest descendant, so one wide
          // table pushes the whole page sideways on a phone instead of
          // scrolling inside its own container.
          minWidth: 0,
          width: { md: `calc(100% - ${DRAWER_WIDTH}px)` },
          px: { xs: 2, md: 3 },
          pb: 4,
        }}
      >
        <Toolbar />
        <Box sx={{ pt: 3, maxWidth: 1440, mx: "auto" }}>
          {/* Here rather than around the routes, so a lazy page loading
              swaps only the content and the drawer and bar stay put. */}
          <Suspense fallback={<Loading />}>
            <Outlet />
          </Suspense>
        </Box>
      </Box>
    </Box>
  );
}

export default AppLayout;
