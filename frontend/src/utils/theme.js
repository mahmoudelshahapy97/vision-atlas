import { createTheme } from "@mui/material/styles";

export const MONO_FONT = '"JetBrains Mono", ui-monospace, "SFMono-Regular", Menlo, Consolas, monospace';

/**
 * Series colours for lab charts, in drawing order. Mid-tone hues so the same
 * list reads on both the dark and the light background.
 */
export const SERIES_COLORS = [
  "#3b82f6",
  "#f59e0b",
  "#22c55e",
  "#ef4444",
  "#8b5cf6",
  "#0ea5e9",
  "#ec4899",
  "#84cc16",
];

/**
 * Same palette and overrides as the lost-found console, so the two products
 * read as one family. Dark by default.
 */
export const buildTheme = (mode = "dark") =>
  createTheme({
    palette: {
      mode,
      primary: { main: "#3b82f6" },
      secondary: { main: "#8b5cf6" },
      success: { main: "#22c55e" },
      warning: { main: "#f59e0b" },
      error: { main: "#ef4444" },
      info: { main: "#0ea5e9" },
      ...(mode === "dark"
        ? {
            background: { default: "#0b1220", paper: "#131c2e" },
            divider: "rgba(148, 163, 184, 0.18)",
          }
        : {
            background: { default: "#f4f6fb", paper: "#ffffff" },
          }),
    },
    shape: { borderRadius: 12 },
    typography: {
      fontFamily:
        '"Inter", "Segoe UI", system-ui, -apple-system, "Helvetica Neue", Arial, sans-serif',
      h4: { fontWeight: 700, letterSpacing: "-0.02em" },
      h5: { fontWeight: 700, letterSpacing: "-0.01em" },
      h6: { fontWeight: 600 },
      subtitle2: { fontWeight: 600 },
      // Scores, counts and timestamps are read column-by-column; tabular
      // figures stop the digits shifting between rows.
      caption: { fontVariantNumeric: "tabular-nums" },
    },
    components: {
      MuiCard: {
        styleOverrides: {
          root: ({ theme }) => ({
            border: `1px solid ${theme.palette.divider}`,
            backgroundImage: "none",
          }),
        },
      },
      MuiButton: {
        defaultProps: { disableElevation: true },
        styleOverrides: { root: { textTransform: "none", fontWeight: 600 } },
      },
      MuiToggleButton: {
        styleOverrides: { root: { textTransform: "none", fontWeight: 600 } },
      },
      MuiTab: {
        styleOverrides: { root: { textTransform: "none", fontWeight: 600 } },
      },
      MuiChip: { styleOverrides: { root: { fontWeight: 600 } } },
      MuiTableCell: {
        styleOverrides: {
          head: { fontWeight: 700, whiteSpace: "nowrap" },
        },
      },
      MuiTooltip: { defaultProps: { arrow: true } },
    },
  });

export default buildTheme;
