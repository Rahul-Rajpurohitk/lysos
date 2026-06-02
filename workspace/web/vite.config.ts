import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// https://vitejs.dev/config/
export default defineConfig({
  plugins: [react()],
  server: {
    // Lysos owns port 5173. strictPort makes vite FAIL loudly if it's taken
    // (by another project) rather than silently drifting to 5174/5175 — which
    // is how the wrong app ("PhD Journey", "JobAutoPilot") kept showing up at
    // localhost:5173. Free 5173 for Lysos rather than letting it drift.
    port: 5173,
    strictPort: true,
    proxy: {
      "/api": {
        target: "http://localhost:7860",
        changeOrigin: true,
      },
      "/workbench": {
        target: "http://localhost:7860",
        changeOrigin: true,
        ws: true,
        // The bare /workbench path is the React SPA route, not an API
        // endpoint. API calls accept JSON; let HTML page navigations fall
        // through to index.html so React Router can render the page.
        bypass(req) {
          const accept = req.headers.accept || "";
          if (req.method === "GET" && accept.includes("text/html")) {
            return "/index.html";
          }
          return null;
        },
      },
    },
  },
  build: {
    outDir: "dist",
    sourcemap: false,
    chunkSizeWarningLimit: 1000,
  },
});
