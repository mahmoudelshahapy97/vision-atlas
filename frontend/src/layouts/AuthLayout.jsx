import { Suspense } from "react";
import { Link as RouterLink, Outlet } from "react-router-dom";
import Box from "@mui/material/Box";
import Link from "@mui/material/Link";
import Paper from "@mui/material/Paper";
import Stack from "@mui/material/Stack";
import Typography from "@mui/material/Typography";
import BrandMark from "../components/BrandMark";
import { Loading } from "../components/DataStates";

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
      }}
    >
      <Paper
        elevation={0}
        variant="outlined"
        sx={{ width: "100%", maxWidth: 420, p: { xs: 3, sm: 4 }, borderRadius: 3 }}
      >
        <Stack spacing={0.5} alignItems="center" sx={{ mb: 3, textAlign: "center" }}>
          <BrandMark size={34} />
          <Typography variant="h5" sx={{ fontWeight: 800 }}>
            Vision Atlas
          </Typography>
          <Typography variant="body2" color="text.secondary">
            Computer-vision project lab
          </Typography>
        </Stack>
        <Suspense fallback={<Loading height={240} />}>
          <Outlet />
        </Suspense>
      </Paper>
      <Link component={RouterLink} to="/" variant="body2" underline="hover" color="text.secondary">
        ← Back to the catalog
      </Link>
    </Box>
  );
}

export default AuthLayout;
