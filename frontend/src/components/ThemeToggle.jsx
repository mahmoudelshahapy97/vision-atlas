import { useEffect, useState } from "react";

const KEY = "atlas.theme";
const ORDER = ["system", "light", "dark"];
const LABEL = { system: "Auto", light: "Light", dark: "Dark" };

export default function ThemeToggle() {
  const [mode, setMode] = useState(() => {
    try {
      return localStorage.getItem(KEY) || "system";
    } catch {
      return "system";
    }
  });

  useEffect(() => {
    const root = document.documentElement;
    if (mode === "system") root.removeAttribute("data-theme");
    else root.setAttribute("data-theme", mode);
    try {
      localStorage.setItem(KEY, mode);
    } catch {
      /* ignore */
    }
  }, [mode]);

  const next = ORDER[(ORDER.indexOf(mode) + 1) % ORDER.length];
  return (
    <button className="btn ghost sm" onClick={() => setMode(next)} title={`Theme: ${LABEL[mode]}. Switch to ${LABEL[next]}`}>
      <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" aria-hidden="true">
        <circle cx="12" cy="12" r="8" />
        <path d="M12 4a8 8 0 0 1 0 16z" fill="currentColor" />
      </svg>
      <span className="hide-sm">{LABEL[mode]}</span>
    </button>
  );
}
