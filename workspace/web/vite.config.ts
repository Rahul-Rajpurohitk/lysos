import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// https://vitejs.dev/config/
export default defineConfig({
  plugins: [react()],
  server: {
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
