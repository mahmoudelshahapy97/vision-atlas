import { defineConfig, loadEnv } from "vite";
import react from "@vitejs/plugin-react";

/**
 * The dev server proxies every backend path, so the browser only ever talks to
 * the Vite origin: no CORS, and <img>/<video> tags can load run outputs from
 * /media and lab samples from /api/lab/samples directly.
 *
 * Keep this list in step with nginx.conf.template, which proxies the same set
 * in the container.
 */
export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), "");
  const target = env.VITE_API_TARGET || env.API_PROXY_TARGET || "http://127.0.0.1:8000";

  const proxy = {
    "/api": { target, changeOrigin: true },
    // Uploaded inputs and run outputs (annotated images, videos, CSV/ZIP files).
    "/media": { target, changeOrigin: true },
    // Health probe outside the /api prefix.
    "/health": { target, changeOrigin: true },
    // FastAPI's own docs.
    "/docs": { target, changeOrigin: true },
    "/redoc": { target, changeOrigin: true },
    "/openapi.json": { target, changeOrigin: true },
  };

  return {
    plugins: [react()],
    server: {
      port: Number(env.VITE_PORT) || 5173,
      strictPort: false,
      open: false,
      proxy,
    },
    preview: {
      port: Number(env.VITE_PREVIEW_PORT) || 4173,
      proxy,
    },
    build: {
      outDir: "dist",
      sourcemap: mode !== "production",
      chunkSizeWarningLimit: 900,
    },
  };
});
