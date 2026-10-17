import { Link as RouterLink, Outlet } from "react-router-dom";
import Box from "@mui/material/Box";
import Link from "@mui/material/Link";
import Paper from "@mui/material/Paper";
import Stack from "@mui/material/Stack";
import Typography from "@mui/material/Typography";

/**
 * Centred single-card shell for /login and /register. Deliberately not
 * AppLayout: no nav drawer or status chip for someone signing in.
 */
export function AuthLayout() {
  return (
    <Box
      sx={{
        minHeight: "100vh",
        display: "flex",
        flexDirection: "column",
        alignItems: "center",
        justifyContent: "center",
        gap: 2,
        px: 2,
        bgcolor: "background.default",
      }}
    >
      <Paper
        elevation={0}
        variant="outlined"
        sx={{ width: "100%", maxWidth: 420, p: { xs: 3, sm: 4 }, borderRadius: 3 }}
      >
        <Stack spacing={0.5} alignItems="center" sx={{ mb: 3, textAlign: "center" }}>
          <svg width="34" height="34" viewBox="0 0 32 32" aria-hidden="true">
            <path d="M3 10V3h7M22 3h7v7M29 22v7h-7M10 29H3v-7" fill="none" stroke="#f59e0b" strokeWidth="3" />
            <circle cx="16" cy="16" r="5" fill="#3b82f6" />
          </svg>
          <Typography variant="h5" sx={{ fontWeight: 800 }}>
            Vision Atlas
          </Typography>
          <Typography variant="body2" color="text.secondary">
            Computer-vision project lab
          </Typography>
        </Stack>
        <Outlet />
      </Paper>
      <Link component={RouterLink} to="/" variant="body2" underline="hover" color="text.secondary">
        ← Back to the catalog
      </Link>
    </Box>
  );
}

export default AuthLayout;
