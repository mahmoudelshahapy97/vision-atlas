// Loading, error and empty states, so every page shows them the same way.

import Alert from "@mui/material/Alert";
import AlertTitle from "@mui/material/AlertTitle";
import Box from "@mui/material/Box";
import Button from "@mui/material/Button";
import Card from "@mui/material/Card";
import CardContent from "@mui/material/CardContent";
import CircularProgress from "@mui/material/CircularProgress";
import Skeleton from "@mui/material/Skeleton";
import Typography from "@mui/material/Typography";

export function Loading({ label = "Loading…", height = 200 }) {
  return (
    <Box
      sx={{
        display: "flex",
        flexDirection: "column",
        alignItems: "center",
        justifyContent: "center",
        gap: 1.5,
        minHeight: height,
      }}
    >
      <CircularProgress size={28} />
      <Typography variant="body2" color="text.secondary">
        {label}
      </Typography>
    </Box>
  );
}

/** `error` is an ApiError from api/client.js or a plain message. */
export function ErrorState({ error, onRetry, title = "Could not load this" }) {
  if (!error) return null;
  return (
    <Alert
      severity="error"
      sx={{ my: 2 }}
      action={
        onRetry && (
          <Button color="inherit" size="small" onClick={onRetry}>
            Retry
          </Button>
        )
      }
    >
      <AlertTitle>{title}</AlertTitle>
      {error.message ?? String(error)}
    </Alert>
  );
}

export function EmptyState({ title, description, action, icon, children }) {
  return (
    <Box
      sx={{
        textAlign: "center",
        py: 6,
        px: 2,
        color: "text.secondary",
      }}
    >
      {icon && <Box sx={{ fontSize: 44, mb: 1, opacity: 0.6 }}>{icon}</Box>}
      <Typography variant="h6" color="text.primary" gutterBottom>
        {title}
      </Typography>
      {(description || children) && (
        <Typography variant="body2" component="div" sx={{ maxWidth: 520, mx: "auto" }}>
          {description || children}
        </Typography>
      )}
      {action && <Box sx={{ mt: 2.5 }}>{action}</Box>}
    </Box>
  );
}

/** Placeholder cards while the first page of results loads. */
export function SkeletonCards({ count = 6, height = 210 }) {
  return Array.from({ length: count }, (_, i) => (
    <Card key={i} aria-hidden="true" sx={{ height }}>
      <CardContent>
        <Skeleton width="45%" />
        <Skeleton width="30%" sx={{ mb: 1.5 }} />
        <Skeleton variant="rounded" height={22} sx={{ mb: 1 }} />
        <Skeleton />
        <Skeleton width="80%" />
      </CardContent>
    </Card>
  ));
}
