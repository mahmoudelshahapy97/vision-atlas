import { useTheme } from "@mui/material/styles";

/** The viewfinder logo: amber corner brackets around a primary-blue dot. Same art as the favicon. */
export function BrandMark({ size = 26 }) {
  const theme = useTheme();
  return (
    <svg width={size} height={size} viewBox="0 0 32 32" aria-hidden="true">
      <path d="M3 10V3h7M22 3h7v7M29 22v7h-7M10 29H3v-7" fill="none" stroke="#f59e0b" strokeWidth="3" />
      <circle cx="16" cy="16" r="5" fill={theme.palette.primary.main} />
    </svg>
  );
}

export default BrandMark;
