import { useCallback, useMemo, useState } from "react";
import CssBaseline from "@mui/material/CssBaseline";
import { ThemeProvider } from "@mui/material/styles";
import { AuthProvider } from "./auth/AuthContext";
import { ToastProvider } from "./components/Toast";
import { AlertsProvider } from "./hooks/useAlerts";
import AppRouter from "./routes/AppRouter";
import { WorkspaceProvider } from "./workspace/WorkspaceContext";
import { buildTheme } from "./utils/theme";

const MODE_KEY = "atlas:color-mode";

function readMode() {
  try {
    return localStorage.getItem(MODE_KEY) === "light" ? "light" : "dark";
  } catch {
    return "dark";
  }
}

export default function App() {
  const [mode, setMode] = useState(readMode);

  const toggleMode = useCallback(() => {
    setMode((current) => {
      const next = current === "dark" ? "light" : "dark";
      try {
        localStorage.setItem(MODE_KEY, next);
      } catch {
        /* private window: the choice lasts for this visit only */
      }
      return next;
    });
  }, []);

  const theme = useMemo(() => buildTheme(mode), [mode]);

  return (
    <ThemeProvider theme={theme}>
      <CssBaseline />
      <ToastProvider>
        <AuthProvider>
          <WorkspaceProvider>
            <AlertsProvider>
              <AppRouter mode={mode} onToggleMode={toggleMode} />
            </AlertsProvider>
          </WorkspaceProvider>
        </AuthProvider>
      </ToastProvider>
    </ThemeProvider>
  );
}
