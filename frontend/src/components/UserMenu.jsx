import { useState } from "react";
import { Link as RouterLink, useNavigate } from "react-router-dom";
import Avatar from "@mui/material/Avatar";
import Box from "@mui/material/Box";
import Button from "@mui/material/Button";
import Chip from "@mui/material/Chip";
import Divider from "@mui/material/Divider";
import IconButton from "@mui/material/IconButton";
import ListItemIcon from "@mui/material/ListItemIcon";
import ListItemText from "@mui/material/ListItemText";
import Menu from "@mui/material/Menu";
import MenuItem from "@mui/material/MenuItem";
import Stack from "@mui/material/Stack";
import Typography from "@mui/material/Typography";
import KeyIcon from "@mui/icons-material/Key";
import LogoutIcon from "@mui/icons-material/Logout";
import PhonelinkEraseIcon from "@mui/icons-material/PhonelinkErase";

import { useAuth } from "../auth/AuthContext";
import PasswordDialog from "./PasswordDialog";
import { useToast } from "./Toast";

const ROLE_COLOR = { admin: "error", user: "primary" };

/** Avatar menu when signed in; sign-in and register buttons when not. */
export function UserMenu() {
  const { user, logout, changePassword } = useAuth();
  const navigate = useNavigate();
  const toast = useToast();
  const [anchorEl, setAnchorEl] = useState(null);
  const [pwOpen, setPwOpen] = useState(false);

  if (!user) {
    return (
      <Stack direction="row" spacing={1}>
        <Button component={RouterLink} to="/login" color="inherit">
          Sign in
        </Button>
        <Button
          component={RouterLink}
          to="/register"
          variant="contained"
          sx={{ display: { xs: "none", sm: "inline-flex" } }}
        >
          Create account
        </Button>
      </Stack>
    );
  }

  const initial = (user.name || user.email || "?").charAt(0).toUpperCase();

  const handleLogout = async (everywhere = false) => {
    setAnchorEl(null);
    await logout({ everywhere });
    toast(everywhere ? "Signed out on every device." : "Signed out.");
    navigate("/", { replace: true });
  };

  const handleChangePassword = async (next, current) => {
    await changePassword(current, next);
    setPwOpen(false);
    toast("Password changed. Your other sessions were signed out.");
  };

  return (
    <>
      <IconButton onClick={(e) => setAnchorEl(e.currentTarget)} aria-label="Account menu">
        <Avatar sx={{ width: 32, height: 32, fontSize: 14, fontWeight: 700 }}>{initial}</Avatar>
      </IconButton>
      <Menu anchorEl={anchorEl} open={Boolean(anchorEl)} onClose={() => setAnchorEl(null)}>
        <Box sx={{ px: 2, py: 1, minWidth: 200 }}>
          <Typography variant="subtitle2" sx={{ fontWeight: 700 }}>
            {user.name}
          </Typography>
          <Typography variant="caption" color="text.secondary" sx={{ display: "block", mb: 0.75 }}>
            {user.email}
          </Typography>
          <Chip size="small" label={user.role} color={ROLE_COLOR[user.role] || "default"} />
        </Box>
        <Divider />
        <MenuItem
          onClick={() => {
            setAnchorEl(null);
            setPwOpen(true);
          }}
        >
          <ListItemIcon>
            <KeyIcon fontSize="small" />
          </ListItemIcon>
          <ListItemText>Change password</ListItemText>
        </MenuItem>
        <MenuItem onClick={() => handleLogout(true)}>
          <ListItemIcon>
            <PhonelinkEraseIcon fontSize="small" />
          </ListItemIcon>
          <ListItemText>Sign out everywhere</ListItemText>
        </MenuItem>
        <MenuItem onClick={() => handleLogout(false)}>
          <ListItemIcon>
            <LogoutIcon fontSize="small" />
          </ListItemIcon>
          <ListItemText>Sign out</ListItemText>
        </MenuItem>
      </Menu>
      <PasswordDialog
        open={pwOpen}
        title="Change your password"
        description="Your other devices are signed out; this one stays signed in."
        requireCurrent
        submitLabel="Change password"
        onSubmit={handleChangePassword}
        onClose={() => setPwOpen(false)}
      />
    </>
  );
}

export default UserMenu;
